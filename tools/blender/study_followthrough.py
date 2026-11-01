"""Rigid stop versus overlapping action; Blender 5.2, no external assets.

--out NEW_DIR --mode block|render [--ffmpeg EXE] [--engine cycles|eevee]
--out EXISTING_DIR --mode review --ffmpeg EXE reopens the saved scene.
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
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_lift as lift

FPS, COUNT, STOP = 30, 135, 1.6
TRAVEL = .24
CASES = {'hard': 1.35, 'follow': -1.35}
CHANNELS = {'body': 11., 'head': 9., 'L_hand': 7.5, 'R_hand': 6.}
SPRING_HZ, DAMPING = 960, .70
LINKS = {'torso': ('pelvis', 'neck'), 'shoulder': ('L_shoulder', 'R_shoulder')}
for side in ('L', 'R'):
    for part, a, b in [('thigh', 'hip', 'knee'), ('shin', 'knee', 'ankle'),
                       ('upperarm', 'shoulder', 'elbow'), ('forearm', 'elbow', 'hand')]:
        LINKS[f'{side}_{part}'] = (f'{side}_{a}', f'{side}_{b}')
_spring = None


def root(t):
    """0.24 m travel: smooth acceleration, constant speed, deliberate hard stop."""
    if t <= .5:
        return 0.
    if t >= STOP:
        return TRAVEL
    speed = TRAVEL / .95
    if t < .8:
        u = (t-.5)/.3
        return speed*.3*(2.5*u**4-3*u**5+u**6)
    return speed*(t-.65)


def spring_table():
    """Fixed-step RK4 damped responses; baked keys do not require this at playback."""
    global _spring
    if _spring is not None:
        return _spring
    dt = 1/SPRING_HZ
    _spring = {}
    for name, omega in CHANNELS.items():
        x = v = 0.
        samples = [x]
        def derivative(t, px, pv):
            return pv, omega*omega*(root(t)-px)-2*DAMPING*omega*pv
        for i in range(math.ceil(COUNT/FPS*SPRING_HZ)):
            t = i*dt
            k1 = derivative(t, x, v)
            k2 = derivative(t+dt/2, x+k1[0]*dt/2, v+k1[1]*dt/2)
            k3 = derivative(t+dt/2, x+k2[0]*dt/2, v+k2[1]*dt/2)
            k4 = derivative(t+dt, x+k3[0]*dt, v+k3[1]*dt)
            x += dt*(k1[0]+2*k2[0]+2*k3[0]+k4[0])/6
            v += dt*(k1[1]+2*k2[1]+2*k3[1]+k4[1])/6
            samples.append(x)
        _spring[name] = samples
    return _spring


def response(channel, t):
    samples = spring_table()[channel]
    q = min(t*SPRING_HZ, len(samples)-1)
    i = int(q)
    x = samples[i] if i == len(samples)-1 else samples[i]+(samples[i+1]-samples[i])*(q-i)
    # Only the already tiny tail is eased to exact rest, 3.6--4.2 seconds.
    return root(t)+(x-root(t))*(1-lift.smooth((t-3.6)/.6))


def pose(case, t):
    travel = root(t)
    lag = {n: response(n, t)-travel if case == 'follow' else 0. for n in CHANNELS}
    body_rot = Matrix.Rotation(5.*lag['body'], 3, 'Y')
    head_rot = Matrix.Rotation(7.*lag['head'], 3, 'Y')
    pelvis = Vector((travel-TRAVEL/2, -.08, .91))
    neck = pelvis+body_rot@Vector((0, 0, .50))
    p = {'pelvis': pelvis, 'neck': neck, 'head': neck+head_rot@Vector((0, 0, .19))}
    for side, sign in [('L', -1), ('R', 1)]:
        hip = pelvis+Vector((sign*.15, 0, 0))
        ankle = Vector((sign*.23, .04, .10))
        shoulder = neck+body_rot@Vector((sign*.23, 0, 0))
        hand = Vector((travel-TRAVEL/2+sign*.50+1.4*lag[side+'_hand'], .04, .79))
        knee = lift.solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
        elbow = lift.solve(shoulder, hand, .44, .42, Vector((sign, -.15, .12)))
        for n, v in [('hip', hip), ('ankle', ankle), ('knee', knee),
                     ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            p[f'{side}_{n}'] = v
    p['Nose'] = p['head']+head_rot@Vector((0, .145, 0))
    for sign, side in [(-1, 'L'), (1, 'R')]:
        p[side+'_eye'] = p['head']+head_rot@Vector((sign*.048, .128, .039))
    offset = Vector((CASES[case], 0, 0))
    return {n: v+offset for n, v in p.items()}


def obj(case, name):
    return bpy.data.objects[f'{case}.{name}']


def text_object(name, words, x, z, size, mat):
    data = bpy.data.curves.new(name, 'FONT')
    data.body, data.align_x, data.size = words, 'CENTER', size
    ob = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = (x, 0, z)
    ob.rotation_euler = bpy.context.scene.camera.rotation_euler
    data.materials.append(mat)
    return ob


def setup(engine):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES' if engine == 'cycles' else 'BLENDER_EEVEE'
    if engine == 'cycles':
        sc.cycles.device, sc.cycles.samples = 'CPU', 16
        sc.cycles.use_denoising = True
        sc.cycles.seed = 0
        sc.cycles.use_animated_seed = False
    else:
        sc.eevee.taa_render_samples = 32
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
    accents = {'hard': lift.material('Control blue', (.13, .40, .60)),
               'follow': lift.material('Follow amber', (.75, .38, .10))}
    lift.cube('Floor', (0, 0, -.06), (200, 200, .12), floor)
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.location = (0, 7, 2.6)
    cam.rotation_euler = (Vector((0, 0, .98))-cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.type, cam.data.ortho_scale = 'ORTHO', 5.4
    for name, loc, energy, size in [('Key', (-3, 4, 6), 1000, 5), ('Rim', (3, -3, 4), 700, 4)]:
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        sc.collection.objects.link(light)
        light.location, light.data.energy, light.data.size = loc, energy, size
        light.rotation_euler = (Vector((0, 0, .8))-light.location).to_track_quat('-Z', 'Y').to_euler()
    for case, offset in CASES.items():
        p = pose(case, 0)
        for name in p:
            radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .055)
            if name.endswith('hand'): radius = .047
            if name.endswith('eye'): radius = .018
            if name == 'Nose': radius = .035
            mat = accents[case] if name == 'pelvis' else (body if name == 'head' or name.endswith('hand') else dark)
            ob = lift.sphere(f'{case}.{name}', radius, mat)
            ob['radius'] = radius
        for name in LINKS:
            ob = lift.rod(f'{case}.{name}', lift.radius_for(name), body)
            ob['radius'] = lift.radius_for(name)
            ob['length'] = lift.LENGTHS[name.split('_')[-1]]
        for side, sign in [('L', -1), ('R', 1)]:
            lift.cube(f'{case}.{side}_foot', (offset+sign*.23, .10, .05), (.18, .34, .10), dark, .025)
        title = 'HARD STOP' if case == 'hard' else 'FOLLOW THROUGH'
        text_object(case+'.title', title, offset, 1.98, .155, accents[case])
    caption = text_object('caption', 'SAME PELVIS MOTION  /  STOP AT 1.6 s', 0, .06, .095, body)
    caption.location.y = 1.0
    for i in range((COUNT-1)*8+1):
        frame = i/8
        for case in CASES:
            p = pose(case, frame/FPS)
            for name, value in p.items():
                ob = obj(case, name)
                ob.location = value
                lift.key(ob, ['location'], frame)
            for name, (a, b) in LINKS.items():
                ob = obj(case, name)
                lift.orient(ob, p[a], p[b])
                lift.key(ob, ['location', 'rotation_quaternion'], frame)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points: key.interpolation = 'LINEAR'
    sc['study'] = 'followthrough'
    sc['limits'] = 'Rigid mannequin, authored secondary responses; not a mass/contact/skin simulation.'
    sc.frame_set(0)
    return sc


def point_segment(p, a, b):
    v = b-a
    return (p-(a+v*max(0., min(1., (p-a).dot(v)/v.length_squared)))).length


def segment_distance(a, b, c, d):
    u, v, w = b-a, d-c, a-c
    aa, bb, cc, dd, ee = u.dot(u), u.dot(v), v.dot(v), u.dot(w), v.dot(w)
    best = min(point_segment(a, c, d), point_segment(b, c, d), point_segment(c, a, b), point_segment(d, a, b))
    den = aa*cc-bb*bb
    if den > 1e-10:
        s, t = (bb*ee-cc*dd)/den, (aa*ee-bb*dd)/den
        if 0 <= s <= 1 and 0 <= t <= 1: best = min(best, (a+u*s-c-v*t).length)
    return best


def validate():
    """Read saved/evaluated world transforms, not the authored pose function."""
    sc = bpy.context.scene
    count = (COUNT-1)*16+1
    report = {'samples_per_actor': count, 'foot_matrix_error': 0., 'length_error': 0.,
              'joint_error': 0., 'min_floor': 1., 'min_clearance': 1., 'min_margin': 1.,
              'max_point_step': 0., 'primary_pair_error': 0., 'hard_poststop_motion': 0., 'settled_error': 0.}
    previous, at_stop = {}, {}
    observed = {n: [] for n in CHANNELS}
    point_names = list(pose('hard', 0))
    for i in range(count):
        frame, t = i/16, i/(16*FPS)
        sc.frame_set(int(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        positions = {}
        for case, offset in CASES.items():
            p = {n: obj(case, n).matrix_world.translation.copy() for n in point_names}
            positions[case] = p
            rods = {}
            for name, (a, b) in LINKS.items():
                ob = obj(case, name)
                start, end = (ob.matrix_world@Vector((0, 0, z)) for z in (-.5, .5))
                radius = ob['radius']
                rods[name] = (start, end, radius)
                report['length_error'] = max(report['length_error'], abs((end-start).length-ob['length']))
                report['joint_error'] = max(report['joint_error'], (start-p[a]).length, (end-p[b]).length)
                report['min_floor'] = min(report['min_floor'], start.z-radius, end.z-radius)
            report['length_error'] = max(report['length_error'], abs((p['head']-p['neck']).length-.19))
            for name in point_names:
                ob = obj(case, name)
                report['min_floor'] = min(report['min_floor'], p[name].z-ob['radius'])
            for side, sign in [('L', -1), ('R', 1)]:
                foot = obj(case, side+'_foot')
                expected = Matrix.Translation(Vector((offset+sign*.23, .10, .05)))
                report['foot_matrix_error'] = max(report['foot_matrix_error'],
                    max(abs(foot.matrix_world[r][c]-expected[r][c]) for r in range(4) for c in range(4)),
                    (p[side+'_ankle']-Vector((offset+sign*.23, .04, .10))).length)
                report['min_floor'] = min(report['min_floor'], min((foot.matrix_world@Vector(v)).z for v in foot.bound_box))
            for name in ('L_upperarm', 'L_forearm', 'R_upperarm', 'R_forearm'):
                a, b, radius = rods[name]
                for other in ('torso', 'L_thigh', 'R_thigh', 'L_shin', 'R_shin'):
                    c, d, r2 = rods[other]
                    report['min_clearance'] = min(report['min_clearance'], segment_distance(a, b, c, d)-radius-r2)
                report['min_clearance'] = min(report['min_clearance'], point_segment(p['head'], a, b)-radius-.14)
            a, b, r = rods['L_forearm']; c, d, r2 = rods['R_forearm']
            report['min_clearance'] = min(report['min_clearance'], segment_distance(a, b, c, d)-r-r2)
            if case in previous:
                report['max_point_step'] = max(report['max_point_step'], max((p[n]-previous[case][n]).length for n in p))
            previous[case] = p
            if abs(t-STOP) < 1e-9: at_stop[case] = p
            if case == 'hard' and t >= STOP:
                report['hard_poststop_motion'] = max(report['hard_poststop_motion'], max((p[n]-at_stop[case][n]).length for n in p))
            if t >= 4.2:
                target = pose(case, 4.4)
                report['settled_error'] = max(report['settled_error'], max((p[n]-target[n]).length for n in p))
            if case == 'follow':
                body, head = p['neck']-p['pelvis'], p['head']-p['neck']
                values = {'body': math.atan2(body.x, body.z), 'head': math.atan2(head.x, head.z),
                          'L_hand': p['L_hand'].x-p['pelvis'].x+.50,
                          'R_hand': p['R_hand'].x-p['pelvis'].x-.50}
                for n, value in values.items(): observed[n].append(value)
        report['primary_pair_error'] = max(report['primary_pair_error'],
            (positions['hard']['pelvis']-Vector((CASES['hard'], 0, 0))-
             positions['follow']['pelvis']+Vector((CASES['follow'], 0, 0))).length)
        if i % 16 == 0:
            for ob in sc.objects:
                if ob.type in ('MESH', 'FONT') and ob.name != 'Floor':
                    for vertex in ob.bound_box:
                        uv = world_to_camera_view(sc, sc.camera, ob.matrix_world@Vector(vertex))
                        report['min_margin'] = min(report['min_margin'], uv.x, uv.y, 1-uv.x, 1-uv.y)
    peaks = {}
    for n, data in observed.items():
        first = round(STOP*FPS*16)
        peak = max(range(first, len(data)), key=lambda k: data[k])
        significant = [v for v in data[first:] if abs(v) > .0005]
        crossings = sum(a*b < 0 for a, b in zip(significant, significant[1:]))
        peaks[n] = {'residual_at_stop': data[first], 'overshoot': data[peak],
                    'peak_seconds': peak/(FPS*16), 'sign_changes_after_stop': crossings}
        if abs(data[first]) < .005 or data[peak] < .001 or crossings > 2:
            raise ValueError('Missing/oscillatory follow-through: '+str(peaks))
    report['followthrough'] = peaks
    if not all(peaks[a]['peak_seconds'] < peaks[b]['peak_seconds'] for a, b in zip(CHANNELS, list(CHANNELS)[1:])):
        raise ValueError('Secondary ordering: '+str(peaks))
    if (report['foot_matrix_error'] > 2e-6 or report['length_error'] > 2e-6 or
        report['joint_error'] > .002 or report['min_floor'] < -.0001 or report['min_clearance'] < -.0001 or
        report['min_margin'] < .025 or report['max_point_step'] > .006 or report['primary_pair_error'] > 2e-6 or
        report['hard_poststop_motion'] > 2e-6 or report['settled_error'] > 2e-5):
        raise ValueError(json.dumps(report))
    return report


def negative_tests():
    caught = []
    for name, field, axis, delta in [('L_foot', 'delta_location', 2, -.01),
                                     ('R_forearm', 'scale', 2, .02), ('head', 'delta_location', 2, .025)]:
        ob = obj('follow', name)
        old = getattr(ob, field).copy()
        getattr(ob, field)[axis] += delta
        try:
            validate()
        except ValueError:
            caught.append(name)
        else:
            raise AssertionError('Missed corrupted '+name)
        finally:
            setattr(ob, field, old)
    return caught


def movie_review(folder, ff):
    movie = folder/'followthrough.mp4'
    header = subprocess.run([str(ff), '-hide_banner', '-i', str(movie)], capture_output=True, text=True).stderr
    if not re.search(r'640x360', header) or not re.search(r'30 fps', header) or 'Audio:' in header:
        raise ValueError('Expected silent 640x360/30fps')
    def decode(args):
        run = subprocess.run([str(ff), '-v', 'error', *args, '-vf', 'scale=160:90', '-an', '-pix_fmt',
                              'rgb24', '-f', 'rawvideo', '-'], capture_output=True, check=True)
        return np.frombuffer(run.stdout, np.uint8).reshape((-1, 90, 160, 3))
    raw = decode(['-i', str(movie)])
    source = decode(['-framerate', str(FPS), '-i', str(folder/'frames/f%04d.png')])
    if raw.shape != source.shape or len(raw) != COUNT: raise ValueError('Wrong frame count')
    error = float(np.abs(raw.astype(float)-source).mean(axis=(1, 2, 3)).max())
    if error > 6 or raw.mean(axis=(1, 2, 3)).min() < 15: raise ValueError('Encoding mismatch/dark frame')
    (folder/'review').mkdir(exist_ok=True)
    subprocess.run([str(ff), '-y', '-v', 'error', '-i', str(movie), '-vf',
                    'scale=480:270,tile=3x5:nb_frames=15:padding=2:margin=2', '-fps_mode', 'passthrough',
                    '-q:v', '2', str(folder/'review/sheet%02d.jpg')], check=True)
    return {'sha256': hashlib.sha256(movie.read_bytes()).hexdigest(), 'bytes': movie.stat().st_size,
            'frames': len(raw), 'fps': FPS, 'duration': len(raw)/FPS, 'max_encoding_error': error}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['block', 'render', 'review'], default='block')
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--engine', choices=['cycles', 'eevee'], default='cycles')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    folder = args.out.resolve()
    if args.mode != 'review' and folder.exists(): raise ValueError('Use a new output directory')
    if args.mode in ('render', 'review') and not args.ffmpeg: raise ValueError('--ffmpeg is required')
    started = time.perf_counter()
    if args.mode == 'review':
        bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
    else:
        folder.mkdir(parents=True)
        sc = setup(args.engine)
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))
        # Validate the persisted animation in all modes, not just live construction.
        bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
    report = validate()
    report['blender_version'] = bpy.app.version_string
    report['engine'] = bpy.context.scene.render.engine
    if args.mode == 'review':
        report['negative_tests'] = negative_tests()
        report['movie'] = movie_review(folder, args.ffmpeg)
    else:
        sc = bpy.context.scene
        (folder/'frames').mkdir()
        if args.mode == 'block':
            for frame in (0, 32, 48, 60, 74, 100, 134):
                sc.frame_set(frame)
                sc.render.filepath = str(folder/'frames'/f'f{frame:04d}.png')
                bpy.ops.render.render(write_still=True)
        else:
            sc.render.filepath = str(folder/'frames/f')
            bpy.ops.render.render(animation=True)
            subprocess.run([str(args.ffmpeg), '-v', 'error', '-framerate', str(FPS), '-i',
                            str(folder/'frames/f%04d.png'), '-frames:v', str(COUNT), '-an', '-c:v',
                            'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                            str(folder/'followthrough.mp4')], check=True)
    report['elapsed_seconds'] = time.perf_counter()-started
    (folder/(args.mode+'.json')).write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
