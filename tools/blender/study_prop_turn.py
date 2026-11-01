"""Two rigid palm surfaces grasp, turn, hold and return a box; Blender CPU.

--out NEW_DIR --mode build|block|render --ffmpeg EXE [--journal JSON]
--out EXISTING_RENDER --mode review --ffmpeg EXE [--journal JSON]
No new rig, game resources, fingers or mass dynamics.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
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
from study_step_touch import LINKS, mesh_vertices
from study_pointing import point_segment, segment_distance

FPS, COUNT = 30, 120
GRAB, LIFTED, TURN, HOLD, RETURN = .75, 1.10, 1.85, 2.45, 3.15
HALF = lift.HALF.copy()
START_BOX = Vector((0, .60, 1.08))
CAMERAS = {'three_quarter': (4.5, 4.5, 2.7), 'profile': (-6.5, .22, 2.1)}
BLOCK_FRAMES = (0, 24, 63, 102)
JOURNAL = None


def journal(stage, next_step, **extra):
    if JOURNAL is None: return
    data = json.loads(JOURNAL.read_text(encoding='utf-8-sig')) if JOURNAL.exists() else {}
    event = dict(stage=stage, next_step=next_step, pid=os.getpid(),
                 utc=datetime.now(timezone.utc).isoformat(), **extra)
    data.pop('error', None)  # A recovered run must not expose an old failure as current.
    data.update(event)
    data['command'] = [bpy.app.binary_path, *sys.argv[1:]]
    data.setdefault('history', []).append(event)
    JOURNAL.write_text(json.dumps(data, indent=2), encoding='utf-8')


def progress(t, a, b):
    return lift.smooth((t-a)/(b-a))


def box_pose(t):
    raised = progress(t, .85, LIFTED)
    turn = progress(t, 1.15, TURN)*(1-progress(t, HOLD, RETURN))
    center = START_BOX+Vector((.025*turn, -.05*raised+.025*math.sin(math.pi*turn),
                              .12*raised+.02*math.sin(math.pi*turn)))
    rotation = Quaternion((0, 0, 1), math.radians(22)*turn) @ Quaternion((0, 1, 0), math.radians(-10)*turn)
    return center, rotation


def palm_local(side, t):
    sign = -1 if side == 'L' else 1
    grip = progress(t, .20, GRAB)
    initial = Vector((sign*.46, .12, .75))-START_BOX-Vector((sign*.025, 0, 0))
    target = Vector((sign*(HALF.x+.025), 0, 0))
    return initial.lerp(target, grip)+Vector((sign*.04*math.sin(math.pi*grip), 0, .06*math.sin(math.pi*grip)))


def foot_center(side):
    return Vector(((-1 if side == 'L' else 1)*.23, .10, .05))


def pose(t):
    center, rotation = box_pose(t)
    pelvis = Vector((0, -.08, .93))
    neck = pelvis+Vector((0, .5*math.sin(.05), .5*math.cos(.05)))
    head = neck+Vector((0, .19*math.sin(.03), .19*math.cos(.03)))
    p = {'pelvis': pelvis, 'neck': neck, 'head': head, 'Nose': head+Vector((0, .145, 0))}
    for side, sign in [('L', -1), ('R', 1)]:
        hip = pelvis+Vector((sign*.15, 0, 0))
        ankle = foot_center(side)+Vector((0, -.06, .05))
        knee = lift.solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
        shoulder = neck+Vector((sign*.23, 0, 0))
        hand = center+rotation@(palm_local(side, t)+Vector((sign*.025, 0, 0)))
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
    crate = lift.material('Box', (.45, .24, .10))
    palm = lift.material('Palm surfaces', (.18, .45, .43))
    floor = lift.material('Floor', (.10, .15, .17))
    lift.cube('Floor', (0, 0, -.06), (200, 200, .12), floor)
    lift.cube('Stand', (0, .60, .43), (.38, .26, .86), dark, .01)
    box = lift.cube('Box', START_BOX, tuple(HALF*2), crate, .01)
    box.rotation_mode = 'QUATERNION'
    stripe = lift.cube('Box stripe', (0, 0, 0), (.045, .36, .006), body)
    stripe.parent, stripe.location = box, (.10, 0, .223)
    for name in pose(0):
        radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .055)
        if name.endswith('hand'): radius = .025
        if name == 'Nose': radius = .035
        ob = lift.sphere(name, radius, body if name in ('head', 'pelvis') or name.endswith('hand') else dark)
        ob['radius'] = radius
    for name in LINKS:
        ob = lift.rod(name, lift.radius_for(name), body)
        ob['radius'], ob['length'] = lift.radius_for(name), lift.LENGTHS[name.split('_')[-1]]
    for side in ('L', 'R'):
        lift.cube(side+'_foot', foot_center(side), (.18, .34, .10), dark, .02)
        ob = lift.cube(side+'_palm', (0, 0, 0), (.05, .16, .18), palm)
        ob.parent = box
    for name, location in CAMERAS.items():
        camera = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        sc.collection.objects.link(camera)
        camera.location = location
        camera.rotation_euler = (Vector((0, .22, .90))-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type, camera.data.ortho_scale = 'ORTHO', (3.9 if name == 'three_quarter' else 3.6)
    sc.camera = bpy.data.objects['three_quarter']
    for name, location, energy, size in [('Key', (-3, 4, 6), 1000, 5), ('Rim', (3, -3, 4), 700, 4)]:
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        sc.collection.objects.link(light)
        light.location, light.data.energy, light.data.size = location, energy, size
        light.rotation_euler = (Vector((0, .4, .8))-light.location).to_track_quat('-Z', 'Y').to_euler()
    for i in range((COUNT-1)*8+1):
        frame, t = i/8, i/(8*FPS)
        center, rotation = box_pose(t)
        box.location, box.rotation_quaternion = center, rotation
        lift.key(box, ['location', 'rotation_quaternion'], frame)
        p = pose(t)
        for name, value in p.items():
            ob = bpy.data.objects[name]
            ob.location = value
            lift.key(ob, ['location'], frame)
        for side in ('L', 'R'):
            ob = bpy.data.objects[side+'_palm']
            ob.location = palm_local(side, t)
            lift.key(ob, ['location'], frame)
        for name, (a, b) in LINKS.items():
            ob = bpy.data.objects[name]
            lift.orient(ob, p[a], p[b])
            lift.key(ob, ['location', 'rotation_quaternion'], frame)
    for ob in sc.objects:
        if ob.animation_data:
            for curve in curves(ob):
                for k in curve.keyframe_points: k.interpolation = 'LINEAR'
    sc['study'] = 'prop_turn'
    sc['limits'] = 'Rigid palm surfaces and kinematic box; no fingers, masses or balance.'
    sc.frame_set(0)
    return sc


def matrix_error(a, b):
    return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))


def validate():
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    geometry = {n: mesh_vertices(bpy.data.objects[n]) for n in
                ('L_foot', 'R_foot', 'L_palm', 'R_palm', 'Box', 'Box stripe')}
    soles = {side: [v for v in geometry[side+'_foot']
                   if abs(v.z-min(p.z for p in geometry[side+'_foot'])) < 1e-6] for side in ('L', 'R')}
    faces = {side: [v for v in geometry[side+'_palm'] if abs(v.x-sign*(-.025)) < 1e-6]
             for side, sign in [('L', -1), ('R', 1)]}
    if any(len(face) != 4 for face in faces.values()): raise ValueError('Expected four corners per palm face')
    names = tuple(pose(0))
    report = dict(samples=(COUNT-1)*16+1, sole_drift=0., length_error=0., joint_error=0.,
                  min_floor=1., min_body_box_clearance=1., min_arm_body_clearance=1., min_palm_body_clearance=1.,
                  palm_penetration=0., face_gap=0., contact_drift=0., contact_margin=1.,
                  hold_surface_speed=0., max_point_step=0., box_scale_error=0., box_motion_error=0.,
                  stand_gap=1., return_error=0., rotation_span=0.,
                  min_margin={name: 1. for name in CAMERAS})
    previous, previous_surface = None, None
    previous_t = -1.
    target_return = Matrix.LocRotScale(*box_pose(RETURN), Vector((1, 1, 1)))
    for i in range((COUNT-1)*16+1):
        frame, t = i/16, i/(16*FPS)
        sc.frame_set(int(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        box = bpy.data.objects['Box']
        inverse = box.matrix_world.inverted()
        expected = Matrix.LocRotScale(*box_pose(t), Vector((1, 1, 1)))
        report['box_motion_error'] = max(report['box_motion_error'], matrix_error(box.matrix_world, expected))
        report['box_scale_error'] = max(report['box_scale_error'], max(abs(s-1) for s in box.matrix_world.to_scale()))
        report['rotation_span'] = max(report['rotation_span'], box.matrix_world.to_quaternion().angle)
        if t >= RETURN: report['return_error'] = max(report['return_error'], matrix_error(box.matrix_world, target_return))
        box_vertices = [box.matrix_world@v for v in geometry['Box']]
        report['stand_gap'] = min(report['stand_gap'], min(v.z for v in box_vertices)-.86)
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
            report['min_body_box_clearance'] = min(report['min_body_box_clearance'],
                lift.segment_box_distance(inverse@start, inverse@end, Vector((0, 0, 0)))-radius)
        report['length_error'] = max(report['length_error'], abs((p['head']-p['neck']).length-.19))
        for name in p:
            radius = bpy.data.objects[name]['radius']
            report['min_floor'] = min(report['min_floor'], p[name].z-radius)
            local = inverse@p[name]
            report['min_body_box_clearance'] = min(report['min_body_box_clearance'],
                lift.segment_box_distance(local, local, Vector((0, 0, 0)))-radius)
        surface = []
        for side, sign in [('L', -1), ('R', 1)]:
            foot = bpy.data.objects[side+'_foot']
            report['sole_drift'] = max(report['sole_drift'],
                max((foot.matrix_world@v-v-foot_center(side)).length for v in soles[side]))
            palm = bpy.data.objects[side+'_palm']
            face_world = [palm.matrix_world@v for v in faces[side]]
            face_local = [inverse@v for v in face_world]
            all_local = [inverse@(palm.matrix_world@v) for v in geometry[side+'_palm']]
            # A sphere enclosing the actual palm mesh is conservative for body clearance.
            palm_radius = max(v.length for v in geometry[side+'_palm'])
            palm_center = palm.matrix_world.translation
            for other in ('torso', 'L_thigh', 'R_thigh', 'L_shin', 'R_shin'):
                a, b, radius = rods[other]
                report['min_palm_body_clearance'] = min(report['min_palm_body_clearance'],
                    point_segment(palm_center, a, b)-radius-palm_radius)
            report['min_palm_body_clearance'] = min(report['min_palm_body_clearance'],
                (palm_center-p['head']).length-.14-palm_radius,
                (palm_center-p['pelvis']).length-.10-palm_radius)
            report['palm_penetration'] = max(report['palm_penetration'], max(HALF.x-sign*v.x for v in all_local))
            report['joint_error'] = max(report['joint_error'],
                (p[side+'_hand']-palm.matrix_world@Vector((sign*.025, 0, 0))).length)
            if t >= GRAB:
                report['face_gap'] = max(report['face_gap'], max(abs(sign*v.x-HALF.x) for v in face_local))
                report['contact_drift'] = max(report['contact_drift'],
                    max((local-v-Vector((sign*(HALF.x+.025), 0, 0))).length
                        for local, v in zip(face_local, faces[side])))
                report['contact_margin'] = min(report['contact_margin'],
                    min(min(HALF.y-.01-abs(v.y), HALF.z-.01-abs(v.z)) for v in face_local))
            surface.extend(face_world)
        for n, vertices in geometry.items():
            ob = bpy.data.objects[n]
            report['min_floor'] = min(report['min_floor'], min((ob.matrix_world@v).z for v in vertices))
        for name in ('L_forearm', 'R_forearm', 'L_upperarm', 'R_upperarm'):
            a, b, radius = rods[name]
            for other in ('torso', 'L_thigh', 'R_thigh', 'L_shin', 'R_shin'):
                c, d, r2 = rods[other]
                report['min_arm_body_clearance'] = min(report['min_arm_body_clearance'], segment_distance(a, b, c, d)-radius-r2)
            report['min_arm_body_clearance'] = min(report['min_arm_body_clearance'], point_segment(p['head'], a, b)-radius-.14)
        if previous:
            report['max_point_step'] = max(report['max_point_step'], max((p[n]-previous[n]).length for n in p),
                                           max((a-b).length for a, b in zip(surface, previous_surface)))
        if TURN <= previous_t < t <= HOLD:
            report['hold_surface_speed'] = max(report['hold_surface_speed'],
                max((a-b).length/(t-previous_t) for a, b in zip(surface, previous_surface)))
        previous, previous_surface, previous_t = p, surface, t
        if i % 16 == 0:
            for view in CAMERAS:
                for ob in sc.objects:
                    if ob.type == 'MESH' and ob.name != 'Floor':
                        for v in ob.bound_box:
                            uv = world_to_camera_view(sc, bpy.data.objects[view], ob.matrix_world@Vector(v))
                            if uv.z <= 0: raise ValueError('Geometry behind camera')
                            report['min_margin'][view] = min(report['min_margin'][view], uv.x, uv.y, 1-uv.x, 1-uv.y)
    report['contact_vertices'] = {side: len(v) for side, v in faces.items()}
    report['sole_vertices'] = {side: len(v) for side, v in soles.items()}
    if (report['sole_drift'] > 2e-6 or report['length_error'] > 2e-6 or report['joint_error'] > .002 or
        report['min_floor'] < -.0001 or report['min_body_box_clearance'] < -.0001 or
        report['min_arm_body_clearance'] < -.0001 or report['min_palm_body_clearance'] < -.0001 or report['palm_penetration'] > .0001 or
        report['face_gap'] > .0001 or report['contact_drift'] > 2e-6 or report['contact_margin'] < .02 or
        report['hold_surface_speed'] > 1e-5 or report['max_point_step'] > .008 or report['box_scale_error'] > 2e-6 or
        report['box_motion_error'] > .0002 or report['stand_gap'] < -.0001 or report['return_error'] > 2e-6 or
        report['rotation_span'] < .35 or min(report['min_margin'].values()) < .025):
        raise ValueError(json.dumps(report))
    return report


def negative_tests():
    caught = []
    cases = [
        ('palm_gap', 'L_palm', 'delta_location', 0, -.01, 'face_gap', lambda v: v > .009),
        ('palm_slide', 'R_palm', 'delta_location', 1, .015, 'contact_drift', lambda v: v > .014),
        ('palm_penetration', 'R_palm', 'delta_location', 0, -.01, 'palm_penetration', lambda v: v > .009),
        ('sliding_sole', 'L_foot', 'delta_location', 1, .015, 'sole_drift', lambda v: v > .014),
        ('stretched_arm', 'R_forearm', 'scale', 2, .02, 'length_error', lambda v: v > .019),
        ('box_body_collision', 'Box', 'delta_location', 1, -.45, 'min_body_box_clearance', lambda v: v < -.05)]
    for label, name, field, axis, delta, metric, predicate in cases:
        ob = bpy.data.objects[name]
        saved = getattr(ob, field).copy()
        getattr(ob, field)[axis] += delta
        try:
            try: validate()
            except ValueError as exc:
                result = json.loads(str(exc))
                if not predicate(result[metric]): raise AssertionError('Wrong failure for '+label) from exc
                caught.append(label)
            else: raise AssertionError('Missed '+label)
        finally: setattr(ob, field, saved)
    validate()
    return caught


def movie_review(folder, ff):
    movie = folder/'prop_turn.mp4'
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
    global JOURNAL
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['build', 'block', 'render', 'review'], default='block')
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    JOURNAL = args.journal.resolve() if args.journal else None
    folder = args.out.resolve()
    journal('starting_'+args.mode, 'Build or reopen scene', active=True, exitcode=None, run_output=str(folder))
    if args.mode != 'review' and folder.exists(): raise ValueError('Use a new output directory')
    if args.mode in ('render', 'review') and not args.ffmpeg: raise ValueError('--ffmpeg is required')
    started = time.perf_counter()
    if args.mode != 'review':
        folder.mkdir(parents=True)
        setup()
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
    journal('validate_saved_scene', 'Measure contact surfaces and rigid lengths')
    report = validate()
    report['blender_version'], report['engine'] = bpy.app.version_string, bpy.context.scene.render.engine
    if args.mode in ('build', 'review'):
        journal('negative_tests', 'Check six deliberate errors and restore original scene')
        report['negative_tests'] = negative_tests()
    if args.mode == 'review':
        journal('decode_movies', 'Compare all decoded frames with source PNG and produce sheets')
        report['movies'] = {view: movie_review(folder/view, args.ffmpeg) for view in CAMERAS}
    elif args.mode in ('block', 'render'):
        sc = bpy.context.scene
        for view in CAMERAS:
            journal(args.mode+'_'+view, 'Render camera and encode if complete sequence')
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
                                '-movflags', '+faststart', str(folder/view/'prop_turn.mp4')], check=True)
    report['elapsed_seconds'] = time.perf_counter()-started
    (folder/(args.mode+'.json')).write_text(json.dumps(report, indent=2))
    following = {'build': 'Inspect key poses', 'block': 'Inspect eight key-pose images before full render',
                 'render': 'Run review mode and inspect every decoded frame',
                 'review': 'Inspect frame sheets, document, commit and transfer JSON bundle'}
    journal(args.mode+'_complete', following[args.mode], active=False, exitcode=0)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        journal('failed', 'Inspect error and fix before continuing', active=False, exitcode=2, error=str(exc))
        raise
