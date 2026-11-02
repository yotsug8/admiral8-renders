"""Addressed source-review defects; synthetic local files, no game or GPU."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import analyze_neutral_windows as neutral
import animation_roadmap as roadmap
import assemble_progress
import post_review
import preview_ready_motion
from run_verified import run

FF = imageio_ffmpeg.get_ffmpeg_exe()


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='production-read-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.font = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts/cour.ttf'
        if not self.font.is_file():
            self.font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        if not self.font.is_file():
            raise RuntimeError('A local TTF is required for these regressions')

    def movie(self, name='input.mp4', fps=30, count=3, vfr=False, audio=False):
        path = self.root/name
        cmd = [FF, '-v', 'error', '-y', '-f', 'lavfi', '-i',
               f'testsrc2=size=64x96:rate={fps}:duration={count/fps:.12g}']
        if audio:
            cmd += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={count/fps:.12g}', '-c:a', 'aac']
        if vfr:
            cmd += ['-vf', "settb=1/30000,setpts='if(eq(N,29),29000,(N+0.5*mod(N,2))*1000)'",
                    '-enc_time_base', '1:30000', '-fps_mode', 'passthrough']
        subprocess.run(cmd + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
        return path

    def main(self, module, args):
        with patch.object(sys, 'argv', [module.__file__, *map(str, args)]), contextlib.redirect_stdout(io.StringIO()):
            module.main()

    def test_neutral_relative_angles_ignore_common_world_rotation(self):
        def matrix(degrees):
            t = np.radians(degrees); m = np.eye(4)
            m[:2, :2] = [[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]]
            return m.tolist()
        base = dict(Hips=matrix(0), Head=matrix(0))
        def data(global_angle):
            return dict(rest={'Head': {'parent': 'Hips'}}, samples=[
                dict(frame=i, amc_sample=100+i, bones={
                    'Hips': {'world_matrix': matrix(global_angle)},
                    'Head': {'world_matrix': matrix(global_angle+a)}})
                for i, a in enumerate([0, 0, 30, 60])])
        a = neutral.analyze(data(0), base, 2)
        b = neutral.analyze(data(90), base, 2)
        self.assertEqual(a['best_rolling_by_head_pelvis']['frames'], [0, 1])
        self.assertEqual(len(a['rolling']), 3)
        for ra, rb, expected in zip(a['per_frame'], b['per_frame'], [0, 0, 30, 60]):
            self.assertAlmostEqual(ra['bones']['Head']['pelvis']['angle_from_converter_tpose_deg'], expected)
            self.assertAlmostEqual(rb['bones']['Head']['pelvis']['angle_from_converter_tpose_deg'], expected)
        reflected = np.eye(4); reflected[0, 0] = -1
        with self.assertRaisesRegex(ValueError, 'reflected'):
            neutral.rotation(reflected)

    def test_roadmap_output_aliases_preserve_input(self):
        source = self.root/'data.json'; source.write_text('{}')
        svg, png = self.root/'poster.svg', self.root/'poster.png'
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            roadmap.check_outputs([source, png, png.with_suffix('.json')], [source])
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            roadmap.check_outputs([svg, png, svg], [source])
        link = self.root/'alias.svg'; os.link(source, link)
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            roadmap.check_outputs([link, png, png.with_suffix('.json')], [source])
        roadmap.check_outputs([svg, png, png.with_suffix('.json')], [source])
        self.assertEqual(source.read_text(), '{}')

    def test_roadmap_svg_uses_requested_font_family(self):
        with patch.object(roadmap, 'W', 400), patch.object(roadmap, 'H', 80), patch.object(roadmap, 'SCALE', 1):
            poster = roadmap.Poster(self.font, self.font)
            poster.text(10, 10, 'Test', 20)
        family = ImageFont.truetype(str(self.font), 20).getname()[0]
        self.assertIn(f'font-family="{family},sans-serif"', poster.svg[-1])

    def test_progress_checks_real_timestamps_and_encodes_valid_clip(self):
        source = self.movie(count=30, vfr=True)
        recipe = self.root/'recipe.json'
        spec = dict(fps=30, clips=[dict(file=source.name, frames=30, title='Test', limit='Synthetic')])
        recipe.write_text(json.dumps(spec))
        out = self.root/'report'
        with self.assertRaisesRegex(ValueError, 'Variable video timestamps'):
            self.main(assemble_progress, [recipe, '--assets', self.root, '--out', out, '--font', self.font])
        self.assertFalse(out.exists())
        self.movie(count=3)
        spec['clips'][0]['frames'] = 3; recipe.write_text(json.dumps(spec))
        self.main(assemble_progress, [recipe, '--assets', self.root, '--out', out, '--font', self.font])
        result = json.loads((out/'report.json').read_text())
        self.assertEqual((result['frames'], result['fps']), (3, 30))

    def test_roadmap_svg_picture_mime_matches_bytes(self):
        path = self.root/'renamed.jpg'
        Image.new('RGB', (8, 8), '#567890').save(path, format='PNG')
        with patch.object(roadmap, 'W', 80), patch.object(roadmap, 'H', 80), patch.object(roadmap, 'SCALE', 1):
            poster = roadmap.Poster(self.font, self.font)
            poster.picture(path, 0, 0, 8, 8)
        self.assertIn('data:image/png;base64,', poster.svg[-1])

    def test_post_review_refuses_wrong_fps_before_creating_output(self):
        source = self.movie(fps=15)
        recipe = self.root/'recipe.json'
        spec = dict(fps=30, picture_frames=2, size=[64, 96], ranges=[dict(start=0)])
        recipe.write_text(json.dumps(spec)); out = self.root/'report'
        with self.assertRaisesRegex(ValueError, 'Recipe FPS'):
            self.main(post_review, [source, '--recipe', recipe, '--out', out])
        self.assertFalse(out.exists())
        spec['fps'] = 15; recipe.write_text(json.dumps(spec))
        self.main(post_review, [source, '--recipe', recipe, '--out', out])
        self.assertEqual(len(json.loads((out/'levels.json').read_text())['frames']), 2)

    def test_preview_hash_guard_survives_optimized_python(self):
        poses, recipe = self.root/'poses.json', self.root/'recipe.json'
        poses.write_text('[]'); recipe.write_text(json.dumps({'poses_sha256': 'wrong'}))
        out = self.root/'preview'
        result = subprocess.run([sys.executable, '-B', '-O', str(HERE/'preview_ready_motion.py'),
            str(recipe), '--poses', str(poses), '--out', str(out), '--font', str(self.font)],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Input coordinates changed', result.stderr)
        self.assertFalse(out.exists())
        zero = {s+n: [[0, 0, 0], [0, 0, 0]] for s in ('Left', 'Right') for n in ('Foot', 'ToeBase')}
        with self.assertRaisesRegex(ValueError, 'heading is undefined'):
            preview_ready_motion.forward_axis(zero)

    def test_privet_rejects_single_missing_frame_even_under_optimization(self):
        # Execute the real script against a private synthetic project tree.
        script = self.root/'tools/skit/privet_delivery.py'
        script.parent.mkdir(parents=True); script.write_bytes((HERE/'privet_delivery.py').read_bytes())
        out = self.root/'_game/skits/privet'; (out/'frames').mkdir(parents=True)
        (out/'scene.json').write_text(json.dumps(dict(frames=3, fps=30)))
        for i in range(3):
            Image.new('RGB', (64, 96), '#567890').save(out/'frames'/f'f{i:05d}.png')
        final = out/'privet_draft.mp4'
        def execute():
            return subprocess.run([sys.executable, '-B', '-O', str(script), '--qa-only'],
                env=dict(os.environ, PYTHONPATH=str(HERE)), capture_output=True, text=True)
        final.write_bytes(self.movie(count=2, audio=True).read_bytes())
        failure = execute()
        self.assertNotEqual(failure.returncode, 0)
        self.assertIn('Greeting output frame count', failure.stderr)
        self.assertFalse((out/'delivery_qa.json').exists())
        final.write_bytes(self.movie(count=3, audio=True).read_bytes())
        success = execute()
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(json.loads((out/'delivery_qa.json').read_text())['decoded'], 3)

    def test_verified_run_does_not_accept_hardlink_to_own_receipt(self):
        out = self.root/'run'
        command = [sys.executable, '-B', '-c',
            "import json,os,pathlib,sys,time\np=pathlib.Path(sys.argv[1]); "
            "receipt=p/'run.json'\n"
            "for i in range(100):\n"
            " try:\n"
            "  if json.loads(receipt.read_text())['status']=='running': break\n"
            " except (OSError,ValueError): pass\n"
            " time.sleep(.01)\n"
            "os.link(receipt,p/'result.bin')\n", str(out)]
        with self.assertRaisesRegex(RuntimeError, 'redirected artifact'):
            run(out, ['result.bin'], command, reserve_mb=0, timeout=5)
        self.assertEqual(json.loads((out/'run.json').read_text())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
