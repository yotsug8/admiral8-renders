"""Offline storage regressions with real multiprocessing spawn workers."""
import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from .render_storage import atomic_copy, cached_file, file_lock
except ImportError:
    from render_storage import atomic_copy, cached_file, file_lock


OLD = b'previous complete result'
NEW = b'new complete result' * 4096
WAIT = 10


def _wait(event):
    if not event.wait(WAIT):
        raise RuntimeError('worker synchronization timed out')


def _hold_lock(path, entered, release):
    with file_lock(path):
        entered.set()
        _wait(release)


def _contender(path, start, ready, count):
    ready.set()
    _wait(start)

    def build(temporary):
        with count.get_lock():
            count.value += 1
        time.sleep(0.15)
        temporary.write_bytes(NEW)

    assert cached_file(path, build, timeout=WAIT).read_bytes() == NEW


def _publish(path, partial, inspected, done, mode):
    path = Path(path)

    def write_partial(temporary):
        with Path(temporary).open('wb') as output:
            output.write(NEW[:100])
            output.flush()
            partial.set()
            _wait(inspected)
            output.write(NEW[100:])

    if mode == 'cache':
        cached_file(path, write_partial, lambda p: p.read_bytes() == NEW)
    else:
        # Exercise atomic_copy with a deliberately paused copyfile operation.
        with patch(f'{atomic_copy.__module__}.shutil.copyfile',
                   side_effect=lambda src, dst: write_partial(dst)):
            with file_lock(str(path) + '.lock'):
                atomic_copy('unused-source', path)
    done.set()


def _reader(path, partial, inspected, done):
    _wait(partial)
    for _ in range(50):
        assert Path(path).read_bytes() == OLD, 'reader observed a partial file'
    # Close reader handles before publication, as required on Windows.
    inspected.set()
    _wait(done)
    assert Path(path).read_bytes() == NEW


def _failed_builder(path):
    def build(temporary):
        temporary.write_bytes(b'partial')
        raise LookupError('builder failed')

    try:
        cached_file(path, build, lambda p: p.read_bytes() == NEW)
    except LookupError as exc:
        assert str(exc) == 'builder failed'
    else:
        raise AssertionError('builder exception was swallowed')


def _build_held(path, entered, release):
    def build(temporary):
        entered.set()
        _wait(release)
        temporary.write_bytes(NEW)
    cached_file(path, build)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.context = multiprocessing.get_context('spawn')
        self.folder = tempfile.TemporaryDirectory(prefix='render-storage-')
        self.root = Path(self.folder.name)
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.is_alive():
                process.kill()
            process.join(WAIT)
            process.close()
        self.folder.cleanup()

    def event(self):
        return self.context.Event()

    def spawn(self, target, *args):
        process = self.context.Process(target=target, args=args)
        process.start()
        self.processes.append(process)
        return process

    def joined(self, process):
        process.join(WAIT)
        self.assertFalse(process.is_alive(), 'worker did not finish')
        self.assertEqual(process.exitcode, 0)

    def test_one_builder_for_concurrent_processes(self):
        start = self.event()
        ready = [self.event() for _ in range(4)]
        count = self.context.Value('i', 0)
        path = self.root / 'shared.json'
        workers = [self.spawn(_contender, path, start, event, count) for event in ready]
        for event in ready:
            self.assertTrue(event.wait(WAIT))
        start.set()
        for worker in workers:
            self.joined(worker)
        self.assertEqual(count.value, 1)
        self.assertEqual(path.read_bytes(), NEW)
        self.assertEqual({p.name for p in self.root.iterdir()},
                         {'shared.json', 'shared.json.lock'})

    def test_readers_never_see_partial_cache_or_copy(self):
        for mode in ('cache', 'copy'):
            with self.subTest(mode=mode):
                path = self.root / f'{mode}.bin'
                path.write_bytes(OLD)
                partial, inspected, done = self.event(), self.event(), self.event()
                reader = self.spawn(_reader, path, partial, inspected, done)
                writer = self.spawn(_publish, path, partial, inspected, done, mode)
                self.joined(writer)
                self.joined(reader)

    def test_failed_builder_preserves_destination_and_other_temporary(self):
        path = self.root / 'result.wav'
        path.write_bytes(OLD)
        other = self.root / '.result.other.wav'
        other.write_bytes(b'owned by another process')
        self.joined(self.spawn(_failed_builder, path))
        self.assertEqual(path.read_bytes(), OLD)
        self.assertEqual(other.read_bytes(), b'owned by another process')
        self.assertEqual({p.name for p in self.root.iterdir()},
                         {'result.wav', 'result.wav.lock', other.name})

    def test_fail_fast_timeout_and_release_after_kill(self):
        path = self.root / 'held.lock'
        entered, release = self.event(), self.event()
        holder = self.spawn(_hold_lock, path, entered, release)
        self.assertTrue(entered.wait(WAIT))
        for timeout in (0, 0.15):
            with self.subTest(timeout=timeout):
                started = time.monotonic()
                with self.assertRaisesRegex(RuntimeError, 'File lock unavailable:.*held.lock'):
                    with file_lock(path, timeout=timeout):
                        self.fail('entered a held lock')
                elapsed = time.monotonic() - started
                self.assertGreaterEqual(elapsed, timeout * 0.9)
                self.assertLess(elapsed, 2)
        holder.kill()
        holder.join(WAIT)
        self.assertFalse(holder.is_alive())
        self.assertNotEqual(holder.exitcode, 0)
        with file_lock(path, timeout=1):
            pass
        self.assertTrue(path.is_file())

    def test_distinct_keys_build_concurrently(self):
        entered_a, entered_b, release = self.event(), self.event(), self.event()
        first = self.spawn(_build_held, self.root / 'a.json', entered_a, release)
        self.assertTrue(entered_a.wait(WAIT))
        second = self.spawn(_build_held, self.root / 'b.json', entered_b, release)
        self.assertTrue(entered_b.wait(WAIT), 'second key blocked behind first')
        release.set()
        self.joined(first)
        self.joined(second)

    def test_cache_hit_skips_builder_and_validation_failure_rebuilds(self):
        path = self.root / 'nested' / 'cache.json'
        seen = []

        def build(temporary):
            self.assertIsInstance(temporary, Path)
            self.assertEqual(temporary.parent, path.parent)
            self.assertEqual(temporary.suffix, path.suffix)
            self.assertNotEqual(temporary, path)
            seen.append(temporary)
            temporary.write_bytes(NEW)

        self.assertEqual(cached_file(path, build), path)
        cached_file(path, lambda p: self.fail('cache hit called builder'))

        def validate(candidate):
            if candidate == path:
                raise ValueError('corrupt cache')
            return candidate.read_bytes() == NEW

        cached_file(path, build, validate)
        self.assertEqual(len(set(seen)), 2)
        self.assertTrue(all(not p.exists() for p in seen))
        path.write_bytes(b'')
        cached_file(path, build)
        self.assertEqual(path.read_bytes(), NEW)

    def test_invalid_built_file_preserves_destination(self):
        path = self.root / 'cache.json'
        path.write_bytes(OLD)

        def raising_validator(candidate):
            raise ValueError('invalid')

        for validate in (lambda p: False, raising_validator):
            for content in (b'', b'invalid'):
                with self.subTest(validate=validate, content=content):
                    with self.assertRaisesRegex(RuntimeError, 'empty or invalid'):
                        cached_file(path, lambda p: p.write_bytes(content), validate)
                    self.assertEqual(path.read_bytes(), OLD)
        self.assertEqual({p.name for p in self.root.iterdir()},
                         {'cache.json', 'cache.json.lock'})

    def test_copy_success_failure_and_replace_failure_cleanup(self):
        src, dst = self.root / 'source.bin', self.root / 'destination.bin'
        src.write_bytes(NEW)
        dst.write_bytes(OLD)
        with self.assertRaises(FileNotFoundError):
            atomic_copy(self.root / 'missing', dst)
        self.assertEqual(dst.read_bytes(), OLD)
        for operation in (lambda: atomic_copy(src, dst),
                          lambda: cached_file(dst, lambda p: p.write_bytes(NEW),
                                              lambda p: p.read_bytes() == NEW)):
            with patch.object(Path, 'replace', side_effect=PermissionError('replace denied')):
                with self.assertRaisesRegex(PermissionError, 'replace denied'):
                    operation()
            self.assertEqual(dst.read_bytes(), OLD)
            self.assertFalse(list(self.root.glob('.destination.*')))
        self.assertEqual(atomic_copy(src, dst), dst)
        self.assertEqual(dst.read_bytes(), NEW)

    def test_exception_releases_lock_and_invalid_timeouts(self):
        path = self.root / 'exception.lock'
        with self.assertRaisesRegex(ValueError, 'body failed'):
            with file_lock(path):
                raise ValueError('body failed')
        with file_lock(path):
            pass
        for timeout in (-1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                with file_lock(path, timeout):
                    pass


if __name__ == '__main__':
    unittest.main()
