"""F06/F07: offline speech alignment, real PCM mixing and Chromium canvas seeks.

Run: py -3.11 -m unittest tools.test_media_timing -v
No network, game assets, real TTS, shared WORK or video.html required.
"""
import base64
import copy
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video

ROOT = Path(__file__).resolve().parents[1]


def write_pcm(path, samples):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(video.SR)
        out.writeframes(np.asarray(samples, dtype=np.int16).tobytes())


def read_pcm(path):
    with wave.open(str(path)) as source:
        return np.frombuffer(source.readframes(source.getnframes()), np.int16)


class SpeechTests(unittest.TestCase):
    text = '[calm] Патч {7.33|семь тридцать три} || {Тайдбрингер|тайдбрИнгер} снова.'
    spoken = [('Патч', 0, .2), ('семь', .3, .5), ('тридцать', .6, .8),
              ('три', .9, 1.1), ('тайдбрИнгер', 1.2, 1.5), ('снова', 1.6, 2)]

    def assert_script(self, words):
        self.assertEqual([w[0] for w in words], ['Патч', '7.33', 'Тайдбрингер', 'снова'])
        self.assertAlmostEqual(video.cue_time(words, '7.33'), .3)
        self.assertAlmostEqual(video.cue_time(words, '7.33:end'), 1.1)
        self.assertAlmostEqual(video.cue_time(words, 'Тайдбрингер'), 1.2)

    def test_edge_and_fish_failure_keep_display_words_and_cues(self):
        for key in ('', 'offline-test-key'):
            with self.subTest(fish=bool(key)), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, {}, clear=True), \
                    patch.object(video, 'HERE', Path(tmp)), patch.object(video, 'FISH_KEY', key), \
                    patch.object(video, 'tts_fish', side_effect=RuntimeError('offline failure')), \
                    patch.object(video, 'tts', return_value=self.spoken) as edge, \
                    patch.object(video, 'align_words', side_effect=AssertionError('ASR forbidden')):
                self.assert_script(video.speak(self.text, Path(tmp) / 'voice.mp3'))
                self.assertEqual(edge.call_args.args[0], 'Патч семь тридцать три   тайдбрИнгер снова.')

    def test_fake_tts_real_silent_file_uses_display_form(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {'FV_FAKE_TTS': '1'}, clear=True), \
                patch.object(video, 'tts_fish', side_effect=AssertionError('TTS forbidden')), \
                patch.object(video, 'align_words', side_effect=AssertionError('ASR forbidden')):
            path = Path(tmp) / 'fake.mp3'
            words = video.speak(self.text, path)
            self.assertEqual([w[0] for w in words], ['Патч', '7.33', 'Тайдбрингер', 'снова'])
            self.assertAlmostEqual(video.cue_time(words, '7.33'), .34)
            self.assertAlmostEqual(video.cue_time(words, '7.33:end'), 1.32)
            self.assertGreater(len(video.mp3_to_pcm(path)), video.SR)
            self.assertEqual(np.max(np.abs(video.mp3_to_pcm(path))), 0)


class ChildDefaultsTests(unittest.TestCase):
    def test_nested_defaults_resolved_once_before_media_and_explicit_overrides_win(self):
        source = {'items': [{'type': 'panel', 'child': {'type': 'row', 'w': 220, 'h': 90},
                             'items': [{'gap': 20, 'child': {
                                 'type': 'video', 'src': 'file:unused', 'audio': .5,
                                 'start': 2, 'loop': True, 'hold': False,
                             }, 'items': [{'id': 'a', 'start': 0}, {'id': 'b', 'audio': 0}]}]}]}
        original = copy.deepcopy(source)
        with patch.object(video, 'video_frames', return_value={'fps': 10, 'frames': ['local']}) as frames:
            result = video.resolve_scene(source, {}, {})
        self.assertEqual(source, original)
        self.assertEqual(frames.call_count, 2)  # the child template itself must not load resources
        row = result['items'][0]['items'][0]
        self.assertNotIn('child', row)
        self.assertNotIn('child', result['items'][0])
        a, b = row['items']
        self.assertEqual((a['w'], a['h'], b['x']), (100, 90, 120))
        self.assertEqual((a['start'], a['audio'], b['start'], b['audio']), (0, .5, 2, 0))
        self.assertTrue(a['loop'])
        self.assertFalse(a['hold'])
        self.assertNotIn('src', a)
        self.assertEqual(frames.call_args_list[0].args[0]['w'], 100)

    def test_real_inherited_video_extracts_frames_and_audio_in_isolated_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav, clip = root / 'source.wav', root / 'source.mkv'
            write_pcm(wav, np.full(video.SR, 2000))
            subprocess.run([video.ffmpeg_exe(), '-y', '-loglevel', 'error',
                            '-f', 'lavfi', '-i', 'color=red:s=32x32:r=30:d=1',
                            '-i', str(wav), '-c:v', 'ffv1', '-c:a', 'pcm_s16le', str(clip)], check=True)
            source = {'items': [{'type': 'col', 'w': 32, 'h': 64, 'gap': 0,
                                 'child': {'type': 'video', 'src': 'file:' + clip.as_posix(),
                                           'audio': .5, 'dur': .2, 'start': 0},
                                 'items': [{}, {'audio': 0}]}]}
            with patch.object(video, 'WORK', root / 'work'):
                resolved = video.resolve_scene(source, {}, {})
            first, second = resolved['items'][0]['items']
            self.assertEqual((first['w'], first['h']), (32, 32))
            self.assertEqual(len(first['clip']['frames']), 6)
            self.assertIn('wav', first['clip'])
            self.assertNotIn('wav', second['clip'])
            with Image.open(next((root / 'work').glob('vid_*/*.jpg'))) as image:
                self.assertEqual(image.size, (32, 32))
            segment = dict(start=0, dur=.1, _pcm=np.zeros(0), scene=resolved)
            with patch.dict(os.environ, {}, clear=True):
                video.mix_audio([segment], .1, root / 'mixed.wav')
            mixed = read_pcm(root / 'mixed.wav')
            self.assertTrue(np.all(mixed[:4410] == 999))
            self.assertTrue(np.all(mixed[4410:] == 0))


class MediaTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(args=['--disable-gpu'])
        cls.frames = []
        for color in ('red', 'lime', 'blue'):
            stream = BytesIO()
            Image.new('RGB', (4, 4), color).save(stream, format='PNG')
            cls.frames.append('data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode())

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wav = self.root / 'source.wav'
        self.period = video.SR * 3 // 10
        self.samples = np.repeat([2000, 4000, 6000], video.SR // 10)
        write_pcm(self.wav, self.samples)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.route('http://**/*', lambda route: route.abort())
        self.page.route('https://**/*', lambda route: route.abort())
        self.page.set_content('<div id="preload" hidden></div><div id="root"></div>')
        self.page.evaluate('''() => { window.$ = (tag, cls, parent) => {
            const el = document.createElement(tag); if (cls) el.className = cls;
            if (parent) parent.appendChild(el); return el;
        }; }''')
        for script in ('vendor/gsap/gsap.min.js', 'vendor/gsap/SplitText.min.js',
                       'scene.js'):
            self.page.add_script_tag(path=str(ROOT / script))

    def item(self, **options):
        return dict(type='video', id='clip', w=4, h=4, audio=1,
                    clip=dict(fps=10, frames=self.frames, wav=str(self.wav)), **options)

    def mix(self, item, dur=1, start=0, total=None, cues=None):
        scene = dict(camera=False, at=cues or {}, items=[item])
        segment = dict(start=start, dur=dur, _pcm=np.zeros(0), scene=scene)
        target = self.root / 'mixed.wav'
        with patch.dict(os.environ, {}, clear=True):
            video.mix_audio([segment], start + dur if total is None else total, target)
        return read_pcm(target), scene

    def build(self, scene, dur=1):
        self.page.evaluate('''async ({scene, dur}) => {
            document.getElementById('root').replaceChildren();
            window.g = {s:{scene, dur}, el:document.getElementById('root'), parts:{}};
            SCN.build(g);
            await Promise.all(g.sc.vids.flatMap(v => v.imgs.map(im => im.decode())));
            SCN.timeline(g, false);
        }''', dict(scene=scene, dur=dur))

    def draw(self, time):
        return self.page.evaluate('''t => {
            SCN.draw(g, t); const v = g.sc.vids[0];
            return {visible:getComputedStyle(v.cv.parentNode).visibility === 'visible',
                    pixel:Array.from(v.cv.getContext('2d').getImageData(0,0,1,1).data).slice(0,3),
                    start:v.t0};
        }''', time)

    def assert_pcm(self, pcm, expected):
        np.testing.assert_allclose(pcm, np.asarray(expected) / 32768 * 32767, atol=1)

    def test_nullish_start_zero_and_cue_offsets_match_real_js(self):
        cases = [({'start': 0, 'in': {'at': .5}, 'at': .7}, 0),
                 ({'in': {'at': 0}, 'at': .7}, 0),
                 ({'start': None, 'in': {'at': 0}, 'at': .7}, 0),
                 ({'in': {'at': None}, 'at': .2}, .2),
                 ({'in': None, 'at': .2}, .2),
                 ({'start': 'cue-0.1', 'at': .7}, .3),
                 ({'in': 'none', 'at': 'cue+0.1'}, .5), ({}, 0)]
        for options, start in cases:
            with self.subTest(options=options):
                pcm, scene = self.mix(self.item(hold=False, **options), cues={'cue': .4})
                expected = np.zeros(len(pcm))
                begin = round(start * video.SR)
                expected[begin:begin + self.period] = self.samples
                self.assert_pcm(pcm, expected)
                self.build(scene)
                self.assertAlmostEqual(self.draw(start)['start'], start)
                self.assertFalse(self.draw(start - .001)['visible'])
                self.assertEqual(self.draw(start + .15)['pixel'], [0, 255, 0])
                self.assertFalse(self.draw(start + .301)['visible'])

    def test_loop_hold_false_repeats_pcm_and_pixels_until_segment_end_and_reverse_seek(self):
        pcm, scene = self.mix(self.item(start=.2, loop=True, hold=False), dur=.95)
        expected = np.zeros(len(pcm))
        expected[8820:41895] = np.resize(self.samples, 33075)
        self.assert_pcm(pcm, expected)
        self.build(scene, .95)
        for t, visible, pixel in [(.199, False, [255, 0, 0]), (.25, True, [255, 0, 0]),
                                  (.55, True, [255, 0, 0]), (.65, True, [0, 255, 0]),
                                  (.949, True, [0, 255, 0]), (.95, False, [0, 255, 0]),
                                  (.25, True, [255, 0, 0]), (.199, False, [255, 0, 0])]:
            with self.subTest(t=t):
                state = self.draw(t)
                self.assertEqual((state['visible'], state['pixel']), (visible, pixel))

    def test_hold_only_extends_still_image_not_audio(self):
        for hold in (False, True):
            with self.subTest(hold=hold):
                pcm, scene = self.mix(self.item(start=.2, hold=hold))
                expected = np.zeros(len(pcm))
                expected[8820:22050] = self.samples
                self.assert_pcm(pcm, expected)
                self.build(scene)
                self.assertEqual(self.draw(.1)['visible'], hold)
                self.assertEqual(self.draw(.6)['visible'], hold)
                self.assertEqual(self.draw(.6)['pixel'], [0, 0, 255])
                self.assertFalse(self.draw(1)['visible'])

    def test_short_audio_is_padded_long_audio_trimmed_at_visual_period(self):
        for size in (video.SR // 10, video.SR):
            for loop in (False, True):
                with self.subTest(size=size, loop=loop):
                    source = np.full(size, 2000)
                    source[self.period:] = 9000  # distinctive tail must never enter the mix
                    write_pcm(self.wav, source)
                    pcm, _ = self.mix(self.item(loop=loop, hold=False), dur=.75)
                    cycle = np.zeros(self.period)
                    cycle[:min(size, self.period)] = 2000
                    expected = np.zeros(len(pcm))
                    length = 33075 if loop else self.period
                    expected[:length] = np.resize(cycle, length)
                    self.assert_pcm(pcm, expected)

    def test_normalized_child_defaults_drive_pcm_and_browser(self):
        panel = {'type': 'panel', 'child': self.item(start=0, loop=True, hold=False),
                 'items': [{'at': .8}]}
        resolved = video.resolve_scene(panel, {}, {})
        pcm, scene = self.mix(resolved, dur=.75)
        expected = np.zeros(len(pcm))
        expected[:33075] = np.resize(self.samples, 33075)
        self.assert_pcm(pcm, expected)
        self.build(scene, .75)
        state = self.draw(.65)
        self.assertEqual((state['start'], state['visible'], state['pixel']), (0, True, [255, 0, 0]))
        self.assertFalse(self.draw(.75)['visible'])

    def test_negative_start_preserves_phase_and_late_start_is_silent(self):
        for loop in (False, True):
            with self.subTest(loop=loop):
                pcm, scene = self.mix(self.item(start=-.1, loop=loop, hold=False), dur=.5)
                expected = np.zeros(len(pcm))
                length = 22050 if loop else 8820
                expected[:length] = np.resize(self.samples, length + 4410)[4410:]
                self.assert_pcm(pcm, expected)
                self.build(scene, .5)
                self.assertEqual(self.draw(0)['pixel'], [0, 255, 0])
        pcm, _ = self.mix(self.item(start=2, loop=True, hold=False))
        self.assertFalse(np.any(pcm))

    def test_segment_and_total_boundaries_no_audio_leak(self):
        # Subtract the identical mixer baseline to isolate clip PCM from the transition SFX.
        for total, end in ((1.5, .75), (.6, .6)):
            with self.subTest(total=total):
                pcm, _ = self.mix(self.item(start=-.1, loop=True, hold=False),
                                  start=.5, dur=.25, total=total)
                muted = self.item(start=-.1, loop=True, hold=False)
                muted['audio'] = 0
                baseline, _ = self.mix(muted, start=.5, dur=.25, total=total)
                diff = pcm.astype(float) - baseline
                begin, stop = round(.5 * video.SR), round(end * video.SR)
                expected = np.zeros(len(pcm))
                expected[begin:stop] = np.resize(self.samples, stop - begin + 4410)[4410:]
                # Two independently truncated int16 renders: <2 LSB error in their difference.
                np.testing.assert_allclose(diff, expected / 32768 * 32767, atol=2)
                self.assertTrue(np.array_equal(pcm[:begin], baseline[:begin]))
                self.assertTrue(np.array_equal(pcm[stop:], baseline[stop:]))


if __name__ == '__main__':
    unittest.main()
