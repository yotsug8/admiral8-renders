"""Regression check for lossless MP4 assembly across track time bases."""

from fractions import Fraction
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().with_name('blender')))
from assemble_shots import (FF, assemble, cut_frames, cut_mp4_timing, mux_wav, picture_hashes,
                            replace_frames, video_timing)
from run_render_job import join_project_audio, run_project


class AssembleShotsTest(unittest.TestCase):
    @staticmethod
    def make_clip(clip, color, timescale, frames):
        subprocess.run([FF, '-nostdin', '-v', 'error', '-f', 'lavfi',
                        '-i', f'color={color}:s=160x96:r=30',
                        '-frames:v', str(frames), '-c:v', 'libx264',
                        '-video_track_timescale', str(timescale), str(clip)],
                       check=True)

    def test_different_track_time_bases(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            clips = []
            for index, (color, timescale, frames) in enumerate(
                    (('blue', 15360, 8), ('orange', 90000, 7))):
                clip = root / f'clip-{index}.mp4'
                self.make_clip(clip, color, timescale, frames)
                clips.append(clip)

            output = assemble(clips, root / 'joined.mp4')
            timing = video_timing(output)
            self.assertEqual((timing['fps'], timing['count']), (Fraction(30), 15))
            self.assertEqual(picture_hashes(output),
                             picture_hashes(clips[0]) + picture_hashes(clips[1]))

    def test_replace_frames_preserves_surrounding_picture_and_previous_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, insert, output = (root / name for name in ('base.mp4', 'insert.mp4', 'edited.mp4'))
            self.make_clip(base, 'blue', 15360, 12)
            self.make_clip(insert, 'orange', 90000, 4)
            replace_frames(base, insert, 3, output)
            original = picture_hashes(base)
            self.assertEqual(picture_hashes(output), original[:3] + picture_hashes(insert) + original[7:])
            previous = output.read_bytes()
            with self.assertRaisesRegex(ValueError, 'диапазон'):
                replace_frames(base, insert, 10, output)
            self.assertEqual(output.read_bytes(), previous)

    def test_lossless_assembly_with_revised_clip(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, insert, edited = (root / name for name in ('base.mp4', 'insert.mp4', 'edited.mp4'))
            self.make_clip(base, 'blue', 15360, 12)
            self.make_clip(insert, 'orange', 15360, 4)
            replace_frames(base, insert, 3, edited)

            output = assemble([base, edited], root / 'project.mp4', lossless=True)
            timing = video_timing(output)
            self.assertEqual((timing['fps'], timing['count']), (Fraction(30), 24))
            self.assertEqual(picture_hashes(output), picture_hashes(base) + picture_hashes(edited))

    def test_cut_keeps_audio_on_the_retained_picture_timeline(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            picture, base, output = (root / name for name in ('picture.mp4', 'base.mp4', 'edited.mp4'))
            self.make_clip(picture, 'blue', 15360, 12)
            samples = [0] * 19200
            for first in (2400, 14400):
                samples[first:first+320] = [10000, 10000, -10000, -10000] * 80
            wav = root / 'input.wav'
            with wave.open(str(wav), 'wb') as audio:
                audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                audio.writeframes(struct.pack(f'<{len(samples)}h', *samples))
            mux_wav(picture, wav, base, len(samples), 1)
            cut_frames(base, output, 4, 7, cut_mp4_timing(base))
            timing = cut_mp4_timing(output)
            self.assertEqual((timing['count'], timing['audio_channels']), (9, 1))
            with wave.open(str(root / 'cut-audio.wav'), 'rb') as audio:
                self.assertEqual(audio.getnframes(), 14400)
                for first in (2400, 9600):
                    audio.setpos(first)
                    signal = struct.unpack('<320h', audio.readframes(320))
                    self.assertGreater(max(signal), 5000)
                audio.setpos(14400 - 2000)
                self.assertLess(max(struct.unpack('<2000h', audio.readframes(2000))), 20)

    def test_project_audio_pads_short_tracks_and_counts_cumulative_samples(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, last, joined = (root / f'{name}.wav' for name in ('first', 'last', 'joined'))
            for path, rate in ((first, 24000), (last, 48000)):
                with wave.open(str(path), 'wb') as audio:
                    audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                    audio.writeframes(struct.pack('<h', 12000) * (rate // 10))
            jobs = [(dict(fps=29, frames=[0, count]), None, None, wav)
                    for count, wav in ((7, first), (3, None), (5, last))]
            join_project_audio(jobs, joined)
            with wave.open(str(joined), 'rb') as audio:
                self.assertEqual((audio.getframerate(), audio.getnchannels()), (48000, 2))
                self.assertEqual(audio.getnframes(), 15 * 48000 // 29)
                left, right = struct.unpack('<hh', audio.readframes(1))
                self.assertGreater(left, 0)
                self.assertEqual(left, right)
                audio.setpos(5000)
                last_start = 10 * 48000 // 29
                self.assertEqual(audio.readframes(last_start - 5000), b'\0' * (4 * (last_start - 5000)))
                left, right = struct.unpack('<hh', audio.readframes(1))
                self.assertGreater(left, 0)
                self.assertEqual(left, right)

    def test_project_rejects_changed_audio_before_replacing_result(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            clip, wav, output = (root / name for name in ('shot.mp4', 'audio.wav', 'project.mp4'))
            self.make_clip(clip, 'blue', 15360, 8)

            def write_sound(sample):
                with wave.open(str(wav), 'wb') as audio:
                    audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(struct.pack('<h', sample) * 12800)

            write_sound(0)
            (root / 'scene.blend').touch()
            job = dict(schema_version=1, scene='scene.blend', out='frames', frames=[1, 9],
                       size=[160, 96], fps=30)
            project = root / 'project.json'

            def staged_shot(*args, snapshot, **kwargs):
                shutil.copyfile(clip, snapshot)
                return snapshot

            def change_during_render(*args, **kwargs):
                write_sound(12000)
                return staged_shot(*args, **kwargs)

            for mode in ('shared', 'shots'):
                with self.subTest(mode=mode):
                    write_sound(0)
                    scene_job = dict(job, wav=wav.name) if mode == 'shots' else job
                    (root / 'job.json').write_text(json.dumps(scene_job), encoding='utf-8')
                    audio = {'audio': 'shots'} if mode == 'shots' else {'wav': wav.name}
                    config = dict(schema_version=1, shots=['job.json'] * 2, out=output.name, **audio)
                    project.write_text(json.dumps(config), encoding='utf-8')
                    with patch('run_render_job.check_tools'), patch('run_render_job.render_job', staged_shot):
                        run_project(project)
                    previous = output.read_bytes()
                    stamp = output.stat().st_mtime_ns
                    with (patch('run_render_job.check_tools'),
                          patch('run_render_job.render_job', change_during_render),
                          self.assertRaisesRegex(ValueError, 'WAV изменился')):
                        run_project(project)
                    self.assertEqual(output.read_bytes(), previous)
                    self.assertEqual(output.stat().st_mtime_ns, stamp)

    def test_project_keeps_one_scene_version_across_shots(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            clip, scene, output = (root / name for name in ('shot.mp4', 'shared.blend', 'project.mp4'))
            self.make_clip(clip, 'blue', 15360, 8)
            shutil.copyfile(clip, output)
            previous = output.read_bytes()
            stamp = output.stat().st_mtime_ns
            scene.write_bytes(b'original')
            job = dict(schema_version=1, scene=scene.name, out='frames', frames=[1, 9],
                       size=[160, 96], fps=30)
            (root / 'job.json').write_text(json.dumps(job), encoding='utf-8')
            project = root / 'project.json'
            config = dict(schema_version=1, shots=['job.json'] * 2, out=output.name)
            project.write_text(json.dumps(config), encoding='utf-8')
            sources = []

            def change_between_shots(job, source, folder, wav, *, snapshot, variant):
                sources.append(source)
                self.assertEqual(source.read_bytes(), b'original')
                if len(sources) == 1:
                    scene.write_bytes(b'changed')
                shutil.copyfile(clip, snapshot)
                return snapshot

            with (patch('run_render_job.check_tools'),
                  patch('run_render_job.render_job', change_between_shots),
                  self.assertRaisesRegex(ValueError, r'\.blend изменился')):
                run_project(project)
            self.assertEqual(len(sources), 2)
            self.assertEqual(sources[0], sources[1])
            self.assertNotEqual(sources[0], scene)
            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(output.stat().st_mtime_ns, stamp)


if __name__ == '__main__':
    unittest.main()
