"""Bounded CPU audit of an assembled scene; never renders or saves a blend.

blender -b scene.blend -P tools/blender/shot_continuity.py --
  --storyboard skits/story.json --expect search=actor --expect black=
  --json report.json

Every shot kind needs --expect kind=comma,separated,actors (or a shot's
``actors`` list). Expectations mean some projected surface, not whole-body fit.
Times use half-open intervals and frame zero unless --frame-origin is supplied.
Exit 0: no threshold flags; 1: flags/inconclusive; 2: invalid input.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import bpy
from mathutils import Vector, Quaternion

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_audit as surface


def scenery_probe(scene, camera, graph, roots):
    """Nine bounded first-hit rays; geometry evidence, never pixel/opacity proof."""
    corners = camera.data.view_frame(scene=scene)
    xmin, xmax = min(p.x for p in corners), max(p.x for p in corners)
    ymin, ymax = min(p.y for p in corners), max(p.y for p in corners)
    rows = []
    available = surface.available_meshes(scene)
    for u in (.15, .5, .85):
        for v in (.25, .5, .75):
            local = Vector((xmin+(xmax-xmin)*u, ymin+(ymax-ymin)*v, corners[0].z))
            direction = camera.matrix_world.to_quaternion() @ (local.normalized() if camera.data.type == 'PERSP' else Vector((0, 0, -1)))
            origin = camera.matrix_world.translation.copy() if camera.data.type == 'PERSP' else camera.matrix_world @ Vector((local.x, local.y, 0))
            # Clip distances are measured along local camera Z, not along the ray.
            cosine = abs((camera.matrix_world.to_quaternion().inverted() @ direction).z)
            origin += direction * camera.data.clip_start / cosine
            remaining = (camera.data.clip_end-camera.data.clip_start)/cosine
            result = dict(uv=[u, v], kind='miss')
            for _ in range(32):
                hit, point, normal, face, obj, matrix = scene.ray_cast(graph, origin, direction, distance=remaining)
                if not hit: break
                obj = obj.original
                if obj in available:
                    actor = next((a for a, root in roots.items() if root in surface.lineage(obj)), None)
                    result.update(kind='actor' if actor else 'scenery', object=obj.name, actor=actor)
                    break
                advance = (point-origin).length + .001
                remaining -= advance
                if remaining <= 0: break
                origin = point + direction*.001
            else:
                result['kind'] = 'inconclusive_skip_budget'
            rows.append(result)
    return rows


def cut_directions(frames, shots, epsilon=.1):
    """Compare world travel in each camera basis, not tracking-cancelled UV drift."""
    by_frame = {r['frame']: r for r in frames}
    results = []
    for left, right in zip(shots, shots[1:]):
        row = dict(before_frame=left['end'], after_frame=right['start'], actors={})
        for actor in sorted(set(left['actors']) & set(right['actors'])):
            directions = []
            for shot, start, end in ((left, max(left['start'], left['end']-3), left['end']),
                                     (right, right['start'], min(right['end'], right['start']+3))):
                a, b = by_frame[start], by_frame[end]
                move = Vector(b['actors'][actor]['root']['position'])-Vector(a['actors'][actor]['root']['position'])
                horizontal = (Quaternion(by_frame[shot['end'] if shot is left else shot['start']]['camera']['quaternion']).inverted() @ move).x / move.length if move.length > 1e-6 else None
                directions.append(horizontal)
            x, y = directions
            row['actors'][actor] = dict(horizontal_travel=directions,
                reversed=x is not None and y is not None and abs(x)>epsilon and abs(y)>epsilon and x*y<0)
        results.append(row)
    return results


def state(matrix):
    loc, rot, scale = matrix.decompose()
    return dict(position=list(loc), quaternion=list(rot), scale=list(scale))


def delta(a, b):
    from mathutils import Quaternion
    angle = math.degrees(Quaternion(a['quaternion']).rotation_difference(
        Quaternion(b['quaternion'])).angle)
    return dict(distance=math.dist(a['position'], b['position']),
                angle_deg=min(angle, 360-angle),
                scale_delta=max(abs(x-y) for x, y in zip(a['scale'], b['scale'])))


def run(args):
    scene = bpy.context.scene
    spec = json.loads(args.storyboard.read_text(encoding='utf-8'))
    fps = scene.render.fps / scene.render.fps_base
    if not math.isclose(float(spec['fps']), fps):
        raise ValueError('Storyboard and scene fps differ')
    expectations = {}
    for item in args.expect:
        kind, sep, actors = item.partition('=')
        if not sep: raise ValueError('--expect needs kind=actor,actor')
        expectations[kind] = [v.strip() for v in actors.split(',') if v.strip()]
    shots = []
    last = None
    for i, shot in enumerate(spec['shots']):
        start = args.frame_origin + math.ceil(float(shot['start'])*fps-1e-7)
        end = args.frame_origin + math.ceil(float(shot['end'])*fps-1e-7)-1
        actors = expectations.get(shot['kind'], shot.get('actors'))
        if actors is None or not isinstance(actors, list):
            raise ValueError('Missing actor expectation for '+shot['kind'])
        if end < start or (last is not None and start != last+1):
            raise ValueError('Shots must be nonempty, ordered and contiguous')
        shots.append(dict(index=i, kind=shot['kind'], start=start, end=end, actors=actors))
        last = end
    if not shots: raise ValueError('Empty storyboard')
    count = shots[-1]['end']-shots[0]['start']+1
    if count > args.max_frames: raise ValueError('Frame budget exceeded')
    if shots[0]['start'] < scene.frame_start or shots[-1]['end'] > scene.frame_end:
        raise ValueError('Storyboard outside scene frame range')
    labels = sorted(set(spec.get('cast', [])) | {a for s in shots for a in s['actors']})
    roots = {a: surface.actor_root(scene, a) for a in labels}
    weapon_pattern = re.compile(args.weapon_regex, re.I)
    weapons = {a: [o for o in scene.objects if o.type == 'MESH'
                   and roots[a] in surface.lineage(o)
                   and weapon_pattern.search(o.name+' '+o.data.name)
                   and not surface.EXCLUDE.search(surface.part_names(o, roots[a]))]
               for a in labels}
    report = dict(scene=Path(bpy.data.filepath).name, storyboard=args.storyboard.name,
                  fps=fps, scene_frame_range=[scene.frame_start, scene.frame_end],
                  audited_frame_range=[shots[0]['start'], shots[-1]['end']],
                  frame_origin=args.frame_origin,
                  scene_file_stat=dict(size=Path(bpy.data.filepath).stat().st_size,
                                       mtime_ns=Path(bpy.data.filepath).stat().st_mtime_ns),
                  thresholds=vars(args).copy(),
                  shots=shots, frames=[], cuts=[], flags=[],
                  weapons={a: [o.name for o in obs] for a, obs in weapons.items()},
                  limitations=surface.LIMITATIONS + [
                      'No rendering, pixel black-frame or audio verification.',
                      'Nine scenery rays only at surface samples; alpha, materials, lighting and unsampled holes remain unknown.',
                      'Expected actors are explicit input, not inferred from action prose.',
                      'Integer frames only; cuts excluded from all within-shot deltas.',
                      'Surface projection sampled at shot endpoints and --surface-step intervals; unsampled visibility is unknown.',
                      'Threshold flags are candidates, not proof of perceptual discontinuity.',
                      'Weapon naming is heuristic; missing selection is inconclusive.',
                      'Weapon surface centroid/bounds do not establish grip or collisions.',
                      'Root object transforms do not measure internal gait or skin deformation.',
                      'Projection margin and clipping diagnostics are retained, not full-body requirements.',
                  ])
    report['thresholds'] = {k: str(v) if isinstance(v, Path) else v
                            for k, v in report['thresholds'].items()}
    old_frame, old_sub = scene.frame_current, scene.frame_subframe
    try:
        # Reuse the existing surface selector and evaluated-vertex projection.
        # Reset its drift history at every shot, including same-camera cuts.
        projection = {}
        for shot in shots:
            print('CONTINUITY_PROJECTION', shot['kind'], flush=True)
            samples = sorted(set(range(shot['start'], shot['end']+1, args.surface_step)) | {shot['end']})
            for actor in shot['actors']:
                for sample in samples:
                    result = surface.audit(scene, SimpleNamespace(
                        actor=actor, mode='body', margin=0., min_bbox=args.min_bbox,
                        max_drift=args.max_uv_step, tiktok=False,
                        start=sample, end=sample))
                    projection[(sample, actor)] = result['frames'][0]
        previous = None
        for shot in shots:
            samples = set(range(shot['start'], shot['end']+1, args.scenery_step)) | {shot['end']}
            for frame in range(shot['start'], shot['end']+1):
                scene.frame_set(frame)
                graph = bpy.context.evaluated_depsgraph_get()
                cam = scene.camera.evaluated_get(graph)
                if cam.data.type not in {'PERSP', 'ORTHO'}:
                    raise ValueError('Only perspective and orthographic cameras are supported')
                row = dict(frame=frame, time=(frame-args.frame_origin)/fps,
                           shot=shot['index'], kind=shot['kind'], expected=shot['actors'],
                           camera=dict(name=cam.name, type=cam.data.type,
                                       lens=cam.data.lens, ortho_scale=cam.data.ortho_scale,
                                       **state(cam.matrix_world)), actors={})
                if frame in samples:
                    row['scenery_rays'] = scenery_probe(scene, cam, graph, roots)
                    if shot['kind'] != 'black' and all(r['kind']=='miss' for r in row['scenery_rays']):
                        report['flags'].append(dict(frame=frame, kind='empty_background_candidate'))
                    if shot['kind'] == 'black':
                        # An empty actor expectation never proves a black output.
                        report['flags'].append(dict(frame=frame, kind='black_output_unverified',
                            geometry_hits=sum(r['kind'] in {'actor','scenery'} for r in row['scenery_rays'])))
                for actor, root in roots.items():
                    entry = dict(root=state(root.evaluated_get(graph).matrix_world), weapons={})
                    for obj in weapons[actor]:
                        ev = obj.evaluated_get(graph)
                        mesh = ev.to_mesh()
                        try:
                            indices = {i for p in mesh.polygons for i in p.vertices}
                            points = [ev.matrix_world @ mesh.vertices[i].co for i in indices]
                            entry['weapons'][obj.name] = dict(
                                transform=state(ev.matrix_world), hidden_render=obj.hide_render,
                                centroid=[sum(p[j] for p in points)/len(points) for j in range(3)] if points else None,
                                bounds=[[min(p[j] for p in points) for j in range(3)],
                                        [max(p[j] for p in points) for j in range(3)]] if points else None)
                        finally: ev.to_mesh_clear()
                    if (frame, actor) in projection:
                        p = projection[(frame, actor)]
                        entry['projection'] = p
                        absent = (not p['surface_vertices'] or p.get('wholly_offscreen')
                                  or sum(p.get(k, 0) for k in ('behind_camera_points', 'near_plane_points', 'far_plane_points')) == p['surface_vertices']
                                  or p.get('clipped_bbox_area', 0) < args.min_bbox)
                        if absent: report['flags'].append(dict(frame=frame, actor=actor, kind='expected_projection_missing'))
                        if previous and previous['shot'] == shot['index']:
                            prior = previous['actors'][actor].get('projection', {})
                            if prior.get('center_uv') and p.get('center_uv'):
                                p['consecutive_center_drift_uv'] = math.dist(prior['center_uv'], p['center_uv'])
                                if p['consecutive_center_drift_uv'] > args.max_uv_step:
                                    report['flags'].append(dict(frame=frame, actor=actor, kind='projection_step'))
                    row['actors'][actor] = entry
                if previous:
                    changes = dict(camera=delta(previous['camera'], row['camera']), actors={})
                    changes['camera']['lens_delta'] = abs(previous['camera']['lens']-cam.data.lens)
                    changes['camera']['ortho_scale_delta'] = abs(previous['camera']['ortho_scale']-cam.data.ortho_scale)
                    changes['camera']['camera_changed'] = previous['camera']['name'] != cam.name
                    for actor, entry in row['actors'].items():
                        prev = previous['actors'][actor]
                        d = dict(root=delta(prev['root'], entry['root']), weapons={})
                        for name, w in entry['weapons'].items():
                            pw = prev['weapons'][name]
                            d['weapons'][name] = dict(
                                centroid_distance=math.dist(pw['centroid'], w['centroid']) if pw['centroid'] and w['centroid'] else None,
                                hidden_changed=pw['hidden_render'] != w['hidden_render'],
                                **delta(pw['transform'], w['transform']))
                        changes['actors'][actor] = d
                    if previous['shot'] != row['shot']:
                        report['cuts'].append(dict(before_frame=frame-1, after_frame=frame,
                                                   before=previous['camera'], after=row['camera'], deltas=changes))
                    else:
                        row['within_shot_deltas'] = changes
                        cd = changes['camera']
                        if (cd['distance'] > args.max_camera_step or cd['angle_deg'] > args.max_angle
                                or cd['lens_delta'] > args.max_lens_step or cd['camera_changed']
                                or cd['ortho_scale_delta'] > args.max_camera_step):
                            report['flags'].append(dict(frame=frame, kind='camera_step'))
                        for actor, d in changes['actors'].items():
                            if actor not in shot['actors']: continue
                            if d['root']['distance'] > args.max_root_step or d['root']['angle_deg'] > args.max_angle or d['root']['scale_delta'] > .01:
                                report['flags'].append(dict(frame=frame, actor=actor, kind='root_step'))
                            for name, wd in d['weapons'].items():
                                if (wd['centroid_distance'] is None or wd['centroid_distance'] > args.max_weapon_step
                                        or wd['angle_deg'] > args.max_angle or wd['hidden_changed'] or wd['scale_delta'] > .01):
                                    report['flags'].append(dict(frame=frame, actor=actor, weapon=name, kind='weapon_step'))
                report['frames'].append(row)
                previous = row
    finally:
        scene.frame_set(old_frame, subframe=old_sub)
    report['inconclusive_weapons'] = [a for a in labels if not weapons[a]]
    report['cut_directions'] = cut_directions(report['frames'], shots)
    for cut in report['cut_directions']:
        for actor, direction in cut['actors'].items():
            if direction['reversed']:
                report['flags'].append(dict(frame=cut['after_frame'], actor=actor, kind='cut_direction_reversal'))
    report['status'] = 'flagged' if report['flags'] else 'inconclusive' if report['inconclusive_weapons'] else 'pass'
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--storyboard', type=Path, required=True)
    p.add_argument('--json', type=Path, required=True)
    p.add_argument('--expect', action='append', default=[])
    p.add_argument('--frame-origin', type=int, default=0)
    p.add_argument('--max-frames', type=int, default=600)
    p.add_argument('--surface-step', type=int, default=30, help='Surface sample interval; endpoints always included')
    p.add_argument('--scenery-step', type=int, default=12, help='Nine CPU rays per sample; endpoints always included')
    p.add_argument('--weapon-regex', default=r'weapon|sword|cutlass|crossbow')
    for name, value in [('min-bbox', .0001), ('max-uv-step', .1),
                        ('max-camera-step', .5), ('max-root-step', .25),
                        ('max-weapon-step', .5), ('max-angle', 20.), ('max-lens-step', 5.)]:
        p.add_argument('--'+name, type=float, default=value)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    try:
        if args.surface_step < 1: raise ValueError('surface-step must be positive')
        if args.scenery_step < 1: raise ValueError('scenery-step must be positive')
        for key, val in vars(args).items():
            if isinstance(val, float) and (not math.isfinite(val) or val < 0):
                raise ValueError('Invalid threshold '+key)
        report = run(args)
        code = 0 if report['status'] == 'pass' else 1
    except Exception as exc:
        report, code = dict(status='error', error=str(exc)), 2
    args.json.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('CONTINUITY_QA', json.dumps(dict(status=report['status'], frames=len(report.get('frames', [])),
          flags=len(report.get('flags', [])), error=report.get('error'))), flush=True)
    return code


if __name__ == '__main__':
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if bpy.app.background: os._exit(exit_code)
    raise SystemExit(exit_code)
