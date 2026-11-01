"""One articulated foot step: heel strike, sole, heel lift and toe push-off.

Blender CPU. --out NEW_DIR --mode build|block|render --ffmpeg EXE
Review an existing render with --mode review. Optional --journal JSON.
Rigid kinematics on flat ground, not a balance or game-rig simulation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

import bpy
import numpy as np
from mathutils import Vector, Quaternion, Matrix
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_lift as lift
import study_prop_turn as common
from study_step_touch import LINKS, mesh_vertices
from study_pointing import point_segment, segment_distance

FPS, COUNT = 30, 120
LIFT, HEEL, FLAT, RISE, TIP, OFF, END = .30, 1.10, 1.45, 2., 2.60, 3., 3.50
LAND_Y = .32
BALL = Vector((0, .14, .06))  # Dorsal hinge avoids overlapping solid foot segments.
PARTS = {'heel': ((0, -.10, .04), (.18, .12, .08)),
         'forefoot': ((0, .05, .03), (.18, .18, .06)),
         'toe': ((0, .05, .03), (.18, .10, .06))}
CAMERAS = {'profile': (6.5, .20, 1.4), 'three_quarter': (4.5, 4.5, 2.3)}
BLOCK_FRAMES = (0, 33, 48, 75, 87, 105)


def progress(t, a, b):
    return lift.smooth((t-a)/(b-a))


def transform(location, angle):
    return Matrix.LocRotScale(Vector(location), Quaternion((1, 0, 0), angle), Vector((1, 1, 1)))


def foot_frames(side, t):
    if side == 'L':
        rear = transform((-.23, -.04, 0), 0)
        return rear, transform((-.23, .10, 0), 0)
    if t <= HEEL:
        u = max(0., min(1., (t-LIFT)/(HEEL-LIFT)))
        angle = math.radians(18)*lift.smooth(u)
        heel = Vector((.23, -.26+.42*lift.smooth(u), .14*math.sin(math.pi*u)**2))
        q = Quaternion((1, 0, 0), angle)
        rear = transform(heel-q@Vector((0, -.16, 0)), angle)
        return rear, transform(rear@Vector((0, .14, 0)), angle)
    if t <= FLAT:
        angle = math.radians(18)*(1-progress(t, HEEL, FLAT))
        q = Quaternion((1, 0, 0), angle)
        rear = transform(Vector((.23, LAND_Y-.16, 0))-q@Vector((0, -.16, 0)), angle)
        return rear, transform(rear@Vector((0, .14, 0)), angle)
    if t <= RISE:
        return transform((.23, LAND_Y, 0), 0), transform((.23, LAND_Y+.14, 0), 0)
    toe_angle = -math.radians(16)*progress(t, TIP, OFF)
    rear_angle = -math.radians(30)*progress(t, RISE, TIP)+toe_angle
    if t >= OFF:
        relax = progress(t, OFF, END)
        toe_angle *= 1-.7*relax
        rear_angle += math.radians(26)*relax
    q = Quaternion((1, 0, 0), toe_angle)
    departure = Vector((0, .06*progress(t, OFF, END), .12*progress(t, OFF, END)))
    toe = transform(Vector((.23, LAND_Y+.24, 0))+departure-q@Vector((0, .10, 0)), toe_angle)
    hinge = toe@Vector((0, 0, .06))
    rear_q = Quaternion((1, 0, 0), rear_angle)
    return transform(hinge-rear_q@BALL, rear_angle), toe


def pose(t):
    pelvis = Vector((0, -.08+.24*progress(t, .5, 2.8),
                     .90-.025*progress(t, HEEL, FLAT)+.025*progress(t, RISE, OFF)))
    lean = .04+.04*progress(t, .6, 2.4)
    neck = pelvis+Vector((0, .5*math.sin(lean), .5*math.cos(lean)))
    head = neck+Vector((0, .19*math.sin(lean*.65), .19*math.cos(lean*.65)))
    p = {'pelvis': pelvis, 'neck': neck, 'head': head, 'Nose': head+Vector((0, .145, 0))}
    for side, sign in [('L', -1), ('R', 1)]:
        rear, _ = foot_frames(side, t)
        ankle = rear@Vector((0, -.075, .10))
        hip = pelvis+Vector((sign*.15, 0, 0))
        knee = lift.solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
        shoulder = neck+Vector((sign*.23, 0, 0))
        hand = pelvis+Vector((sign*.40, .10-sign*.045*progress(t, .5, 2.4), -.24))
        elbow = lift.solve(shoulder, hand, .44, .42, Vector((sign, -.15, .12)))
        for name, value in [('hip', hip), ('knee', knee), ('ankle', ankle),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            p[f'{side}_{name}'] = value
    return p


def setup():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine, sc.cycles.device, sc.cycles.samples = 'CYCLES', 'CPU', 16
    sc.cycles.use_denoising, sc.cycles.use_animated_seed, sc.cycles.seed = True, False, 0
    sc.render.resolution_x, sc.render.resolution_y = 640, 360
    sc.render.resolution_percentage, sc.render.fps = 100, FPS
    sc.frame_start, sc.frame_end = 0, COUNT-1
    sc.render.image_settings.file_format = 'PNG'
    sc.view_settings.view_transform = 'AgX'
    sc.world = bpy.data.worlds.new('Studio')
    sc.world.use_nodes = True
    sc.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.22, .27, .30, 1)
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .5
    body = lift.material('Ivory', (.66, .71, .69))
    dark = lift.material('Joints', (.08, .15, .18))
    foot_mats = {'heel': lift.material('Heel', (.08, .22, .29)),
                 'forefoot': lift.material('Forefoot', (.16, .39, .40)),
                 'toe': lift.material('Toe', (.72, .36, .09))}
    lift.cube('Floor', (0, 0, -.06), (200, 200, .12), lift.material('Floor', (.10, .15, .17)))
    for name in pose(0):
        radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .055)
        if name.endswith('hand'): radius = .047
        if name == 'Nose': radius = .035
        ob = lift.sphere(name, radius, body if name in ('head', 'pelvis') or name.endswith('hand') else dark)
        ob['radius'] = radius
    for name in LINKS:
        ob = lift.rod(name, lift.radius_for(name), body)
        ob['radius'], ob['length'] = lift.radius_for(name), lift.LENGTHS[name.split('_')[-1]]
    for side in ('L', 'R'):
        for root_name in ('rear', 'toe_root'):
            root = bpy.data.objects.new(side+'_'+root_name, None)
            sc.collection.objects.link(root)
            root.rotation_mode = 'QUATERNION'
        for part, (center, size) in PARTS.items():
            ob = lift.cube(side+'_'+part, (0, 0, 0), size, foot_mats[part])
            ob.parent = bpy.data.objects[side+('_toe_root' if part == 'toe' else '_rear')]
            ob.location = center
    for name, location in CAMERAS.items():
        camera = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        sc.collection.objects.link(camera)
        camera.location = location
        camera.rotation_euler = (Vector((0, .20, .86))-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type, camera.data.ortho_scale = 'ORTHO', (3.7 if name == 'profile' else 3.9)
    sc.camera = bpy.data.objects['profile']
    for name, location, energy, size in [('Key', (-3, 4, 6), 1000, 5), ('Rim', (3, -3, 4), 700, 4)]:
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        sc.collection.objects.link(light)
        light.location, light.data.energy, light.data.size = location, energy, size
        light.rotation_euler = (Vector((0, .4, .8))-light.location).to_track_quat('-Z', 'Y').to_euler()
    for i in range((COUNT-1)*8+1):
        frame, t = i/8, i/(8*FPS)
        p = pose(t)
        for name, value in p.items():
            ob = bpy.data.objects[name]
            ob.location = value
            lift.key(ob, ['location'], frame)
        for name, (a, b) in LINKS.items():
            ob = bpy.data.objects[name]
            lift.orient(ob, p[a], p[b])
            lift.key(ob, ['location', 'rotation_quaternion'], frame)
        for side in ('L', 'R'):
            for name, matrix in zip(('rear', 'toe_root'), foot_frames(side, t)):
                ob = bpy.data.objects[side+'_'+name]
                ob.location, ob.rotation_quaternion, _ = matrix.decompose()
                lift.key(ob, ['location', 'rotation_quaternion'], frame)
    for ob in sc.objects:
        if ob.animation_data:
            for curve in common.curves(ob):
                for k in curve.keyframe_points: k.interpolation = 'LINEAR'
    sc['study'] = 'foot_roll'
    sc['limits'] = 'One right-foot roll with planted left foot; no mass balance or game-rig transfer.'
    sc.frame_set(0)
    return sc


def validate():
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    geometry = {side+'_'+part: mesh_vertices(bpy.data.objects[side+'_'+part])
                for side in ('L', 'R') for part in PARTS}
    soles = {n: [v for v in vertices if abs(v.z-min(p.z for p in vertices)) < 1e-6]
             for n, vertices in geometry.items()}
    heel_edge = [v for v in soles['R_heel'] if abs(v.y-min(p.y for p in soles['R_heel'])) < 1e-6]
    toe_tip = [v for v in soles['R_toe'] if abs(v.y-max(p.y for p in soles['R_toe'])) < 1e-6]
    if len(heel_edge) != 2 or len(toe_tip) != 2: raise ValueError('Expected real two-vertex contact edges')
    names = tuple(pose(0))
    report = dict(samples=(COUNT-1)*16+1, left_support_error=0., full_sole_error=0.,
                  heel_support_error=0., toe_area_error=0., toe_tip_error=0.,
                  min_floor=1., length_error=0., joint_error=0., hinge_error=0., foot_shape_error=0.,
                  min_arm_body_clearance=1., min_swing_gap=1., min_departure_gap=1.,
                  witnesses={}, min_margin={name: 1. for name in CAMERAS})
    witness_times = {'swing': .70, 'heel': 1.10, 'flat': 1.60, 'toe_area': 2.50, 'toe_tip': 2.90, 'toe_off': 3.50}
    witness_indices = {round(t*FPS*16): label for label, t in witness_times.items()}
    tracks = []
    def support(metric, actual, expected):
        report[metric] = max(report[metric], max((a-b).length for a, b in zip(actual, expected)))
    for i in range((COUNT-1)*16+1):
        frame, t = i/16, i/(16*FPS)
        sc.frame_set(int(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        p = {n: bpy.data.objects[n].matrix_world.translation.copy() for n in names}
        rods = {}
        for name, (a, b) in LINKS.items():
            ob = bpy.data.objects[name]
            start, end = (ob.matrix_world@Vector((0, 0, z)) for z in (-.5, .5))
            radius = ob['radius']
            rods[name] = start, end, radius
            report['length_error'] = max(report['length_error'], abs((end-start).length-ob['length']))
            report['joint_error'] = max(report['joint_error'], (start-p[a]).length, (end-p[b]).length)
            report['min_floor'] = min(report['min_floor'], start.z-radius, end.z-radius)
        report['length_error'] = max(report['length_error'], abs((p['head']-p['neck']).length-.19))
        for name in p:
            report['min_floor'] = min(report['min_floor'], p[name].z-bpy.data.objects[name]['radius'])
        surfaces = {}
        for name, vertices in geometry.items():
            ob = bpy.data.objects[name]
            world = [ob.matrix_world@v for v in vertices]
            surfaces[name] = [ob.matrix_world@v for v in soles[name]]
            report['min_floor'] = min(report['min_floor'], min(v.z for v in world))
            for a in range(len(vertices)):
                for b in range(a):
                    report['foot_shape_error'] = max(report['foot_shape_error'],
                        abs((world[a]-world[b]).length-(vertices[a]-vertices[b]).length))
        for side in ('L', 'R'):
            rear, toe = (bpy.data.objects[side+'_'+name].matrix_world for name in ('rear', 'toe_root'))
            report['joint_error'] = max(report['joint_error'], (p[side+'_ankle']-rear@Vector((0, -.075, .10))).length)
            report['hinge_error'] = max(report['hinge_error'], (rear@BALL-toe@Vector((0, 0, .06))).length)
        for part, (center, _) in PARTS.items():
            offset = Vector((-.23, .10 if part == 'toe' else -.04, 0))+Vector(center)
            support('left_support_error', surfaces['L_'+part], [offset+v for v in soles['L_'+part]])
            if t <= LIFT or FLAT <= t <= RISE:
                base = -.10 if t <= LIFT else LAND_Y
                offset = Vector((.23, base+(.14 if part == 'toe' else 0), 0))+Vector(center)
                support('full_sole_error', surfaces['R_'+part], [offset+v for v in soles['R_'+part]])
        if HEEL <= t <= FLAT:
            ob = bpy.data.objects['R_heel']
            support('heel_support_error', [ob.matrix_world@v for v in heel_edge],
                    [Vector((.23+v.x, LAND_Y-.16, 0)) for v in heel_edge])
        if RISE <= t <= TIP:
            offset = Vector((.23, LAND_Y+.14, 0))+Vector(PARTS['toe'][0])
            support('toe_area_error', surfaces['R_toe'], [offset+v for v in soles['R_toe']])
        if TIP <= t <= OFF:
            ob = bpy.data.objects['R_toe']
            support('toe_tip_error', [ob.matrix_world@v for v in toe_tip],
                    [Vector((.23+v.x, LAND_Y+.24, 0)) for v in toe_tip])
        right_bottom = [v for part in PARTS for v in surfaces['R_'+part]]
        if LIFT+1/FPS < t < HEEL-1/FPS:
            report['min_swing_gap'] = min(report['min_swing_gap'], min(v.z for v in right_bottom))
        if t > OFF+1/FPS:
            report['min_departure_gap'] = min(report['min_departure_gap'], min(v.z for v in right_bottom))
        if i in witness_indices:
            report['witnesses'][witness_indices[i]] = {
                part: [min(v.z for v in surfaces['R_'+part]), max(v.z for v in surfaces['R_'+part])]
                for part in PARTS}
        for name in ('L_forearm', 'R_forearm', 'L_upperarm', 'R_upperarm'):
            a, b, radius = rods[name]
            for other in ('torso', 'L_thigh', 'R_thigh', 'L_shin', 'R_shin'):
                c, d, r2 = rods[other]
                report['min_arm_body_clearance'] = min(report['min_arm_body_clearance'], segment_distance(a, b, c, d)-radius-r2)
            report['min_arm_body_clearance'] = min(report['min_arm_body_clearance'], point_segment(p['head'], a, b)-radius-.14)
        tracks.append([tuple(p[n]) for n in names]+[tuple(v) for name in geometry for v in surfaces[name]])
        if i % 16 == 0:
            for view in CAMERAS:
                for ob in sc.objects:
                    if ob.type == 'MESH' and ob.name != 'Floor':
                        for v in ob.bound_box:
                            uv = world_to_camera_view(sc, bpy.data.objects[view], ob.matrix_world@Vector(v))
                            if uv.z <= 0: raise ValueError('Geometry behind camera')
                            report['min_margin'][view] = min(report['min_margin'][view], uv.x, uv.y, 1-uv.x, 1-uv.y)
    points = np.asarray(tracks)
    velocity = np.diff(points, axis=0)*(FPS*16)
    report['max_point_step'] = float(np.linalg.norm(np.diff(points, axis=0), axis=2).max())
    report['max_acceleration'] = float(np.linalg.norm(np.diff(velocity, axis=0)*(FPS*16), axis=2).max())
    report['event_velocity_jump'] = {str(t): float(np.linalg.norm(velocity[round(t*FPS*16)]-velocity[round(t*FPS*16)-1], axis=1).max())
                                     for t in (LIFT, HEEL, FLAT, RISE, TIP, OFF, END)}
    w = report['witnesses']
    tests = {'swing': min(a[0] for a in w['swing'].values()) > .10,
             'heel': abs(w['heel']['heel'][0]) < 2e-5 and w['heel']['forefoot'][0] > .02 and w['heel']['toe'][0] > .07,
             'flat': max(abs(h) for bounds in w['flat'].values() for h in bounds) < 2e-5,
             'toe_area': w['toe_area']['heel'][0] > .07 and max(abs(v) for v in w['toe_area']['toe']) < 2e-5,
             'toe_tip': abs(w['toe_tip']['toe'][0]) < 2e-5 and w['toe_tip']['toe'][1] > .02,
             'toe_off': min(a[0] for a in w['toe_off'].values()) > .10}
    report['phases'] = tests
    contacts = ('left_support_error', 'full_sole_error', 'heel_support_error', 'toe_area_error', 'toe_tip_error')
    if (max(report[n] for n in contacts) > 2e-5 or report['min_floor'] < -2e-5 or
        report['length_error'] > 2e-6 or report['joint_error'] > .002 or report['hinge_error'] > 2e-5 or
        report['foot_shape_error'] > 2e-6 or report['min_arm_body_clearance'] < -.0001 or
        report['min_swing_gap'] < .0001 or report['min_departure_gap'] < .0001 or
        report['max_point_step'] > .008 or report['max_acceleration'] > 100 or
        max(report['event_velocity_jump'].values()) > .10 or not all(tests.values()) or
        min(report['min_margin'].values()) < .025):
        raise ValueError(json.dumps(report))
    return report


def negative_tests():
    caught = []
    def fail(label, metric, predicate):
        try: validate()
        except ValueError as exc:
            result = json.loads(str(exc))
            if not predicate(result[metric]): raise AssertionError('Wrong failure for '+label) from exc
            caught.append(label)
        else: raise AssertionError('Missed '+label)
    for label, name, field, axis, delta, metric, predicate in [
        ('sliding_support', 'L_heel', 'delta_location', 1, .015, 'left_support_error', lambda v: v > .014),
        ('heel_contact_gap', 'R_heel', 'delta_location', 2, .01, 'heel_support_error', lambda v: v > .009),
        ('toe_penetration', 'R_toe', 'delta_location', 2, -.01, 'min_floor', lambda v: v < -.009),
        ('toe_hinge_break', 'R_toe_root', 'delta_location', 1, .01, 'hinge_error', lambda v: v > .009),
        ('stretched_shin', 'R_shin', 'scale', 2, .02, 'length_error', lambda v: v > .019)]:
        ob = bpy.data.objects[name]
        old = getattr(ob, field).copy()
        getattr(ob, field)[axis] += delta
        try: fail(label, metric, predicate)
        finally: setattr(ob, field, old)
    curve = next(c for c in common.curves(bpy.data.objects['R_rear']) if c.data_path == 'location' and c.array_index == 1)
    point = next(k for k in curve.keyframe_points if abs(k.co.x-60) < 1e-6)
    old = point.co.copy()
    point.co.y += .05
    curve.update()
    bpy.data.objects['R_rear'].animation_data.action.update_tag()
    try: fail('foot_curve_pop', 'max_point_step', lambda v: v > .02)
    finally:
        # update() may reorder key storage; reacquire the point before restoring.
        next(k for k in curve.keyframe_points if abs(k.co.x-old.x) < 1e-6).co = old
        curve.update()
        bpy.data.objects['R_rear'].animation_data.action.update_tag()
    validate()
    return caught


def movie_review(folder, ff):
    movie = folder/'foot_roll.mp4'
    header = subprocess.run([str(ff), '-hide_banner', '-i', str(movie)], capture_output=True, text=True).stderr
    if not re.search(r'640x360', header) or not re.search(r'30 fps', header) or 'Audio:' in header:
        raise ValueError('Expected silent 640x360/30fps')
    def decode(args):
        raw = subprocess.run([str(ff), '-v', 'error', *args, '-vf', 'scale=160:90', '-an',
                              '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape((-1, 90, 160, 3))
    raw = decode(['-i', str(movie)])
    source = decode(['-framerate', str(FPS), '-i', str(folder/'frames/f%04d.png')])
    if raw.shape != source.shape or len(raw) != COUNT: raise ValueError('Frame count mismatch')
    error = float(np.abs(raw.astype(float)-source).mean(axis=(1, 2, 3)).max())
    if error > 6 or raw.mean(axis=(1, 2, 3)).min() < 15: raise ValueError('Encoding mismatch/dark frame')
    (folder/'review').mkdir(exist_ok=True)
    subprocess.run([str(ff), '-y', '-v', 'error', '-i', str(movie), '-vf',
                    'scale=320:180,tile=5x3:nb_frames=15:padding=2:margin=2', '-fps_mode', 'passthrough',
                    '-q:v', '2', str(folder/'review/sheet%02d.jpg')], check=True)
    return dict(sha256=hashlib.sha256(movie.read_bytes()).hexdigest(), bytes=movie.stat().st_size,
                frames=len(raw), fps=FPS, duration=len(raw)/FPS, max_encoding_error=error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['build', 'block', 'render', 'review'], default='block')
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    common.JOURNAL = args.journal.resolve() if args.journal else None
    folder = args.out.resolve()
    common.journal('starting_'+args.mode, 'Build or reopen foot roll scene', active=True, exitcode=None, run_output=str(folder))
    if args.mode != 'review' and folder.exists(): raise ValueError('Use a new output directory')
    if args.mode in ('render', 'review') and not args.ffmpeg: raise ValueError('--ffmpeg is required')
    started = time.perf_counter()
    if args.mode != 'review':
        folder.mkdir(parents=True)
        setup()
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
    common.journal('validate_saved_scene', 'Check actual surfaces, phase witnesses and velocity transitions')
    report = validate()
    report['blender_version'], report['engine'] = bpy.app.version_string, bpy.context.scene.render.engine
    if args.mode in ('build', 'review'):
        common.journal('negative_tests', 'Check deliberate contact, length, hinge and curve errors')
        report['negative_tests'] = negative_tests()
    if args.mode == 'review':
        common.journal('decode_movies', 'Decode all frames and prepare contact sheets')
        report['movies'] = {view: movie_review(folder/view, args.ffmpeg) for view in CAMERAS}
    elif args.mode in ('block', 'render'):
        sc = bpy.context.scene
        for view in CAMERAS:
            common.journal(args.mode+'_'+view, 'Render current camera')
            sc.camera = bpy.data.objects[view]
            frames = folder/view/'frames'
            frames.mkdir(parents=True)
            if args.mode == 'block':
                for frame in BLOCK_FRAMES:
                    sc.frame_set(frame)
                    sc.render.filepath = str(frames/f'f{frame:04d}.png')
                    bpy.ops.render.render(write_still=True)
            else:
                sc.render.filepath = str(frames/'f')
                bpy.ops.render.render(animation=True)
                subprocess.run([str(args.ffmpeg), '-v', 'error', '-framerate', str(FPS), '-i', str(frames/'f%04d.png'),
                                '-frames:v', str(COUNT), '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
                                '-movflags', '+faststart', str(folder/view/'foot_roll.mp4')], check=True)
    report['elapsed_seconds'] = time.perf_counter()-started
    (folder/(args.mode+'.json')).write_text(json.dumps(report, indent=2))
    next_step = {'build': 'Inspect six key poses', 'block': 'Inspect key poses before short render',
                 'render': 'Run review and inspect every decoded frame', 'review': 'Document result and transfer bundle'}
    common.journal(args.mode+'_complete', next_step[args.mode], active=False, exitcode=0)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        common.journal('failed', 'Inspect failure; fix within two meaningful visual variants', active=False, exitcode=2, error=str(exc))
        raise
