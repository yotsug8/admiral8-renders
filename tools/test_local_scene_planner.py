"""Regression checks for explicit details a local model may misread."""

import unittest

from local_scene_planner import (
    compile_action, compile_contact, compile_lift, compile_plan, compile_push, compile_sequence, plan_request,
)


class LocalPlannerTest(unittest.TestCase):
    def setUp(self):
        self.intent = {
            "status": "plan", "reason": "", "aspect": "landscape", "seconds": 3,
            "order": "sequential", "sound": True,
            "objects": [
                {"shape": "ball", "color": "red", "motion": "up"},
                {"shape": "cube", "color": "green", "motion": "down"},
            ],
        }

    def test_explicit_profile_is_preserved(self):
        plan = compile_plan("Вертикально, 4 секунды, одновременно и без звука.", self.intent)
        self.assertEqual(plan["size"], [432, 768])
        self.assertEqual(plan["frames"], 96)
        self.assertEqual(plan["cues"], [])
        objects = [o for o in plan["objects"] if "positions" in o]
        self.assertEqual(objects[0]["positions"][1][0], objects[1]["positions"][1][0])
        self.assertEqual(objects[0]["positions"][-1][0], objects[1]["positions"][-1][0])

    def test_explicit_out_of_range_duration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "длительность"):
            compile_plan("Движение за 9 секунд.", self.intent)

    def test_named_close_up_preserves_simultaneous_motion(self):
        request = "Красный шар и зелёный куб движутся одновременно. Общий план, затем крупный план куба."
        plan = compile_plan(request, dict(self.intent, close_up=2))
        self.assertEqual(len(plan["shots"]), 2)
        cut = plan["shots"][1]["frame"]
        self.assertEqual([check["frames"][1] for check in plan["checks"]], [cut - 1, plan["frames"]])
        moving = [obj for obj in plan["objects"] if "positions" in obj]
        self.assertEqual(moving[0]["positions"][1][0], moving[1]["positions"][1][0])

    def test_wrong_close_up_is_rejected(self):
        request = "Красный шар и зелёный куб. Общий план, затем крупный план зелёного куба."
        with self.assertRaisesRegex(ValueError, "предмет крупного плана"):
            compile_plan(request, dict(self.intent, close_up=1))

    def test_single_shot_does_not_add_unrequested_close_up(self):
        plan = compile_plan("Один план. Красный шар, затем зелёный куб.", dict(self.intent, close_up=2))
        self.assertEqual(len(plan["shots"]), 1)

    def test_unsupported_brief_is_rejected_before_inference(self):
        for profile in ("objects", "sequence"):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, "Диалоги"):
                plan_request("Интервью Пуджа с Инвокером, в кадре красный шар.", None, None, profile)

    def test_single_shot_rejects_replaced_objects(self):
        with self.assertRaisesRegex(ValueError, "формы или цвета"):
            compile_plan("Красный цилиндр и зелёный куб.", self.intent)

    def test_character_uses_explicit_format_and_checks_signal_side(self):
        intent = dict(status="plan", reason="", aspect="landscape", seconds=3,
                      gesture="nod", side="right", color="blue")
        request = "Рейн замечает синюю лампу справа и кивает. Вертикальный ролик на 4 секунды."
        plan = compile_action(request, intent)
        self.assertEqual(plan["size"], [432, 768])
        self.assertEqual(plan["frames"], 120)
        self.assertEqual(plan["signal"]["side"], "right")
        with self.assertRaisesRegex(ValueError, "side"):
            compile_action(request, dict(intent, side="left"))

    def test_contact_preserves_silence_and_rejects_changed_hold(self):
        request = "Вертикально. Робот нажимает кнопку и удерживает её 0,5 секунды. Без звука."
        intent = dict(status="plan", reason="", aspect="landscape", hold="half_second", sound=True)
        plan = compile_contact(request, intent)
        self.assertEqual((plan["aspect"], plan["hold_frames"], plan["sound"]), ("portrait", 15, False))
        with self.assertRaisesRegex(ValueError, "удержание"):
            compile_contact(request, dict(intent, hold="one_second"))
        with self.assertRaisesRegex(ValueError, "удержание"):
            compile_contact(request.replace("0,5", "две"), intent)
        with self.assertRaisesRegex(ValueError, "речь"):
            compile_contact(request + " Робот произносит речь.", intent)

    def test_push_checks_distance_and_keeps_crate_on_floor(self):
        intent = dict(status="plan", distance_cm=20)
        request = "Робот сдвигает ящик на двадцать сантиметров. Без звука."
        self.assertEqual(compile_push(request, intent)["distance_cm"], 20)
        with self.assertRaisesRegex(ValueError, "расстояние"):
            compile_push(request, dict(intent, distance_cm=10))
        with self.assertRaisesRegex(ValueError, "на полу"):
            compile_push(request + " Затем поднимает ящик.", intent)

    def test_lift_checks_pause_and_rejects_release(self):
        request = "Рейн берётся за ручку чемодана, ждёт 0,3 секунды и поднимает его. Без звука."
        intent = dict(status="plan", pause_frames=9)
        self.assertEqual(compile_lift(request, intent)["pause_frames"], 9)
        with self.assertRaisesRegex(ValueError, "Подтвердите паузу"):
            compile_lift(request, dict(intent, pause_frames=18))
        with self.assertRaisesRegex(ValueError, "одним чемоданом"):
            compile_lift(request + " Потом бросает чемодан.", intent)

    def test_sequence_preserves_scene_order_and_rejects_swapped_model_output(self):
        request = ("Горизонтально. Сцена 1: красный шар поднимается, 2 секунды, без звука. "
                   "Сцена 2: синий куб опускается, 3 секунды, со звуковым сигналом.")
        scenes = [dict(shape="ball", color="red", motion="up", seconds=2, sound=False),
                  dict(shape="cube", color="blue", motion="down", seconds=3, sound=True)]
        intent = dict(status="plan", aspect="landscape", scenes=scenes)
        plan = compile_sequence(request, intent)
        self.assertEqual([scene["frames"] for scene in plan["scenes"]], [48, 72])
        self.assertEqual([bool(scene["cues"]) for scene in plan["scenes"]], [False, True])
        with self.assertRaisesRegex(ValueError, "в сцене 1"):
            compile_sequence(request, dict(intent, scenes=scenes[::-1]))
        with self.assertRaisesRegex(ValueError, "ориентация"):
            compile_sequence(request.replace("Сцена 2:", "Сцена 2: вертикально,"), intent)


if __name__ == "__main__":
    unittest.main()
