"""Sample the wrist region against explicitly selected disjoint body meshes.

Reuses contact_metrics ray parity. Closed-surface assumptions and sparse vertex
coverage apply: a pass is not proof of no intersections or correct skinning.
Run in background Blender with a prepared scene. No scene save or render.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contact_metrics import frame_metrics, resolve, wrist_bone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor', default='pudge')
    parser.add_argument('--own', action='append', required=True, help='Exact mesh name suffix')
    parser.add_argument('--target', action='append', required=True, help='Exact mesh name suffix')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--end', type=int, default=84)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root, arm, members = resolve(args.actor, list(bpy.context.scene.objects))

    def select(suffixes):
        selected = []
        for suffix in suffixes:
            hits = [o for o in members if o.type == 'MESH' and o.name.endswith(suffix)]
            if len(hits) != 1:
                raise ValueError(f'Ambiguous or absent surface {suffix}')
            selected.extend(hits)
        return selected

    own, targets = select(args.own), select(args.target)
    if set(own) & set(targets):
        raise ValueError('Tested surfaces must be disjoint')
    if args.end < 0:
        raise ValueError('Invalid end frame')
    args.radius, args.epsilon, args.max_depth = .45, .00001, .005
    wrist = wrist_bone(arm, None)
    rows = [frame_metrics(f, arm, wrist, own, targets,
                          bpy.context.scene.unit_settings.scale_length, args)
            for f in range(args.end+1)]
    deep = [r['frame'] for r in rows if r['vertices_deeper_than_threshold']]
    inconclusive = sum(r['inconclusive_vertices'] for r in rows)
    report = dict(status='deep_samples' if deep else 'no_deep_samples',
                  deep_frames=deep, uncertain_vertex_samples=inconclusive,
                  max_confirmed_depth_m=max(r['max_confirmed_depth_m'] for r in rows),
                  min_sampled_gap_m=min(r['min_surface_gap_m'] for r in rows),
                  radius_m=args.radius, threshold_m=args.max_depth,
                  own=args.own, targets=args.target, frames=rows,
                  limits='Wrist-region vertex samples only. Open surfaces may be inconclusive; no whole-arm/self-collision proof.')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'frames'}))
    if deep:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
