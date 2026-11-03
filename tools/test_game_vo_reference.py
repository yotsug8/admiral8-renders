"""Reference-cache language regressions; no game resources, ASR model or network."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'skit'))
import game_vo
import voices


class ReferenceLanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        context = patch.object(game_vo, 'VO', str(self.folder))
        context.start()
        self.addCleanup(context.stop)
        self.wav = self.folder / 'ref_axe.wav'
        self.wav.write_bytes(b'unchanged test audio')
        self.meta = self.folder / 'ref_axe.json'

    def write_metadata(self, **extra):
        metadata = {'text': 'Я принесу победу в этой битве.', 'files': ['axe_rare_01.mp3'], **extra}
        self.meta.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
        return metadata

    def test_explicit_english_cache_is_rejected_before_asr_or_extraction(self):
        self.write_metadata(source_language='en')
        with patch.object(game_vo, '_detect_reference_language') as inspect, patch.object(game_vo, 'catalog') as catalog:
            with self.assertRaisesRegex(ValueError, 'ожидается русский голос'):
                game_vo.reference('axe')
        inspect.assert_not_called()
        catalog.assert_not_called()

    def test_verified_russian_cache_is_reused_without_asr(self):
        metadata = self.write_metadata(source_language='ru')
        metadata['language_verification'] = {
            'method': 'faster-whisper:auto-language:small', 'hero': 'axe',
            'audio_sha256': hashlib.sha256(self.wav.read_bytes()).hexdigest(),
            'text_sha256': hashlib.sha256(metadata['text'].encode()).hexdigest(),
            'language': 'ru', 'probability': .99, 'text_similarity': 1.0}
        self.meta.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
        with patch.object(game_vo, '_detect_reference_language') as inspect:
            result = game_vo.reference('axe')
        self.assertEqual(result, (str(self.wav), metadata['text']))
        inspect.assert_not_called()

    def test_legacy_russian_cache_is_verified_once_without_replacing_audio(self):
        metadata = self.write_metadata()
        original = self.wav.read_bytes()
        original_metadata = self.meta.read_bytes()
        with patch.object(game_vo, '_detect_reference_language', return_value={
                'language': 'ru', 'probability': .99, 'text': metadata['text']}) as inspect:
            game_vo.reference('axe')
            game_vo.reference('axe')
        inspect.assert_called_once_with(str(self.wav))
        self.assertEqual(self.wav.read_bytes(), original)
        self.assertEqual(self.meta.read_bytes(), original_metadata)
        evidence = json.loads((self.folder / 'ref_axe.language.json').read_text(encoding='utf-8'))
        self.assertEqual(evidence['source_language'], 'ru')

    def test_russian_caption_does_not_relabel_english_audio(self):
        self.write_metadata()
        old_metadata = self.meta.read_bytes()
        with patch.object(game_vo, '_detect_reference_language', return_value={
                'language': 'en', 'probability': .99, 'text': 'Axe brings the Red Mist!'}):
            with self.assertRaisesRegex(ValueError, 'автоматически определён en'):
                game_vo.reference('axe')
        self.assertEqual(self.meta.read_bytes(), old_metadata)

    def test_changed_verified_wav_cannot_reuse_old_language_evidence(self):
        self.write_metadata(source_language='ru', language_verification={'audio_sha256': '0' * 64})
        with patch.object(game_vo, '_detect_reference_language') as inspect:
            with self.assertRaisesRegex(ValueError, 'WAV изменился'):
                game_vo.reference('axe')
        inspect.assert_not_called()

    def test_synthesized_cache_hit_cannot_bypass_reference_language(self):
        self.write_metadata(source_language='en')
        folder = self.folder / 'speech'
        folder.mkdir()
        text = 'Клянусь, ты будешь молить о пощаде!'
        cache_key = hashlib.md5(f'fishref|axe|{text}|0.0'.encode()).hexdigest()[:12]
        (folder / 'threat.wav').write_bytes(b'previous synthesized speech')
        (folder / 'voices.json').write_text(json.dumps({'threat': {'key': cache_key}}))
        video_stub = SimpleNamespace(say_text=lambda value: value, show_text=lambda value: value)
        with patch.dict(sys.modules, {'video': video_stub}), patch.object(voices, 'engine', return_value='fish'), \
                patch.object(voices, 'fish_key', return_value='local-test-only'), patch.object(voices, '_fishref') as synth:
            with self.assertRaisesRegex(ValueError, 'ожидается русский голос'):
                voices.make(str(folder), [{'name': 'threat', 'who': 'axe', 'text': text, 'voice': {'ref': 'axe'}}])
        synth.assert_not_called()
        self.assertEqual((folder / 'threat.wav').read_bytes(), b'previous synthesized speech')

    def test_replacing_reference_invalidates_synthesized_cache(self):
        folder = self.folder / 'speech'
        folder.mkdir()
        text = 'Клянусь, ты будешь молить о пощаде!'
        old_ref = 'audio-sha256:' + hashlib.sha256(b'old English reference').hexdigest()
        old_key = hashlib.md5(f'fishref|axe|{text}|0.0|{old_ref}'.encode()).hexdigest()[:12]
        (folder / 'threat.wav').write_bytes(b'previous synthesized speech')
        (folder / 'voices.json').write_text(json.dumps({'threat': {'key': old_key}}))
        video_stub = SimpleNamespace(say_text=lambda value: value, show_text=lambda value: value)
        with patch.dict(sys.modules, {'video': video_stub}), patch.object(voices, 'engine', return_value='fish'), \
                patch.object(voices, 'fish_key', return_value='local-test-only'), \
                patch.object(game_vo, 'reference', return_value=(str(self.wav), 'Русский образец')), \
                patch.object(voices, '_fishref', side_effect=RuntimeError('generation boundary; no network')) as synth:
            with self.assertRaisesRegex(RuntimeError, 'generation boundary'):
                voices.make(str(folder), [{'name': 'threat', 'who': 'axe', 'text': text, 'voice': {'ref': 'axe'}}])
        synth.assert_called_once()
        self.assertEqual((folder / 'threat.wav').read_bytes(), b'previous synthesized speech')

    def test_unchanged_verified_reference_keeps_synthesized_cache(self):
        folder = self.folder / 'speech'
        folder.mkdir()
        text = 'Клянусь, ты будешь молить о пощаде!'
        ref = 'audio-sha256:' + hashlib.sha256(self.wav.read_bytes()).hexdigest()
        key = hashlib.md5(f'fishref|axe|{text}|0.0|{ref}'.encode()).hexdigest()[:12]
        (folder / 'threat.wav').write_bytes(b'previous synthesized speech')
        (folder / 'voices.json').write_text(json.dumps({'threat': {'key': key}}))
        video_stub = SimpleNamespace(say_text=lambda value: value, show_text=lambda value: value)
        with patch.dict(sys.modules, {'video': video_stub}), patch.object(voices, 'engine', return_value='fish'), \
                patch.object(voices, 'fish_key', return_value='local-test-only'), \
                patch.object(game_vo, 'reference', return_value=(str(self.wav), 'Русский образец')), \
                patch.object(voices, '_fishref') as synth:
            result = voices.make(str(folder), [{'name': 'threat', 'who': 'axe', 'text': text, 'voice': {'ref': 'axe'}}])
        synth.assert_not_called()
        self.assertEqual(result['threat']['key'], key)
        self.assertEqual((folder / 'threat.wav').read_bytes(), b'previous synthesized speech')


if __name__ == '__main__':
    unittest.main()
