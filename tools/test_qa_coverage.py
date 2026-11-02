"""Coverage must be real at draft cadence; skipped work is not a pass."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video
from tools import check


class FrameCoverageTests(unittest.TestCase):
    def test_draft_samples_all_segments_on_real_frames(self):
        segments = [dict(start=0, dur=4), dict(start=4, dur=4.1), dict(start=8.1, dur=.25)]
        for draft in (False, True):
            frames, checks, records = video._frame_plan(segments, 8.35, draft)
            self.assertTrue(checks <= set(frames))
            self.assertEqual(len(records), len(segments))
            if draft:
                self.assertTrue(all(f % 2 == 0 for f in checks))
            for segment, record in zip(segments, records):
                self.assertTrue(record['expected_frames'])
                self.assertTrue(all(segment['start'] <= f / video.FPS < segment['start'] + segment['dur']
                                    for f in record['expected_frames']))
            # The old draft calculation dropped two of this segment's three samples.
            self.assertEqual(len(records[0]['expected_frames']), 3)
            only, same_checks, _ = video._frame_plan(segments, 8.35, draft, True)
            self.assertEqual(set(only), checks)
            self.assertEqual(same_checks, checks)

    def test_short_segment_is_clamped_to_its_only_frame(self):
        frames, checks, _ = video._frame_plan([dict(start=0, dur=.04)], .04)
        self.assertEqual(frames, [0])
        self.assertEqual(checks, {0})

    def test_unrendered_segment_and_invalid_intervals_fail(self):
        for segs, total, draft in [([], 1, False), ([dict(start=0, dur=1)], 0, False),
                                  ([dict(start=.01, dur=.01)], .2, True),
                                  ([dict(start=-1, dur=2)], 2, False),
                                  ([dict(start=0, dur=float('nan'))], 2, False)]:
            with self.subTest(segs=segs), self.assertRaises(ValueError):
                video._frame_plan(segs, total, draft)

    def test_missing_duplicate_extra_or_empty_actual_samples_fail(self):
        for actual in [[], [0], [0, 2, 2], [0, 2, 4]]:
            with self.subTest(actual=actual), self.assertRaises(RuntimeError):
                video._require_frame_coverage({0, 2}, actual)
        with self.assertRaises(RuntimeError):
            video._require_frame_coverage(set(), [])
        video._require_frame_coverage({0, 2}, [2, 0])


class CheckSelectionTests(unittest.TestCase):
    def run_check(self, episodes=(), skits=(), pick=(), run_result=(0, [])):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'episodes').mkdir()
            (root / 'skits').mkdir()
            for name, content in episodes:
                (root / 'episodes' / name).write_text(content, encoding='utf-8')
            for name in skits:
                (root / 'skits' / name).write_text('fixture', encoding='utf-8')
            with patch.object(check, 'REPO', tmp), patch.object(sys, 'argv', ['check.py', *pick]), \
                    patch.object(check, 'run', return_value=run_result) as runner, \
                    patch.object(sys, 'stdout') as output, self.assertRaises(SystemExit) as stopped:
                check.main()
            text = ''.join(str(c.args[0]) for c in output.write.call_args_list if c.args)
            return stopped.exception.code, text, runner.call_count

    def test_unknown_selection_and_empty_repository_do_not_pass(self):
        for kwargs in [dict(pick=['missing']), {},
                       dict(episodes=[('demo.json', '{}')], pick=['demo', 'missing'])]:
            code, text, calls = self.run_check(**kwargs)
            self.assertEqual(code, 2)
            self.assertNotIn('всё в порядке', text)
            self.assertEqual(calls, 0)

    def test_all_and_partial_skips_do_not_pass(self):
        for episodes, skits in [([('game.json', '{"type": "model"}')], []),
                                ([], ['demo.txt']), ([('demo.json', '{}')], ['demo.txt'])]:
            code, text, _ = self.run_check(episodes, skits)
            self.assertEqual(code, 2)
            self.assertIn('неполная проверка', text)
            self.assertNotIn('всё в порядке', text)

    def test_executed_clean_case_passes_and_failure_remains_failure(self):
        for result, expected in [((0, []), 0), ((1, []), 1), ((0, ['JS-ошибка']), 1)]:
            code, _, calls = self.run_check([('demo.json', '{}')], run_result=result)
            self.assertEqual(code, expected)
            self.assertEqual(calls, 1)


if __name__ == '__main__':
    unittest.main()
