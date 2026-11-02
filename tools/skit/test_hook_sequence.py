"""Later speech and a second hook must survive the first hook's reaction."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skit


class HookSequenceTests(unittest.TestCase):
    def test_reaction_preserves_later_speech_and_second_reaction(self):
        track = [(0, 'idle'), (1, 'talk_before'), (2.4, 'idle'),
                 (4, 'talk_after'), (5, 'idle'), (8, 'talk_last')]
        track = skit.hook_animation(track, {'hit': 2, 'back': 3}, 'flail', 'stun')
        track = skit.hook_animation(track, {'hit': 6, 'back': 7}, 'flail', 'stun')
        self.assertEqual(sorted(track), [(0, 'idle'), (1, 'talk_before'), (2, 'flail'),
                                        (3, 'stun'), (4, 'talk_after'), (5, 'idle'),
                                        (6, 'flail'), (7, 'stun'), (8, 'talk_last')])

    def test_second_pull_starts_from_previous_landing(self):
        hooks = [dict(hit=1, back=2, land=(200, 0)), dict(hit=4, back=5, land=(200, 400))]
        self.assertEqual(skit.hook_position(800, 0, 0, hooks, .5), (800, 0, 0))
        x, y, z = skit.hook_position(800, 0, 0, hooks, 4.5)
        self.assertAlmostEqual(x, 200)
        self.assertAlmostEqual(y, 200)
        self.assertAlmostEqual(z, 45)
        self.assertAlmostEqual(skit.hook_position(800, 0, 0, hooks, 6)[1], 400)

    def test_zero_length_pull_has_no_division_by_zero(self):
        self.assertEqual(skit.hook_position(200, 0, 0, [dict(hit=1, back=1, land=(200, 0))], .9), (200, 0, 0))
        self.assertAlmostEqual(skit.hook_position(200, 0, 0, [dict(hit=1, back=1, land=(200, 0))], 1)[0], 200)

    def test_timeline_second_hook_uses_updated_static_position(self):
        sc = {'cast': {'a': {'at': (0, 0), 'look': 'b'}, 'b': {'at': (800, 0), 'look': 'a'}},
              'events': [{'kind': 'hook', 'who': 'a', 'to': 'b'},
                         {'kind': 'hook', 'who': 'a', 'to': 'b'}]}
        _, _, hooks = skit.timeline(sc, {})
        self.assertAlmostEqual(hooks[1]['hit'] - hooks[1]['rel'], 200 / skit.HOOK_V, delta=.011)
        self.assertEqual(hooks[1]['hit'], hooks[1]['back'])


if __name__ == '__main__':
    unittest.main()
