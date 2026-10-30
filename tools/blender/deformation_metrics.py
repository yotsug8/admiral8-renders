"""CPU-only, same-frame evaluated mesh comparison; never saves either scene.

Run: blender -b --disable-autoexec --python-exit-code 2 -P
tools/blender/deformation_metrics.py -- baseline.blend candidate.blend
--actor pudge --mesh-suffix lower_body --frames 6-102 --json report.json

Exit codes: 0 below thresholds, 1 deformation threshold exceeded, 2 error.
The output parent must already exist. Triangle/vertex IDs are evaluated IDs.
Topology identity is required but cannot establish semantic correspondence.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

import bpy


def frames_arg(value):
    match = re.fullmatch(r"(-?\d+)(?:-(-?\d+))?", value)
    if not match:
        raise argparse.ArgumentTypeError("expected inclusive START-END or FRAME")
    first = int(match[1])
    last = int(match[2]) if match[2] else first
    if last < first:
        raise argparse.ArgumentTypeError("frame range is reversed")
    return range(first, last + 1)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def snapshot(path, args):
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
    roots = [o for o in bpy.context.scene.objects
             if o.name.casefold() in {args.actor.casefold(),
                                     (args.actor + '_root').casefold()}]
    if len(roots) != 1:
        raise ValueError(f"expected one exact actor/root: found {len(roots)}")
    objects = [roots[0], *roots[0].children_recursive]
    matches = [o for o in objects if o.type == 'MESH'
               and o.name.endswith(args.mesh_suffix)]
    if len(matches) != 1:
        raise ValueError(f"expected one mesh suffix match: {[o.name for o in matches]}")
    obj = matches[0]
    scene = bpy.context.scene
    scale = scene.unit_settings.scale_length
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("invalid scene unit scale")
    result = {}
    for frame in args.frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = ev.to_mesh()
        try:
            mesh.calc_loop_triangles()
            points = [(ev.matrix_world @ v.co) * scale for v in mesh.vertices]
            if any(not math.isfinite(x) for p in points for x in p):
                raise ValueError(f"nonfinite coordinates at frame {frame}")
            result[frame] = dict(
                points=points,
                edges=[tuple(e.vertices) for e in mesh.edges],
                triangles=[tuple(t.vertices) for t in mesh.loop_triangles],
                polygons=[tuple(p.vertices) for p in mesh.polygons],
                world_matrix=[list(row) for row in ev.matrix_world])
        finally:
            ev.to_mesh_clear()
    return dict(mesh=obj.name, unit_system=scene.unit_settings.system,
                metres_per_blender_unit=scale), result


def compare(base, candidate, frame, args):
    if (len(base['points']) != len(candidate['points']) or
            any(base[key] != candidate[key] for key in ('edges', 'triangles', 'polygons'))):
        raise ValueError(f"evaluated topology differs at frame {frame}")
    p, q = base['points'], candidate['points']
    edges = []
    zero_edges = []
    for index, (a, b) in enumerate(base['edges']):
        before, after = (p[a] - p[b]).length, (q[a] - q[b]).length
        ratio = after / before if before > args.edge_epsilon else None
        growth = after - before
        # An undefined ratio from a degenerate edge is reported, not silently passed.
        flagged = growth > args.growth_m and (ratio is None or ratio > args.stretch_ratio)
        item = dict(edge_index=index, vertices=[a, b], baseline_m=before,
                    candidate_m=after, growth_m=growth, ratio=ratio, flagged=flagged)
        edges.append(item)
        if ratio is None:
            zero_edges.append(index)
    triangles = []
    for index, ids in enumerate(base['triangles']):
        a, b, c = ids
        n = (p[b] - p[a]).cross(p[c] - p[a])
        m = (q[b] - q[a]).cross(q[c] - q[a])
        before, after = n.length / 2, m.length / 2
        ratio = after / before if before > args.area_epsilon else None
        angle = math.degrees(n.angle(m)) if n.length > 0 and m.length > 0 else None
        triangles.append(dict(triangle=index, vertices=list(ids), baseline_m2=before,
                              candidate_m2=after, ratio=ratio, normal_rotation_deg=angle,
                              contracted=ratio is not None and ratio < args.contraction_ratio))
    valid_edges = [e for e in edges if e['ratio'] is not None]
    valid_tri = [t for t in triangles if t['ratio'] is not None]
    top = args.top
    stretch = [e for e in edges if e['flagged']]
    contraction = [t for t in triangles if t['contracted']]
    normals = sorted([t for t in triangles if t['normal_rotation_deg'] is not None],
                     key=lambda t: t['normal_rotation_deg'], reverse=True)
    return dict(frame=frame, threshold_exceeded=bool(stretch or contraction),
                vertex_count=len(p), edge_count=len(edges), triangle_count=len(triangles),
                max_edge_ratio=max((e['ratio'] for e in valid_edges), default=None),
                max_growth_m=max((e['growth_m'] for e in edges), default=None),
                min_area_ratio=min((t['ratio'] for t in valid_tri), default=None),
                max_area_ratio=max((t['ratio'] for t in valid_tri), default=None),
                stretched_edge_count=len(stretch), contracted_triangle_count=len(contraction),
                normals_over_90_count=sum(t['normal_rotation_deg'] > 90 for t in normals),
                degenerate_baseline_edges=zero_edges,
                degenerate_baseline_triangles=[t['triangle'] for t in triangles if t['ratio'] is None],
                worst_edges=sorted(valid_edges, key=lambda e: e['ratio'], reverse=True)[:top],
                largest_growth_edges=sorted(edges, key=lambda e: e['growth_m'], reverse=True)[:top],
                flagged_edges=sorted(stretch, key=lambda e: e['growth_m'], reverse=True)[:top],
                smallest_area_triangles=sorted(valid_tri, key=lambda t: t['ratio'])[:top],
                largest_area_triangles=sorted(valid_tri, key=lambda t: t['ratio'], reverse=True)[:top],
                most_rotated_triangles=normals[:top],
                baseline_world_matrix=base['world_matrix'],
                candidate_world_matrix=candidate['world_matrix'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--mesh-suffix', required=True)
    parser.add_argument('--frames', type=frames_arg, required=True)
    parser.add_argument('--json', type=Path, required=True)
    parser.add_argument('--stretch-ratio', type=float, default=2.0)
    parser.add_argument('--growth-m', type=float, default=0.03)
    parser.add_argument('--contraction-ratio', type=float, default=0.1)
    parser.add_argument('--area-epsilon', type=float, default=1e-8, help='baseline area floor, m²')
    parser.add_argument('--edge-epsilon', type=float, default=1e-9, help='baseline length floor, m')
    parser.add_argument('--top', type=int, default=10)
    parser.add_argument('--hash-inputs', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    output = args.json.resolve()
    inputs = [args.baseline.resolve(), args.candidate.resolve()]
    if not output.parent.is_dir() or output in inputs or output.suffix.lower() == '.blend':
        raise ValueError('output must have an existing parent and cannot overwrite a scene')
    report = dict(status='error', warnings=[
        'Normal rotation >90 degrees is not proof of inversion or self-intersection.',
        'These metrics do not infer physical contact or collisions.',
        'World transforms and scene scale_length are applied; rigid pose rotations affect normals.',
        'Matching topology does not prove matching vertex semantics; degenerate ratios are null.',
        'Threshold pass is not proof of visually correct deformation.'])
    try:
        if (args.top < 1 or not all(math.isfinite(v) for v in
                (args.stretch_ratio, args.growth_m, args.contraction_ratio,
                 args.area_epsilon, args.edge_epsilon)) or
                args.stretch_ratio <= 1 or args.growth_m < 0 or
                not 0 < args.contraction_ratio < 1 or
                args.area_epsilon <= 0 or args.edge_epsilon <= 0):
            raise ValueError('invalid threshold settings')
        report['thresholds'] = {k: getattr(args, k) for k in
                                ('stretch_ratio', 'growth_m', 'contraction_ratio',
                                 'area_epsilon', 'edge_epsilon', 'top')}
        hashes = [digest(p) for p in inputs] if args.hash_inputs else None
        meta_b, baseline = snapshot(inputs[0], args)
        meta_c, candidate = snapshot(inputs[1], args)
        report['inputs'] = dict(baseline=dict(file=inputs[0].name, **meta_b),
                                candidate=dict(file=inputs[1].name, **meta_c))
        rows = [compare(baseline[f], candidate[f], f, args) for f in args.frames]
        report['per_frame'] = rows
        report['summary'] = dict(
            frames=len(rows), flagged_frames=[r['frame'] for r in rows if r['threshold_exceeded']],
            worst_edge_frame=max(rows, key=lambda r: r['max_edge_ratio'] or 0)['frame'],
            max_edge_ratio=max((r['max_edge_ratio'] for r in rows if r['max_edge_ratio'] is not None), default=None),
            max_growth_m=max((r['max_growth_m'] for r in rows if r['max_growth_m'] is not None), default=None),
            min_area_ratio=min((r['min_area_ratio'] for r in rows if r['min_area_ratio'] is not None), default=None))
        if hashes is not None:
            after = [digest(p) for p in inputs]
            report['sha256'] = dict(before=hashes, after=after, unchanged=hashes == after)
            if hashes != after:
                raise ValueError('input files changed during analysis')
        if any(not r['edge_count'] or not r['triangle_count'] for r in rows):
            raise ValueError('empty evaluated mesh')
        report['status'] = 'threshold' if report['summary']['flagged_frames'] else 'pass'
        code = 1 if report['status'] == 'threshold' else 0
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        code = 2
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(status=report['status'], summary=report.get('summary'),
                          error=report.get('error')), allow_nan=False), flush=True)
    return code


if __name__ == '__main__':
    try:
        exit_code = main()
    except Exception as error:
        print(f'deformation_metrics error: {error}', file=sys.stderr, flush=True)
        exit_code = 2
    sys.stdout.flush()
    sys.stderr.flush()
    # Blender may swallow SystemExit; guarantee the documented process status.
    os._exit(exit_code)
