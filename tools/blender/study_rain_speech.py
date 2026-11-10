"""Stage a close-up on Rain using mouth events from the recorded local voice."""

import argparse
from bisect import bisect_right
import csv
import json
import math
from pathlib import Path
import sys
import wave

import bpy
from mathutils import Matrix, Quaternion, Vector


SOURCE = Path(__file__).resolve().parents[2] / "_game/external/rain_v33/Rain v3.3/rain_v3.2.blend"
FPS = 30
REST = (0, 0, 0)
# Jaw angle, corner spread, and mouth protrusion. Calibrated for this rig.
FORMS = {
    0: REST, 21: REST,
    1: (7, .001, 0), 2: (14, .002, 0),
    3: (9, -.008, .004), 4: (8, .004, 0),
    6: (4, .006, 0), 7: (5, -.009, .006), 8: (8, -.007, .004),
    16: (4, -.004, .002), 18: (3, .001, 0),
    19: (4, 0, 0), 20: (6, 0, 0),
}


def read_events(path, duration):
    events = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))
        for index, (ticks, form) in enumerate(rows):
            time, form = int(ticks) / 10_000_000, int(form)
            # SAPI may place its final silence marker just past the PCM tail.
            if index == len(rows) - 1 and form == 0 and duration < time <= duration + 2 / FPS:
                time = duration
            if not 0 <= time <= duration or not 0 <= form <= 21:
                raise ValueError("Invalid SAPI event")
            events[time] = form
    if len(events) < 2 or list(events) != sorted(events) or events.get(0) != 0:
        raise ValueError("Expected an ordered SAPI event track starting with silence")
    if events[next(reversed(events))] != 0:
        events[duration] = 0
    return list(events), list(events.values())


def sampled_form(times, forms, time):
    # Begin the transition just ahead of the acoustic boundary.
    time += .012
    index = bisect_right(times, time) - 1
    target = FORMS.get(forms[index], (5, 0, 0))
    if index == 0:
        return target
    previous = FORMS.get(forms[index - 1], (5, 0, 0))
    mix = min(1, (time - times[index]) / .030)
    mix = mix * mix * (3 - 2 * mix)
    return tuple(a + (b - a) * mix for a, b in zip(previous, target))


def stage(scene):
    for obj in list(scene.objects):
        if obj.type in ("CAMERA", "LIGHT"):
            bpy.data.objects.remove(obj, do_unlink=True)
    target = Vector((0, -.04, 1.45))
    bpy.ops.object.camera_add(location=(.16, -2.1, 1.52))
    camera = bpy.context.object
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = .58
    scene.camera = camera
    for position, power, size in (((-.7, -1.1, 2.4), 75, 1.1),
                                  ((.8, -.6, 1.8), 32, 1.0),
                                  ((.1, .5, 2.2), 60, .8)):
        bpy.ops.object.light_add(type="AREA", location=position)
        light = bpy.context.object
        light.rotation_euler = (target - light.location).to_track_quat("-Z", "Y").to_euler()
        light.data.energy, light.data.size = power, size
    scene.world = bpy.data.worlds.new("Speech study background")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (.09, .15, .20, 1)
    background.inputs["Strength"].default_value = .5
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x = scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"


def rotate_control(bone, original, axis, angle):
    pivot = original.translation
    rotation = Quaternion(axis, math.radians(angle)).to_matrix().to_4x4()
    bone.matrix = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot) @ original
    bpy.context.view_layer.update()


def animate(scene, rig, times, forms, count):
    switches = rig.pose.bones["Properties_IKFK"]
    for side in ("left", "right"):
        switches["ik_arm_" + side] = 0
    rig.update_tag()
    bpy.context.view_layer.update()
    for side, angle in (("L", 67), ("R", -70)):
        arm = rig.pose.bones["FK-Upperarm." + side]
        rotate_control(arm, arm.matrix.copy(), (0, 1, 0), angle)
    return animate_mouth(scene, rig, times, forms, count)


def animate_mouth(scene, rig, times, forms, count):
    jaw = rig.pose.bones["MSTR-Jaw"]
    if jaw.rotation_mode != "XYZ":
        raise RuntimeError("The Rain jaw must use its native XYZ mode for this study")
    mouth = rig.pose.bones["MSTR-Mouth"]
    corners = [rig.pose.bones["ACT-Lips_Corner." + side] for side in ("L", "R")]
    controls = [jaw, mouth, *corners]
    rest = {bone.name: bone.matrix.copy() for bone in controls}
    rows = []
    for frame in range(count):
        angle, spread, protrusion = sampled_form(times, forms, frame / FPS)
        rotate_control(jaw, rest[jaw.name], (1, 0, 0), angle)
        jaw.keyframe_insert("rotation_euler", frame=frame)
        for bone, displacement in zip([mouth, *corners],
                                      [(0, -protrusion, 0), (spread, 0, 0), (-spread, 0, 0)]):
            # Preserve the mouth's natural travel with the lower jaw.
            bone.location = (0, 0, 0)
            bpy.context.view_layer.update()
            bone.matrix = Matrix.Translation(displacement) @ bone.matrix
            bone.keyframe_insert("location", frame=frame)
        rows.append({"frame": frame, "jaw_deg": angle, "corner_spread_m": spread})
    scene.frame_set(0)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames", help="Comma-separated diagnostic frames")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    with wave.open(str(args.wav), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    times, forms = read_events(args.events, duration)
    count = math.ceil(duration * FPS) + 9
    frames = list(map(int, args.frames.split(","))) if args.frames else range(count)
    if any(not 0 <= frame < count for frame in frames):
        parser.error("Frames outside the speech study")
    if args.out.exists():
        parser.error("Choose a new output directory")
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    scene = bpy.context.scene
    rig = bpy.data.objects["RIG-rain"]
    stage(scene)
    scene.frame_start, scene.frame_end = 0, count - 1
    rows = animate(scene, rig, times, forms, count)
    args.out.mkdir(parents=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str((args.out / "speech.blend").resolve()))
    for frame in frames:
        scene.frame_set(frame)
        scene.render.filepath = str((args.out / f"{frame:04d}.png").resolve())
        bpy.ops.render.render(write_still=True)
    (args.out / "speech-report.json").write_text(json.dumps({
        "fps": FPS, "frames": count, "audio_duration_s": duration,
        "events": list(zip(times, forms)), "poses": rows,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
