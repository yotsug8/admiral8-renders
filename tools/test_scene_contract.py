"""Reject ambiguous scene IDs/time references before voice and browser rendering."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import video
from tools import check
from tools import test_resource_loading as resources


class SceneContractTests(unittest.TestCase):
    def errors(self, scene):
        with contextlib.redirect_stdout(io.StringIO()):
            return video.check_scene(scene, 'fixture')

    def test_duplicate_ids_and_inherited_ids_are_rejected(self):
        for items in ([{'id': 'a'}, {'id': 'a'}],
                      [{'id': 'a', 'type': 'panel', 'items': [{'id': 'a'}]}],
                      [{'type': 'panel', 'child': {'id': 'shared'}, 'items': [{}, {}]}]):
            self.assertTrue(any('повторный id' in e for e in self.errors({'items': items})))

    def test_all_timing_fields_are_checked(self):
        for field in ('at', 'start'):
            for value in ('missing+.2', 'declared+1..2', True, float('nan'), []):
                with self.subTest(field=field, value=value):
                    self.assertTrue(self.errors({'cues': {'declared': 'слово'}, 'items': [{field: value}]}))
        self.assertEqual(self.errors({'at': {'cue': 0}, 'items': [
            {'id': 'x', 'start': 'cue+.25', 'at': 0}, {'start': -.2}]}), [])

    def test_invalid_scene_never_calls_voice(self):
        with patch.object(video, 'speak', side_effect=AssertionError('voice must not run')) as speak:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                video.prepare({'parts': [{'voice': 'текст', 'scene': {'items': [{'start': 'missing'}]}}]}, {}, {})
            speak.assert_not_called()

    def test_missing_cue_in_mixer_is_an_error_not_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            segment = dict(start=0, dur=.5, _pcm=np.zeros(0),
                           scene={'sounds': [{'kind': 'pop', 'at': 'missing+.2'}]})
            with self.assertRaisesRegex(ValueError, 'missing'):
                video.mix_audio([segment], .5, Path(tmp) / 'out.wav')
            self.assertFalse((Path(tmp) / 'out.wav').exists())

    def test_game_detection_uses_json_structure(self):
        cases = [({'parts': [{'scene': {'items': [{'type': 'model'}]}}]}, True),
                 ({'parts': [{'scene': {'items': [{'type': 'stage'}]}}]}, True),
                 ({'src': 'file:_game\\models\\a.glb'}, True),
                 ({'src': 'game:hero'}, True),
                 ({'voice': 'пример "type": "model" в тексте'}, False),
                 ({'src': 'file:assets/a.png'}, False)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'scene.json'
            for data, expected in cases:
                for indent in (None, 2):
                    path.write_text(json.dumps(data, indent=indent, separators=(',', ':') if indent is None else None), encoding='utf-8')
                    self.assertEqual(check.needs_game(path), expected)


class BrowserSceneContractTests(unittest.TestCase):
    setUpClass = classmethod(resources.ResourceLoadingTests.setUpClass.__func__)
    setUp = resources.ResourceLoadingTests.setUp
    tearDown = resources.ResourceLoadingTests.tearDown
    reload = resources.ResourceLoadingTests.reload
    outcome = resources.ResourceLoadingTests.outcome

    def data(self, items, **scene):
        return resources.ResourceLoadingTests.data(scene=dict(camera=False, items=items, **scene))

    def test_duplicate_parent_or_sibling_id_rejects_init(self):
        for items in ([{'id': 'a'}, {'id': 'a'}],
                      [{'id': 'a', 'type': 'panel', 'items': [{'id': 'a'}]}]):
            self.reload()
            result = self.outcome('init(arg)', self.data(items))
            self.assertFalse(result['ok'])
            self.assertIn('повторный id', result['error'])

    def test_unknown_or_malformed_cue_does_not_start_at_zero(self):
        for value in ('missing', 'missing+.2', 'ok+1..2', True):
            self.reload()
            item = dict(type='text', id='test', text='Текст', x=100, y=300, w=400, h=300,
                        **{'in': {'fx': 'fade', 'at': value}})
            result = self.outcome('init(arg)', self.data([item], at={'ok': .3}))
            self.assertFalse(result['ok'])
            self.assertIn('метка времени', result['error'])

    def test_valid_zero_and_cue_and_prototype_named_id(self):
        items = [dict(type='text', id='__proto__', text='Текст', x=100, y=300, w=400, h=300,
                      **{'in': {'fx': 'fade', 'at': 'ok+.2'}})]
        self.assertEqual(self.outcome('init(arg)', self.data(items, at={'ok': 0})), {'ok': True})
        self.page.evaluate('seek(.5)')


if __name__ == '__main__':
    unittest.main()
