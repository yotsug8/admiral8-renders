"""Stage and score the checked Rain suitcase performance as a short film."""
import argparse
import json
from pathlib import Path
import sys
import wave

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "skit")]
from beacon_preview import area, box, camera, material
from check_rain_handle_contact import inspect
from prepare_study_scene import localize_widget_meshes
from rain_lightcase_audio import FPS, FRAMES, RATE, landing_frame, write_footfall
from study_rain_lightcase import SOURCE, build, preflight


GRIP, LIFT = 53, 65
CUTS = (0, 35, 63, 114)
SIZE = (640, 360)
HOLD = LIFT - 1


def frame_at(scene, frame):
    scene.frame_set(int(frame), subframe=frame % 1)
    bpy.context.view_layer.update()


def add_hold(scene, rig, pause):
    """Keep the authored action intact and remap time on its native NLA strip."""
    probes = (0, 38, GRIP, HOLD - .5, HOLD, HOLD + .5, LIFT, 82, 92, CUTS[-1], FRAMES - 1)
    reference = {}
    for frame in probes:
        frame_at(scene, frame)
        reference[frame] = [bone.matrix.copy() for bone in rig.pose.bones]

    animation = rig.animation_data
    action, slot = animation.action, animation.action_slot
    animation.action = None
    track = animation.nla_tracks.new()
    track.name = 'Lift with authored pause'
    strip = track.strips.new(action.name, 0, action)
    strip.action_slot = slot
    strip.frame_end = scene.frame_end + pause
    strip.use_animated_time = True
    for frame, source in ((0, 0), (HOLD, HOLD), (HOLD + pause, HOLD),
                          (scene.frame_end + pause, scene.frame_end)):
        strip.strip_time = source
        strip.keyframe_insert('strip_time', frame=frame)
    for curve in strip.fcurves:
        for point in curve.keyframe_points:
            point.interpolation = 'LINEAR'

    comparisons = [(frame + pause if frame > HOLD else frame, frame) for frame in probes]
    comparisons += [(HOLD + offset, HOLD) for offset in range(1, pause + 1)]
    error = 0.
    for frame, source in comparisons:
        frame_at(scene, frame)
        error = max(error, *(abs(a[i][j] - b.matrix[i][j])
                             for a, b in zip(reference[source], rig.pose.bones)
                             for i in range(4) for j in range(4)))
    if error > 1e-4:
        raise RuntimeError(f'Playback changed the authored pose: {error:.6f}')
    return error


def stage(scene):
    for obj in list(scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    painted = material("Petrol enamel", (.062, .19, .20), metal=.27, roughness=.42)
    pale = material("Workshop stone", (.22, .25, .24), roughness=.91)
    black = material("Blackened steel", (.043, .065, .067), metal=.42)
    timber = material("Oiled ash", (.24, .18, .13), roughness=.58)
    paper = material("Muted shipping marks", (.29, .26, .20), roughness=.58)
    bpy.data.objects["Floor"].data.materials[0] = pale
    box("Workshop back wall", (0, 1.75, 1.5), (14, .16, 3), painted)
    box("Workshop kick plate", (0, 1.65, .14), (14, .09, .24), black)
    for x in (-4.85, -3.55, -2.25, -.95, .35, 1.65, 2.95, 4.25):
        box("Wall seam", (x, 1.658, 1.52), (.018, .016, 2.85), black, .005)
    box("Packing counter", (1.50, 1.09, .86), (1.7, .66, .10), timber)
    for x in (.80, 2.20):
        box("Counter support", (x, 1.17, .40), (.10, .42, .79), black)
    for x, height in ((1.04, .34), (1.52, .26), (1.94, .38)):
        box("Packed carton", (x, 1.14, .91 + height / 2), (.36, .37, height), timber)
        box("Packing tape", (x, .951, .91 + height * .71), (.30, .010, .050), paper, .004)
    area("Window softbox", (-2, -2.2, 3.4), (0, 0, 1), 420, 2.7, (1, .80, .58))
    area("Cool bounce", (2.5, -1.35, 2.3), (-.2, 0, .9), 280, 2.6, (.69, .86, 1))
    area("Rim strip", (.64, .95, 2.75), (0, -.20, 1.15), 220, 1.35, (.65, .83, 1))
    camera(scene, "01 Approach", (1.55, -3.52, 1.78), (-.16, -.03, .90), 39, CUTS[0])
    camera(scene, "02 Grip", (-1.38, -1.75, 1.19), (-.25, -.28, .91), 61, CUTS[1])
    # Return to the same angle before the lift to keep the step and case visible.
    scene.timeline_markers.new("03 Lift and catch balance", frame=CUTS[2]).camera = (
        bpy.data.objects["01 Approach"]
    )
    camera(scene, "04 Compose", (1.05, -2.62, 1.51), (-.18, .04, 1.18), 48, CUTS[3])
    scene.frame_end = FRAMES - 1
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.eevee.taa_render_samples = 12
    scene.frame_set(0)


def score(out, step, *, count=FRAMES, touchdown=None):
    footfall = out / "footfall.wav"
    write_footfall(footfall, step)
    with wave.open(str(footfall), "rb") as source:
        mono = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2") / 32767.
    stereo = np.zeros((count * RATE // FPS, 2))
    stereo[:len(mono)] = mono[:, None] * (.69, 1.)
    rng = np.random.default_rng(204)
    # Short handle contacts use filtered noise. The setdown also excites the stand.
    cues = [(GRIP, .075, 5, 75, (), .075),
            (LIFT, .14, 11, 39, ((260, .12, 66),), .085)]
    if touchdown is not None:
        cues.append((touchdown, .18, 12, 54, ((83, .14, 44), (171, .08, 56)), .22))
    for frame, length, smoothing, decay, modes, gain in cues:
        t = np.arange(round(RATE * length)) / RATE
        grit = np.convolve(rng.uniform(-1, 1, len(t)), np.ones(smoothing) / smoothing, mode="same")
        hit = grit * np.exp(-decay * t)
        for frequency, weight, damping in modes:
            hit += weight * np.sin(2 * np.pi * frequency * t) * np.exp(-damping * t)
        hit *= np.minimum(t / .002, 1) * np.clip((length - t) / .015, 0, 1)
        hit *= gain / np.max(np.abs(hit))
        start = frame * RATE // FPS
        stereo[start:start + len(t)] += hit[:, None] * (1., .62)
    if touchdown is not None:
        # Lift the quiet contact mix as a whole, leaving headroom for AAC.
        stereo *= 10 ** (-3.5 / 20) / np.max(np.abs(stereo))
    with wave.open(str(out / "mix.wav"), "wb") as audio:
        audio.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        audio.writeframes(np.round(stereo * 32767).astype("<i2").tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    out = args.out.resolve()
    pause = 0
    if args.plan:
        request = json.loads(args.plan.read_text(encoding='utf-8'))
        if (not isinstance(request, dict) or request.get('schema_version') != 1
                or request.get('actor') != 'rain' or request.get('action') != 'lift_case'
                or type(request.get('pause_frames')) is not int or request['pause_frames'] not in (9, 18)):
            raise ValueError('Use a version 1 Rain lift plan')
        pause = request['pause_frames']
    out.mkdir(parents=True, exist_ok=True)
    scene, rig, case = build(out, save=False, source=args.source.resolve(strict=True))
    count = FRAMES + pause
    error = add_hold(scene, rig, pause) if pause else 0.

    def source_frame(frame):
        return frame - min(max(frame - HOLD, 0), pause)

    report = preflight(scene, rig, case, range(count), source_frame=source_frame)
    (out / "contact.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    step = landing_frame(report) if not pause else None
    if pause and not report['passed']:
        raise RuntimeError('Rain lift did not pass surface and support checks')
    grip_frames = list(range(GRIP, count))
    if pause:
        grip_frames += [frame + .5 for frame in range(HOLD - 1, LIFT + pause + 7)]
    grip = inspect(scene, bpy.data.objects["GEO-rain-body"], bpy.data.objects["Case handle"],
                   sorted(grip_frames), "R")
    (out / "grip.json").write_text(json.dumps(grip, indent=2), encoding="utf-8")
    if not grip["passed"]:
        failed = [row["frame"] for row in grip["rows"] if row["failures"]]
        raise RuntimeError(f"Case grasp failed on frames: {failed[:12]}")
    stage(scene)
    if pause:
        bpy.data.scenes[scene.name].timeline_markers['04 Compose'].frame += pause
        scene.frame_end = count - 1
        scene.eevee.taa_render_samples = 8
        scene.frame_set(0)
    localize_widget_meshes()
    bpy.ops.file.pack_all()
    external = bpy.utils.blend_paths(absolute=True, packed=False)
    if external:
        raise RuntimeError(f"Scene still references an external file: {external[0]}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "scene.blend"))
    job = dict(schema_version=1, scene="scene.blend", out="draft",
               frames=[0, count], size=SIZE, fps=FPS)
    if not pause:
        score(out, step)
        job['wav'] = 'mix.wav'
    (out / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    plan = dict(cuts=(*CUTS[:-1], CUTS[-1] + pause), grip=GRIP, lift=LIFT + pause, step=step,
                character="Rain Rig (CC) Blender Foundation, CC BY 4.0")
    if pause:
        plan.update(pause_frames=pause, hold_frame=HOLD, pose_error=error)
    (out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
