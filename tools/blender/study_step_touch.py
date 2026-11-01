"""One step, stop, surface palm contact and release; Blender 5.2 / CPU.

--out NEW_DIR --mode build|block|render --ffmpeg EXE
--out EXISTING_DIR --mode review --ffmpeg EXE
Both cameras share the same saved animation. No game assets or add-ons.
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
from study_pointing import point_segment, segment_distance

FPS, COUNT = 30, 120
LAND, TOUCH, RELEASE, REST = 1.15, 2.05, 2.65, 3.35
STEP = .34
TARGET = Vector((.32, 1.03, 1.26))
TARGET_SIZE = Vector((.40, .08, .40))
CAMERAS = {'profile': (6.5, .45, 2.0), 'three_quarter': (4.5, -4.5, 2.5)}
LINKS = {'torso': ('pelvis', 'neck'), 'shoulder': ('L_shoulder', 'R_shoulder')}
for side in ('L', 'R'):
    for part, a, b in [('thigh', 'hip', 'knee'), ('shin', 'knee', 'ankle'),
                       ('upperarm', 'shoulder', 'elbow'), ('forearm', 'elbow', 'hand')]:
        LINKS[f'{side}_{part}'] = (f'{side}_{a}', f'{side}_{b}')


def progress(t, a, b):
    return lift.smooth((t-a)/(b-a))


def foot_center(side, t):
    sign = -1 if side == 'L' else 1
    initial_y = -.04 if side == 'L' else .10
    forward = STEP*progress(t, .40, .95) if side == 'R' else 0.
    height = .14*progress(t, .25, .50)*(1-progress(t, .90, LAND)) if side == 'R' else 0.
    return Vector((sign*.23, initial_y+forward, .05+height))


def pose(t):
    reach = progress(t, 1.40, TOUCH)*(1-progress(t, RELEASE, REST))
    advance = progress(t, .35, LAND)
    pelvis = Vector((0, -.08+.18*advance, .89-.015*math.sin(math.pi*progress(t, .25, LAND))**2))
    lean = .03+.07*reach
    neck = pelvis+Vector((0, .50*math.sin(lean), .50*math.cos(lean)))
    head = neck+Vector((0, .19*math.sin(lean*.65), .19*math.cos(lean*.65)))
    p = {'pelvis': pelvis, 'neck': neck, 'head': head}
    for side, sign in [('L', -1), ('R', 1)]:
        foot = foot_center(side, t)
        ankle = foot+Vector((0, -.06, .05))
        hip = pelvis+Vector((sign*.15, 0, 0))
        knee = lift.solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
        shoulder = neck+Vector((sign*.23, 0, 0))
        rest = Vector((sign*.40, pelvis.y+.10, .79))
        # The palm's front face is 5 cm beyond the wrist, not at its centre.
        goal = Vector((TARGET.x, TARGET.y-TARGET_SIZE.y/2-.05, TARGET.z))
        hand = rest.lerp(goal, reach)+Vector((0, 0, .07*math.sin(math.pi*reach))) if side == 'R' else rest
        elbow = lift.solve(shoulder, hand, .44, .42, Vector((sign, -.15, .12)))
        for name, value in [('hip', hip), ('knee', knee), ('ankle', ankle),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            p[f'{side}_{name}'] = value
    attention = progress(t, 1.2, 1.7)*(1-progress(t, RELEASE, REST))
    face = Vector((0, 1, 0)).lerp((TARGET-head).normalized(), attention).normalized()
    p['Nose'] = head+face*.145
    p['Palm'] = p['R_hand']+Vector((0, .025, 0))
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
    gold = lift.material('Fixed target', (.72, .35, .06))
    palm_mat = lift.material('Palm surface', (.35, .61, .60))
    floor = lift.material('Floor', (.10, .15, .17))
    lift.cube('Floor', (0, 0, -.06), (200, 200, .12), floor)
    lift.cube('Target', TARGET, TARGET_SIZE, gold)
    post = lift.rod('Target post', .025, gold)
    lift.orient(post, Vector((TARGET.x, TARGET.y, .025)), Vector((TARGET.x, TARGET.y, TARGET.z-.20)))
    lift.cube('Target base', (TARGET.x, TARGET.y, .025), (.32, .30, .05), dark, .01)
    for name in pose(0):
        if name == 'Palm':
            # No bevel: the four front vertices form a real flat contact face.
            lift.cube('Palm', (0, 0, 0), (.12, .05, .14), palm_mat)
            continue
        radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .055)
        if name.endswith('hand'): radius = .035 if name == 'R_hand' else .047
        if name == 'Nose': radius = .035
        ob = lift.sphere(name, radius, body if name in ('head', 'pelvis') or name.endswith('hand') else dark)
        ob['radius'] = radius
    for name in LINKS:
        ob = lift.rod(name, lift.radius_for(name), body)
        ob['radius'], ob['length'] = lift.radius_for(name), lift.LENGTHS[name.split('_')[-1]]
    for side in ('L', 'R'):
        lift.cube(side+'_foot', foot_center(side, 0), (.18, .34, .10), dark, .02)
    for name, location in CAMERAS.items():
        camera = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        sc.collection.objects.link(camera)
        camera.location = location
        camera.rotation_euler = (Vector((0, .45, .86))-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type, camera.data.ortho_scale = 'ORTHO', 3.8
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
        for side in ('L', 'R'):
            ob = bpy.data.objects[side+'_foot']
            ob.location = foot_center(side, t)
            lift.key(ob, ['location'], frame)
        for name, (a, b) in LINKS.items():
            ob = bpy.data.objects[name]
            lift.orient(ob, p[a], p[b])
            lift.key(ob, ['location', 'rotation_quaternion'], frame)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for k in curve.keyframe_points: k.interpolation = 'LINEAR'
    sc['study'] = 'step_touch'
    sc['limits'] = 'One flat step and a rigid palm face. No physical balance, skin or finger rig.'
    sc.frame_set(0)
    return sc


def mesh_vertices(ob):
    """Evaluated local surface, including the bevel on the feet."""
    evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    result = [v.co.copy() for v in mesh.vertices]
    evaluated.to_mesh_clear()
    return result


def validate():
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    geometry = {n: mesh_vertices(bpy.data.objects[n]) for n in ('L_foot', 'R_foot', 'Palm', 'Target')}
    soles = {side: [v for v in geometry[side+'_foot'] if abs(v.z-min(p.z for p in geometry[side+'_foot'])) < 1e-6]
             for side in ('L', 'R')}
    palm_face = [v for v in geometry['Palm'] if abs(v.y-max(p.y for p in geometry['Palm'])) < 1e-6]
    if len(palm_face) != 4: raise ValueError('Expected a four-vertex physical palm face')
    target_world = [bpy.data.objects['Target'].matrix_world@v for v in geometry['Target']]
    lo = Vector(tuple(min(v[k] for v in target_world) for k in range(3)))
    hi = Vector(tuple(max(v[k] for v in target_world) for k in range(3)))
    report = dict(samples=1905, support_surface_drift=0., landed_surface_drift=0.,
                  length_error=0., joint_error=0., min_floor=1., min_body_plane_gap=1.,
                  min_arm_clearance=1., palm_penetration=0., hold_face_gap=0., hold_surface_speed=0.,
                  contact_area_margin=1., release_gap=1., wrist_plane_gap=1., target_drift=0.,
                  max_point_step=0., max_swing_height=0., step_distance=0., backwards_foot_step=0.,
                  min_margin={name: 1. for name in CAMERAS})
    previous = None
    previous_face = None
    previous_time = -1.
    previous_foot_y = None
    airborne = []
    for i in range((COUNT-1)*16+1):
        frame, t = i/16, i/(16*FPS)
        sc.frame_set(int(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        p = {n: bpy.data.objects[n].matrix_world.translation.copy() for n in pose(0)}
        rods = {}
        for name, (a, b) in LINKS.items():
            ob = bpy.data.objects[name]
            start, end = (ob.matrix_world@Vector((0, 0, z)) for z in (-.5, .5))
            radius = ob['radius']
            rods[name] = (start, end, radius)
            report['length_error'] = max(report['length_error'], abs((end-start).length-ob['length']))
            report['joint_error'] = max(report['joint_error'], (start-p[a]).length, (end-p[b]).length)
            report['min_floor'] = min(report['min_floor'], start.z-radius, end.z-radius)
            report['min_body_plane_gap'] = min(report['min_body_plane_gap'], lo.y-max(start.y, end.y)-radius)
        report['length_error'] = max(report['length_error'], abs((p['head']-p['neck']).length-.19))
        report['joint_error'] = max(report['joint_error'], (p['Palm']-p['R_hand']-Vector((0, .025, 0))).length)
        for name in p:
            if name != 'Palm':
                radius = bpy.data.objects[name]['radius']
                report['min_floor'] = min(report['min_floor'], p[name].z-radius)
                report['min_body_plane_gap'] = min(report['min_body_plane_gap'], lo.y-p[name].y-radius)
        for side in ('L', 'R'):
            foot = bpy.data.objects[side+'_foot']
            world = [foot.matrix_world@v for v in soles[side]]
            all_vertices = [foot.matrix_world@v for v in geometry[side+'_foot']]
            report['min_floor'] = min(report['min_floor'], min(v.z for v in all_vertices))
            report['min_body_plane_gap'] = min(report['min_body_plane_gap'], lo.y-max(v.y for v in all_vertices))
            if side == 'L' or t >= LAND:
                expected = foot_center(side, 0 if side == 'L' else LAND)
                drift = max((actual-(v+expected)).length for actual, v in zip(world, soles[side]))
                metric = 'support_surface_drift' if side == 'L' else 'landed_surface_drift'
                report[metric] = max(report[metric], drift)
            ankle = foot.matrix_world@Vector((0, -.06, .05))
            report['joint_error'] = max(report['joint_error'], (ankle-p[side+'_ankle']).length)
            if side == 'R':
                height = min(v.z for v in world)
                report['max_swing_height'] = max(report['max_swing_height'], height)
                airborne.append(height > .0001)
                y = foot.matrix_world.translation.y
                if previous_foot_y is not None:
                    report['backwards_foot_step'] = max(report['backwards_foot_step'], previous_foot_y-y)
                previous_foot_y = y
                report['step_distance'] = y-foot_center('R', 0).y
        for name in ('L_forearm', 'R_forearm', 'L_upperarm', 'R_upperarm'):
            a, b, radius = rods[name]
            for other in ('torso', 'L_thigh', 'R_thigh', 'L_shin', 'R_shin'):
                c, d, r2 = rods[other]
                report['min_arm_clearance'] = min(report['min_arm_clearance'], segment_distance(a, b, c, d)-radius-r2)
            report['min_arm_clearance'] = min(report['min_arm_clearance'], point_segment(p['head'], a, b)-radius-.14)
        palm = bpy.data.objects['Palm']
        front = [palm.matrix_world@v for v in palm_face]
        all_palm = [palm.matrix_world@v for v in geometry['Palm']]
        gaps = [lo.y-v.y for v in front]
        report['palm_penetration'] = max(report['palm_penetration'], max(v.y for v in all_palm)-lo.y)
        report['min_floor'] = min(report['min_floor'], min(v.z for v in all_palm))
        if TOUCH <= t <= RELEASE:
            report['hold_face_gap'] = max(report['hold_face_gap'], max(abs(g) for g in gaps))
            report['contact_area_margin'] = min(report['contact_area_margin'],
                min(min(v.x-lo.x, hi.x-v.x, v.z-lo.z, hi.z-v.z) for v in front))
            report['wrist_plane_gap'] = min(report['wrist_plane_gap'], lo.y-p['R_hand'].y)
            if previous_time >= TOUCH:
                report['hold_surface_speed'] = max(report['hold_surface_speed'],
                    max((a-b).length/(t-previous_time) for a, b in zip(front, previous_face)))
        if t >= REST: report['release_gap'] = min(report['release_gap'], min(gaps))
        current_target = [bpy.data.objects['Target'].matrix_world@v for v in geometry['Target']]
        report['target_drift'] = max(report['target_drift'], max((a-b).length for a, b in zip(target_world, current_target)))
        if previous: report['max_point_step'] = max(report['max_point_step'], max((p[n]-previous[n]).length for n in p))
        previous, previous_face, previous_time = p, front, t
        if i % 16 == 0:
            for view in CAMERAS:
                camera = bpy.data.objects[view]
                for ob in sc.objects:
                    if ob.type == 'MESH' and ob.name != 'Floor':
                        for v in ob.bound_box:
                            uv = world_to_camera_view(sc, camera, ob.matrix_world@Vector(v))
                            report['min_margin'][view] = min(report['min_margin'][view], uv.x, uv.y, 1-uv.x, 1-uv.y)
    report['airborne_intervals'] = sum(b and not a for a, b in zip([False]+airborne, airborne))
    report['palm_face_vertices'], report['sole_vertices'] = len(palm_face), {side: len(v) for side, v in soles.items()}
    if (report['support_surface_drift'] > 2e-6 or report['landed_surface_drift'] > 2e-6 or
        report['length_error'] > 2e-6 or report['joint_error'] > .002 or report['min_floor'] < -.0001 or
        report['min_body_plane_gap'] < -.0001 or report['min_arm_clearance'] < -.0001 or
        report['palm_penetration'] > .0001 or report['hold_face_gap'] > .0001 or report['hold_surface_speed'] > 1e-5 or
        report['contact_area_margin'] < .01 or report['release_gap'] < .5 or report['wrist_plane_gap'] < .04 or
        report['target_drift'] > 2e-6 or report['max_point_step'] > .006 or report['max_swing_height'] < .13 or
        abs(report['step_distance']-STEP) > 2e-6 or report['backwards_foot_step'] > 2e-6 or
        report['airborne_intervals'] != 1 or min(report['min_margin'].values()) < .025):
        raise ValueError(json.dumps(report))
    return report


def negative_tests():
    caught = []
    def expect_failure(label, metric, minimum):
        try:
            validate()
        except ValueError as exc:
            failure = json.loads(str(exc))
            if failure[metric] < minimum: raise AssertionError('Wrong failure for '+label) from exc
            caught.append(label)
        else:
            raise AssertionError('Missed '+label)
    foot = bpy.data.objects['L_foot']
    curves = [curve for layer in foot.animation_data.action.layers for strip in layer.strips
              for bag in strip.channelbags for curve in bag.fcurves]
    curve = next(c for c in curves if c.data_path == 'location' and c.array_index == 1)
    old = [k.co.copy() for k in curve.keyframe_points]
    for k in curve.keyframe_points: k.co.y += .015*progress(k.co.x, 10, 30)
    curve.update()
    try:
        expect_failure('sliding_support_surface', 'support_surface_drift', .014)
    finally:
        for k, value in zip(curve.keyframe_points, old): k.co = value
        curve.update()
    for label, name, field, axis, delta, metric, minimum in [
            ('palm_gap', 'Palm', 'delta_location', 1, -.01, 'hold_face_gap', .009),
            ('palm_penetration', 'Palm', 'delta_location', 1, .01, 'palm_penetration', .009),
            ('stretched_forearm', 'R_forearm', 'scale', 2, .02, 'length_error', .019)]:
        ob = bpy.data.objects[name]
        saved = getattr(ob, field).copy()
        getattr(ob, field)[axis] += delta
        try:
            expect_failure(label, metric, minimum)
        finally:
            setattr(ob, field, saved)
    validate()  # Confirm that negative probes restored the original saved motion.
    return caught


def movie_review(folder, ff):
    movie = folder/'step_touch.mp4'
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
    report['blender_version'] = bpy.app.version_string
    report['engine'] = bpy.context.scene.render.engine
    if args.mode == 'build':
        report['negative_tests'] = negative_tests()
    elif args.mode == 'review':
        report['negative_tests'] = negative_tests()
        report['movies'] = {view: movie_review(folder/view, args.ffmpeg) for view in CAMERAS}
    else:
        sc = bpy.context.scene
        for view in CAMERAS:
            sc.camera = bpy.data.objects[view]
            frames = folder/view/'frames'
            frames.mkdir(parents=True)
            if args.mode == 'block':
                for frame in (22, 36, 69, 105):
                    sc.frame_set(frame)
                    sc.render.filepath = str(frames/f'f{frame:04d}.png')
                    bpy.ops.render.render(write_still=True)
            else:
                sc.render.filepath = str(frames/'f')
                bpy.ops.render.render(animation=True)
                subprocess.run([str(args.ffmpeg), '-v', 'error', '-framerate', str(FPS), '-i', str(frames/'f%04d.png'),
                                '-frames:v', str(COUNT), '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
                                '-movflags', '+faststart', str(folder/view/'step_touch.mp4')], check=True)
    report['elapsed_seconds'] = time.perf_counter()-started
    (folder/(args.mode+'.json')).write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
