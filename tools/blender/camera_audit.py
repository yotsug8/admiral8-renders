"""CPU projection audit: blender -b scene.blend -P camera_audit.py --
--actor pudge --frames 1-120 [--json report.json] [--mode head|body].

Exit 0: projected surfaces satisfy thresholds; 1: violations or inconclusive;
2: invalid input/scene. No rendering, saved changes, or occlusion claims.
"""
import argparse
import json
import math
from pathlib import Path
import re
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view

EXCLUDE = re.compile(r'physics|hitbox|collision|blob|helper|shadow|proxy', re.I)
HEAD = re.compile(r'(?:^|[^a-z])head(?:[^a-z]|$)', re.I)
LIMITATIONS = [
    'Projection bounds do not establish visibility or occlusion; no ray tests.',
    'Coverage is clipped bounding-box area, not visible surface area.',
    'Head selection uses explicitly head-named mesh surfaces, not bone samples.',
    'Merged heads without a separate named surface are inconclusive.',
    'Name-based helper exclusions and render/view-layer availability limit selection.',
    'Vertices do not prove curved/subdivision extrema between samples or subframes.',
    'Render borders, panoramic cameras and non-square-pixel TikTok output are unsupported.',
]


def bounds_metrics(points, margin=.03, min_bbox=.0001, safe=None):
    """Pure helper; points are (u, v, positive camera depth)."""
    if not points or any(not all(math.isfinite(n) for n in p) for p in points):
        return {'bbox_uv': None, 'violations': ['empty_or_nonfinite_projection']}
    x0, y0 = min(p[0] for p in points), min(p[1] for p in points)
    x1, y1 = max(p[0] for p in points), max(p[1] for p in points)
    area = (x1-x0)*(y1-y0)
    clipped = max(0., min(1., x1)-max(0., x0))*max(0., min(1., y1)-max(0., y0))
    off = x1 < 0 or x0 > 1 or y1 < 0 or y0 > 1
    errors = []
    if off: errors.append('wholly_offscreen')
    if x0 < margin or y0 < margin or x1 > 1-margin or y1 > 1-margin:
        errors.append('margin_truncation')
    if clipped < min_bbox: errors.append('bbox_below_threshold')
    if safe and (x0 < safe[0] or y0 < safe[1] or x1 > safe[2] or y1 > safe[3]):
        errors.append('outside_tiktok_safe_zone')
    return {'bbox_uv': [x0, y0, x1, y1], 'center_uv': [(x0+x1)/2, (y0+y1)/2],
            'bbox_area': area, 'clipped_bbox_area': clipped,
            'bbox_in_frame_fraction': clipped/area if area else 0.,
            'wholly_offscreen': off, 'violations': errors}


def lineage(obj):
    while obj:
        yield obj
        obj = obj.parent


def part_names(obj, root):
    return ' '.join(p.name for p in lineage(obj) if p != root)


def actor_root(scene, label):
    matches = [o for o in scene.objects if o.name.casefold() in
               {label.casefold(), (label+'_root').casefold()} and o.type != 'MESH']
    if len(matches) != 1:
        raise ValueError(f'Expected one exact actor root for {label!r}; found {len(matches)}')
    return matches[0]


def available_meshes(scene):
    result = set()
    def visit(coll):
        if coll.hide_render: return
        result.update(o for o in coll.objects if o.type == 'MESH' and
                      not o.hide_render and o.visible_get())
        for child in coll.children: visit(child)
    visit(scene.collection)
    return result


def audit(scene, args):
    root = actor_root(scene, args.actor)
    if not scene.camera or scene.camera.type != 'CAMERA':
        raise ValueError('No active scene camera')
    if scene.render.use_border: raise ValueError('Render borders are unsupported')
    r = scene.render
    aspect = r.resolution_x*r.pixel_aspect_x/(r.resolution_y*r.pixel_aspect_y)
    safe = None
    if args.tiktok:
        if abs(aspect-1080/1920) > 1e-6 or r.pixel_aspect_x != r.pixel_aspect_y:
            raise ValueError('--tiktok requires vertical 1080:1920 aspect and square pixels')
        safe = [60/1080, 1-1560/1920, 940/1080, 1-150/1920]
    report = {'actor': args.actor, 'mode': args.mode, 'margin': args.margin,
              'min_bbox_area': args.min_bbox, 'max_drift_uv': args.max_drift,
              'resolution': [r.resolution_x*r.resolution_percentage/100,
                             r.resolution_y*r.resolution_percentage/100],
              'display_aspect': aspect, 'safe_zone_uv': safe,
              'limitations': LIMITATIONS, 'frames': []}
    old_frame, old_sub = scene.frame_current, scene.frame_subframe
    previous = first = None
    try:
        for frame in range(args.start, args.end+1):
            scene.frame_set(frame)
            graph = bpy.context.evaluated_depsgraph_get()
            camera = scene.camera.evaluated_get(graph)
            if camera.data.type not in {'PERSP', 'ORTHO'}:
                raise ValueError('Only perspective and orthographic cameras are supported')
            members = [o for o in scene.objects if root in lineage(o)]
            available = available_meshes(scene)
            meshes = [o for o in members if o in available
                      and not EXCLUDE.search(part_names(o, root))]
            if args.mode == 'head':
                meshes = [o for o in meshes if HEAD.search(o.name) or HEAD.search(o.data.name)]
            points = []
            for obj in meshes:
                evaluated = obj.evaluated_get(graph)
                mesh = evaluated.to_mesh()
                try:
                    # Loose helper vertices do not define a genuine surface.
                    indices = {i for polygon in mesh.polygons for i in polygon.vertices}
                    points.extend(tuple(world_to_camera_view(scene, camera,
                                  evaluated.matrix_world @ mesh.vertices[i].co)) for i in indices)
                finally:
                    evaluated.to_mesh_clear()
            row = {'frame': frame, 'camera': scene.camera.name,
                   'meshes': [o.name for o in meshes], 'surface_vertices': len(points)}
            if not points:
                row.update(status='inconclusive', violations=['no_selected_surface'],
                           head_bone_diagnostics=[])
                if args.mode == 'head':
                    for arm in members:
                        if arm.type != 'ARMATURE': continue
                        ev = arm.evaluated_get(graph)
                        for bone in ev.pose.bones:
                            if HEAD.search(bone.name):
                                row['head_bone_diagnostics'].append({'bone': bone.name,
                                    'uv_depth': list(world_to_camera_view(scene, camera,
                                                        ev.matrix_world @ bone.head))})
                previous = None
            else:
                row.update(bounds_metrics(points, args.margin, args.min_bbox, safe))
                row['behind_camera_points'] = sum(p[2] <= 0 for p in points)
                row['near_plane_points'] = sum(0 < p[2] < camera.data.clip_start for p in points)
                row['far_plane_points'] = sum(p[2] > camera.data.clip_end for p in points)
                for key in ('behind_camera_points', 'near_plane_points', 'far_plane_points'):
                    if row[key]: row['violations'].append(key)
                center = row.get('center_uv')
                if center:
                    if first is None: first = center
                    row['drift_from_first_uv'] = math.dist(first, center)
                    row['frame_drift_uv'] = math.dist(previous, center) if previous else None
                    if previous and row['frame_drift_uv'] > args.max_drift:
                        row['violations'].append('frame_drift_exceeds_threshold')
                previous = center
                row['status'] = 'violation' if row['violations'] else 'pass'
            report['frames'].append(row)
    finally:
        scene.frame_set(old_frame, subframe=old_sub)
    report['status'] = ('violation' if any(f['status']=='violation' for f in report['frames'])
                        else 'inconclusive' if any(f['status']=='inconclusive' for f in report['frames'])
                        else 'pass')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--frames', required=True, help='Inclusive integer range a-b')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--margin', type=float, default=.03)
    parser.add_argument('--mode', choices=['head', 'body'], default='head')
    parser.add_argument('--tiktok', action='store_true')
    parser.add_argument('--min-bbox', type=float, default=.0001, help='Minimum clipped bbox area in UV')
    parser.add_argument('--max-drift', type=float, default=.1, help='Maximum consecutive center drift in UV')
    args = parser.parse_args(argv)
    try:
        match = re.fullmatch(r'(-?\d+)-(-?\d+)', args.frames)
        if not match: raise ValueError('--frames must be a-b')
        args.start, args.end = map(int, match.groups())
        if args.end < args.start: raise ValueError('Reversed frame range')
        if not 0 <= args.margin < .5: raise ValueError('Margin must be in [0, .5)')
        if not 0 <= args.min_bbox <= 1: raise ValueError('Invalid minimum bbox area')
        if not math.isfinite(args.max_drift) or args.max_drift < 0: raise ValueError('Invalid drift threshold')
        report = audit(bpy.context.scene, args)
        code = 0 if report['status'] == 'pass' else 1
    except Exception as exc:
        report, code = {'status': 'error', 'error': str(exc), 'limitations': LIMITATIONS}, 2
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.json:
        try: args.json.write_text(payload+'\n', encoding='utf-8')
        except OSError as exc:
            print(f'camera_audit: cannot write JSON: {exc}', file=sys.stderr)
            return 2
    print(payload)
    return code


if __name__ == '__main__':
    # Blender does not reliably propagate SystemExit from -P; background CLI only.
    import os
    code = main(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    sys.stdout.flush()
    sys.stderr.flush()
    if bpy.app.background: os._exit(code)
    raise SystemExit(code)
