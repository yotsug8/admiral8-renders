"""Read-only rotation audit of the saved CMU excerpt; no bake or render."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

BONES = ('Hips', 'LowerBack', 'Spine', 'Spine1', 'Neck', 'Neck1', 'Head')
SCENE_SHA = 'dd59e466d8508890aec628fbbad00cf53f42e9fff5459b503db3e077c6eaa05f'


def matrix(m):
    return [list(row) for row in m]


def quat(m):
    q = m.to_quaternion().normalized()
    return [q.w, q.x, q.y, q.z]


def angle(a, b):
    # q and -q describe the same orientation. Normalize in Python doubles.
    an = math.sqrt(sum(x*x for x in a))
    bn = math.sqrt(sum(x*x for x in b))
    dot = min(1.0, abs(sum(x*y for x,y in zip(a,b))/(an*bn)))
    return math.degrees(2*math.atan2(math.sqrt(max(0, 1-dot*dot)), dot))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    before = hashlib.sha256(args.blend.read_bytes()).hexdigest()
    assert before == SCENE_SHA, 'Unexpected source scene'
    args.out.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    assert (scene.frame_start,scene.frame_end,scene.render.fps,scene.render.fps_base)==(1,180,60,1)
    rigs = [o for o in scene.objects if o.type == 'ARMATURE']
    assert len(rigs) == 1
    rig = rigs[0]
    assert all(n in rig.pose.bones for n in BONES)
    assert not rig.constraints and not rig.animation_data.drivers
    assert all(not b.constraints for b in rig.pose.bones)
    scene.frame_set(1)
    world = rig.matrix_world.copy()
    forward = Vector((0,0,0))
    for side in ('Left','Right'):
        forward += world @ rig.pose.bones[side+'ToeBase'].tail - world @ rig.pose.bones[side+'Foot'].head
    forward.z = 0
    forward.normalize()
    rest = {}
    for n in BONES:
        b = rig.data.bones[n]
        local = b.parent.matrix_local.inverted() @ b.matrix_local if b.parent else b.matrix_local
        rest[n] = dict(parent=b.parent.name if b.parent else None,
                       armature_matrix=matrix(b.matrix_local),
                       world_matrix=matrix(world @ b.matrix_local),
                       parent_relative_matrix=matrix(local),
                       rotation_mode=rig.pose.bones[n].rotation_mode)
    samples = []
    first = {}
    previous_heading = {n:0.0 for n in BONES}
    unwrapped = {n:0.0 for n in BONES}
    for frame in range(1,181):
        scene.frame_set(frame)
        assert rig.matrix_world == world, 'Object transform changed'
        entry = dict(frame=frame, amc_sample=720+frame, time_s=(frame-1)/60, bones={})
        for n in BONES:
            b = rig.pose.bones[n]
            wm = world @ b.matrix
            lm = b.parent.matrix.inverted() @ b.matrix if b.parent else b.matrix
            q = wm.to_quaternion().normalized()
            if frame == 1:
                first[n] = q.copy()
            delta = q @ first[n].inverted()
            direction = delta @ forward
            horizontal_norm = math.hypot(direction.x,direction.y)
            assert horizontal_norm > 0.1, 'Heading projection near vertical'
            heading = math.degrees(math.atan2(forward.x*direction.y-forward.y*direction.x,
                                             forward.x*direction.x+forward.y*direction.y))
            step = (heading-previous_heading[n]+180)%360-180
            unwrapped[n] += step
            previous_heading[n] = heading
            entry['bones'][n] = dict(world_quaternion_wxyz=quat(wm),
                                     local_quaternion_wxyz=quat(lm),
                                     basis_quaternion_wxyz=quat(b.matrix_basis),
                                     world_matrix=matrix(wm),
                                     local_matrix=matrix(lm),
                                     heading_from_first_deg=unwrapped[n],
                                     heading_horizontal_norm=horizontal_norm)
        samples.append(entry)
    stats = {}
    for n in BONES:
        stats[n] = {}
        for space in ('world','local','basis'):
            qs = [s['bones'][n][space+'_quaternion_wxyz'] for s in samples]
            steps = [angle(a,b) for a,b in zip(qs,qs[1:])]
            offsets = [angle(qs[0],q) for q in qs]
            worst = max(range(179),key=lambda j:steps[j])
            peak = max(range(180),key=lambda j:offsets[j])
            stats[n][space] = dict(max_step_deg=steps[worst],
                                   max_step_frames=[worst+1,worst+2],
                                   max_step_amc=[worst+721,worst+722],
                                   max_step_equivalent_deg_per_s=steps[worst]*60,
                                   max_from_first_deg=offsets[peak],
                                   max_from_first_frame=peak+1,
                                   final_from_first_deg=offsets[-1],
                                   raw_quaternion_sign_changes=sum(sum(x*y for x,y in zip(a,b))<0 for a,b in zip(qs,qs[1:])),
                                   top_steps=[dict(from_frame=j+1,to_frame=j+2,deg=steps[j]) for j in sorted(range(179),key=lambda j:steps[j],reverse=True)[:3]])
        headings = [s['bones'][n]['heading_from_first_deg'] for s in samples]
        stats[n]['heading'] = dict(min_deg=min(headings),max_deg=max(headings),
                                   min_frame=headings.index(min(headings))+1,
                                   max_frame=headings.index(max(headings))+1,
                                   final_deg=headings[-1],
                                   min_horizontal_projection=min(s['bones'][n]['heading_horizontal_norm'] for s in samples))
    exported = dict(source_blend_sha256=before,blender=bpy.app.version_string,
                    build=bpy.app.build_hash.decode(),fps=60,frames=180,
                    quaternion_order='w,x,y,z; raw signs retained',
                    local_definition='inverse(parent pose matrix) @ bone pose matrix; Hips local is armature space',
                    basis_definition='PoseBone.matrix_basis: rest-relative channel transform; separate from parent-relative local',
                    heading_definition='World delta from frame 1 rotates the fixed initial horizontal foot direction; projected angle around +Z, positive counterclockwise viewed from above. Not measured gaze.',
                    heading_reference_forward=list(forward),object_world_matrix=matrix(world),
                    rest=rest,samples=samples)
    (args.out/'rotations.json').write_text(json.dumps(exported,separators=(',',':')),encoding='utf-8')
    summary = dict(source_blend_sha256=before,frames=180,fps=60,bones=stats,
                   source_unchanged=hashlib.sha256(args.blend.read_bytes()).hexdigest()==before,
                   limits='Sampled 60 fps orientations only, not angular acceleration/subframe continuity, mesh deformation, or target-rig comparison. Maximum from first is not pairwise diameter.')
    assert summary['source_unchanged']
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    for n,s in stats.items():
        print(n,json.dumps({space:{k:s[space][k] for k in ('max_step_deg','max_step_frames','max_from_first_deg','max_from_first_frame','raw_quaternion_sign_changes')} for space in ('world','local','basis')}),json.dumps(s['heading']))


if __name__ == '__main__':
    main()
