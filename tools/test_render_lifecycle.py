"""Real encoder and HTTP lifecycle checks; no GPU, TTS or external network."""
from io import BytesIO
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video


class RenderLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'chunk.mp4'
        self.processes = []
        real_popen = subprocess.Popen

        def record(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            self.processes.append(process)
            return process

        self.patch = patch.object(video.subprocess, 'Popen', side_effect=record)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def png(self):
        image = BytesIO()
        video.Image.new('RGB', (16, 16), 'red').save(image, format='PNG')
        return image.getvalue()

    def assert_reaped(self):
        self.assertEqual(len(self.processes), 1)
        self.assertIsNotNone(self.processes[0].poll())
        self.assertTrue(self.processes[0].stdin.closed)

    def test_success_finishes_encoder(self):
        with video._png_encoder(self.output, False) as pipe:
            pipe.write(self.png() * 3)
        self.assert_reaped()
        self.assertEqual(self.processes[0].returncode, 0)
        self.assertGreater(self.output.stat().st_size, 0)

    def test_frame_failure_does_not_leave_encoder(self):
        with self.assertRaisesRegex(RuntimeError, 'frame failed'):
            with video._png_encoder(self.output, False) as pipe:
                pipe.write(self.png())
                raise RuntimeError('frame failed')
        self.assert_reaped()

    def test_bad_stream_is_reported_as_failure(self):
        with self.assertRaises(subprocess.CalledProcessError):
            with video._png_encoder(self.output, False) as pipe:
                pipe.write(b'not a PNG stream')
        self.assert_reaped()
        self.assertNotEqual(self.processes[0].returncode, 0)

    def test_failed_browser_start_does_not_start_encoder(self):
        context = Mock()
        context.__enter__ = Mock(return_value=context)
        context.__exit__ = Mock(return_value=False)
        context.chromium.launch.side_effect = RuntimeError('browser failed')
        with patch('playwright.sync_api.sync_playwright', return_value=context):
            with self.assertRaisesRegex(RuntimeError, 'browser failed'):
                video._render_chunk(({}, [0], set(), self.output, False))
        self.assertEqual(self.processes, [])

    def test_server_socket_closed_on_success_and_failure(self):
        opener = build_opener(ProxyHandler({}))
        for fail in (False, True):
            with self.subTest(failure=fail):
                try:
                    with video._frame_server() as root:
                        port = urlsplit(root).port
                        with opener.open(root + 'video.html', timeout=3) as response:
                            self.assertEqual(response.status, 200)
                        if fail:
                            raise RuntimeError('render failed')
                except RuntimeError as exc:
                    self.assertEqual(str(exc), 'render failed')
                with socket.socket() as sock:
                    sock.settimeout(1)
                    self.assertNotEqual(sock.connect_ex(('127.0.0.1', port)), 0)

    def test_frame_failure_closes_browser_and_encoder(self):
        context = Mock()
        context.__enter__ = Mock(return_value=context)
        context.__exit__ = Mock(return_value=False)
        browser = context.chromium.launch.return_value
        page = browser.new_page.return_value
        page.evaluate.side_effect = [None, RuntimeError('seek failed')]
        with patch('playwright.sync_api.sync_playwright', return_value=context):
            with self.assertRaisesRegex(RuntimeError, 'seek failed'):
                video._render_chunk(({}, [0], set(), self.output, False))
        browser.close.assert_called_once()
        self.assert_reaped()


if __name__ == '__main__':
    unittest.main()
