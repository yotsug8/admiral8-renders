"""Build a silent Rain reaction from an editable local action plan."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from beacon_preview import aim, box, material, sphere
from prepare_study_scene import localize_widget_meshes
from rain_shy_flower import key_rotation
from study_rain_dialogue import move_control
from study_rain_partner import ease
from study_rain_speech import SOURCE, rotate_control, stage


COLORS = {"blue": (.06, .26, 1), "green": (.08, .75, .23),
          "yellow": (.87, .49, .06), "red": (.78, .06, .04)}
SIZES = ((640, 360), (432, 768))
FPS = 30


def validate(plan):
    if (not isinstance(plan, dict) or plan.get("schema_version") != 1 or plan.get("actor") != "rain"
            or plan.get("gesture") not in ("nod", "shake") or plan.get("fps") != FPS
            or tuple(plan.get("size", ())) not in SIZES or plan.get("frames") not in (90, 120, 150)):
        raise ValueError("Use a version 1 Rain action plan")
    signal = plan["signal"]
    if (signal["color"] not in COLORS or signal["side"] not in ("left", "right")
            or type(signal["frame"]) is not int or not 5 <= signal["frame"] <= plan["frames"] - 40):
        raise ValueError("Invalid signal in Rain action plan")


def add_signal(scene, point, signal):
    coat = material("Indicator housing", (.065, .095, .12), metal=.28)
    box("Indicator post", (point.x, point.y + .035, point.z - .49), (.048, .050, .96), coat, .01)
    box("Indicator housing", point + Vector((0, .037, 0)), (.145, .074, .145), coat, .024)
    color = COLORS[signal["color"]]
    lens = material("Indicator glass", tuple(.20 * value for value in color), roughness=.30)
    lamp = sphere("Indicator lens", point, .048, lens)
    lamp.scale.y = .36
    shader = lens.node_tree.nodes["Principled BSDF"]
    shader.inputs["Emission Color"].default_value = (*color, 1)
    power = shader.inputs["Emission Strength"]
    for frame, value in ((1, 0.), (signal["frame"] - 1, 0.), (signal["frame"], 2.5)):
        power.default_value = value
        power.keyframe_insert("default_value", frame=frame)
    return lamp


def animate(scene, rig, target, plan, sign):
    bones = rig.pose.bones
    settings = bones["Properties_IKFK"]
    for prop in ("ik_arm_left", "ik_arm_right", "ik_spine"):
        settings[prop] = 0
    rig.update_tag()
    bpy.context.view_layer.update()
    for side, angle in (("L", 74), ("R", -75)):
        arm = bones[f"FK-Upperarm.{side}"]
        rotate_control(arm, arm.matrix.copy(), (0, 1, 0), angle)
    for index, drop in enumerate((15, 25, 20, 10), 1):
        hair = bones[f"FK-Hair_Ponytail{index}"]
        rotate_control(hair, hair.matrix.copy(), (1, 0, 0), -drop)
    head = bones["FK-Head"]
    head_base = head.matrix_basis.copy()
    eyes = [bones[f"TGT-Eye.{side}"] for side in ("L", "R")]
    before = [bone.matrix_basis.copy() for bone in eyes]
    local_target = rig.matrix_world.inverted() @ target
    onset = plan["signal"]["frame"]
    gesture_start = onset + 17
    meshes = {obj: obj.hide_viewport for obj in scene.objects if obj.type == "MESH"}
    for obj in meshes:
        obj.hide_viewport = True
    for frame in (*range(1, plan["frames"], 2), plan["frames"]):
        scene.frame_set(frame)
        head.matrix_basis = head_base
        for bone, rest in zip(eyes, before):
            bone.matrix_basis = rest
        bpy.context.view_layer.update()
        attention = ease(frame, onset + 3, 12)
        phase = ease(frame, gesture_start, 18)
        nod = 11 * math.sin(math.pi * phase) if plan["gesture"] == "nod" else 0
        shake = 9 * math.sin(math.tau * phase) if plan["gesture"] == "shake" else 0
        rotate_control(head, head.matrix.copy(), (0, 0, 1), sign * 23 * attention + shake)
        rotate_control(head, head.matrix.copy(), (1, 0, 0), 6 * attention + nod)
        key_rotation(head, frame)
        gaze = Vector((0, -2, 1.48)).lerp(local_target, ease(frame, onset + 1, 10))
        for eye in eyes:
            move_control(eye, gaze - eye.matrix.translation)
            eye.keyframe_insert("location", frame=frame)
    for obj, hidden in meshes.items():
        obj.hide_viewport = hidden
    return gesture_start


def check_frame(scene, rig, lamp, count):
    margin = 1.
    for frame in range(1, count + 1):
        scene.frame_set(frame)
        head = rig.matrix_world @ rig.pose.bones["FK-Head"].head
        points = [head + Vector((x, 0, z)) for x in (-.13, .13) for z in (-.10, .17)]
        points += [lamp.matrix_world @ Vector(vertex) for vertex in lamp.bound_box]
        views = [world_to_camera_view(scene, scene.camera, point) for point in points]
        margin = min(margin, *(min(p.x, 1-p.x, p.y, 1-p.y, p.z) for p in views))
    if margin < .045:
        raise ValueError(f"Face or indicator outside the frame margin: {margin:.3f}")
    return margin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", default=SOURCE, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    validate(plan)
    if args.out.exists():
        parser.error("Choose a new output folder")
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve(strict=True)), use_scripts=False)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    scene = bpy.context.scene
    rig = scene.objects["RIG-rain"]
    stage(scene)
    scene.frame_start, scene.frame_end = 1, plan["frames"]
    scene.render.resolution_x, scene.render.resolution_y = plan["size"]
    scene.eevee.taa_render_samples = 8
    sign = 1 if plan["signal"]["side"] == "right" else -1
    target = Vector((sign * .34, -.46, 1.43))
    camera = scene.camera
    camera.location = (.02 * sign, -2.3, 1.59)
    portrait = plan["size"][0] < plan["size"][1]
    aim(camera, (.09 * sign, -.15, 1.28 if portrait else 1.46))
    camera.data.ortho_scale = 1.43 if portrait else 1.00
    lamp = add_signal(scene, target, plan["signal"])
    gesture = animate(scene, rig, target, plan, sign)
    margin = check_frame(scene, rig, lamp, plan["frames"])
    scene.frame_set(1)
    localize_widget_meshes()
    bpy.ops.file.pack_all()
    if bpy.data.libraries or bpy.utils.blend_paths(absolute=True, packed=False):
        raise RuntimeError("Scene has external references")
    args.out.mkdir(parents=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve() / "scene.blend"))
    job = dict(schema_version=1, scene="scene.blend", out="draft", size=plan["size"],
               fps=FPS, frames=[1, plan["frames"] + 1])
    checks = dict(frames=plan["frames"], minimum_frame_margin=margin,
                  signal_frame=plan["signal"]["frame"], gesture_start=gesture)
    for name, data in (("plan.json", plan), ("job.json", job), ("checks.json", checks)):
        (args.out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
