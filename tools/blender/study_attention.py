"""Apply an existing neck/head look before a prepared reach; preserve the body.

This is directional head attention, not an optical eye-target solve. Run with
Blender -b point_A.blend ... -P study_attention.py -- --out NEW.blend.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contact_metrics import resolve
from look_motion import apply_looks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--yaw', type=float, default=8.)
    parser.add_argument('--pitch', type=float, default=-4.)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out = args.out.resolve()
    if args.out.exists():
        raise ValueError('Preserve existing scenes: choose a new output')
    sc = bpy.context.scene
    root, arm, members = resolve('pudge', list(sc.objects))
    head = arm.pose.bones['head']
    neck = next((b for b in head.parent_recursive if b.name.lower().startswith('neck')), head)
    moving = {neck.name, *[b.name for b in neck.children_recursive]}
    protected = [b.name for b in arm.pose.bones if b.name not in moving]
    reference = []
    for i in range(337):
        frame = i/4
        sc.frame_set(int(frame), subframe=frame % 1)
        reference.append({n: (arm.matrix_world @ arm.pose.bones[n].matrix).copy() for n in protected})
    ad = arm.animation_data
    source = ad.action
    if source is None:
        raise ValueError('Prepared reach must have an active baked action')
    slot = ad.action_slot
    ad.action = None
    track = ad.nla_tracks.new()
    track.name = 'study_reach_base'
    strip = track.strips.new('study_reach_base', 0, source)
    strip.action_slot = slot
    strip.blend_type = 'REPLACE'
    strip.extrapolation = 'HOLD'
    strip.influence = 1.
    event = dict(who='pudge', start=.15, end=2.55, yaw_deg=args.yaw, pitch_deg=args.pitch,
                 attack=.4, release=.5, eye_lead=0.)
    report = apply_looks(dict(frames=85, fps=30, looks=[event]),
                         {'pudge': dict(arm=arm, root=root)}, sc, 30)
    error = 0.
    for i, expected in enumerate(reference):
        frame = i/4
        sc.frame_set(int(frame), subframe=frame % 1)
        for n in protected:
            matrix = arm.matrix_world @ arm.pose.bones[n].matrix
            error = max(error, max(abs(matrix[r][c]-expected[n][r][c])
                                   for r in range(4) for c in range(4)))
    if error > 1e-5:
        raise ValueError(f'Body changed after attention overlay: {error}')
    sc.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out))
    result = dict(event=event, protected_samples=337, protected_matrix_error=error,
                  look_report=report,
                  limits='Head/neck only. Eye direction, skin deformation and full visual quality require separate checks.')
    args.out.with_suffix('.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
