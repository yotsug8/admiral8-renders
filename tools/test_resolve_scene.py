"""Узкая регрессия F01: GLB anim у stage-актёров и обычная 2D-рекурсия."""
import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video


class ResolveSceneTests(unittest.TestCase):
    def test_lottie_source_directory_is_preserved_without_mutation(self):
        with tempfile.TemporaryDirectory(prefix="lottie_source_") as tmp:
            source = Path(tmp) / "nested" / "anim.json"
            source.parent.mkdir()
            animation = {"assets": [{"u": "images/", "p": "example.png"}]}
            source.write_text(json.dumps(animation), encoding="utf-8")
            scene = {"type": "panel", "children": [
                {"type": "lottie", "src": "file:" + source.as_posix()}]}
            original = copy.deepcopy(scene)
            result = video.resolve_scene(scene, {}, {})["children"][0]
            self.assertEqual(result["data"], animation)
            self.assertEqual(result["assetBase"], source.parent.as_uri() + "/")
            self.assertNotIn("src", result)
            self.assertEqual(scene, original)

    def test_stage_actor_anim_preserves_2d_model_and_sources(self):
        with tempfile.TemporaryDirectory(prefix="resolve_scene_") as tmp:
            root = Path(tmp)
            model_dir = root / "models" / "dummy"
            model_dir.mkdir(parents=True)
            # resolve_scene embeds bytes; GLB decoding belongs to the renderer.
            glb = b"dummy GLB bytes"
            (model_dir / "dummy.glb").write_bytes(glb)
            source = root / "source.png"
            source.write_bytes(b"dummy image bytes")
            src = "file:" + source.as_posix()
            scene = {"type": "panel", "children": [
                {"type": "stage", "actors": [
                    {"hero": "dummy", "anim": "walk", "src": src,
                     "nested": {"anim": "actor-overlay", "src": src}},
                    {"hero": "dummy", "anim": "idle"},
                ]},
                {"type": "model", "hero": "dummy", "anim": "attack",
                 "nested": [{"anim": "model-overlay", "src": src}]},
                {"type": "image", "anim": "sprite", "src": src},
                # A hero key or an actors key alone must not imply a stage actor.
                {"hero": "dummy", "anim": "portrait"},
                {"actors": [{"anim": "ordinary", "src": src}]},
                {"anim": {"fps": 12, "frames": ["existing"]}},
                None, 7,
            ]}
            original = copy.deepcopy(scene)

            def frames(key):
                return {"fps": 15, "frames": [key + ".webp"]}

            with patch.dict(os.environ, {"FV_GAME_DIR": str(root)}), \
                    patch.object(video, "anim_frames", side_effect=frames) as convert:
                result = video.resolve_scene(scene, {}, {})

            stage, model, sprite, portrait, ordinary, existing, *scalars = result["children"]
            self.assertEqual([a["anim"] for a in stage["actors"]], ["walk", "idle"])
            self.assertEqual(model["anim"], "attack")
            encoded = base64.b64encode(glb).decode()
            self.assertEqual(stage["heroes"], {"dummy": [encoded]})
            self.assertEqual(model["glb"], [encoded])
            self.assertEqual(stage["actors"][0]["src"], source.as_uri())
            for node, key in [(stage["actors"][0]["nested"], "actor-overlay"),
                              (model["nested"][0], "model-overlay"),
                              (sprite, "sprite"), (ordinary["actors"][0], "ordinary")]:
                self.assertEqual(node["anim"], frames(key))
                self.assertEqual(node["src"], source.as_uri())
            self.assertEqual(portrait["anim"], frames("portrait"))
            self.assertEqual(existing, original["children"][5])
            self.assertEqual(scalars, [None, 7])
            self.assertEqual(convert.call_args_list, [call(key) for key in
                             ("actor-overlay", "model-overlay", "sprite", "portrait", "ordinary")])
            self.assertEqual(scene, original)


if __name__ == "__main__":
    unittest.main()
