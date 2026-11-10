"""Stage a shy mechanical flower and Rain's wordless change of approach."""
import argparse
import json
import math
from pathlib import Path
import sys
import wave

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from beacon_preview import area, box, camera, material, sphere
from prepare_study_scene import localize_widget_meshes
from study_rain_dialogue import move_control
from study_rain_speech import FPS, SOURCE, rotate_control, stage


COUNT = 162
FLOWER = Vector((.37, -.40, 1.29))
CUTS = (1, 43, 108)
EVENTS = (20, 75, 123)


def ramp(frame, start, end):
    x = min(1., max(0., (frame - start) / (end - start)))
    return x * x * (3 - 2 * x)


def key_rotation(bone, frame):
    bone.keyframe_insert(
        "rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_euler",
        frame=frame,
    )


def stage_flower():
    gold = material("Brass fixture", (.32, .20, .076), metal=.55)
    pink = material("Folded copper", (.70, .12, .065), metal=.24, roughness=.38)
    pale = material("Warm centre", (.92, .54, .15), roughness=.35)
    base = FLOWER - Vector((0, 0, .29))
    box("Small plinth", base + Vector((0, 0, .047)), (.26, .26, .094), gold, .032)
    box("Stalk", base + Vector((0, 0, .17)), (.024, .024, .20), gold, .009)
    core = sphere("Flower centre", FLOWER, .043, pale)
    core.scale.z = .68
    pivots = []
    for index in range(6):
        azimuth = math.tau * index / 6
        hinge = bpy.data.objects.new(f"Petal hinge {index + 1}", None)
        bpy.context.scene.collection.objects.link(hinge)
        hinge.location = FLOWER
        hinge.rotation_euler.z = azimuth
        petal = sphere(f"Petal {index + 1}", (0, 0, 0), 1, pink)
        petal.parent = hinge
        petal.location = (.092, 0, .017)
        petal.scale = (.081, .036, .010)
        pivots.append(hinge)
    return pivots


def pose_rain(scene, rig, petals):
    bones = rig.pose.bones
    settings = bones["Properties_IKFK"]
    for prop in ("ik_arm_left", "ik_arm_right", "ik_spine"):
        settings[prop] = 0
    rig.update_tag()
    bpy.context.view_layer.update()
    for side, angle in (("L", 68), ("R", -69)):
        arm = bones["FK-Upperarm." + side]
        rotate_control(arm, arm.matrix.copy(), (0, 1, 0), angle)
    for index, drop in enumerate((15, 25, 20, 10), 1):
        bone = bones[f"FK-Hair_Ponytail{index}"]
        rotate_control(bone, bone.matrix.copy(), (1, 0, 0), -drop)
    names = ("FK-Spine", "FK-Chest", "FK-Head", "MSTR-Jaw",
             "MSTR-Eyebrow.L", "MSTR-Eyebrow.R", "ACT-Lips_Corner.L",
             "ACT-Lips_Corner.R", "TGT-Eye.L", "TGT-Eye.R")
    rest = {name: bones[name].matrix_basis.copy() for name in names}
    # The easing spans several frames. Keep the pose keys two frames apart
    # and include the last frame so Blender can interpolate the full shot.
    for frame in (*range(1, COUNT, 2), COUNT):
        scene.frame_set(frame)
        for name, matrix in rest.items():
            bones[name].matrix_basis = matrix
        bpy.context.view_layer.update()
        notice = ramp(frame, 22, 37)
        approach = ramp(frame, 43, 73) * (1 - ramp(frame, 80, 109))
        surprise = ramp(frame, 77, 86) * (1 - ramp(frame, 91, 105))
        smile = ramp(frame, 125, 147)
        nod = ramp(frame, 141, 150) * (1 - ramp(frame, 150, 162))
        for name, axis, angle in (
            ("FK-Spine", (1, 0, 0), 10 * approach - 3 * surprise),
            ("FK-Chest", (1, 0, 0), 13 * approach - 5 * surprise),
            ("FK-Chest", (0, 1, 0), 13 * approach),
            ("FK-Head", (0, 0, 1), 35 * notice + 8 * approach - 4 * smile),
            ("FK-Head", (1, 0, 0), 18 * notice - 9 * approach - 9 * surprise + 5 * nod),
            ("FK-Head", (0, 1, 0), 7 * smile + 4 * surprise),
            ("MSTR-Jaw", (1, 0, 0), 7 * surprise + 2 * smile),
        ):
            bone = bones[name]
            rotate_control(bone, bone.matrix.copy(), axis, angle)
            key_rotation(bone, frame)
        for name, offset in (
            ("MSTR-Eyebrow.L", (0, 0, .007 * notice + .012 * surprise - .006 * smile)),
            ("MSTR-Eyebrow.R", (0, 0, .004 * notice + .009 * surprise - .004 * smile)),
            ("ACT-Lips_Corner.L", (.007 * smile, -.002 * smile, .009 * smile)),
            ("ACT-Lips_Corner.R", (-.004 * smile, -.002 * smile, .006 * smile)),
        ):
            move_control(bones[name], offset)
            bones[name].keyframe_insert("location", frame=frame)
        flower = rig.matrix_world.inverted() @ FLOWER
        target = Vector((-.18, -2, 1.48)).lerp(flower, ramp(frame, 20, 29))
        for side in ("L", "R"):
            eye = bones["TGT-Eye." + side]
            move_control(eye, target - eye.matrix.translation)
            eye.keyframe_insert("location", frame=frame)
        for index, hinge in enumerate(petals):
            delay = index % 3
            opening = (ramp(frame, 20 + delay, 37 + delay)
                       * (1 - ramp(frame, 75 + delay, 84 + delay))
                       + ramp(frame, 123 + delay, 142 + delay))
            hinge.rotation_euler.y = math.radians(-64 + 60 * opening)
            hinge.keyframe_insert("rotation_euler", frame=frame)


def soundtrack(path):
    rate = 48_000
    samples = np.zeros((COUNT * rate // FPS, 2))
    for frame, start_hz, end_hz, length, gain in (
        (EVENTS[0], 510, 750, .37, .16), (EVENTS[1], 660, 275, .24, .23),
        (EVENTS[2], 490, 680, .45, .16),
    ):
        t = np.arange(round(length * rate)) / rate
        phase = math.tau * (start_hz * t + (end_hz - start_hz) * t**2 / (2 * length))
        envelope = np.minimum(t / .018, 1) * np.minimum((length - t) / .07, 1)
        sound = gain * envelope * np.exp(-3 * t / length) * (np.sin(phase) + .18 * np.sin(2.03 * phase))
        start = (frame - 1) * rate // FPS
        samples[start:start + len(t)] += sound[:, None] * (.69, 1)
    with wave.open(str(path), "wb") as output:
        output.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(np.round(samples * 32767).astype("<i2").tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args(sys.argv[sys.argv.index("--") + 1:]).out.resolve()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    scene = bpy.context.scene
    rig = bpy.data.objects["RIG-rain"]
    stage(scene)
    bpy.data.objects.remove(scene.camera, do_unlink=True)
    scene.render.resolution_x, scene.render.resolution_y = 640, 360
    scene.eevee.taa_render_samples = 12
    scene.frame_start, scene.frame_end = 1, COUNT
    table = material("Blue lacquer", (.055, .13, .16), roughness=.49)
    box("Table", (.29, -.47, .958), (.90, .48, .084), table, .032)
    box("Wall", (0, .90, 1.12), (5, .14, 3), material("Muted lavender wall", (.18, .15, .23)))
    area("Warm table fill", (.62, -.72, 1.89), FLOWER, 35, .50, (1, .79, .60))
    petals = stage_flower()
    camera(scene, "Invitation", (.76, -2.27, 1.64), (.16, -.19, 1.34), 53, CUTS[0])
    camera(scene, "Too close", (.94, -2.0, 1.56), (.20, -.21, 1.38), 61, CUTS[1])
    # See the opened petals from above while keeping Rain's reaction in the shot.
    camera(scene, "Give it space", (.64, -2.20, 2.06), (.15, -.20, 1.36), 55, CUTS[2])
    meshes = {obj: obj.hide_viewport for obj in scene.objects if obj.type == "MESH"}
    for obj in meshes:
        obj.hide_viewport = True
    pose_rain(scene, rig, petals)
    for obj, hidden in meshes.items():
        obj.hide_viewport = hidden
    scene.frame_set(1)
    out.mkdir(parents=True, exist_ok=True)
    localize_widget_meshes()
    bpy.ops.file.pack_all()
    external = bpy.utils.blend_paths(absolute=True, packed=False)
    if external:
        raise RuntimeError(f"Scene still references an external file: {external[0]}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "scene.blend"))
    soundtrack(out / "mix.wav")
    job = dict(schema_version=1, scene="scene.blend", out="draft",
               frames=[1, COUNT + 1], size=[640, 360], fps=FPS, wav="mix.wav")
    (out / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
