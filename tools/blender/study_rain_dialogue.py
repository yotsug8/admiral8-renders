"""A short two-person scene around a flattened toy block."""

import argparse
from array import array
import json
import math
from pathlib import Path
import sys
import wave

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_rain_lightcase import box, material
from study_rain_partner import duplicate_rain, ease
from study_rain_speech import FPS, SOURCE, animate, read_events, rotate_control, stage
from prepare_study_scene import localize_widget_meshes


def load_line(folder, name):
    with wave.open(str(folder / f"{name}.wav"), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 22050):
            raise ValueError("Expected mono 16-bit SAPI PCM at 22050 Hz")
        duration = audio.getnframes() / audio.getframerate()
        pcm = audio.readframes(audio.getnframes())
    times, forms = read_events(folder / f"{name}.csv", duration)
    return duration, pcm, times, forms


def write_mix(output, question, reply, reply_frame, count, signal_frame=None):
    bytes_per_frame = 2 * (22050 // FPS)
    samples = bytearray(count * bytes_per_frame)
    samples[:len(question)] = question
    start = reply_frame * bytes_per_frame
    samples[start:start + len(reply)] = reply
    if signal_frame is not None:
        pcm = array("h")
        pcm.frombytes(samples)
        start = signal_frame * (22050 // FPS)
        length = round(.13 * 22050)
        for i in range(length):
            phase = 2 * math.pi * 660 * i / 22050
            tone = round(3400 * math.sin(phase) * math.sin(math.pi * i / length) ** 2)
            pcm[start + i] = min(32767, max(-32768, pcm[start + i] + tone))
        samples = pcm.tobytes()
    with wave.open(str(output), "wb") as audio:
        audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        audio.writeframes(samples)


def move_control(bone, displacement):
    bone.matrix = Matrix.Translation(displacement) @ bone.matrix
    bpy.context.view_layer.update()


def play_attention(scene, actors, toy, reply_time, count, extra_pause_frames, signal_frame=None):
    heads = [rig.pose.bones["FK-Head"] for rig in actors]
    head_bases = [head.matrix.copy() for head in heads]
    brows = [rig.pose.bones["MSTR-Eyebrow.L"] for rig in actors]
    brow_rest = [brow.location.copy() for brow in brows]
    eye_centers = [
        rig.matrix_world @ base.translation + Vector((0, 0, .075))
        for rig, base in zip(actors, head_bases)
    ]
    for frame in range(count):
        scene.frame_set(frame)
        time = frame / FPS
        # The questioner asks about the object. The listener checks it before answering.
        look_to_partner = (
            ease(time, .87, .48),
            1 - ease(time, .25, .40) + ease(time, 1.35 + extra_pause_frames / FPS, .42),
        )
        no = ease(time, reply_time + .40, .19) - ease(time, reply_time + .65, .18)
        surprise = ease(time, reply_time + .55, .24) - ease(time, reply_time + 1.05, .23)
        if signal_frame is not None:
            signal = signal_frame / FPS
            look_to_partner = (ease(time, reply_time + .28, .46),
                               .65 * (1 - ease(time, .27, .38)) + ease(time, signal + .06, .35))
            no = ease(time, reply_time + .04, .16) - ease(time, reply_time + .22, .21)
            surprise = ease(time, signal + .09, .23) - .60 * ease(time, reply_time + .39, .43)
        for i, rig in enumerate(actors):
            head, brow = heads[i], brows[i]
            look = look_to_partner[i]
            yaw = (1 if i == 0 else -1) * (28 * look - 7 * (1 - look))
            pitch = (1 - look) * (15 if signal_frame is not None else 21)
            if i == 1:
                yaw += 6 * no
                pitch += 4 * no
            else:
                pitch -= (8 if signal_frame is not None else 5) * surprise
            rotate_control(head, head_bases[i], (0, 0, 1), yaw)
            rotate_control(head, head.matrix.copy(), (1, 0, 0), pitch)
            head.keyframe_insert("rotation_quaternion" if head.rotation_mode == "QUATERNION"
                                 else "rotation_euler", frame=frame)
            brow.location = brow_rest[i]
            bpy.context.view_layer.update()
            lift = .007 * surprise if i == 0 else .005 * no
            move_control(brow, (0, 0, lift))
            brow.keyframe_insert("location", frame=frame)
            eye_target = toy.lerp(eye_centers[1 - i], look)
            eye_target = eye_centers[i] + (eye_target - eye_centers[i]).normalized() * 2.0
            for side in ("L", "R"):
                eye = rig.pose.bones["TGT-Eye." + side]
                target_local = rig.matrix_world.inverted() @ eye_target
                move_control(eye, target_local - eye.matrix.translation)
                eye.keyframe_insert("location", frame=frame)


def add_dialogue_cameras(scene, reply_frame, extra_pause_frames=0):
    wide = scene.camera
    wide.name = "Shared view"
    shots = [(0, wide)]
    question_close_frame = max(1, reply_frame - extra_pause_frames - 19)
    for side, frame in ((-1, question_close_frame), (1, reply_frame)):
        bpy.ops.object.camera_add(location=(-side * 2.45, -1.12, 1.65))
        camera = bpy.context.object
        camera.name = "Question close-up" if side == -1 else "Reply close-up"
        focus = Vector((side * .415, -.06, 1.44))
        camera.rotation_euler = (focus - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = .82
        shots.append((frame, camera))
    shots.append((min(reply_frame + 30, scene.frame_end), shots[1][1]))
    for frame, camera in shots:
        marker = scene.timeline_markers.new(camera.name, frame=frame)
        marker.camera = camera
    scene.camera = wide
    return [frame for frame, _ in shots[1:]]


def signal_lamp(scene, frame):
    box("Signal base", (0, -.46, 1.045), (.21, .13, .03), material("Lamp base", (.065, .07, .07)))
    box("Signal housing", (0, -.46, 1.126), (.154, .115, .14),
        material("Lamp enamel", (.095, .12, .11)), bevel=.013)
    glass = material("Signal lens", (.055, .28, .12))
    shader = glass.node_tree.nodes["Principled BSDF"]
    shader.inputs["Emission Color"].default_value = (.11, 1, .29, 1)
    lamp = box("Signal lens", (0, -.522, 1.13), (.095, .016, .073), glass, bevel=.012)
    data = bpy.data.lights.new("Green spill", "POINT")
    light = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(light)
    light.location = (0, -.60, 1.15)
    data.color, data.shadow_soft_size = (.15, 1, .30), .085
    for f, strength, energy in ((0, 0, 0), (frame - 1, 0, 0), (frame, 2.2, 3.2)):
        shader.inputs["Emission Strength"].default_value = strength
        shader.inputs["Emission Strength"].keyframe_insert("default_value", frame=f)
        data.energy = energy
        data.keyframe_insert("energy", frame=f)
    return lamp.location.copy()


def add_signal_cameras(scene, reply_frame, signal_frame, reply_end):
    add_dialogue_cameras(scene, reply_frame)
    wide, question, reply = (scene.objects[name] for name in
                             ("Shared view", "Question close-up", "Reply close-up"))
    scene.timeline_markers.clear()
    bpy.ops.object.camera_add(location=(.37, -1.55, 1.36))
    detail = bpy.context.object
    detail.name = "Signal insert"
    detail.rotation_euler = (Vector((0, -.48, 1.13)) - detail.location).to_track_quat("-Z", "Y").to_euler()
    detail.data.type, detail.data.ortho_scale = "ORTHO", .39
    shots = ((0, wide), (12, question), (signal_frame - 5, detail),
             (reply_frame - 2, reply), (reply_end, wide))
    if [f for f, _ in shots] != sorted(set(f for f, _ in shots)):
        raise ValueError("The lines are too short for the planned signal cuts")
    for frame, camera in shots:
        scene.timeline_markers.new(camera.name, frame=frame).camera = camera
    scene.camera = wide
    return [frame for frame, _ in shots[1:]]


def settle_signal_gaze(scene, actors, signal_frame, reply_end):
    """Keep attention on the lamp when the audience sees both performers."""
    scene.frame_set(signal_frame)
    for index, rig in enumerate(actors):
        scene.frame_set(signal_frame)
        head = rig.pose.bones["FK-Head"]
        eyes = [rig.pose.bones["TGT-Eye." + side] for side in ("L", "R")]
        rotation = ("rotation_quaternion" if head.rotation_mode == "QUATERNION" else "rotation_euler")
        lamp_head = getattr(head, rotation).copy()
        lamp_eyes = [eye.location.copy() for eye in eyes]
        opening = range(13) if index == 1 else ()
        closing = range(reply_end - 8, scene.frame_end + 1)
        for frames, start, duration, fade_in in (
            (opening, 0, 12, False), (closing, reply_end - 8, 12, True)
        ):
            for f in frames:
                scene.frame_set(f)
                weight = ease(f, start, duration)
                if not fade_in:
                    weight = 1 - weight
                current = getattr(head, rotation)
                value = current.slerp(lamp_head, weight) if rotation == "rotation_quaternion" else (
                    current.to_quaternion().slerp(lamp_head.to_quaternion(), weight)
                    .to_euler(head.rotation_mode, current)
                )
                setattr(head, rotation, value)
                head.keyframe_insert(rotation, frame=f)
                for eye, location in zip(eyes, lamp_eyes):
                    eye.location = eye.location.lerp(location, weight)
                    eye.keyframe_insert("location", frame=f)


def insert_signal_reaction(scene, timeline, out):
    info = json.loads(timeline.read_text(encoding="utf-8"))
    markers = sorted((mark.frame, mark.camera.name) for mark in scene.timeline_markers if mark.camera)
    names = ("Shared view", "Question close-up", "Signal insert", "Reply close-up", "Shared view")
    if (not bpy.data.filepath or bpy.data.libraries or bpy.utils.blend_paths(absolute=True, packed=False)
            or scene.frame_start != 0 or scene.frame_end + 1 != info["frames"]
            or info["fps"] != FPS or scene.render.fps / scene.render.fps_base != FPS
            or markers != list(zip([0, *info["cuts"]], names, strict=True))):
        raise ValueError("Open the packed five-shot signal scene and its timeline")
    reply = scene.timeline_markers["Reply close-up"]
    first, stop = reply.frame, info["reply_frame"] + 22
    if not info["signal_frame"] < first < stop < info["reply_end"]:
        raise ValueError("There is no room for the reaction before the end of the reply")
    name = "Signal reaction"
    camera = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    scene.collection.objects.link(camera)
    camera.location = (0, -3.60, 1.60)
    camera.rotation_euler = (Vector((0, -.12, 1.33)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type, camera.data.ortho_scale = "ORTHO", 1.42
    reply.frame = stop
    scene.timeline_markers.new(name, frame=first).camera = camera
    info["cuts"].insert(3, stop)
    scene.frame_set(0)
    out.mkdir(parents=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out.resolve() / "dialogue.blend"), copy=True)
    job = dict(schema_version=1, scene="dialogue.blend", out="insert", frames=[first, stop], fps=FPS,
               size=[scene.render.resolution_x, scene.render.resolution_y])
    for filename, data in (("insert.json", job), ("timeline.json", info)):
        (out / filename).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--lines", type=Path)
    source.add_argument("--reaction-timeline", type=Path, help="Insert a reaction in the packed signal scene")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra-pause-frames", type=int, default=0,
                        help="Hold on the question shot before moving the reply")
    parser.add_argument("--signal", action="store_true", help="Stage the exchange around a signal lamp")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.out.exists():
        parser.error("Choose a new output directory")
    if args.reaction_timeline:
        if args.signal or args.extra_pause_frames:
            parser.error("The reaction uses the existing signal scene and its timing")
        insert_signal_reaction(bpy.context.scene, args.reaction_timeline, args.out)
        return
    if args.extra_pause_frames < 0:
        parser.error("Extra pause must be nonnegative")
    ask_duration, ask_pcm, ask_times, ask_forms = load_line(args.lines, "ask")
    reply_duration, reply_pcm, reply_times, reply_forms = load_line(args.lines, "reply")
    if args.signal and args.extra_pause_frames < 8:
        parser.error("The signal insert needs at least eight extra pause frames")
    reply_frame = math.ceil(ask_duration * FPS) + 6 + args.extra_pause_frames
    reply_time = reply_frame / FPS
    reply_end = reply_frame + math.ceil(reply_duration * FPS)
    count = reply_end + (15 if args.signal else 9)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    scene = bpy.context.scene
    first = bpy.data.objects["RIG-rain"]
    second, _, copies = duplicate_rain(first)
    actors = (first, second)
    for rig, side in zip(actors, (-1, 1)):
        rig.location.x = side * .415
        rig.rotation_euler.z = -side * math.radians(42)
    top = next(obj for obj in copies if obj.name.startswith("GEO-rain-top"))
    top.data.materials.clear()
    top.data.materials.append(material("Listener teal", (.035, .20, .19)))
    bpy.context.view_layer.update()
    for rig in actors:
        for index, drop in enumerate((15, 25, 20, 10), 1):
            hair = rig.pose.bones[f"FK-Hair_Ponytail{index}"]
            rotate_control(hair, hair.matrix.copy(), (1, 0, 0), -drop)
    stage(scene)
    scene.camera.location = (0, -4, 1.96)
    scene.camera.rotation_euler = (Vector((0, -.10, 1.33)) - scene.camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera.data.ortho_scale = 1.54
    scene.render.resolution_x, scene.render.resolution_y = 512, 288
    scene.eevee.taa_render_samples = 12
    box("Table", (0, -.38, .99), (1.27, .58, .08), material("Warm neutral table", (.18, .11, .065)))
    toy = Vector((0, -.48, 1.06))
    signal_frame = reply_frame - 7 if args.signal else None
    if args.signal:
        toy = signal_lamp(scene, signal_frame)
    else:
        block = box("Flattened yellow toy block", toy, (.23, .15, .06),
                    material("Yellow toy", (.76, .36, .025)), bevel=.004)
        block.rotation_euler.z = math.radians(-17)
    scene.frame_start, scene.frame_end = 0, count - 1
    mesh_visibility = {obj: obj.hide_viewport for obj in scene.objects if obj.type == "MESH"}
    for obj in mesh_visibility:
        obj.hide_viewport = True
    bpy.context.view_layer.update()
    animate(scene, first, ask_times, ask_forms, count)
    animate(scene, second, [0, *(time + reply_time for time in reply_times)], [0, *reply_forms], count)
    play_attention(scene, actors, toy, reply_time, count, args.extra_pause_frames, signal_frame)
    if args.signal:
        settle_signal_gaze(scene, actors, signal_frame, reply_end)
    for obj, hidden in mesh_visibility.items():
        obj.hide_viewport = hidden
    cuts = (add_signal_cameras(scene, reply_frame, signal_frame, reply_end) if args.signal
            else add_dialogue_cameras(scene, reply_frame, args.extra_pause_frames))
    scene.frame_set(0)
    args.out.mkdir(parents=True)
    write_mix(args.out / "dialogue.wav", ask_pcm, reply_pcm, reply_frame, count, signal_frame)
    if args.signal:
        localize_widget_meshes()
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str((args.out / "dialogue.blend").resolve()))
    timeline = {
        "fps": FPS, "frames": count, "reply_frame": reply_frame,
        "extra_pause_frames": args.extra_pause_frames, "cuts": cuts,
        "first": first.name, "second": second.name,
    }
    if args.signal:
        timeline.update(signal_frame=signal_frame, reply_end=reply_end)
        job = dict(schema_version=1, scene="dialogue.blend", out="draft", frames=[0, count],
                   fps=FPS, size=[512, 288], wav="dialogue.wav")
        (args.out / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    (args.out / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
