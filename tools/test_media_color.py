"""Real encoders: preserve sRGB patch colors and describe their YUV matrix."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

import video
from tools.blender.export_render_job import export


class ColorEncodingTests(unittest.TestCase):
    colors = [(8, 8, 8), (245, 245, 245), (25, 180, 70), (210, 40, 30)]

    def picture(self):
        data = np.zeros((64, 128, 3), dtype=np.uint8)
        for i, color in enumerate(self.colors):
            data[:, i * 32:(i + 1) * 32] = color
        return Image.fromarray(data)

    def verify_movie(self, movie):
        info = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(movie)]))
        stream = info['streams'][0]
        self.assertEqual(stream['color_space'], 'bt709')
        self.assertEqual(stream['color_primaries'], 'bt709')
        self.assertEqual(stream['color_transfer'], 'iec61966-2-1')
        self.assertEqual(stream['color_range'], 'tv')
        self.assertEqual(stream['nb_frames'], '2')
        raw = subprocess.check_output([
            video.ffmpeg_exe(), '-v', 'error', '-i', str(movie), '-frames:v', '1',
            '-vf', 'scale=in_color_matrix=bt709:out_range=pc',
            '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
        decoded = np.frombuffer(raw, np.uint8).reshape(64, 128, 3)
        for i, color in enumerate(self.colors):
            delta = np.abs(decoded[32, i * 32 + 16].astype(int) - color)
            self.assertLessEqual(int(delta.max()), 4, (color, delta.tolist()))

    def test_blender_png_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            scene = folder / 'scene.blend'
            scene.write_bytes(b'color-test-source')
            (folder / 'render_job.json').write_text(json.dumps({
                'schema': 1, 'source': hashlib.sha256(scene.read_bytes()).hexdigest(),
                'size': [128, 64], 'fps': 30}))
            for number in (1, 2):
                frame = folder / f'f{number:04d}.png'
                self.picture().save(frame)
                frame.with_suffix('.sha256').write_text(hashlib.sha256(frame.read_bytes()).hexdigest())
            self.verify_movie(export(scene, folder, 1, 3))

    def test_browser_png_encoder(self):
        with tempfile.TemporaryDirectory() as temporary:
            movie = Path(temporary) / 'browser.mp4'
            image = BytesIO()
            self.picture().save(image, format='PNG')
            with video._png_encoder(movie, False) as pipe:
                pipe.write(image.getvalue() * 2)
            self.verify_movie(movie)


if __name__ == '__main__':
    unittest.main()
