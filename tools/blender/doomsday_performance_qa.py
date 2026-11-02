"""Numeric rig/camera audit; run inside Blender after authoring and cameras.

Reports measurements, not an artistic PASS or a skin-intersection guarantee.
The contact convention in doomsday_performance.author is index_1_R HEAD.
"""
import json
import math
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


OUT = Path(__file__).resolve().parents[2] / '_game/skits/doomsday/v6'
N, LIFT, HIT = 420, 231, 279


def _matrix(arm, name):
    return arm.matrix_world @ arm.pose.bones[name].matrix


def _difference(a, b):
    pa, qa, sa = a.decompose()
    pb, qb, sb = b.decompose()
    angle = math.degrees(qa.rotation_difference(qb).angle)
    return {'position': (pa - pb).length,
            'rotation_degrees': min(angle, 360-angle),
            'scale_component': max(abs(x - y) for x, y in zip(sa, sb))}


def _maximum(bucket, name, value, time):
    if not math.isfinite(value):
        raise ValueError(f'Non-finite audit measurement: {name} at {time}')
    old = bucket.get(name)
    if old is None or value > old['value']:
        bucket[name] = {'value': float(value), 'frame': time, 'seconds': time / 30}


def _diff_metrics(bucket, name, current, baseline, time):
    for suffix, value in _difference(current, baseline).items():
        _maximum(bucket, name + '.' + suffix, value, time)


def _world_snapshot(arm, names):
    return {name: _matrix(arm, name).copy() for name in names}


def _projection(scene, camera, point):
    value = world_to_camera_view(scene, camera, point)
    # x/y are normalized image coordinates, with y increasing upwards.
    return float(value.x), float(value.y), float(value.z)


def _record_projection(records, name, value, time):
    x, y, z = value
    if not all(math.isfinite(component) for component in value):
        raise ValueError(f'Non-finite camera projection: {name} at {time}')
    entry = records.setdefault(name, {'samples': 0, 'outside_image': [],
                                     'outside_tiktok_safe_zone': [], 'behind_camera': [],
                                     'min_xy': [x, y], 'max_xy': [x, y]})
    entry['samples'] += 1
    entry['min_xy'] = [min(entry['min_xy'][0], x), min(entry['min_xy'][1], y)]
    entry['max_xy'] = [max(entry['max_xy'][0], x), max(entry['max_xy'][1], y)]
    record = {'frame': time, 'x': x, 'y': y, 'depth': z}
    if z <= 0:
        entry['behind_camera'].append(record)
    if not (0 <= x <= 1 and 0 <= y <= 1):
        entry['outside_image'].append(record)
    # Normalized from the project 1080x1920 delivery safe zone.
    if not (60/1080 <= x <= 940/1080 and 1-1560/1920 <= y <= 1-150/1920):
        entry['outside_tiktok_safe_zone'].append(record)


def audit(scene, axe, rubick, contact, poses, defender):
    """Measure evaluated matrices at all integer and specified quarter frames.

    Returns a JSON-serializable report and saves performance_qa.json. No
    tolerances are promoted into a PASS; failed structural prerequisites raise.
    """
    if len(poses) != N or len(defender) != N:
        raise ValueError('Audit requires 420 authored poses for both characters')
    if scene.camera is None:
        raise ValueError('Audit requires the authored camera')
    required = {axe: ('axe_1', 'wrist_L', 'wrist_R', 'head', 'ankle_L', 'ankle_R'),
                rubick: ('wrist_R', 'index_1_R', 'Head_0')}
    for arm, names in required.items():
        missing = [name for name in names if name not in arm.pose.bones]
        if missing:
            raise ValueError(f'Missing required audit bones in {arm.name}: {missing}')
    contact = Vector(contact)
    # Union of quarter frames around 231..290 and throughout 279..419;
    # exclude times after the actual last frame 419.
    times = sorted(set(range(N)) | {q / 4 for q in range(LIFT * 4, (N-1) * 4 + 1)})
    old_frame, old_subframe = scene.frame_current, scene.frame_subframe
    report = {'frames': N, 'fps': 30, 'samples': len(times),
              'integer_samples': N, 'quarter_samples': len(times)-N,
              'quarter_interval': [LIFT, N-1], 'contact': list(contact),
              'units': {'position': 'Blender world units', 'rotation': 'degrees',
                        'grip_relative_position': 'weapon-local coordinates including inverse weapon scale'},
              'maxima': {'integer': {}, 'subframe': {}}, 'projections': {},
              'missing_optional_chains': [], 'baseline_segment_lengths': {},
              'limitations': ['No mesh self-intersection or skin-deformation audit.',
                             'Head bone origins are projection markers, not actual face centers or bounds.',
                             'Projection does not detect foreground occlusion.',
                             'Bone-head grip invariance does not prove fingers wrap the mesh.',
                             'Weapon fixation measures axe_1, not independently deformed mesh vertices.',
                             'Planting measures ankle/descendant transform drift, not sole-ground clearance.',
                             'No listening or perceptual motion approval.',
                             'No numeric tolerance is used to infer an overall PASS.']}
    chains = []
    for label, arm in (('axe', axe), ('rubick', rubick)):
        for kind, components in (('arm', ('bicep', 'elbow', 'wrist')),
                                 ('leg', ('thigh', 'knee', 'ankle'))):
            for side in ('L', 'R'):
                names = tuple(name + '_' + side for name in components)
                title = f'{label}.{kind}_{side}'
                if all(name in arm.pose.bones for name in names):
                    chains.append((label, title, names))
                else:
                    report['missing_optional_chains'].append(title)
    try:
        scene.frame_set(0)
        graph = bpy.context.evaluated_depsgraph_get()
        arms = {'axe': axe.evaluated_get(graph), 'rubick': rubick.evaluated_get(graph)}
        weapon0 = _matrix(arms['axe'], 'axe_1')
        relative0 = {side: weapon0.inverted() @ _matrix(arms['axe'], 'wrist_' + side) for side in ('L', 'R')}
        foot_names = sorted({bone.name for side in ('L', 'R')
                             for bone in [arms['axe'].pose.bones['ankle_' + side],
                                          *arms['axe'].pose.bones['ankle_' + side].children_recursive]})
        feet0 = _world_snapshot(arms['axe'], foot_names)
        report['planted_bones'] = foot_names
        lengths0 = {}
        for label, title, names in chains:
            points = [_matrix(arms[label], name).translation for name in names]
            lengths0[title] = [(points[i+1]-points[i]).length for i in range(2)]
        report['baseline_segment_lengths'] = lengths0
        scene.frame_set(HIT)
        graph = bpy.context.evaluated_depsgraph_get()
        a, r = axe.evaluated_get(graph), rubick.evaluated_get(graph)
        held = {'weapon': _matrix(a, 'axe_1').copy(),
                'axe_wrist_R': _matrix(a, 'wrist_R').copy(),
                'rubick_wrist_R': _matrix(r, 'wrist_R').copy(),
                'rubick_index_1_R': _matrix(r, 'index_1_R').copy()}
        finger = r.pose.bones['index_1_R']
        head, tail = r.matrix_world @ finger.head, r.matrix_world @ finger.tail
        report['contact_convention'] = {
            'source': 'doomsday_performance.author aligns cast[index_1_R].translation; this is the bone head, not fingertip',
            'geometry_point': 'author selects the evaluated weapon vertex with minimum world y at HIT',
            'head_to_contact_at_hit': (head-contact).length,
            'tail_to_contact_at_hit': (tail-contact).length,
            'head_at_hit': list(head), 'tail_at_hit': list(tail),
            'fingertip_surface_contact_verified': False}
        for time in times:
            integer = int(time)
            scene.frame_set(integer, subframe=time-integer)
            graph = bpy.context.evaluated_depsgraph_get()
            a, r = axe.evaluated_get(graph), rubick.evaluated_get(graph)
            arms = {'axe': a, 'rubick': r}
            metrics = report['maxima']['integer' if time == integer else 'subframe']
            weapon = _matrix(a, 'axe_1')
            inverse = weapon.inverted()
            for side in ('L', 'R'):
                _diff_metrics(metrics, 'grip_' + side, inverse @ _matrix(a, 'wrist_' + side), relative0[side], time)
            if time < LIFT:
                for name, baseline in feet0.items():
                    _diff_metrics(metrics, 'planted.' + name, _matrix(a, name), baseline, time)
            if time >= HIT:
                current = {'weapon': weapon, 'axe_wrist_R': _matrix(a, 'wrist_R'),
                           'rubick_wrist_R': _matrix(r, 'wrist_R'),
                           'rubick_index_1_R': _matrix(r, 'index_1_R')}
                for name, baseline in held.items():
                    _diff_metrics(metrics, 'held.' + name, current[name], baseline, time)
                _maximum(metrics, 'contact.index_head_distance',
                         (current['rubick_index_1_R'].translation-contact).length, time)
            for label, title, names in chains:
                points = [_matrix(arms[label], name).translation for name in names]
                for segment in range(2):
                    length = (points[segment+1]-points[segment]).length
                    baseline = lengths0[title][segment]
                    _maximum(metrics, title + f'.segment_{segment}.absolute_length_change', abs(length-baseline), time)
                    if baseline:
                        _maximum(metrics, title + f'.segment_{segment}.relative_length_change', abs(length/baseline-1), time)
            if time == integer:
                for label, authored in (('axe', poses), ('rubick', defender)):
                    for name in required[axe if label == 'axe' else rubick]:
                        _diff_metrics(metrics, 'bake.' + label + '.' + name,
                                      _matrix(arms[label], name), authored[integer][name], time)
            camera = scene.camera.evaluated_get(graph)
            markers = []
            if time < 45 or 120 <= time < 273 or 279 <= time < 303 or time >= 363:
                markers.append(('axe_head', _matrix(a, 'head').translation))
            if time < 45 or 273 <= time < 279 or 324 <= time < 363:
                markers.append(('rubick_head', _matrix(r, 'Head_0').translation))
            if HIT <= time < 324:
                markers.append(('contact', contact))
            for name, point in markers:
                _record_projection(report['projections'], name, _projection(scene, camera, point), time)
    finally:
        scene.frame_set(old_frame, subframe=old_subframe)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'performance_qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
