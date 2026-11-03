"""Compare one Axe pose with the existing deformation-review skin cache.

Blender -b --python tools/blender/doomsday_pose_deformation.py --
  --blend candidate.blend --frame 48 --source-frame 327 --output pose_audit.json

No render, scene save, pose correction or overall PASS. The local cache contains
external game data and is deliberately not committed. A saved pose at the requested
frame is preserved; other frames are evaluated normally.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / '_game/skits/doomsday/v12/deformation_review'


def matrix_metrics(matrix):
    a = np.asarray(matrix, dtype=float)[:3, :3]
    scales = np.linalg.norm(a, axis=0)
    normalized = a / np.maximum(scales, 1e-30)
    return {'axis_scales': scales.tolist(),
            'shear_cos_max': float(np.max(np.abs(normalized.T @ normalized - np.eye(3)))),
            'determinant': float(np.linalg.det(a))}


def axial_angle(quaternion, axis):
    q, axis = quaternion.normalized(), axis.normalized()
    projection = Vector((q.x, q.y, q.z)).dot(axis)
    norm = math.hypot(q.w, projection)
    # Swing near 180 degrees can make a twist projection undefined.
    angle = ((2 * math.atan2(projection, q.w) + math.pi) % (2 * math.pi) - math.pi)
    return {'degrees': math.degrees(angle) if norm > 1e-8 else None,
            'projection_norm': norm}


def strain(points, reference, edges, triangles, selected):
    edge_ids = np.array([i for i, e in enumerate(edges) if all(int(v) in selected for v in e)], int)
    tri_ids = np.array([i for i, t in enumerate(triangles) if all(int(v) in selected for v in t)], int)
    e, t = edges[edge_ids], triangles[tri_ids]
    if not len(e) or not len(t):
        return {'vertices': len(selected), 'edges': len(e), 'triangles': len(t), 'measured': False}
    actual = np.linalg.norm(points[e[:, 1]] - points[e[:, 0]], axis=1)
    baseline = np.linalg.norm(reference[e[:, 1]] - reference[e[:, 0]], axis=1)
    valid = baseline > 1e-6
    ratio = actual[valid] / baseline[valid]
    if not len(ratio):
        raise ValueError('All selected reference edges are degenerate')
    valid_ids = np.flatnonzero(valid)
    def sample(j):
        k = int(valid_ids[j])
        return {'edge': int(edge_ids[k]), 'vertices': e[k].tolist(),
                'actual_length': float(actual[k]), 'reference_length': float(baseline[k]),
                'ratio': float(ratio[j])}
    def area(p):
        return np.linalg.norm(np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]]), axis=1) / 2
    base_area = area(reference)
    valid_area = base_area > 1e-10
    area_ratio = area(points)[valid_area] / base_area[valid_area]
    return {'vertices': len(selected), 'edges': len(e), 'triangles': len(t), 'measured': True,
            'edge_ratio_percentiles': dict(zip(('min', 'p05', 'median', 'p95', 'max'),
                                             np.percentile(ratio, (0, 5, 50, 95, 100)).tolist())),
            'most_compressed': sample(int(np.argmin(ratio))),
            'most_stretched': sample(int(np.argmax(ratio))),
            'triangle_area_ratio_percentiles': dict(zip(('min', 'p05', 'median', 'p95', 'max'),
                np.percentile(area_ratio, (0, 5, 50, 95, 100)).tolist())) if len(area_ratio) else None,
            'degenerate_reference_edges_omitted': int((~valid).sum()),
            'degenerate_reference_triangles_omitted': int((~valid_area).sum())}


def evaluate(blend, frame, source_frame, cache_dir=DEFAULT_CACHE):
    baseline = json.loads((cache_dir / 'deformation_metrics.json').read_text(encoding='utf8'))
    source_rows = baseline['poses']['source']
    index = next((i for i, row in enumerate(source_rows) if row['frame'] == source_frame), None)
    if index is None:
        raise ValueError('Requested source frame is absent from deformation cache')
    with np.load(cache_dir / 'evaluated_skin_cache.npz') as cache:
        source, candidate, edges = cache['source'][index], cache['candidate'][0], cache['edges'].copy()
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    scene = bpy.context.scene
    preserved_saved_pose = scene.frame_current == frame and scene.frame_subframe == 0
    if not preserved_saved_pose:
        scene.frame_set(frame)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    arm = next(o for o in scene.objects if o.type == 'ARMATURE' and o.parent
               and o.parent.name == 'axe_root' and o.name.endswith('axe.vmdl_c'))
    skin = next(o for o in scene.objects if o.type == 'MESH' and o.name.endswith('axe.vmdl_c.axe_model'))
    if not np.array_equal(edges, np.array([list(e.vertices) for e in skin.data.edges])):
        raise ValueError('Skin edge topology differs from cache; vertex correspondence is unsafe')
    ev = skin.evaluated_get(graph)
    mesh = ev.to_mesh()
    try:
        mesh.calc_loop_triangles()
        points = np.array([list(ev.matrix_world @ v.co) for v in mesh.vertices])
        triangles = np.array([list(t.vertices) for t in mesh.loop_triangles])
    finally:
        ev.to_mesh_clear()
    if points.shape != source.shape:
        raise ValueError('Evaluated vertex count differs from cache')
    names = {g.index: g.name for g in skin.vertex_groups}
    weights = [{names[g.group]: float(g.weight) for g in v.groups} for v in skin.data.vertices]
    evaluated = arm.evaluated_get(graph)
    pose = {b.name: evaluated.matrix_world @ b.matrix for b in evaluated.pose.bones}
    report = {'blend': blend.name, 'frame': frame, 'source_frame': source_frame,
              'preserved_saved_pose': preserved_saved_pose, 'regions': {}, 'bones': {}, 'grip_markers': {}}
    for side in ('L', 'R'):
        shoulder = {i for i, w in enumerate(weights) if w.get('bicep_' + side, 0) > .05
                    and sum(v for n, v in w.items() if n.startswith('spine') or n == 'clavicle_' + side) > .05}
        forearm = {i for i, w in enumerate(weights) if w.get('elbow_' + side, 0) + w.get('wrist_' + side, 0) > .65}
        for name, selected in [('shoulder_transition_' + side, shoulder), ('forearm_' + side, forearm)]:
            report['regions'][name] = {label: strain(points, ref, edges, triangles, selected)
                                      for label, ref in [('vs_v11', source), ('vs_grip_candidate318', candidate)]}
        for prefix in ('clavicle', 'bicep', 'elbow', 'wrist'):
            name = prefix + '_' + side
            b, rest = evaluated.pose.bones[name], arm.data.bones[name]
            relative = b.parent.matrix.inverted() @ b.matrix if b.parent else b.matrix
            rest_relative = rest.parent.matrix_local.inverted() @ rest.matrix_local if rest.parent else rest.matrix_local
            delta = rest_relative.inverted() @ relative
            proximal = 'elbow' if prefix == 'wrist' else 'bicep'
            distal = 'wrist' if prefix == 'wrist' else 'elbow'
            axis = rest.matrix_local.to_3x3().inverted() @ (arm.data.bones[distal + '_' + side].head_local
                    - arm.data.bones[proximal + '_' + side].head_local)
            report['bones'][name] = {'world': matrix_metrics(pose[name]), 'local_basis': matrix_metrics(b.matrix_basis),
                'parent_relative': matrix_metrics(relative), 'rest_relative_axial': axial_angle(delta.to_quaternion(), axis),
                'rest_relative_rotation_degrees': math.degrees(delta.to_quaternion().angle),
                'source_axial_degrees': source_rows[index]['bones'][name]['axial_twist_degrees'],
                'candidate318_axial_degrees': baseline['poses']['candidate'][0]['bones'][name]['axial_twist_degrees']}
        h, k, w = (pose[n + '_' + side].translation for n in ('bicep', 'elbow', 'wrist'))
        report['grip_markers'][side] = {'elbow_interior_degrees': math.degrees((h - k).angle(w - k)),
            'upper_length': (k - h).length, 'forearm_length': (w - k).length,
            'joint_heads_world': {n: list(pose[n + '_' + side].translation)
                                  for n in ('bicep', 'elbow', 'wrist', 'index_2', 'mid_2', 'thumb_1')
                                  if n + '_' + side in pose},
            'wrist_relative_weapon': [list(row) for row in pose['axe_1'].inverted() @ pose['wrist_' + side]]}
    report['weapon_marker_world'] = [list(row) for row in pose['axe_1']]
    static_hash = hashlib.sha256(np.array([list(v.co) for v in skin.data.vertices], np.float32).tobytes()).hexdigest()
    report['skin_basis_matches_source'] = static_hash == baseline['sources']['source']['static_skin_hash']
    report['limits'] = [
        'Facts only: no overall PASS, visual-motion judgement or collision test.',
        'References are previously rejected poses, not anatomical ground truth.',
        'Forearm region uses summed elbow/wrist weights>.65; shoulder uses bicep>.05 and spine/clavicle>.05.',
        'Edge strain and triangle area are actual surface measurements, not enclosed volume.',
        'Rest-relative axial wrist rotation is a residual orientation proxy; projection norm flags mathematical ambiguity.',
        'Grip markers are bone joint heads, not actual finger pads or certified contact points.',
        'Evaluated topology-changing modifiers are unsupported; source mesh must retain cached vertex correspondence.',
        'No scene or animation is modified or saved.']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blend', type=Path, required=True)
    parser.add_argument('--frame', type=int, required=True)
    parser.add_argument('--source-frame', type=int, required=True)
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    result = evaluate(args.blend.resolve(), args.frame, args.source_frame, args.cache.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps({'frame': args.frame, 'source_frame': args.source_frame,
                      'output': args.output.name, 'skin_basis_matches_source': result['skin_basis_matches_source']}))
