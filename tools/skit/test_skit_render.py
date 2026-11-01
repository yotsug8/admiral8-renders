"""Регрессии повторной сборки: команды, старый хвост и остановка при сбое.

Запуск: py -3.11 -m unittest discover -s tools/skit -p test_skit_render.py -v
Blender/озвучка подменены; короткий MP4 кодируется настоящим FFmpeg.
Временные результаты сохраняются, файлы не удаляются.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import imageio_ffmpeg
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skit
import voices


class SkitRenderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="skit_render_test_"))
        self.folder = self.root / "_game" / "skits" / "sample"
        self.folder.mkdir(parents=True)

    def pipeline(self, runner, frames=7, fps=24):
        """Подменяем подготовку сцены, но вызываем настоящие main и render."""
        def build(*args):
            (self.folder / "scene.json").write_text(json.dumps(
                {"frames": frames, "fps": fps, "dur": 99.125}), encoding="utf-8")
            return None, {}, {}, [], 99.125

        stack = ExitStack()
        stack.enter_context(patch.object(skit, "REPO", str(self.root)))
        stack.enter_context(patch.object(skit, "parse", return_value={
            "name": "sample", "cast": {}, "events": []}))
        stack.enter_context(patch.object(skit, "build", side_effect=build))
        stack.enter_context(patch.object(voices, "make", return_value={}))
        stack.enter_context(patch.object(sys, "argv", ["skit.py", "sample.txt", "--all"]))
        stack.enter_context(patch.object(sys, "stdout", Mock()))
        stack.enter_context(patch.dict(os.environ, {"SKIT_FAKE": ""}))
        stack.enter_context(patch.object(skit.subprocess, "run", side_effect=runner))
        return stack

    def test_render_requests_overwrite_and_python_failure_exit(self):
        for frames, half in [(None, False), ([0, 9], True)]:
            with self.subTest(frames=frames), \
                    patch.dict(os.environ, {"A8_REDO": "", "SKIT_TEST_KEEP": "yes"}), \
                    patch.object(skit.subprocess, "run") as run:
                out = skit.render(str(self.folder), frames, half)
                cmd = run.call_args.args[0]
                opts = run.call_args.kwargs
                self.assertEqual(cmd[cmd.index("--") + 1:], [
                    str(self.folder / "scene.json"), out,
                    "0,9" if frames else "all", *(["half"] if half else [])])
                self.assertLess(cmd.index("--python-exit-code"), cmd.index("-P"))
                self.assertNotEqual(int(cmd[cmd.index("--python-exit-code") + 1]), 0)
                self.assertTrue(opts["check"])
                self.assertEqual(opts["env"]["A8_REDO"], "1")
                self.assertEqual(opts["env"]["SKIT_TEST_KEEP"], "yes")
                self.assertEqual(os.environ["A8_REDO"], "")

    def test_all_encodes_only_current_frames_at_scene_fps(self):
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        real_run = subprocess.run
        # Включая N=1: нельзя потерять последний кадр или включить первый старый.
        for count, fps in [(7, 24), (1, 30)]:
            with self.subTest(count=count, fps=fps):
                folder = self.folder / "frames"
                folder.mkdir(exist_ok=True)
                for i in range(12):
                    Image.new("RGB", (16, 16), "green" if i < count else "red").save(
                        folder / f"f{i:05d}.png")
                before = {p.name: p.read_bytes() for p in folder.iterdir()}
                calls = []

                def run(cmd, **kwargs):
                    calls.append(cmd)
                    if cmd[0] == ff:
                        return real_run(cmd, **kwargs)
                    return subprocess.CompletedProcess(cmd, 0)

                with self.pipeline(run, count, fps):
                    skit.main()
                self.assertEqual(len(calls), 3)
                raw = self.folder / "sample_raw.mp4"
                n, seconds = imageio_ffmpeg.count_frames_and_secs(str(raw))
                self.assertEqual(n, count)
                self.assertAlmostEqual(seconds, count / fps, delta=0.011)
                decoded = real_run([ff, "-v", "error", "-i", str(raw),
                                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                   check=True, capture_output=True).stdout
                self.assertEqual(len(decoded), count * 16 * 16 * 3)
                self.assertTrue(all(g > r + 50 for r, g in zip(decoded[0::3], decoded[1::3])))
                self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_all_propagates_each_process_failure_without_next_step(self):
        folder = self.folder / "frames"
        folder.mkdir()
        for i in range(7):
            Image.new("RGB", (16, 16), "green").save(folder / f"f{i:05d}.png")
        for failed_step in range(3):
            with self.subTest(failed_step=failed_step):
                calls = []
                error = subprocess.CalledProcessError(17, "failed process")

                def run(cmd, **kwargs):
                    calls.append(cmd)
                    self.assertTrue(kwargs["check"])
                    if len(calls) == failed_step + 1:
                        raise error
                    return subprocess.CompletedProcess(cmd, 0)

                with self.pipeline(run), self.assertRaises(subprocess.CalledProcessError) as caught:
                    skit.main()
                self.assertIs(caught.exception, error)
                self.assertEqual(len(calls), failed_step + 1)

    def test_all_rejects_missing_or_empty_frame_before_encoding(self):
        # Начало, середина и последний кадр; никаких удалений исходных файлов.
        for bad_frame in (0, 3, 6):
            for empty in (False, True):
                with self.subTest(bad_frame=bad_frame, empty=empty):
                    folder = self.folder / f"incomplete_{bad_frame}_{empty}"
                    folder.mkdir()
                    for i in range(9):  # старый хвост не компенсирует дыру
                        path = folder / f"f{i:05d}.png"
                        if i != bad_frame:
                            Image.new("RGB", (16, 16), "green").save(path)
                        elif empty:
                            path.write_bytes(b"")
                    run = Mock()
                    with self.pipeline(run), \
                            patch.object(skit, "render", return_value=str(folder)) as render, \
                            self.assertRaisesRegex(RuntimeError, f"f{bad_frame:05d}\\.png"):
                        skit.main()
                    render.assert_called_once_with(str(self.folder))
                    run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
