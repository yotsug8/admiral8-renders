"""Rigid mannequin recovery, 156 frames at 30 fps; no game assets or dynamics.

Run in background Blender with --python-exit-code 2. Default: build/save only.
--verify reopens the saved blend and checks actual playback geometry.
--render keys / --render all are explicit, separate rendering operations.
--review decodes the completed MP4 and writes exhaustive contact sheets.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

from study_lift import cube, key, material, orient, rod, smooth, solve, sphere
from study_blocking import camera

FPS, FRAMES, BAKE = 30, 156, 8
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / '_game/study/recovery'
LENGTHS = {'torso': .50, 'shoulder': .46, 'thigh': .46, 'shin': .46,
           'upperarm': .44, 'forearm': .42}
RADII = {'torso': .105, 'shoulder': .055, 'thigh': .06, 'shin': .045,
         'upperarm': .05, 'forearm': .035}
# seconds, rear knee height, pelvis Y, torso lean, rear foot tilt, right wrist Y/Z.
# The planted knee is solved first; pelvis height follows a fixed-length thigh.
KEYS = [
    (0.,   .47, -.04, .03, 0., .08, .79),
    (.30,  .43, -.06, .12, 0., .12, .76),
    (1.15, .18,  .09, .70, .70, .55, .46),
    (1.65, .075, .12, .75, .96, .70, .25),
    (2.10, .075, .12, 1.10, .96, .75, .07),
    (2.60, .075, .12, 1.12, .96, .75, .07),
    (3.05, .075, .10, 1.00, .96, .75, .07),
    (3.50, .075, .12, .75, .96, .70, .30),
    (4.35, .32,  .02, .28, .35, .30, .68),
    (4.90, .47, -.04, .03, 0., .08, .79),
    (5.20, .47, -.04, .03, 0., .08, .79),
]
ACTORS = {'three_quarter': (-1.15, -.35), 'profile': (1.05, -math.pi / 2)}
KNEE_ON, KNEE_OFF = 1.65, 3.50
PALM_ON, PALM_OFF = 2.10, 3.05
PROBES = [0, 50, 72, 105, 147]


def values(t):
    for a, b in zip(KEYS, KEYS[1:]):
        if t <= b[0]:
            u = smooth((t-a[0])/(b[0]-a[0]))
            return [x+(y-x)*u for x, y in zip(a[1:], b[1:])]
    return KEYS[-1][1:]


def actor_matrix(name):
    x, angle = ACTORS[name]
    return Matrix.Translation((x, 0, 0)) @ Matrix.Rotation(angle, 4, 'Z')


def foot_pose(tilt):
    rotation = Matrix.Rotation(-tilt, 3, 'X')
    toe = Vector((.23, -.25, 0))
    center = toe - rotation @ Vector((0, .15, -.04))
    ankle = center + rotation @ Vector((0, -.05, .055))
    return center, ankle, rotation.to_quaternion()


def pose(t):
    kz, py, lean, tilt, hy, hz = values(t)
    foot, ankle, foot_rotation = foot_pose(tilt)
    # Frontward knee on a circle around the rear ankle: exact shin length.
    knee = Vector((.23, ankle.y + math.sqrt(.46**2-(kz-ankle.z)**2), kz))
    pelvis = Vector((0, py, kz + math.sqrt(.46**2-(py-knee.y)**2-.08**2)))
    neck = pelvis + Vector((0, .5*math.sin(lean), .5*math.cos(lean)))
    points = {'pelvis': pelvis, 'neck': neck,
              'head': neck + Vector((0, .19*math.sin(lean*.65), .19*math.cos(lean*.65)))}
    for side, sign in (('L', -1), ('R', 1)):
        hip = pelvis + Vector((sign*.15, 0, 0))
        a = Vector((-.23, .35, .095)) if side == 'L' else ankle
        k = solve(hip, a, .46, .46, Vector((0, 1, 0))) if side == 'L' else knee
        shoulder = neck + Vector((sign*.23, 0, 0))
        hand = (pelvis + Vector((-.40, .25, -.02))) if side == 'L' else Vector((.40, hy, hz))
        elbow = solve(shoulder, hand, .44, .42, Vector((sign, -.15, .12)))
        for name, point in [('hip', hip), ('ankle', a), ('knee', k),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            points[f'{side}_{name}'] = point
    points['nose'] = points['head'] + Vector((0, .13*math.cos(lean*.65), -.13*math.sin(lean*.65)))
    return points, foot, foot_rotation


def endpoints():
    result = {'torso': ('pelvis', 'neck'), 'shoulder': ('L_shoulder', 'R_shoulder')}
    for side in ('L', 'R'):
        for part, a, b in [('thigh', 'hip', 'knee'), ('shin', 'knee', 'ankle'),
                           ('upperarm', 'shoulder', 'elbow'), ('forearm', 'elbow', 'hand')]:
            result[f'{side}_{part}'] = (f'{side}_{a}', f'{side}_{b}')
    return result


def point_radius(name):
    return {'head': .14, 'pelvis': .095, 'nose': .035, 'R_knee': .075,
            'L_hand': .035, 'R_hand': .035}.get(name, .055)


def linear_keys():
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:
                            point.interpolation = 'LINEAR'


def build():
    # Check all authored targets before creating the scene.
    for i in range((FRAMES-1)*16+1):
        pose(i/(16*FPS))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 32
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 960, 540
    sc.render.resolution_percentage = 100
    sc.render.fps, sc.render.fps_base = FPS, 1.
    sc.frame_start, sc.frame_end = 0, FRAMES-1
    sc.render.image_settings.file_format = 'PNG'
    sc.render.use_motion_blur = False
    sc.view_settings.view_transform = 'AgX'
    sc.world = bpy.data.worlds.new('Recovery studio')
    sc.world.use_nodes = True
    sc.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.22, .27, .30, 1)
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .5
    body = material('Recovery ivory', (.66, .71, .69))
    joint = material('Recovery joints', (.08, .15, .18))
    contact = material('Recovery contact parts', (.63, .29, .075))
    floor = material('Recovery floor', (.10, .15, .17))
    cube('Floor', (0, 0, -.06), (200, 200, .12), floor)
    initial, _, _ = pose(0)
    objects = {}
    for actor in ACTORS:
        objects[actor] = local = {}
        for name in initial:
            mat = contact if name == 'R_knee' else body if name in ('head', 'pelvis') else joint
            local[name] = sphere(f'{actor}:{name}', point_radius(name), mat)
        for name in endpoints():
            part = name.split('_')[-1]
            obj = rod(f'{actor}:{name}', RADII[part], body)
            obj.scale.z = LENGTHS[part]
            local[name] = obj
        for side in ('L', 'R'):
            obj = cube(f'{actor}:{side}_foot', (0, 0, 0), (.18, .30, .08), joint)
            obj.rotation_mode = 'QUATERNION'
            local[f'{side}_foot'] = obj
            local[f'{side}_palm'] = cube(f'{actor}:{side}_palm', (0, 0, 0), (.14, .18, .06),
                                       contact if side == 'R' else joint)
            local[f'{side}_palm'].rotation_mode = 'QUATERNION'
    # Same area-light recipe as study_lift, expanded for the paired composition.
    for name, location, energy, size in [('Key', (-3, 4, 6), 1000, 5), ('Rim', (3, -3, 4), 800, 4)]:
        lamp = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        sc.collection.objects.link(lamp)
        lamp.location, lamp.data.energy, lamp.data.size = location, energy, size
        lamp.rotation_euler = (Vector((0, .2, .7))-lamp.location).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = camera(sc, 'Recovery camera', Vector((0, .05, .83)), Vector((0, 7, 2.2)), 5.1)
    for row in KEYS[:-1]:
        sc.timeline_markers.new(f'key {row[0]:.2f}s', frame=round(row[0]*FPS))
    for i in range((FRAMES-1)*BAKE+1):
        frame = i/BAKE
        p, foot, foot_rotation = pose(frame/FPS)
        for actor, local in objects.items():
            transform = actor_matrix(actor)
            rotation = transform.to_quaternion()
            for name, point in p.items():
                local[name].location = transform @ point
                key(local[name], ['location'], frame)
            for name, (a, b) in endpoints().items():
                obj = local[name]
                orient(obj, transform @ p[a], transform @ p[b])
                # Never key scale: the rod stays rigid even between baked samples.
                obj.scale.z = LENGTHS[name.split('_')[-1]]
                key(obj, ['location', 'rotation_quaternion'], frame)
            for side in ('L', 'R'):
                obj = local[f'{side}_foot']
                obj.location = transform @ (Vector((-.23, .40, .04)) if side == 'L' else foot)
                obj.rotation_quaternion = rotation if side == 'L' else rotation @ foot_rotation
                key(obj, ['location', 'rotation_quaternion'], frame)
                palm = local[f'{side}_palm']
                palm.location = transform @ (p[f'{side}_hand'] - Vector((0, 0, .04)))
                palm.rotation_quaternion = rotation
                key(palm, ['location'], frame)
    linear_keys()
    sc['recovery_version'] = 1
    sc['recovery_limits'] = 'Kinematic rigid links; no dynamics, balance guarantee, skin or game rig transfer.'
    sc.frame_set(0)
    return sc


class VerificationError(ValueError):
    pass


def require(condition, kind, detail):
    if not condition:
        raise VerificationError(f'{kind}: {detail}')


def segment_distance(a, b, c, d):
    """Closest distance of two finite segments, including parallel/end cases."""
    u, v, w = b-a, d-c, a-c
    aa, bb, cc = u.dot(u), u.dot(v), v.dot(v)
    dd, ee = u.dot(w), v.dot(w)
    clamp = lambda x: min(1., max(0., x))
    candidates = [(0., clamp(ee/cc)), (1., clamp((ee+bb)/cc)),
                  (clamp(-dd/aa), 0.), (clamp((bb-dd)/aa), 1.)]
    determinant = aa*cc-bb*bb
    if determinant > 1e-12:
        s, t = (bb*ee-cc*dd)/determinant, (aa*ee-bb*dd)/determinant
        if 0 <= s <= 1 and 0 <= t <= 1:
            candidates.append((s, t))
    return min((w+s*u-t*v).length for s, t in candidates)


def verify(frames=None):
    """Inspect evaluated saved objects; never call pose() or regenerate motion."""
    sc = bpy.context.scene
    require(sc.get('recovery_version') == 1, 'scene', 'Missing recovery scene')
    require((sc.frame_start, sc.frame_end, sc.render.fps) == (0, 155, 30)
            and abs(sc.render.fps_base-1) < 1e-9, 'timing', 'Expected 156 frames at 30 fps')
    required = list(pose_names()) + list(endpoints()) + ['L_foot', 'R_foot', 'L_palm', 'R_palm']
    objects = {}
    for actor in ACTORS:
        for name in required:
            obj = bpy.data.objects.get(f'{actor}:{name}')
            require(obj is not None and obj.type == 'MESH' and not obj.hide_render,
                    'object', f'Missing/hidden mesh {actor}:{name}')
            objects[actor, name] = obj
    # Cache evaluated local mesh vertices only for these undeformed rigid meshes.
    # Reject deformation/constraints/drivers rather than trust a static cache.
    vertices = {}
    for identifier, obj in objects.items():
        require(not obj.modifiers and not obj.constraints and not obj.data.shape_keys
                and not (obj.animation_data and obj.animation_data.drivers), 'rigid', obj.name)
        vertices[identifier] = np.array([tuple(v.co) for v in obj.data.vertices], dtype=np.float64)
    floor = bpy.data.objects.get('Floor')
    require(floor is not None and not floor.animation_data and not floor.modifiers,
            'floor', 'Expected static floor mesh')
    floor_z = max((floor.matrix_world @ v.co).z for v in floor.data.vertices)
    require(abs(floor_z) < 1e-7, 'floor', 'Floor top must be world Z=0')
    frames = list(frames) if frames is not None else [i/16 for i in range((FRAMES-1)*16+1)]
    stats = dict(samples=len(frames), min_floor_clearance_m=1., max_support_error_m=0.,
                 max_length_error_m=0., max_endpoint_error_m=0., min_camera_margin=1.,
                 min_actor_screen_gap=1., min_nonadjacent_link_clearance_m=1.,
                 max_joint_speed_m_s=0., max_joint_acceleration_m_s2=0.)
    history = []
    for frame in frames:
        sc.frame_set(math.floor(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        matrices = {k: obj.evaluated_get(deps).matrix_world.copy() for k, obj in objects.items()}
        bounds = {}
        for identifier, matrix in matrices.items():
            v = vertices[identifier]
            # Actual polygon geometry, not just joint positions or ideal capsules.
            world = v @ np.array(matrix.to_3x3()).T + np.array(matrix.translation)
            low = float(world[:, 2].min()) - floor_z
            stats['min_floor_clearance_m'] = min(stats['min_floor_clearance_m'], low)
            require(low >= -2e-5, 'floor', f'{identifier} frame {frame}: {low:.8f}m')
            bounds[identifier] = (world.min(axis=0), world.max(axis=0))
        screen_bounds = []
        all_points = []
        for actor in ACTORS:
            transform = actor_matrix(actor)
            get = lambda name: matrices[actor, name]
            # Foot sole / toe edge, knee sphere and palm underside are the supports.
            contacts = [('L_foot', Vector((-.23, .40, 0))),
                        ('R_foot', Vector((.23, -.25, 0)))]
            t = frame/FPS
            if KNEE_ON <= t <= KNEE_OFF:
                _, ankle, _ = foot_pose(.96)
                ky = ankle.y + math.sqrt(.46**2-(.075-ankle.z)**2)
                contacts.append(('R_knee', Vector((.23, ky, 0))))
            if PALM_ON <= t <= PALM_OFF:
                contacts.append(('R_palm', Vector((.40, .75, 0))))
            for name, expected in contacts:
                v = vertices[actor, name]
                bottom = v[np.abs(v[:, 2]-v[:, 2].min()) < 1e-7]
                if name == 'R_foot':
                    bottom = bottom[np.abs(bottom[:, 1]-bottom[:, 1].max()) < 1e-7]
                local_contact = Vector(bottom.mean(axis=0))
                error = (get(name) @ local_contact - transform @ expected).length
                # Also require an actual mesh surface on the floor, not an abstract marker.
                surface_gap = abs(bounds[actor, name][0][2]-floor_z)
                error = max(error, surface_gap)
                stats['max_support_error_m'] = max(stats['max_support_error_m'], error)
                require(error < 2e-5, 'support', f'{actor}:{name} frame {frame}: {error:.8f}m')
            links = {}
            for name, (a, b) in endpoints().items():
                v = vertices[actor, name]
                actual_a = get(name) @ Vector((0, 0, float(v[:, 2].min())))
                actual_b = get(name) @ Vector((0, 0, float(v[:, 2].max())))
                length_error = abs((actual_b-actual_a).length-LENGTHS[name.split('_')[-1]])
                endpoint_error = max((actual_a-get(a).translation).length, (actual_b-get(b).translation).length)
                stats['max_length_error_m'] = max(stats['max_length_error_m'], length_error)
                stats['max_endpoint_error_m'] = max(stats['max_endpoint_error_m'], endpoint_error)
                require(length_error < 2e-6, 'length', f'{actor}:{name} frame {frame}: {length_error}')
                require(endpoint_error < 8e-5, 'endpoint', f'{actor}:{name} frame {frame}: {endpoint_error}')
                links[name] = (actual_a, actual_b)
            # Conservative capsules for disconnected rods. Shared sockets, the
            # shoulder/torso junction and the two pelvis sockets intentionally overlap.
            names = list(links)
            for i, name in enumerate(names):
                for other in names[i+1:]:
                    if set(endpoints()[name]) & set(endpoints()[other]):
                        continue
                    if name == 'torso' and (other == 'shoulder' or other.endswith('thigh')):
                        continue
                    gap = segment_distance(*links[name], *links[other]) - RADII[name.split('_')[-1]] - RADII[other.split('_')[-1]]
                    stats['min_nonadjacent_link_clearance_m'] = min(stats['min_nonadjacent_link_clearance_m'], gap)
                    require(gap > -.00002, 'self-collision', f'{actor}:{name}/{other} frame {frame}: {gap}')
            for side in ('L', 'R'):
                for part, joint, attach in [('foot', 'ankle', (0, -.05, .055)),
                                             ('palm', 'hand', (0, 0, .04))]:
                    error = (get(f'{side}_{part}') @ Vector(attach)-get(f'{side}_{joint}').translation).length
                    require(error < 8e-5, 'attachment', f'{actor}:{side}_{part} frame {frame}: {error}')
            all_points.extend(tuple(get(name).translation) for name in pose_names())
            if frame % 1 == 0:
                uv = [world_to_camera_view(sc, sc.camera, get(name) @ Vector(corner))
                      for name in required for corner in objects[actor, name].bound_box]
                margin = min(min(p.x, p.y, 1-p.x, 1-p.y) for p in uv)
                stats['min_camera_margin'] = min(stats['min_camera_margin'], margin)
                require(all(p.z > 0 for p in uv) and margin > .035, 'framing', f'{actor} frame {frame}: {margin}')
                screen_bounds.append((min(p.x for p in uv), max(p.x for p in uv)))
        if screen_bounds:
            screen_bounds.sort()
            gap = screen_bounds[1][0]-screen_bounds[0][1]
            stats['min_actor_screen_gap'] = min(stats['min_actor_screen_gap'], gap)
            require(gap > .04, 'framing', f'Actors overlap at {frame}: {gap}')
        # Independent playback finite differences catch discontinuities at phase joins.
        history.append((frame/FPS, np.array(all_points)))
        if len(history) >= 2:
            dt = history[-1][0]-history[-2][0]
            velocity = (history[-1][1]-history[-2][1])/dt
            speed = float(np.linalg.norm(velocity, axis=1).max())
            stats['max_joint_speed_m_s'] = max(stats['max_joint_speed_m_s'], speed)
            require(speed < 3., 'motion', f'Joint speed {speed} at {frame}')
            if len(history) >= 3:
                before_dt = history[-2][0]-history[-3][0]
                before_v = (history[-2][1]-history[-3][1])/before_dt
                accel = float(np.linalg.norm((velocity-before_v)/((dt+before_dt)/2), axis=1).max())
                stats['max_joint_acceleration_m_s2'] = max(stats['max_joint_acceleration_m_s2'], accel)
                require(accel < 45., 'motion', f'Joint acceleration {accel} at {frame}')
            history = history[-2:]
    stats['limits'] = ('Finite 1/16-frame samples; mesh-floor, prescribed support anchors, link length, '
                       'attachments, nonadjacent rod capsules and frame bounds. No balance/dynamics, general self-collision, '
                       'surface visibility or artistic-quality certification. No render performed by verify.')
    return stats


def pose_names():
    return ['pelvis', 'neck', 'head', 'nose'] + [f'{s}_{p}' for s in ('L', 'R')
            for p in ('hip', 'ankle', 'knee', 'shoulder', 'elbow', 'hand')]


def negative_tests():
    """Corrupt real objects in memory; assert specific failure classes; never save."""
    detected = []
    cases = [('R_palm', 'delta_location', 2, .02, 'support'),
             ('R_knee', 'delta_location', 2, .02, 'support'),
             ('R_foot', 'delta_location', 0, .02, 'support'),
             ('L_foot', 'delta_location', 2, -.02, 'floor'),
             ('L_upperarm', 'scale', 2, .02, 'length')]
    for name, field, axis, amount, kind in cases:
        obj = bpy.data.objects[f'three_quarter:{name}']
        original = getattr(obj, field).copy()
        getattr(obj, field)[axis] += amount
        try:
            verify([75.])
        except VerificationError as exc:
            require(str(exc).startswith(kind+':'), 'negative-test', f'{name}: wrong failure {exc}')
            detected.append(dict(object=name, mutation=field, amount=amount, detected_as=kind))
        else:
            raise AssertionError(f'Undetected corrupt support/geometry: {name}')
        finally:
            setattr(obj, field, original)
            bpy.context.view_layer.update()
    # Mesh-only corruption: object origin and animation remain unchanged.
    obj = bpy.data.objects['three_quarter:R_palm']
    original = [v.co.copy() for v in obj.data.vertices]
    for vertex in obj.data.vertices:
        vertex.co.x += .02
    obj.data.update()
    try:
        verify([75.])
    except VerificationError as exc:
        require(str(exc).startswith('support:'), 'negative-test', f'Mesh-only palm corruption: {exc}')
        detected.append(dict(object='R_palm', mutation='mesh_vertices_x', amount=.02, detected_as='support'))
    else:
        raise AssertionError('Undetected mesh-only palm displacement')
    finally:
        for vertex, co in zip(obj.data.vertices, original):
            vertex.co = co
        obj.data.update()
    return detected


def movie_review(out, ffmpeg):
    """Decode the delivered MP4; compare all frames and make exhaustive sheets."""
    movie = out / 'recovery.mp4'
    header = subprocess.run([str(ffmpeg), '-hide_banner', '-i', str(movie)],
                            capture_output=True, text=True).stderr
    require(bool(re.search(r'960x540', header) and re.search(r'30 fps', header))
            and 'Audio:' not in header, 'movie', 'Expected silent 960x540/30fps delivery')
    def decode(arguments):
        raw = subprocess.run([str(ffmpeg), '-v', 'error', *arguments, '-vf', 'scale=160:90',
                              '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape((-1, 90, 160, 3))
    actual = decode(['-i', str(movie)])
    source = decode(['-framerate', str(FPS), '-start_number', '0', '-i', str(out/'frames/f%04d.png')])
    require(actual.shape == source.shape and len(actual) == FRAMES, 'movie', 'Frame count/source mismatch')
    errors = np.abs(actual.astype(np.int16)-source.astype(np.int16)).mean(axis=(1, 2, 3))
    means = actual.mean(axis=(1, 2, 3))
    require(float(errors.max()) < 6 and float(means.min()) > 15, 'movie', 'Encoding mismatch or dark frame')
    review = out / 'review'
    review.mkdir(exist_ok=True)
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-i', str(movie), '-vf',
                    'scale=320:180,tile=4x3:nb_frames=12:padding=2:margin=2',
                    '-fps_mode', 'passthrough', '-q:v', '2', str(review/'sheet%02d.jpg')], check=True)
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-i', str(movie), '-vf',
                    "select='eq(n,0)+eq(n,30)+eq(n,60)+eq(n,90)+eq(n,120)+eq(n,155)',"
                    'scale=480:270,tile=3x2:nb_frames=6:padding=2:margin=2',
                    '-frames:v', '1', '-update', '1', str(review/'seconds.jpg')], check=True)
    return dict(file=movie.name, sha256=hashlib.sha256(movie.read_bytes()).hexdigest(),
                bytes=movie.stat().st_size, frames=len(actual), fps=FPS, duration_seconds=FRAMES/FPS,
                resolution=[960, 540], audio_stream=False,
                max_decoded_source_mean_abs_error=float(errors.max()), min_frame_mean=float(means.min()),
                review_sheets=13, sheet_order='sheet01..13: twelve consecutive frames each, row-major, covers 0..155',
                seconds_sheet_frames=[0, 30, 60, 90, 120, 155],
                visual_review='Sheets generated; human/model inspection must be recorded separately.')


def write_report(out, name, report):
    (out / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--render', choices=['keys', 'all'])
    mode.add_argument('--review', action='store_true', help='Verify, decode MP4, make review sheets; no render')
    parser.add_argument('--rebuild', action='store_true', help='Replace this exercise output after editing')
    parser.add_argument('--device', choices=['CPU', 'GPU'], default='CPU', help='Only used by explicit --render')
    parser.add_argument('--ffmpeg', type=Path, help='Optionally encode the full render as recovery.mp4')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out = args.out.resolve()
    blend = out / 'recovery.blend'
    if args.ffmpeg and not args.ffmpeg.is_file():
        parser.error('--ffmpeg must be an existing executable')
    if args.review and not args.ffmpeg:
        parser.error('--review requires --ffmpeg')
    if args.rebuild and (args.verify or args.render or args.review):
        parser.error('--rebuild is only valid when building')
    if not args.verify and not args.render and not args.review:
        if out.exists() and not args.rebuild:
            parser.error('Output exists; use --verify, --render or explicit --rebuild')
        out.mkdir(parents=True, exist_ok=True)
        build()
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    if not blend.is_file():
        parser.error(f'Saved scene missing: {blend.name}; build first')
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    report_name = 'verify.json' if args.verify else 'render.json' if args.render else 'review.json' if args.review else 'build.json'
    write_report(out, report_name, dict(status='RUNNING', rendered=False))
    try:
        playback, negatives = verify(), negative_tests()
    except Exception as exc:
        write_report(out, report_name, dict(status='FAIL', error=str(exc), rendered=False))
        raise
    report = dict(status='PASS', blender=bpy.app.version_string, fps=FPS, frames=FRAMES,
                  duration_seconds=FRAMES/FPS, blend_sha256=hashlib.sha256(blend.read_bytes()).hexdigest(),
                  key_poses=KEYS, supports=dict(knee_seconds=[KNEE_ON, KNEE_OFF],
                                              palm_seconds=[PALM_ON, PALM_OFF], feet='entire sequence'),
                  playback=playback, negative_tests=negatives, rendered=False)
    # Discard all negative-test edits, including future changes to test cases.
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    write_report(out, report_name, report)
    if args.review:
        report['status'] = 'REVIEW_RUNNING'
        write_report(out, report_name, report)
        try:
            report['movie'] = movie_review(out, args.ffmpeg)
        except Exception as exc:
            report.update(status='FAIL', error=str(exc))
            write_report(out, report_name, report)
            raise
        report['status'] = 'PASS'
        write_report(out, report_name, report)
    if args.render:
        report['status'] = 'RENDER_RUNNING'
        write_report(out, report_name, report)
        sc = bpy.context.scene
        sc.cycles.device = args.device
        if args.device == 'GPU':
            prefs = bpy.context.preferences.addons['cycles'].preferences
            devices = []
            for backend in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
                try:
                    prefs.compute_device_type = backend
                    prefs.get_devices()
                except (TypeError, RuntimeError):
                    continue
                devices = [d for d in prefs.devices if d.type == backend]
                if devices:
                    break
            if not devices:
                raise ValueError('No configured Cycles GPU device; use CPU or configure Blender first')
            for d in prefs.devices:
                d.use = d.type == prefs.compute_device_type
            report['render_device'] = dict(backend=prefs.compute_device_type,
                                           devices=[d.name for d in devices])
        folder = out / ('probes' if args.render == 'keys' else 'frames')
        folder.mkdir(exist_ok=True)
        for frame in PROBES if args.render == 'keys' else range(FRAMES):
            sc.frame_set(frame)
            sc.render.filepath = str(folder / f'f{frame:04d}.png')
            bpy.ops.render.render(write_still=True)
        report['rendered'] = True
        report['render_frames'] = PROBES if args.render == 'keys' else list(range(FRAMES))
        if args.render == 'all' and args.ffmpeg:
            movie = out / 'recovery.mp4'
            subprocess.run([str(args.ffmpeg), '-y', '-v', 'error', '-framerate', str(FPS),
                            '-start_number', '0', '-i', str(folder/'f%04d.png'), '-frames:v', str(FRAMES),
                            '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
                            '-movflags', '+faststart', str(movie)], check=True)
            report['movie_sha256'] = hashlib.sha256(movie.read_bytes()).hexdigest()
        report['status'] = 'PASS'
        write_report(out, report_name, report)
    print('RECOVERY_QA ' + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
