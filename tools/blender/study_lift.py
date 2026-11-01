"""Procedural two-hand lift study. Run inside Blender 5.2; no external assets.

blender -b --factory-startup --python-exit-code 2 -P tools/blender/study_lift.py --
  --out _game/study/foundations/lift_weight --mode block
Modes: block (validate + key poses), render (validate + all frames), verify
(reload and validate), review (reload, negative tests, decoded movie sheets).
Output directory must be new except verify/review. Movies are encoded only
when --ffmpeg points to an existing executable.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import subprocess
import sys
import time

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

FPS, FRAMES = 30, 135
HALF = Vector((.28, .20, .22))
LENGTHS = {'thigh': .46, 'shin': .46, 'upperarm': .44, 'forearm': .42,
           'torso': .50, 'shoulder': .46}
# time, pelvis Y/Z, torso pitch radians, box Y/Z. Identical box and proportions.
KEYS = {
    'light': [(0, -.08, .93, .02, .70, .22),
              (.25, -.08, .93, .05, .70, .22),
              (.90, -.10, .52, .85, .70, .22),
              (1.02, -.10, .52, .85, .70, .22),
              (1.55, -.08, .90, .08, .49, .86),
              (1.78, -.07, .93, .00, .48, .90),
              (2.25, -.08, .91, .04, .49, .86),
              (4.50, -.08, .91, .04, .49, .86)],
    'heavy': [(0, -.08, .93, .02, .70, .22),
              (.25, -.08, .93, .05, .70, .22),
              (1.10, -.10, .52, .85, .70, .22),
              (1.45, -.13, .58, .90, .70, .22),
              (1.75, -.15, .48, .88, .70, .22),
              (2.55, -.15, .76, .35, .52, .65),
              (3.15, -.13, .88, -.12, .44, .84),
              (3.42, -.14, .84, -.09, .45, .81),
              (3.95, -.13, .88, -.06, .44, .83),
              (4.50, -.13, .88, -.06, .44, .83)]}
GRAB = {'light': .9, 'heavy': 1.1}
BLOCK = {'light': [0, 27, 31, 46, 53, 68, 134],
         'heavy': [0, 33, 44, 53, 76, 94, 103, 119, 134]}


def smooth(x):
    x = min(1., max(0., x))
    return x*x*x*(10+x*(-15+6*x))


def values(case, t):
    keys = KEYS[case]
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            u = smooth((t-a[0])/(b[0]-a[0]))
            return [x+(y-x)*u for x, y in zip(a[1:], b[1:])]
    return keys[-1][1:]


def solve(a, b, first, second, pole):
    """Two rigid segments; reject unreachable targets rather than stretch."""
    delta = b-a
    distance = delta.length
    if not abs(first-second)+1e-5 < distance < first+second-1e-5:
        raise ValueError(f'Unreachable two-link target: {distance:.6f}')
    axis = delta/distance
    outward = pole-axis*pole.dot(axis)
    if outward.length < 1e-6:
        raise ValueError('Degenerate bend plane')
    along = (first*first-second*second+distance*distance)/(2*distance)
    return a+axis*along+outward.normalized()*math.sqrt(first*first-along*along)


def pose(case, t):
    py, pz, lean, by, bz = values(case, t)
    pelvis = Vector((0, py, pz))
    neck = pelvis+Vector((0, .5*math.sin(lean), .5*math.cos(lean)))
    box = Vector((0, by, bz))
    points = {'pelvis': pelvis, 'neck': neck,
              'head': neck+Vector((0, .17*math.sin(lean*.65), .19))}
    segments = {'torso': (pelvis, neck)}
    grip = smooth((t-.25)/(GRAB[case]-.25))
    for side, sign in [('L', -1), ('R', 1)]:
        hip = pelvis+Vector((sign*.15, 0, 0))
        ankle = Vector((sign*.23, .04, .10))
        knee = solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
        shoulder = neck+Vector((sign*.23, 0, 0))
        target = box+Vector((sign*.34, 0, 0))
        rest = Vector((sign*.36, .04, .78))
        # Reach is a world-space arc with outward clearance, ending at a handle.
        hand = rest.lerp(target, grip)+Vector((sign*.09*math.sin(math.pi*grip),
                                               0, .08*math.sin(math.pi*grip)))
        try:
            elbow = solve(shoulder, hand, .44, .42, Vector((sign, -.15, .12)))
        except ValueError as exc:
            raise ValueError(f'{case} t={t:.6f}: {exc}') from exc
        for name, value in [('hip', hip), ('ankle', ankle), ('knee', knee),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            points[f'{side}_{name}'] = value
        for name, ends in [('thigh', (hip, knee)), ('shin', (knee, ankle)),
                           ('upperarm', (shoulder, elbow)), ('forearm', (elbow, hand))]:
            segments[f'{side}_{name}'] = ends
    segments['shoulder'] = (points['L_shoulder'], points['R_shoulder'])
    return points, segments, box


def segment_box_distance(a, b, center):
    """Exact piecewise-quadratic distance between a segment and axis-aligned box."""
    a, b = a-center, b-center
    delta = b-a
    cuts = [0., 1.]
    for k in range(3):
        if abs(delta[k]) > 1e-12:
            cuts.extend(u for bound in (-HALF[k], HALF[k])
                        if 0 < (u := (bound-a[k])/delta[k]) < 1)
    cuts = sorted(set(cuts))
    def squared(u):
        return sum(max(abs(a[k]+delta[k]*u)-HALF[k], 0.)**2 for k in range(3))
    best = min(squared(u) for u in cuts)
    for lo, hi in zip(cuts, cuts[1:]):
        middle = (lo+hi)/2
        qa = qb = 0.
        for k in range(3):
            v = a[k]+delta[k]*middle
            if abs(v) > HALF[k]:
                offset = a[k]-math.copysign(HALF[k], v)
                qa += delta[k]**2
                qb += delta[k]*offset
        if qa:
            best = min(best, squared(max(lo, min(hi, -qb/qa))))
    return math.sqrt(best)


def material(name, color, metal=0.):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = .57
    bsdf.inputs['Metallic'].default_value = metal
    return mat


def cube(name, location, dimensions, mat, bevel=0.):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        mod = obj.modifiers.new('Soft edges', 'BEVEL')
        mod.width, mod.segments = bevel, 2
        obj.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    obj.data.materials.append(mat)
    return obj


def sphere(name, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=radius)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def rod(name, radius, mat):
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=radius, depth=1)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    obj.rotation_mode = 'QUATERNION'
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def key(obj, fields, frame):
    for field in fields:
        obj.keyframe_insert(field, frame=frame)


def orient(obj, a, b):
    obj.location = (a+b)/2
    q = (b-a).to_track_quat('Z', 'Y')
    if obj.rotation_quaternion.dot(q) < 0:
        q.negate()
    obj.rotation_quaternion = q
    obj.scale.z = (b-a).length


def setup(case):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.eevee.taa_render_samples = 16
    sc.render.resolution_x, sc.render.resolution_y = 640, 360
    sc.render.resolution_percentage = 100
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 0, FRAMES-1
    sc.render.image_settings.file_format = 'PNG'
    sc.view_settings.view_transform = 'AgX'
    sc.world = bpy.data.worlds.new('Studio')
    sc.world.use_nodes = True
    sc.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.22, .27, .30, 1)
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .5
    body = material('Ivory mannequin', (.66, .71, .69))
    joint = material('Dark joints', (.08, .15, .18))
    crate = material('Same crate in both variants', (.43, .23, .10))
    trim = material('Crate edges', (.19, .10, .055))
    handle = material('Handles', (.48, .43, .31), .3)
    floor = material('Floor', (.10, .15, .17))
    cube('Floor', (0, 0, -.06), (200, 200, .12), floor)
    box = cube('Box', (0, .7, .22), tuple(HALF*2), crate, .012)
    # All crate details are parented in local space, retaining one rigid box.
    for x in (-.27, .27):
        for z in (-.20, .20):
            detail = cube('Edge', (0, 0, 0), (.025, .402, .025), trim, .004)
            detail.parent, detail.location = box, (x, 0, z)
    for sign in (-1, 1):
        bar = rod('Handle', .016, handle)
        bar.parent = box
        orient(bar, Vector((sign*.34, -.085, 0)), Vector((sign*.34, .085, 0)))
        for y in (-.085, .085):
            mount = rod('Handle mount', .014, handle)
            mount.parent = box
            orient(mount, Vector((sign*.28, y, 0)), Vector((sign*.34, y, 0)))
    points, segments, _ = pose(case, 0)
    for name in points:
        radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .055)
        if name.endswith('hand'):
            radius = .047
        sphere(name, radius, body if name in ('head', 'pelvis') or name.endswith('hand') else joint)
    for name in segments:
        radius = radius_for(name)
        obj = rod(name, radius, body)
        obj['radius'] = radius
        obj['length'] = LENGTHS[name.split('_')[-1]]
    for side, sign in [('L', -1), ('R', 1)]:
        cube(f'{side}_foot', (sign*.23, .10, .05), (.18, .34, .10), joint, .025)
    # A small nose makes head direction visible without facial animation.
    nose = sphere('Nose', .035, joint)
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.location = (3.6, 5.3, 2.65)
    cam.rotation_euler = (Vector((0, .25, .85))-cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.type, cam.data.ortho_scale = 'ORTHO', 4.1
    for name, location, energy, size in [('Key', (-3, 4, 6), 1000, 5),
                                         ('Rim', (3, -3, 4), 800, 4)]:
        lamp = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        sc.collection.objects.link(lamp)
        lamp.location, lamp.data.energy, lamp.data.size = location, energy, size
        lamp.rotation_euler = (Vector((0, .2, .7))-lamp.location).to_track_quat('-Z', 'Y').to_euler()
    # Eighth-frame authored keys; validate independent sixteenth-frame playback.
    for i in range((FRAMES-1)*8+1):
        f = i/8
        p, links, center = pose(case, f/FPS)
        box.location = center
        key(box, ['location'], f)
        for name, position in p.items():
            obj = bpy.data.objects[name]
            obj.location = position
            key(obj, ['location'], f)
        # Nose follows a delayed, downward attention arc during the reach.
        down = smooth((f/FPS-.20)/.7)*(1-smooth((f/FPS-2.4)/.7))
        nose.location = p['head']+Vector((0, .13*math.cos(down*.8), -.13*math.sin(down*.8)))
        key(nose, ['location'], f)
        for name, (a, b) in links.items():
            obj = bpy.data.objects[name]
            orient(obj, a, b)
            key(obj, ['location', 'rotation_quaternion'], f)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:
                            point.interpolation = 'LINEAR'
    sc['study_case'] = case
    sc['study_limits'] = 'Rigid procedural mannequin; visual effort, no dynamics, skin, finger grasp or game rig transfer.'
    return sc


def radius_for(name):
    return {'torso': .13, 'shoulder': .065, 'thigh': .065,
            'shin': .06, 'upperarm': .055, 'forearm': .04}[name.split('_')[-1]]


def validate(case):
    sc = bpy.context.scene
    max_length = max_grip = max_foot = max_endpoint = 0.
    min_clearance = min_floor = min_margin = min_capsule = 1.
    worst = {}
    count = (FRAMES-1)*16+1
    for i in range(count):
        frame = i/16
        sc.frame_set(math.floor(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        center = bpy.data.objects['Box'].matrix_world.translation.copy()
        min_floor = min(min_floor, center.z-HALF.z)
        points = {name: bpy.data.objects[name].matrix_world.translation.copy()
                  for name in pose(case, 0)[0]}
        for side, sign in [('L', -1), ('R', 1)]:
            foot = bpy.data.objects[f'{side}_foot']
            max_foot = max(max_foot, (foot.matrix_world.translation-Vector((sign*.23, .10, .05))).length,
                           (points[f'{side}_ankle']-Vector((sign*.23, .04, .10))).length)
            # Fixed, world-aligned beveled feet are enclosed by these AABBs.
            foot_half = Vector((.09,.17,.05))
            separation = [max(abs(center[k]-foot.matrix_world.translation[k])-HALF[k]-foot_half[k],0.)
                          for k in range(3)]
            min_clearance = min(min_clearance, math.sqrt(sum(x*x for x in separation)))
            if frame/FPS >= GRAB[case]:
                max_grip = max(max_grip, (points[f'{side}_hand']-center-Vector((sign*.34, 0, 0))).length)
        endpoints = {'torso': ('pelvis', 'neck'), 'shoulder': ('L_shoulder', 'R_shoulder')}
        for side in ('L', 'R'):
            for part, a, b in [('thigh', 'hip', 'knee'), ('shin', 'knee', 'ankle'),
                               ('upperarm', 'shoulder', 'elbow'), ('forearm', 'elbow', 'hand')]:
                endpoints[f'{side}_{part}'] = (f'{side}_{a}', f'{side}_{b}')
        for name, (a, b) in endpoints.items():
            obj = bpy.data.objects[name]
            length = obj['length']
            # Check geometry endpoints from evaluated object matrices, independently
            # of the analytic targets and with rigid, unchanging object scale.
            actual_a = obj.matrix_world@Vector((0, 0, -.5))
            actual_b = obj.matrix_world@Vector((0, 0, .5))
            max_length = max(max_length, abs((actual_b-actual_a).length-length))
            max_endpoint = max(max_endpoint, (actual_a-points[a]).length, (actual_b-points[b]).length)
            clearance = segment_box_distance(actual_a, actual_b, center)-obj['radius']
            if clearance < min_capsule:
                min_capsule = clearance
                worst = dict(frame=frame, part=name)
            min_clearance = min(min_clearance, clearance)
            min_floor = min(min_floor, min(actual_a.z, actual_b.z)-obj['radius'])
        # Spheres include palms: grip intersects a handle, never the box solid.
        for name, point in points.items():
            radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .055)
            if name.endswith('hand'):
                radius = .047
            min_clearance = min(min_clearance, segment_box_distance(point, point, center)-radius)
            min_floor = min(min_floor, point.z-radius)
        nose = bpy.data.objects['Nose'].matrix_world.translation
        min_clearance = min(min_clearance, segment_box_distance(nose,nose,center)-.035)
        min_floor = min(min_floor,nose.z-.035)
        # Actual crate+mannequin bounding boxes stay inside the same camera.
        if i%16 == 0:
            for obj in sc.objects:
                if obj.type != 'MESH' or obj.name == 'Floor':
                    continue
                for corner in obj.bound_box:
                    uv = world_to_camera_view(sc, sc.camera, obj.matrix_world@Vector(corner))
                    min_margin = min(min_margin, uv.x, uv.y, 1-uv.x, 1-uv.y)
                    if uv.z <= 0:
                        raise ValueError('Geometry behind camera')
    result = dict(case=case, samples=count, frames=FRAMES, fps=FPS,
                  max_segment_length_error_m=max_length, max_grip_error_m=max_grip,
                  max_foot_or_ankle_drift_m=max_foot, max_joint_endpoint_error_m=max_endpoint,
                  min_box_body_capsule_clearance_m=min_clearance,
                  min_box_link_capsule_clearance_m=min_capsule,
                  min_floor_clearance_m=min_floor, min_screen_margin=min_margin,
                  worst_capsule=worst, grab_seconds=GRAB[case],
                  limits='Sixteenth-frame finite playback samples; capsule/sphere collision envelopes, no dynamics or arbitrary rig certification.')
    if max_length > 2e-6 or max_grip > 2e-5 or max_foot > 2e-6 or max_endpoint > .002:
        raise ValueError(f'Playback contact/length failure: {result}')
    if min_clearance < -.0001 or min_floor < -.0001 or min_margin < .025:
        raise ValueError(f'Collision/floor/framing failure: {result}')
    return result


def self_test():
    assert abs(segment_box_distance(Vector((1,0,0)), Vector((2,0,0)), Vector())-.72)<1e-6
    assert segment_box_distance(Vector((-1,0,0)), Vector((1,0,0)), Vector()) == 0
    assert abs(segment_box_distance(Vector((.5,.5,0)), Vector((.5,.5,1)), Vector())-
               math.hypot(.22,.30)) < 1e-6
    try:
        solve(Vector(), Vector((3,0,0)), 1, 1, Vector((0,1,0)))
    except ValueError:
        pass
    else:
        raise AssertionError('Unreachable chain must fail')
    # All procedural poses at independent eighth frames must be reachable.
    for case in KEYS:
        for i in range((FRAMES-1)*8+1):
            pose(case, i/(8*FPS))


def movie_review(folder, case, ffmpeg):
    """Decode the actual delivery, compare all source images, make dense sheets."""
    import numpy as np  # Bundled with Blender; no pip installation.
    movie = folder/f'lift_{case}.mp4'
    header = subprocess.run([str(ffmpeg), '-hide_banner', '-i', str(movie)],
                            capture_output=True, text=True).stderr
    if not re.search(r'640x360', header) or not re.search(r'30 fps', header) or 'Audio:' in header:
        raise ValueError('Expected silent 640x360/30fps movie')
    def decode(input_args):
        result = subprocess.run([str(ffmpeg),'-v','error',*input_args,'-vf','scale=160:90',
                                 '-an','-pix_fmt','rgb24','-f','rawvideo','-'],
                                capture_output=True,check=True)
        return np.frombuffer(result.stdout,np.uint8).reshape((-1,90,160,3))
    actual = decode(['-i',str(movie)])
    source = decode(['-framerate','30','-start_number','0','-i',str(folder/'frames/f%04d.png')])
    if actual.shape != source.shape or len(actual) != FRAMES:
        raise ValueError('Decoded/source frame count mismatch')
    errors = np.abs(actual.astype(np.int16)-source.astype(np.int16)).mean(axis=(1,2,3))
    if errors.max() > 6 or actual.mean(axis=(1,2,3)).min() < 15:
        raise ValueError('Decoded delivery differs from source or has a dark frame')
    sheets = folder/'review'
    sheets.mkdir(exist_ok=True)
    subprocess.run([str(ffmpeg),'-y','-v','error','-i',str(movie),'-vf',
                    'scale=320:180,tile=5x3:nb_frames=15:padding=2:margin=2',
                    '-fps_mode','passthrough','-q:v','2',str(sheets/'sheet%02d.jpg')],check=True)
    return dict(name=movie.name,sha256=hashlib.sha256(movie.read_bytes()).hexdigest(),
                bytes=movie.stat().st_size,decoded_frames=len(actual),size=[640,360],fps=30,duration=4.5,
                audio_stream=False,max_decoded_source_mean_abs_error=float(errors.max()),
                min_frame_mean=float(actual.mean(axis=(1,2,3)).min()),
                review_sheets=9,review_order='15 consecutive frames per sheet; rows left-to-right; sheets 01–09 cover 0–134.')


def negative_playback_tests(case):
    """Perturb saved geometry, require the independent playback checks to fail."""
    detected = []
    for name, field, component, amount in [('L_foot','delta_location',0,.01),
                                          ('L_hand','delta_location',0,.01),
                                          ('Box','delta_location',2,-.03),
                                          ('L_upperarm','scale',2,.01)]:
        obj = bpy.data.objects[name]
        original = getattr(obj,field).copy()
        getattr(obj,field)[component] += amount
        try:
            validate(case)
        except ValueError:
            detected.append(f'{name}:{field}:{component}')
        else:
            raise AssertionError(f'Undetected geometry corruption: {name}')
        finally:
            setattr(obj,field,original)
    return detected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['block','render','verify','review'], default='block')
    parser.add_argument('--case', choices=['light','heavy','both'], default='both')
    parser.add_argument('--ffmpeg', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out = args.out.resolve()
    existing = args.mode in ('verify','review')
    if not existing and out.exists():
        raise ValueError('Use a new output directory')
    if args.ffmpeg and not args.ffmpeg.is_file():
        raise ValueError('FFmpeg executable missing')
    self_test()
    cases = list(KEYS) if args.case == 'both' else [args.case]
    for case in cases:
        started = time.perf_counter()
        folder = out/case
        if existing:
            bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
        else:
            folder.mkdir(parents=True)
            setup(case)
        qa = validate(case)
        qa['blender'] = bpy.app.version_string
        qa['key_poses'] = KEYS[case]
        qa['self_tests'] = 'Distance cases, rejection of unreachable chain, all pose targets reachable.'
        report_name = args.mode+'.json' if existing else 'qa.json'
        (folder/report_name).write_text(json.dumps(qa,indent=2),encoding='utf-8')
        if args.mode == 'review':
            if not args.ffmpeg:
                raise ValueError('Review requires --ffmpeg')
            qa['negative_playback_tests'] = negative_playback_tests(case)
            qa['movie'] = movie_review(folder,case,args.ffmpeg)
        if not existing:
            sc = bpy.context.scene
            sc.frame_set(0)
            bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))
            frames = folder/'frames'
            frames.mkdir()
            if args.mode == 'block':
                for f in BLOCK[case]:
                    sc.frame_set(f)
                    sc.render.filepath = str(frames/f'f{f:04d}.png')
                    bpy.ops.render.render(write_still=True)
            else:
                sc.render.filepath = str(frames/'f')
                bpy.ops.render.render(animation=True)
                if args.ffmpeg:
                    movie = folder/f'lift_{case}.mp4'
                    subprocess.run([str(args.ffmpeg),'-v','error','-framerate','30','-start_number','0',
                                    '-i',str(frames/'f%04d.png'),'-frames:v',str(FRAMES),'-an',
                                    '-c:v','libx264','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)],check=True)
                    qa['movie'] = dict(name=movie.name, bytes=movie.stat().st_size,
                                       sha256=hashlib.sha256(movie.read_bytes()).hexdigest())
        qa['elapsed_seconds'] = time.perf_counter()-started
        (folder/report_name).write_text(json.dumps(qa,indent=2),encoding='utf-8')
        print('LIFT_QA '+json.dumps(qa),flush=True)


if __name__ == '__main__':
    main()
