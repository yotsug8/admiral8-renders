"""Forward mannequin jump: anticipation, one flight, cushioned landing.

Blender 5.2 CPU; --out NEW_DIR --mode build|block|render --ffmpeg EXE.
Review an existing render with --mode review. No game assets or add-ons.
The ballistic reference is the pelvis, not a computed centre of mass.
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
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_lift as lift
from study_step_touch import LINKS, mesh_vertices
from study_pointing import point_segment, segment_distance
from jump_motion import plan_jumps, refine_jump_roots

FPS, COUNT = 30, 105
GRAVITY, FLIGHT, TAKEOFF = 9.81, .6, 1.1
HEIGHT = GRAVITY*FLIGHT**2/8
PLAN = plan_jumps(dict(fps=FPS, frames=COUNT,
    actors={'mannequin': {'keys': [[0, 0, 0, 0, 0, 0] for _ in range(COUNT)]}},
    jumps=[dict(who='mannequin', at=TAKEOFF, height=HEIGHT, gravity=GRAVITY,
                depth=.24, down=.55, hold=.1, launch=.2, landing=.85)]))
EVENT = PLAN['jump_plan'][0]
LAND, RECOVER = EVENT['land'], EVENT['recover']
COMPRESS = PLAN['crouches'][1]['down']
CAMERAS = {'profile': (6.5, .40, 2.1), 'three_quarter': (4.5, 4.5, 2.7)}
BLOCK_FRAMES = (0, 24, 33, 42, 51, 56, 80)


def progress(t, a, b):
    return lift.smooth((t-a)/(b-a))


def hermite(t, a, b, p0, p1, v0=0., v1=0.):
    u = max(0., min(1., (t-a)/(b-a)))
    return ((2*u**3-3*u*u+1)*p0+(u**3-2*u*u+u)*(b-a)*v0
            +(-2*u**3+3*u*u)*p1+(u**3-u*u)*(b-a)*v1)


def interpolate(t, keys):
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            u = progress(t, a[0], b[0])
            return [x+(y-x)*u for x, y in zip(a[1:], b[1:])]
    return list(keys[-1][1:])


def root_position(t):
    if t < .9: y = -.08
    elif t < TAKEOFF: y = hermite(t, .9, TAKEOFF, -.08, .02, 0, 1)
    elif t < LAND: y = .02+(t-TAKEOFF)
    else: y = hermite(t, LAND, LAND+.2, .62, .72, 1, 0)
    u = t-TAKEOFF
    z = GRAVITY*u*(FLIGHT-u)/2 if TAKEOFF < t < LAND else 0.
    return Vector((0, y, z))


def pelvis_height(t):
    speed = EVENT['impact_speed']
    if t < .9: return .93-.24*progress(t, EVENT['prep_start'], .8)
    if t < TAKEOFF: return hermite(t, .9, TAKEOFF, .69, .93, 0, speed)
    if t < LAND: return .93+root_position(t).z
    if t < LAND+COMPRESS: return hermite(t, LAND, LAND+COMPRESS, .93, .69, -speed, 0)
    return .69+.24*progress(t, LAND+COMPRESS, RECOVER)


def foot_center(side, t):
    u = max(0., min(1., (t-TAKEOFF)/FLIGHT))
    y = .10+.70*lift.smooth(u)
    z = .05+root_position(t).z+.10*math.sin(math.pi*u)**2
    return Vector(((-1 if side == 'L' else 1)*.23, y, z))


def pose(t):
    root = root_position(t)
    pelvis = Vector((0, root.y, pelvis_height(t)))
    lean, hy, hz = interpolate(t, [
        (0, .02, .10, -.28), (.25, .02, .10, -.28),
        (.8, .35, -.40, .05), (.9, .35, -.20, .18),
        (TAKEOFF, .10, .48, .38), (TAKEOFF+FLIGHT/2, .08, .50, .48),
        (LAND, .12, .45, .15), (LAND+COMPRESS, .36, .48, .20),
        (RECOVER, .02, .10, -.28), (COUNT/FPS, .02, .10, -.28)])
    neck = pelvis+Vector((0, .50*math.sin(lean), .50*math.cos(lean)))
    head = neck+Vector((0, .19*math.sin(lean*.65), .19*math.cos(lean*.65)))
    p = {'pelvis': pelvis, 'neck': neck, 'head': head, 'Nose': head+Vector((0, .145, 0))}
    for side, sign in [('L', -1), ('R', 1)]:
        hip = pelvis+Vector((sign*.15, 0, 0))
        ankle = foot_center(side, t)+Vector((0, -.06, .05))
        knee = lift.solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
        shoulder = neck+Vector((sign*.23, 0, 0))
        hand = pelvis+Vector((sign*.40, hy, hz))
        elbow = lift.solve(shoulder, hand, .44, .42, Vector((sign, -.15, .12)))
        for name, value in [('hip', hip), ('knee', knee), ('ankle', ankle),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            p[f'{side}_{name}'] = value
    return p


def curves(ob):
    return [c for layer in ob.animation_data.action.layers for strip in layer.strips
            for bag in strip.channelbags for c in bag.fcurves]


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
    floor = lift.material('Floor', (.10, .15, .17))
    lift.cube('Floor', (0, 0, -.06), (200, 200, .12), floor)
    root = bpy.data.objects.new('Flight root', None)
    sc.collection.objects.link(root)
    for name in pose(0):
        radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .055)
        if name.endswith('hand'): radius = .047
        if name == 'Nose': radius = .035
        ob = lift.sphere(name, radius, body if name in ('head', 'pelvis') or name.endswith('hand') else dark)
        ob['radius'], ob.parent = radius, root
    for name in LINKS:
        ob = lift.rod(name, lift.radius_for(name), body)
        ob['radius'], ob['length'] = lift.radius_for(name), lift.LENGTHS[name.split('_')[-1]]
        ob.parent = root
    for side in ('L', 'R'):
        ob = lift.cube(side+'_foot', (0, 0, 0), (.18, .34, .10), dark, .02)
        ob.parent = root
    for name, location in CAMERAS.items():
        camera = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        sc.collection.objects.link(camera)
        camera.location = location
        camera.rotation_euler = (Vector((0, .40, 1.05))-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type, camera.data.ortho_scale = 'ORTHO', 4.5
    sc.camera = bpy.data.objects['profile']
    for name, location, energy, size in [('Key', (-3, 4, 6), 1000, 5), ('Rim', (3, -3, 4), 700, 4)]:
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        sc.collection.objects.link(light)
        light.location, light.data.energy, light.data.size = location, energy, size
        light.rotation_euler = (Vector((0, .4, .8))-light.location).to_track_quat('-Z', 'Y').to_euler()
    for i in range((COUNT-1)*8+1):
        frame, t = i/8, i/(8*FPS)
        offset = root_position(t)
        root.location = offset
        lift.key(root, ['location'], frame)
        p = {name: value-offset for name, value in pose(t).items()}
        for name, value in p.items():
            ob = bpy.data.objects[name]
            ob.location = value
            lift.key(ob, ['location'], frame)
        for side in ('L', 'R'):
            ob = bpy.data.objects[side+'_foot']
            ob.location = foot_center(side, t)-offset
            lift.key(ob, ['location'], frame)
        for name, (a, b) in LINKS.items():
            ob = bpy.data.objects[name]
            lift.orient(ob, p[a], p[b])
            lift.key(ob, ['location', 'rotation_quaternion'], frame)
    for ob in sc.objects:
        if ob.animation_data:
            for curve in curves(ob):
                for k in curve.keyframe_points: k.interpolation = 'LINEAR'
    refine_jump_roots(PLAN, {'mannequin': {'root': root}}, sc, FPS)
    sc['study'] = 'jump_land'
    sc['limits'] = 'Kinematic rigid mannequin. Ballistic pelvis, not mass centre or physical balance.'
    sc.frame_set(0)
    return sc


def validate():
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    geometry = {side: mesh_vertices(bpy.data.objects[side+'_foot']) for side in ('L', 'R')}
    soles = {side: [v for v in vertices if abs(v.z-min(p.z for p in vertices)) < 1e-6]
             for side, vertices in geometry.items()}
    names = tuple(pose(0))
    report = dict(samples=(COUNT-1)*16+1, prep_surface_drift=0., landed_surface_drift=0.,
                  length_error=0., joint_error=0., min_floor=1., min_arm_clearance=1.,
                  ballistic_error=0., flight_min_sole_gap=1., compression_error=0.,
                  max_point_step=0., min_margin={name: 1. for name in CAMERAS})
    airborne, previous, positions = [], None, []
    for i in range((COUNT-1)*16+1):
        frame, t = i/16, i/(16*FPS)
        sc.frame_set(int(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        p = {n: bpy.data.objects[n].matrix_world.translation.copy() for n in names}
        positions.append(p['pelvis'])
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
        gaps = []
        for side in ('L', 'R'):
            ob = bpy.data.objects[side+'_foot']
            vertices = [ob.matrix_world@v for v in geometry[side]]
            surface = [ob.matrix_world@v for v in soles[side]]
            report['min_floor'] = min(report['min_floor'], min(v.z for v in vertices))
            gaps.append(min(v.z for v in surface))
            report['joint_error'] = max(report['joint_error'],
                (p[side+'_ankle']-ob.matrix_world@Vector((0, -.06, .05))).length)
            if t <= TAKEOFF or t >= LAND:
                end_time = 0 if t <= TAKEOFF else LAND
                metric = 'prep_surface_drift' if t <= TAKEOFF else 'landed_surface_drift'
                report[metric] = max(report[metric], max((world-v-foot_center(side, end_time)).length
                                                       for world, v in zip(surface, soles[side])))
        airborne.append(min(gaps) > .0001)
        if TAKEOFF+1e-7 < t < LAND-1e-7:
            expected = Vector((0, .02+t-TAKEOFF, .93+GRAVITY*(t-TAKEOFF)*(LAND-t)/2))
            report['ballistic_error'] = max(report['ballistic_error'], (p['pelvis']-expected).length)
            report['flight_min_sole_gap'] = min(report['flight_min_sole_gap'], min(gaps))
        if LAND <= t <= RECOVER:
            report['compression_error'] = max(report['compression_error'], abs(p['pelvis'].z-pelvis_height(t)))
        for name in ('L_forearm', 'R_forearm', 'L_upperarm', 'R_upperarm'):
            a, b, radius = rods[name]
            for other in ('torso', 'L_thigh', 'R_thigh', 'L_shin', 'R_shin'):
                c, d, r2 = rods[other]
                report['min_arm_clearance'] = min(report['min_arm_clearance'], segment_distance(a, b, c, d)-radius-r2)
            report['min_arm_clearance'] = min(report['min_arm_clearance'], point_segment(p['head'], a, b)-radius-.14)
        if previous: report['max_point_step'] = max(report['max_point_step'], max((p[n]-previous[n]).length for n in p))
        previous = p
        if i % 16 == 0:
            for view in CAMERAS:
                for ob in sc.objects:
                    if ob.type == 'MESH' and ob.name != 'Floor':
                        for v in ob.bound_box:
                            uv = world_to_camera_view(sc, bpy.data.objects[view], ob.matrix_world@Vector(v))
                            if uv.z <= 0: raise ValueError('Geometry behind camera')
                            report['min_margin'][view] = min(report['min_margin'][view], uv.x, uv.y, 1-uv.x, 1-uv.y)
    report['airborne_intervals'] = sum(b and not a for a, b in zip([False]+airborne, airborne))
    report['velocity_jump'] = {}
    for label, event in [('takeoff', TAKEOFF), ('landing', LAND)]:
        i = round(event*FPS*16)
        before = (positions[i]-positions[i-1])*(FPS*16)
        after = (positions[i+1]-positions[i])*(FPS*16)
        report['velocity_jump'][label] = (after-before).length
    report['sole_vertices'] = {side: len(v) for side, v in soles.items()}
    report['events'] = EVENT
    if (report['prep_surface_drift'] > 2e-6 or report['landed_surface_drift'] > 2e-6 or
        report['length_error'] > 2e-6 or report['joint_error'] > .002 or report['min_floor'] < -.0001 or
        report['min_arm_clearance'] < -.0001 or report['ballistic_error'] > 3e-6 or
        report['flight_min_sole_gap'] <= .0001 or report['compression_error'] > .0002 or
        report['max_point_step'] > .025 or report['airborne_intervals'] != 1 or
        min(report['min_margin'].values()) < .025 or max(report['velocity_jump'].values()) > .10):
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
        ('sliding_landed_foot', 'L_foot', 'delta_location', 1, .015, 'landed_surface_drift', lambda v: v > .014),
        ('ground_penetration', 'R_foot', 'delta_location', 2, -.02, 'min_floor', lambda v: v < -.019),
        ('stretched_shin', 'R_shin', 'scale', 2, .02, 'length_error', lambda v: v > .019)]:
        ob = bpy.data.objects[name]
        old = getattr(ob, field).copy()
        getattr(ob, field)[axis] += delta
        try: fail(label, metric, predicate)
        finally: setattr(ob, field, old)
    foot_curve = next(c for c in curves(bpy.data.objects['L_foot'])
                      if c.data_path == 'location' and c.array_index == 2)
    foot_old = [k.co.copy() for k in foot_curve.keyframe_points]
    for k in foot_curve.keyframe_points:
        t = k.co.x/FPS
        if TAKEOFF <= t <= LAND: k.co.y = .05-root_position(t).z
    foot_curve.update()
    try: fail('contact_during_flight', 'flight_min_sole_gap', lambda v: v <= .0001)
    finally:
        for k, co in zip(foot_curve.keyframe_points, foot_old): k.co = co
        foot_curve.update()
    curve = next(c for c in curves(bpy.data.objects['Flight root']) if c.data_path == 'location' and c.array_index == 2)
    old = [(k.co.copy(), k.handle_left.copy(), k.handle_right.copy()) for k in curve.keyframe_points]
    for k in curve.keyframe_points:
        u = (k.co.x/FPS-TAKEOFF)/FLIGHT
        if 0 < u < 1:
            change = .04*math.sin(math.pi*u)**2
            k.co.y += change
            k.handle_left.y += change
            k.handle_right.y += change
    curve.update()
    try: fail('nonballistic_flight', 'ballistic_error', lambda v: v > .039)
    finally:
        for k, (co, left, right) in zip(curve.keyframe_points, old):
            k.co, k.handle_left, k.handle_right = co, left, right
        curve.update()
    validate()
    return caught


def movie_review(folder, ff):
    movie = folder/'jump_land.mp4'
    header = subprocess.run([str(ff), '-hide_banner', '-i', str(movie)], capture_output=True, text=True).stderr
    if not re.search(r'640x360', header) or not re.search(r'30 fps', header) or 'Audio:' in header:
        raise ValueError('Expected silent 640x360/30fps')
    def decode(args):
        result = subprocess.run([str(ff), '-v', 'error', *args, '-vf', 'scale=160:90', '-an',
                                 '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True, check=True)
        return np.frombuffer(result.stdout, np.uint8).reshape((-1, 90, 160, 3))
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
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    folder = args.out.resolve()
    if args.mode != 'review' and folder.exists(): raise ValueError('Use a new output directory')
    if args.mode in ('render', 'review') and not args.ffmpeg: raise ValueError('--ffmpeg is required')
    started = time.perf_counter()
    if args.mode != 'review':
        folder.mkdir(parents=True)
        setup()
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
    report = validate()
    report['blender_version'], report['engine'] = bpy.app.version_string, bpy.context.scene.render.engine
    if args.mode in ('build', 'review'): report['negative_tests'] = negative_tests()
    if args.mode == 'review':
        report['movies'] = {view: movie_review(folder/view, args.ffmpeg) for view in CAMERAS}
    elif args.mode in ('block', 'render'):
        sc = bpy.context.scene
        for view in CAMERAS:
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
                                '-movflags', '+faststart', str(folder/view/'jump_land.mp4')], check=True)
    report['elapsed_seconds'] = time.perf_counter()-started
    (folder/(args.mode+'.json')).write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
