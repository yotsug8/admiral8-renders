"""Process-safe render storage using only the standard library.

Writers must cooperate on the same persistent lock path. Atomic replacement
publishes complete files, but does not promise durability across power loss.
"""
from contextlib import contextmanager
import errno
import math
import os
from pathlib import Path
import shutil
import tempfile
import time


@contextmanager
def file_lock(path, timeout=0):
    """Hold an OS lock; fail fast by default, or poll until timeout seconds.

    Like check.exclusive_check, use msvcrt's first byte on Windows and flock
    elsewhere. Never unlink the lock file: the OS releases it on process exit.
    Locks are not reentrant. Parent directories are created as needed.
    """
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError('timeout must be finite and non-negative')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            acquire = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise RuntimeError(f'Cannot acquire file lock: {path}: {exc}') from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        f'File lock unavailable: {path} (timeout={timeout}s); '
                        'another process may hold it; do not delete the lock file'
                    ) from exc
                time.sleep(min(0.05, remaining))
        try:
            # Windows permits locking beyond EOF. Initialize only after acquiring
            # the byte, so concurrent first users cannot race on initialization.
            if os.name == 'nt':
                lock.seek(0, os.SEEK_END)
                if lock.tell() == 0:
                    lock.write(b'0')
                    lock.flush()
            yield
        finally:
            lock.seek(0)
            release()


def _valid(path, validate):
    try:
        return (path.is_file() and path.stat().st_size > 0
                and (validate is None or bool(validate(path))))
    except Exception:
        return False


@contextmanager
def _temporary(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f'.{destination.stem}.', suffix=destination.suffix,
        dir=destination.parent,
    )
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def cached_file(path, build, validate=None, timeout=600) -> Path:
    """Reuse a nonempty valid file, or build and atomically publish under its lock.

    build(Path) receives a unique, initially empty file beside the destination,
    with the same suffix. It must close its handles before returning. Validator
    exceptions mean invalid; builder exceptions propagate unchanged. A failed
    build/validation/replace leaves the destination untouched.
    """
    path = Path(path)
    with file_lock(str(path) + '.lock', timeout=timeout):
        if _valid(path, validate):
            return path
        with _temporary(path) as temporary:
            build(temporary)
            if not _valid(temporary, validate):
                raise RuntimeError(f'Built cache file is empty or invalid: {path}')
            temporary.replace(path)
    return path


def atomic_copy(src, dst) -> Path:
    """Copy and atomically publish a finished file; caller provides locking.

    Copy/replace errors propagate and leave an existing destination untouched.
    On Windows, readers must close handles or allow delete sharing for replace.
    """
    dst = Path(dst)
    with _temporary(dst) as temporary:
        shutil.copyfile(src, temporary)
        temporary.replace(dst)
    return dst
