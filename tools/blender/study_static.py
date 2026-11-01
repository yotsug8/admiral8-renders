"""Freeze hero rigs in a prepared scene for repeatable studies; save a new file.

Keeps the selected frame's root transform and pose. Does not freeze arbitrary
props, modifiers, cameras or the whole scene. Game resources remain external.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contact_metrics import resolve
from contact_reaction import _action
from joint_skin import stabilize_crouch_skins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor', action='append', required=True)
    parser.add_argument('--frame', type=int, default=0)
    parser.add_argument('--end', type=int, default=100)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--stabilize-crouch', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out = args.out.resolve()
    if args.end < 1 or args.out.exists() or args.out.suffix != '.blend':
        raise ValueError('Require a new .blend file and positive end frame')
    if len(set(args.actor)) != len(args.actor):
        raise ValueError('Duplicate actors')
    sc = bpy.context.scene
    sc.frame_set(args.frame)
    actors = {}
    for who in args.actor:
        root, arm, members = resolve(who, list(sc.objects))
        if root == arm or any(not c.mute and c.influence for c in root.constraints):
            raise ValueError('Freeze needs an unconstrained independent actor root')
        actors[who] = dict(root=root, arm=arm)
        bones = list(arm.pose.bones)
        basis = {b.name: b.matrix_basis.copy() for b in bones}
        root_matrix = root.matrix_world.copy()
        action = _action(arm, bones, [dict(frame=f, basis=basis) for f in (0, args.end)], 'static_'+who, sc)
        arm.animation_data_clear()
        track = arm.animation_data_create().nla_tracks.new()
        track.name = 'static_'+who
        strip = track.strips.new(action.name, 0, action)
        strip.action_slot = action.slots[0]
        strip.action_frame_start, strip.action_frame_end = 0, args.end
        strip.frame_start, strip.frame_end = 0, args.end
        strip.blend_type, strip.extrapolation = 'REPLACE', 'HOLD'
        strip.influence = 1.
        root.animation_data_clear()
        root.matrix_world = root_matrix
        for obj in members:
            if obj.type == 'MESH' and obj.data.shape_keys:
                keys = obj.data.shape_keys
                values = {k.name: k.value for k in keys.key_blocks}
                keys.animation_data_clear()
                for name, value in values.items():
                    keys.key_blocks[name].value = value
    sc.frame_start, sc.frame_end = 0, args.end
    sc.render.fps, sc.render.fps_base = 30, 1.
    sc.frame_set(0)
    skin = []
    if args.stabilize_crouch:
        data = dict(fps=30, frames=args.end+1, actors={who: {} for who in actors},
                    crouches=[dict(who=who, at=0) for who in actors])
        skin = stabilize_crouch_skins(data, actors, sc, 30)
    expected = {who: {b.name: (a['arm'].matrix_world @ b.matrix).copy() for b in a['arm'].pose.bones}
                for who, a in actors.items()}
    error = 0.
    for frame in range(args.end+1):
        sc.frame_set(frame)
        for who, actor in actors.items():
            for bone in actor['arm'].pose.bones:
                matrix = actor['arm'].matrix_world @ bone.matrix
                error = max(error, max(abs(matrix[r][c]-expected[who][bone.name][r][c])
                                       for r in range(4) for c in range(4)))
    if error > 1e-5:
        raise ValueError(f'Frozen rig changes: {error}')
    sc.frame_set(0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out))
    args.out.with_suffix('.json').write_text(json.dumps(dict(actors=args.actor, frames=args.end+1,
        max_bone_matrix_drift=error, skin=skin,
        limits='Prepared rigs required; fixed pose is not a surface or balance check.'), indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
