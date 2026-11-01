"""Start, two articulated steps, brake and hold; existing mannequin, CPU only."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import bpy
import numpy as np
from mathutils import Vector, Quaternion
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_foot_roll as roll
import study_lift as lift
import study_prop_turn as common
from study_step_touch import LINKS, mesh_vertices
from study_pointing import segment_distance

FPS, COUNT = 30, 120
# heel rise, toe-tip roll, toe-off, heel strike, sole down, destination
STEPS = {'R': (.35, .55, .65, 1.20, 1.40, .42),
         'L': (1.28, 1.48, 1.58, 2.18, 2.40, .68)}
CAMERAS = {'profile': (6.5, .30, 1.5), 'three_quarter': (4.5, -4.5, 2.3)}
BLOCK = (0, 12, 27, 39, 54, 68, 87, 113)


def curve(t, keys):
    for (a, x), (b, y) in zip(keys, keys[1:]):
        if t <= b:
            return x + (y-x)*lift.smooth((t-a)/(b-a))
    return keys[-1][1]


def foot_frames(side, t):
    rise, tip, off, heel, flat, distance = STEPS[side]
    x = -.18 if side == 'L' else .18
    if t <= rise:
        return roll.transform((x, 0, 0), 0), roll.transform((x, .14, 0), 0)
    if t <= off:
        toe_angle = -math.radians(10)*roll.progress(t, tip, off)
        rear_angle = -math.radians(25)*roll.progress(t, rise, tip) + toe_angle
        toe_q = Quaternion((1, 0, 0), toe_angle)
        toe = roll.transform(Vector((x, .24, 0))-toe_q@Vector((0, .10, 0)), toe_angle)
    elif t < heel:
        u = (t-off)/(heel-off)
        eased = lift.smooth(u)
        rear_angle = math.radians(-35+53*eased)
        toe_angle = math.radians(-10+28*eased)
        start = Vector((x, .24, 0))-Quaternion((1, 0, 0), math.radians(-10))@Vector((0, .10, 0))
        end = Vector((x, distance-.16, 0))+Quaternion((1, 0, 0), math.radians(18))@Vector((0, .30, 0))
        toe = roll.transform(start.lerp(end, eased)+Vector((0, 0, .16*math.sin(math.pi*u)**2)), toe_angle)
    else:
        rear_angle = math.radians(18)*(1-roll.progress(t, heel, flat))
        rear_q = Quaternion((1, 0, 0), rear_angle)
        rear = roll.transform(Vector((x, distance-.16, 0))-rear_q@Vector((0, -.16, 0)), rear_angle)
        return rear, roll.transform(rear@Vector((0, .14, 0)), rear_angle)
    rear_q = Quaternion((1, 0, 0), rear_angle)
    return roll.transform(toe@Vector((0, 0, .06))-rear_q@roll.BALL, rear_angle), toe


def pelvis_y(t):
    keys = ((.35, -.075, 0), (1.30, .15, .45), (2.20, .46, .20), (2.85, .475, 0))
    if t <= keys[0][0]: return keys[0][1]
    for (a, x, vx), (b, y, vy) in zip(keys, keys[1:]):
        if t <= b:
            u = (t-a)/(b-a)
            return (2*u**3-3*u**2+1)*x+(u**3-2*u**2+u)*(b-a)*vx+(-2*u**3+3*u**2)*y+(u**3-u**2)*(b-a)*vy
    return keys[-1][1]


def pose(t):
    px = curve(t, [(0, 0), (.4, -.10), (.95, -.10), (1.45, .10), (2.15, .10), (2.85, 0)])
    pz = curve(t, [(0, .91), (.4, .89), (1., .92), (1.45, .89), (1.95, .92), (2.45, .875), (2.85, .91)])
    lean = curve(t, [(0, 0), (.45, .08), (1.75, .06), (2.38, -.06), (2.85, 0)])
    pelvis = Vector((px, pelvis_y(t), pz))
    neck = pelvis+Vector((0, .5*math.sin(lean), .5*math.cos(lean)))
    head = neck+Vector((0, .19*math.sin(lean*.65), .19*math.cos(lean*.65)))
    p = {'pelvis': pelvis, 'neck': neck, 'head': head, 'Nose': head+Vector((0, .145, 0))}
    swing = curve(t, [(0, 0), (.4, .03), (1.15, -.13), (2.10, .13), (2.55, -.025), (2.85, 0)])
    for side, sign in [('L', -1), ('R', 1)]:
        rear, _ = foot_frames(side, t)
        ankle = rear@Vector((0, -.075, .10))
        hip = pelvis+Vector((sign*.15, 0, 0))
        knee = lift.solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
        shoulder = neck+Vector((sign*.23, 0, 0))
        hand = pelvis+Vector((sign*.40, .08+sign*swing, -.24))
        elbow = lift.solve(shoulder, hand, .44, .42, Vector((sign, -.15, .12)))
        for name, value in [('hip', hip), ('knee', knee), ('ankle', ankle),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            p[f'{side}_{name}'] = value
    return p


def setup():
    # Reuse the existing geometry, parenting, lights and dense-key baker unchanged.
    old = roll.pose, roll.foot_frames, roll.CAMERAS
    roll.pose, roll.foot_frames, roll.CAMERAS = pose, foot_frames, CAMERAS
    try: sc = roll.setup()
    finally: roll.pose, roll.foot_frames, roll.CAMERAS = old
    for view in CAMERAS:
        camera = bpy.data.objects[view]
        camera.rotation_euler = (Vector((0, .30, .86))-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.ortho_scale = 3.9
    sc['study'] = 'start_stop'
    sc['limits'] = 'Two kinematic steps, no physical mass, balance simulation or skin.'
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    bpy.context.preferences.filepaths.save_version = 0
    return sc


def validate():
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    geometry = {s+'_'+p: mesh_vertices(bpy.data.objects[s+'_'+p]) for s in STEPS for p in roll.PARTS}
    soles = {n: [v for v in verts if abs(v.z-min(p.z for p in verts)) < 1e-6] for n, verts in geometry.items()}
    r = dict(samples=(COUNT-1)*16+1, contact_drift=0., contact_speed=0., min_floor=1.,
             length_error=0., joint_error=0., hinge_error=0., hold_drift=0.,
             min_arm_clearance=1., max_point_step=0., margin={v: 1. for v in CAMERAS},
             phases={}, airborne_intervals={}, max_swing_height={s: 0. for s in STEPS})
    names = tuple(pose(0))
    tracks, airborne, previous_contacts = [], {s: [] for s in STEPS}, {}
    hold_start = None
    witness_times = {}
    for side, (rise, tip, off, heel, flat, _) in STEPS.items():
        for label, t in [('toe_area', (rise+tip)/2), ('toe_tip', (tip+off)/2),
                         ('swing', (off+heel)/2), ('heel', heel), ('flat', flat+.04)]:
            witness_times.setdefault(round(t*FPS*16), []).append((side, label))
    for i in range(r['samples']):
        frame, t = i/16, i/(FPS*16)
        sc.frame_set(int(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        points = {n: bpy.data.objects[n].matrix_world.translation.copy() for n in names}
        rods = {}
        for n, (a, b) in LINKS.items():
            ob = bpy.data.objects[n]
            start, end = (ob.matrix_world@Vector((0, 0, z)) for z in (-.5, .5))
            rods[n] = start, end, ob['radius']
            r['length_error'] = max(r['length_error'], abs((end-start).length-ob['length']))
            r['joint_error'] = max(r['joint_error'], (start-points[a]).length, (end-points[b]).length)
            r['min_floor'] = min(r['min_floor'], start.z-ob['radius'], end.z-ob['radius'])
        r['length_error'] = max(r['length_error'], abs((points['head']-points['neck']).length-.19))
        for n, p in points.items(): r['min_floor'] = min(r['min_floor'], p.z-bpy.data.objects[n]['radius'])
        surfaces, contacts = {}, {}
        for side, (rise, tip, off, heel, flat, distance) in STEPS.items():
            x = -.18 if side == 'L' else .18
            rear, toe = (bpy.data.objects[side+'_'+n].matrix_world for n in ('rear', 'toe_root'))
            r['joint_error'] = max(r['joint_error'], (points[side+'_ankle']-rear@Vector((0, -.075, .10))).length)
            r['hinge_error'] = max(r['hinge_error'], (rear@roll.BALL-toe@Vector((0, 0, .06))).length)
            for part, (center, _) in roll.PARTS.items():
                name = side+'_'+part
                ob = bpy.data.objects[name]
                surfaces[name] = [ob.matrix_world@v for v in soles[name]]
                r['min_floor'] = min(r['min_floor'], min((ob.matrix_world@v).z for v in geometry[name]))
                for j, (local, world) in enumerate(zip(soles[name], surfaces[name])):
                    target = None
                    if t <= rise or t >= flat:
                        target = local+Vector(center)+Vector((x, (0 if t <= rise else distance)+(.14 if part == 'toe' else 0), 0))
                    elif rise <= t <= tip and part == 'toe':
                        target = local+Vector(center)+Vector((x, .14, 0))
                    elif tip <= t <= off and part == 'toe' and local.y > 0:
                        target = Vector((x+local.x, .24, 0))
                    elif heel <= t <= flat and part == 'heel' and local.y < 0:
                        target = Vector((x+local.x, distance-.16, 0))
                    if target is not None:
                        key = (name, j, tuple(round(v, 6) for v in target))
                        contacts[key] = world
                        r['contact_drift'] = max(r['contact_drift'], (world-target).length)
                        if key in previous_contacts:
                            r['contact_speed'] = max(r['contact_speed'], (world-previous_contacts[key]).length*FPS*16)
            height = min(v.z for part in roll.PARTS for v in surfaces[side+'_'+part])
            airborne[side].append(height > .0001)
            r['max_swing_height'][side] = max(r['max_swing_height'][side], height)
        for side, label in witness_times.get(i, []):
            bounds = {part: [min(v.z for v in surfaces[side+'_'+part]), max(v.z for v in surfaces[side+'_'+part])]
                      for part in roll.PARTS}
            r['phases'][side+'_'+label] = bounds
        for n in ('L_upperarm', 'R_upperarm', 'L_forearm', 'R_forearm'):
            a, b, rad = rods[n]
            for other in ('torso', 'L_thigh', 'R_thigh', 'L_shin', 'R_shin'):
                c, d, rad2 = rods[other]
                r['min_arm_clearance'] = min(r['min_arm_clearance'], segment_distance(a, b, c, d)-rad-rad2)
        current = [tuple(points[n]) for n in names]+[tuple(v) for n in geometry for v in surfaces[n]]
        tracks.append(current)
        if t >= 2.85:
            if hold_start is None: hold_start = np.array(current)
            r['hold_drift'] = max(r['hold_drift'], float(np.linalg.norm(np.array(current)-hold_start, axis=1).max()))
        previous_contacts = contacts
        if i % 16 == 0:
            for view in CAMERAS:
                for ob in sc.objects:
                    if ob.type == 'MESH' and ob.name != 'Floor':
                        for corner in ob.bound_box:
                            uv = world_to_camera_view(sc, bpy.data.objects[view], ob.matrix_world@Vector(corner))
                            if uv.z <= 0: raise ValueError('Behind camera')
                            r['margin'][view] = min(r['margin'][view], uv.x, uv.y, 1-uv.x, 1-uv.y)
    for side, states in airborne.items():
        r['airborne_intervals'][side] = sum(b and not a for a, b in zip([False]+states, states))
    r['airborne_times'] = {s: [next(i for i, v in enumerate(a) if v)/(FPS*16),
                               max(i for i, v in enumerate(a) if v)/(FPS*16)]
                           for s, a in airborne.items() if any(a)}
    r['double_airborne_samples'] = sum(a and b for a, b in zip(airborne['R'], airborne['L']))
    tracks = np.array(tracks)
    speeds = np.linalg.norm(np.diff(tracks, axis=0), axis=2)*FPS*16
    r['max_point_step'] = float(speeds.max()/(FPS*16))
    r['pelvis_forward_peak_speed'] = float(np.diff(tracks[:, 0, 1]).max()*FPS*16)
    r['pelvis_forward_distance'] = float(tracks[-1, 0, 1]-tracks[0, 0, 1])
    r['preparation_lateral_shift'] = float(tracks[round(.4*FPS*16), 0, 0]-tracks[0, 0, 0])
    r['pelvis_forward_overshoot'] = float(tracks[:, 0, 1].max()-tracks[-1, 0, 1])
    phase_pass = {}
    for side in STEPS:
        p = {label: r['phases'][side+'_'+label] for label in ('toe_area', 'toe_tip', 'swing', 'heel', 'flat')}
        phase_pass[side] = (p['toe_area']['heel'][0] > .02 and max(abs(v) for v in p['toe_area']['toe']) < 2e-5
                           and abs(p['toe_tip']['toe'][0]) < 2e-5 and p['toe_tip']['toe'][1] > .002
                           and min(v[0] for v in p['swing'].values()) > .08
                           and abs(p['heel']['heel'][0]) < 2e-5 and p['heel']['toe'][0] > .05
                           and max(abs(v) for bounds in p['flat'].values() for v in bounds) < 2e-5)
    r['phase_pass'] = phase_pass
    if (r['contact_drift'] > 2e-5 or r['contact_speed'] > .003 or r['min_floor'] < -2e-5
        or r['length_error'] > 2e-6 or r['joint_error'] > .002 or r['hinge_error'] > 2e-5
        or r['hold_drift'] > 2e-6 or r['min_arm_clearance'] < -.0001 or r['max_point_step'] > .008
        or min(r['margin'].values()) < .025 or not all(phase_pass.values())
        or r['double_airborne_samples'] != 0 or r['preparation_lateral_shift'] > -.09
        or any(v != 1 for v in r['airborne_intervals'].values())):
        raise ValueError(json.dumps(r))
    return r


def negative_tests():
    caught = []
    for label, name, prop, axis, delta, metric, limit in [
        ('contact_offset', 'R_heel', 'delta_location', 1, .015, 'contact_drift', .014),
        ('toe_sink', 'L_toe', 'delta_location', 2, -.01, 'min_floor', -.009),
        ('length', 'R_shin', 'scale', 2, .02, 'length_error', .019)]:
        ob = bpy.data.objects[name]
        original = getattr(ob, prop).copy()
        getattr(ob, prop)[axis] += delta
        try:
            try: validate()
            except ValueError as exc:
                value = json.loads(str(exc))[metric]
                assert value < limit if limit < 0 else value > limit
                caught.append(label)
            else: raise AssertionError('Missed '+label)
        finally: setattr(ob, prop, original)
    for label, names, metric in [('sliding_stop', ('R_rear', 'R_toe_root'), 'contact_speed'),
                                  ('unstable_hold', ('pelvis',), 'hold_drift')]:
        saved = []
        for name in names:
            ob = bpy.data.objects[name]
            fc = next(c for c in common.curves(ob) if c.data_path == 'location' and c.array_index == 1)
            coords = [k.co.copy() for k in fc.keyframe_points]
            saved.append((ob, fc, coords))
            for k in fc.keyframe_points: k.co.y += .02*roll.progress(k.co.x/FPS, 2.85, 3.8)
            fc.update()
            ob.animation_data.action.update_tag()
        try:
            try: validate()
            except ValueError as exc:
                assert json.loads(str(exc))[metric] > .01
                caught.append(label)
            else: raise AssertionError('Missed '+label)
        finally:
            for ob, fc, coords in saved:
                for k, co in zip(fc.keyframe_points, coords): k.co = co
                fc.update()
                ob.animation_data.action.update_tag()
    validate()
    return caught


def movie_review(folder, ffmpeg):
    # Reuse existing decoder and all-frame contact sheets with its expected basename.
    return roll.movie_review(folder, ffmpeg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--mode', choices=('build', 'block', 'render', 'verify', 'review'), default='build')
    ap.add_argument('--ffmpeg', type=Path)
    ap.add_argument('--journal', type=Path)
    args = ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.mode in ('render', 'review') and (not args.ffmpeg or not args.ffmpeg.is_file()):
        raise ValueError('--ffmpeg must point to an existing executable')
    common.JOURNAL = args.journal.resolve() if args.journal else None
    common.journal('start_stop_'+args.mode, 'Check saved motion before rendering', active=True, exitcode=None)
    start = time.perf_counter()
    out = args.out.resolve()
    if args.mode not in ('verify', 'review'):
        if out.exists(): raise ValueError('Use a new directory')
        out.mkdir(parents=True)
        setup()
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'))
    report = validate()
    report['blender'] = bpy.app.version_string
    if args.mode in ('build', 'verify', 'review'): report['negative_tests'] = negative_tests()
    if args.mode == 'review':
        report['movies'] = {v: movie_review(out/v, args.ffmpeg) for v in CAMERAS}
    elif args.mode in ('block', 'render'):
        for view in CAMERAS:
            common.journal('start_stop_'+args.mode+'_'+view, 'Render CPU camera', active=True)
            sc = bpy.context.scene
            sc.camera = bpy.data.objects[view]
            frames = out/view/'frames'
            frames.mkdir(parents=True)
            if args.mode == 'block':
                for f in BLOCK:
                    sc.frame_set(f)
                    sc.render.filepath = str(frames/f'f{f:04d}.png')
                    bpy.ops.render.render(write_still=True)
            else:
                sc.render.filepath = str(frames/'f')
                bpy.ops.render.render(animation=True)
                subprocess.run([str(args.ffmpeg), '-v', 'error', '-framerate', str(FPS), '-i', str(frames/'f%04d.png'),
                                '-frames:v', str(COUNT), '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
                                '-movflags', '+faststart', str(out/view/'foot_roll.mp4')], check=True)
    report['elapsed_seconds'] = time.perf_counter()-start
    (out/(args.mode+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    common.journal('start_stop_'+args.mode+'_complete', 'Inspect result; retain scope', active=False, exitcode=0)
    print(json.dumps(report))


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        common.journal('start_stop_failed', 'Inspect measured failure', active=False, exitcode=2, error=str(exc))
        raise
