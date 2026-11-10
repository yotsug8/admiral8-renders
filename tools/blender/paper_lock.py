"""Stage a paper boat waiting at a lock, then drifting into sunlight."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from beacon_preview import aim, area, box, camera, material
from study_lift import smooth


FPS, COUNT = 30, 156
GATE_START, GATE_OPEN = 64, 93
BOAT_RESTART = 85
CUTS = (1, 55, 110)
BRIEF = 'Бумажный кораблик подходит к закрытому шлюзу, ждёт подъёма ворот и выходит в тёплый свет.'
LANDSCAPE = (640, 360)
PORTRAIT = (432, 768)
PHONE_SAFE = (60 / 1080, 940 / 1080, 1 - 1560 / 1920, 1 - 150 / 1920)


def progress(frame, start, end):
    return min(1, max(0, (frame - start) / (end - start)))


def paper_boat():
    ivory = material('Warm paper', (.84, .74, .53), roughness=.76)
    shade = material('Inner paper', (.38, .30, .17), roughness=.77)
    coral = material('Painted folded edge', (.54, .13, .055), roughness=.68)
    points = [(-.64, 0, .25), (.64, 0, .25), (-.34, -.23, .135), (.34, -.23, .135),
              (-.34, .23, .135), (.34, .23, .135), (-.26, 0, -.065), (.26, 0, -.065),
              (-.24, -.07, .055), (.24, -.07, .055), (0, 0, .44),
              (-.24, .07, .055), (.24, .07, .055), (-.48, 0, .14), (.48, 0, .14)]
    faces = [(0, 6, 2), (2, 6, 7, 3), (3, 7, 1), (0, 4, 6), (4, 5, 7, 6), (5, 1, 7),
             (0, 2, 8, 13), (2, 3, 9, 8), (3, 1, 14, 9),
             (0, 13, 11, 4), (4, 11, 12, 5), (5, 12, 14, 1),
             (8, 9, 10), (11, 10, 12), (8, 10, 11), (9, 12, 10), (8, 11, 13), (9, 14, 12)]
    mesh = bpy.data.meshes.new('Folded hull')
    mesh.from_pydata(points, [], faces)
    mesh.update()
    boat = bpy.data.objects.new('Paper boat', mesh)
    bpy.context.scene.collection.objects.link(boat)
    for coat in (ivory, shade, coral):
        mesh.materials.append(coat)
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = 1 if 6 <= index <= 11 else (2 if index in (2, 5) else 0)
    return boat


def water():
    coat = material('Deep moving water', (.025, .14, .21), .38, .22)
    tree = coat.node_tree
    coords = tree.nodes.new('ShaderNodeTexCoord')
    noise = tree.nodes.new('ShaderNodeTexNoise')
    noise.noise_dimensions = '4D'
    noise.inputs['Scale'].default_value = 5
    noise.inputs['Detail'].default_value = 2.5
    phase = noise.inputs['W']
    for frame, value in ((1, 0), (COUNT, 1.15)):
        phase.default_value = value
        phase.keyframe_insert('default_value', frame=frame)
    tree.links.new(coords.outputs['Object'], noise.inputs['Vector'])
    bump = tree.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .31
    bump.inputs['Distance'].default_value = .075
    tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
    tree.links.new(bump.outputs['Normal'], tree.nodes.get('Principled BSDF').inputs['Normal'])
    box('Water', (0, 0, -.055), (100, 2.85, .11), coat, bevel=0)
    return material('Wake crests', (.31, .66, .73), .14, .26)


def wake_curves(coat):
    parts = []
    for side in (-1, 1):
        for index in range(3):
            curve = bpy.data.curves.new('Broken crest', 'CURVE')
            curve.dimensions = '3D'
            curve.bevel_depth = .0075 - .001 * index
            spline = curve.splines.new('POLY')
            spline.points.add(5)
            for j, point in enumerate(spline.points):
                u = j / 5
                x = -.44 - .25 * index - .20 * u
                point.co = (x, side * (.18 + .24 * (-x - .4) + .035 * math.sin(math.pi * u)), .015, 1)
                point.radius = .25 + .75 * math.sin(math.pi * u)
            crest = bpy.data.objects.new('Wake crest', curve)
            bpy.context.scene.collection.objects.link(crest)
            curve.materials.append(coat)
            parts.append(crest)
    return parts


def build(out, size, *, side_exit=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 32
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.fps, scene.frame_end = FPS, COUNT
    scene.world = bpy.data.worlds.new('Twilight')
    scene.world.color = (.055, .072, .10)
    boat, wake = paper_boat(), wake_curves(water())
    stone = material('Blue slate', (.080, .122, .147), roughness=.78)
    edge = material('Capstones', (.20, .24, .24), roughness=.76)
    bronze = material('Lock iron', (.21, .115, .056), .54, .32)
    rail = material('Guide rails', (.28, .29, .25), .58, .34)
    pavement = material('Towpath', (.093, .095, .078), roughness=.83)
    box('Towpath paving', (0, 3.8, .09), (29, 4.1, .27), pavement, .04)
    box('Far retaining wall', (0, 3.2, .71), (29, .31, 1.23), stone, .034)
    box('Far coping', (0, 3.2, 1.36), (29, .43, .14), edge, .02)
    for i in range(-7, 8):
        box('Wall pilaster', (i * 1.15, 2.99, .73), (.25, .20, 1.22), edge, .028)
    for side in (-1, 1):
        box('Canal bank', (0, side * 1.80, -.22), (28, .88, .83), stone, .032)
        for i in range(-8, 9):
            box('Capstone', (i * .78, side * 1.49, .22), (.75, .36, .115), edge, .022)
        box('Masonry pier', (0, side * 1.20, .76), (.51, .32, 1.82), stone, .042)
        box('Gate runner', (0, side * 1.034, .73), (.25, .038, 1.71), rail, .012)
    # The lift gate travels between two beams with space for the ribs.
    for x in (-.235, .235):
        box('Lock lintel beam', (x, 0, 1.64), (.19, 2.70, .24), edge, .035)
    gate = box('Moving gate', (0, 0, .58), (.12, 2.055, 1.28), bronze, .023)
    for y in (-.75, -.40, 0, .40, .75):
        slat = box('Reinforcing rib', (0, 0, 0), (.063, .065, 1.15), rail, .012)
        slat.parent, slat.location = gate, (-.069, y, 0)
    for z in (-.43, .43):
        brace = box('Cross brace', (0, 0, 0), (.07, 2.015, .070), rail, .012)
        brace.parent, brace.location = gate, (-.075, 0, z)
    area('Cold skylight', (-4.2, -1, 4.1), (-1.3, 0, 0), 730, 5, (.45, .70, 1))
    area('River mouth', (3.2, .5, 3.3), (1.5, 0, 0), 1250, 3.0, (1, .66, .31))
    area('Paper rim', (1.4, 2.4, 3.9), (-.7, 0, .2), 470, 2.7, (1, .81, .56))
    if size == PORTRAIT:
        camera(scene, 'Approach', (-5.80, -1.05, 2.52), (-3.17, .17, .47), 44, CUTS[0])
        camera(scene, 'Gate rises', (-2.70, -2.65, 1.90), (-.85, .10, .55), 39, CUTS[1])
        camera(scene, 'In daylight', (1.90, -2.55, 1.85), (.25, .10, .45), 38, CUTS[2])
    else:
        camera(scene, 'Approach', (-3.15, -5.08, 2.28), (-1.85, 0, .58), 39, CUTS[0])
        camera(scene, 'Gate rises', (-1.75, -3.10, 1.68), (-.53, 0, .64), 42, CUTS[1])
        camera(scene, 'In daylight', (2.58, -4.36, 1.95), (1.25, .12, .51), 41, CUTS[2])
        exit_camera = bpy.data.objects['In daylight']
        exit_camera.keyframe_insert('location', frame=CUTS[2])
        exit_camera.location.x += 1.92
        exit_camera.keyframe_insert('location', frame=COUNT)

    if side_exit:
        camera(scene, 'Side exit', (0, -3.55, 1.98), (0, .1, .40), 36, CUTS[2])
        scene.timeline_markers.remove(scene.timeline_markers['Side exit'])
        side = bpy.data.objects['Side exit']

    for frame in range(1, COUNT + 1):
        t = (frame - 1) / FPS
        incoming = progress(frame, 1, 52)
        outgoing = progress(frame, BOAT_RESTART, COUNT)
        x = -3.52 + 2.39 * (1 - (1 - incoming) ** 1.65) + 4.43 * outgoing ** 1.22
        boat.location = (x, .13 + .055 * math.sin(t * 1.45), .018 + .014 * math.sin(t * 4.5))
        boat.rotation_euler = (.044 * math.sin(t * 5), .033 * math.cos(t * 3.6), .042 * math.sin(t * 2))
        boat.keyframe_insert('location', frame=frame)
        boat.keyframe_insert('rotation_euler', frame=frame)
        if side_exit and frame >= CUTS[2]:
            side.location.x = x + 1.18
            aim(side, (x + .16, .10, .42))
            side.keyframe_insert('location', frame=frame)
            side.keyframe_insert('rotation_euler', frame=frame)
        if size == PORTRAIT:
            if frame < CUTS[1]:
                view = bpy.data.objects['Approach']
                view.location.x = -5.80 + 1.50 * progress(frame, 1, CUTS[1] - 1)
                aim(view, (x + .35, .17, .47))
            elif frame < CUTS[2]:
                view = bpy.data.objects['Gate rises']
                aim(view, (x + .14, .10, .55))
            else:
                view = bpy.data.objects['In daylight']
                view.location.x = x + 1.65
                aim(view, (x + .17, .10, .45))
            view.keyframe_insert('location', frame=frame)
            view.keyframe_insert('rotation_euler', frame=frame)
        gate.location.z = .58 + 1.34 * smooth(progress(frame, GATE_START, GATE_OPEN))
        gate.keyframe_insert('location', index=2, frame=frame)
        activity = max((1 - incoming) ** .65, outgoing ** .22)
        for crest in wake:
            crest.location = (x, boat.location.y, 0)
            crest.scale = (activity, activity, activity)
            crest.keyframe_insert('location', frame=frame)
            crest.keyframe_insert('scale', frame=frame)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'scene.blend'))


def verify(out, *, side_exit=False):
    bpy.ops.wm.open_mainfile(filepath=str(out / 'scene.blend'), use_scripts=False)
    scene = bpy.context.scene
    boat, gate = bpy.data.objects['Paper boat'], bpy.data.objects['Moving gate']
    previous = -10.
    min_gap = float('inf')
    min_margin = 1.
    min_safe = 1.
    side_margin = 1.
    cross_frame = None
    portrait = scene.render.resolution_x < scene.render.resolution_y
    left, right, bottom, top = PHONE_SAFE
    if tuple(sorted(marker.frame for marker in scene.timeline_markers if marker.camera)) != CUTS:
        raise ValueError('Camera cuts differ from the shot plan')
    for i in range((COUNT - 1) * 4 + 1):
        frame = 1 + i / 4
        scene.frame_set(int(frame), subframe=frame % 1)
        assert boat.location.x >= previous - 1e-5
        previous = boat.location.x
        corners = [boat.matrix_world @ vertex.co for vertex in boat.data.vertices]
        assert max(abs(vertex.y) for vertex in corners) < 1.02
        assert min(vertex.z for vertex in corners) < 0 < max(vertex.z for vertex in corners)
        if min(v.x for v in corners) < .125 and max(v.x for v in corners) > -.125:
            min_gap = min(min_gap, gate.location.z - .64 - max(v.z for v in corners))
        if i % 4 == 0:
            if cross_frame is None and boat.location.x >= 0:
                cross_frame = int(frame)
            views = [world_to_camera_view(scene, scene.camera, vertex) for vertex in corners]
            min_margin = min(min_margin, *(min(p.x, p.y, 1 - p.x, 1 - p.y) for p in views))
            if any(p.z <= 0 for p in views):
                raise ValueError(f'Boat behind camera at frame {frame:g}')
            if portrait:
                margin = min(min(p.x - left, right - p.x, p.y - bottom, top - p.y) for p in views)
                if margin < 0:
                    raise ValueError(f'Boat outside phone safe area at frame {frame:g}: {margin:.3f}')
                min_safe = min(min_safe, margin)
            if side_exit and frame >= CUTS[2]:
                side_views = [world_to_camera_view(scene, scene.objects['Side exit'], v) for v in corners]
                if any(p.z <= 0 for p in side_views):
                    raise ValueError(f'Boat behind alternate camera at frame {frame:g}')
                if portrait:
                    border = min(min(p.x - left, right - p.x, p.y - bottom, top - p.y) for p in side_views)
                else:
                    border = min(min(p.x, 1 - p.x, p.y, 1 - p.y) for p in side_views)
                if border < .02:
                    raise ValueError(f'Boat outside alternate camera at frame {frame:g}: {border:.3f}')
                side_margin = min(side_margin, border)
    assert min_gap > .05 and math.isfinite(min_gap) and cross_frame is not None
    assert min_margin > .02
    report = dict(clearance_m=round(min_gap, 6), frame_margin=round(min_margin, 6),
                  motion_samples=(COUNT - 1) * 4 + 1, camera_frames=COUNT, cross_frame=cross_frame)
    if portrait:
        report['phone_safe_margin'] = round(min_safe, 6)
    if side_exit:
        report['side_exit_margin'] = round(side_margin, 6)
    return report


def soundtrack(path):
    rate = 48_000
    time = np.arange(COUNT * rate // FPS) / rate
    rng = np.random.default_rng(230)
    stream = np.interp(time, np.arange(len(time) // 40 + 1) * 40 / rate,
                       rng.uniform(-1, 1, len(time) // 40 + 1))
    wash = np.convolve(stream, np.ones(79) / 79, mode='same')
    water = (.014 * stream + .032 * wash) * (.65 + .35 * np.sin(3.4 * time) ** 2)
    gate_age = time - (GATE_START - 1) / FPS
    gate_dur = (GATE_OPEN - GATE_START) / FPS
    grit = np.convolve(rng.uniform(-1, 1, len(time)), np.ones(13) / 13, mode='same')
    motion = np.clip(np.minimum(gate_age / .07, (gate_dur - gate_age) / .16), 0, 1)
    lift = .20 * grit * motion
    for contact in (.06, .18, .33, .49, .64, .77):
        age = gate_age - contact
        decay = np.exp(-58 * np.maximum(0, age))
        lift += .30 * grit * decay * np.clip(age / .002, 0, 1) * motion
    stop_age = np.maximum(0, time - (GATE_OPEN - 1) / FPS)
    stop = (.16 * np.sin(math.tau * 94 * stop_age) + .32 * grit) * np.exp(-48 * stop_age)
    stop *= np.clip(stop_age / .002, 0, 1)
    pcm = np.stack((water + .78 * lift + .77 * stop, water * .86 + lift + stop), axis=1)
    edge = np.clip(np.minimum(time, time[-1] - time) / .075, 0, 1)
    with wave.open(str(path), 'wb') as output:
        output.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(np.round(pcm * edge[:, None] * 32767).astype('<i2').tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--portrait', action='store_true', help='Reframe the three shots for 9:16')
    parser.add_argument('--side-exit', action='store_true', help='Check and save an alternate final shot')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = args.out.resolve()
    size = PORTRAIT if args.portrait else LANDSCAPE
    ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Set FFMPEG or add ffmpeg to PATH')
    out.mkdir(parents=True)
    build(out, size, side_exit=args.side_exit)
    checks = verify(out, side_exit=args.side_exit)
    soundtrack(out / 'mix.wav')
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(out / 'mix.wav'),
                    '-af', 'loudnorm=I=-14:TP=-2:LRA=7', '-ar', '48000', '-c:a', 'pcm_s16le',
                    str(out / 'mix-master.wav')], check=True)
    plan = dict(brief=BRIEF, fps=FPS, size=size, frame_count=COUNT, cuts=list(CUTS),
                shots=['Подход к закрытым воротам', 'Пауза и подъём ворот', 'Выход в тёплый свет'],
                cues={'gate_start': GATE_START, 'gate_stop': GATE_OPEN,
                      'boat_restart': BOAT_RESTART, 'boat_cross': checks['cross_frame']})
    (out / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'scene_check.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    job = dict(schema_version=1, scene='scene.blend', out='draft', frames=[1, COUNT + 1],
               size=size, fps=FPS, wav='mix-master.wav')
    (out / 'job.json').write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
    if args.side_exit:
        insert = dict(job, out='insert', frames=[CUTS[2], COUNT + 1], camera='Side exit')
        del insert['wav']
        (out / 'insert.json').write_text(json.dumps(insert, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
