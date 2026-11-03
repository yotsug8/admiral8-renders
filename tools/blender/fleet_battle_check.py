"""CPU continuity checks for the fleet. Not an artistic or collision certificate."""
import hashlib
import json
import math
import os
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / os.environ.get('FLEET_OUTPUT', '_game/skits/fleet_battle/v2')


def main():
    scene_path = Path(os.environ.get('FLEET_CHECK_SCENE', str(OUT / 'scene.blend')))
    bpy.ops.wm.open_mainfile(filepath=str(scene_path), use_scripts=False)
    sc = bpy.context.scene
    meta = json.loads((OUT / 'staging.json').read_text())
    roots = [bpy.data.objects[a['root']] for a in meta['actors']]
    giant_root = bpy.data.objects[meta['giant']['root']]
    previous_giant = None
    support_steps = []
    head=next(o for o in sc.objects if o.name.startswith('Giant_') and o.name.endswith('.head'))
    body=next(o for o in sc.objects if o.name.startswith('Giant_') and o.name.endswith('.upper_body'))
    from mathutils.kdtree import KDTree
    tree=KDTree(len(body.data.vertices));matrix=head.matrix_world.inverted()@body.matrix_world
    for vertex in body.data.vertices:tree.insert(matrix@vertex.co,vertex.index)
    tree.balance()
    seam_pairs=[(v.index,tree.find(v.co)[1]) for v in head.data.vertices if tree.find(v.co)[2]<1e-5]
    if len(seam_pairs)<3:raise RuntimeError('Neck junction missing; cannot validate seam')
    neck_gaps=[]
    previous = {}
    jumps = []
    failures = []
    cleaver=next(o for o in sc.objects if o.type=='MESH' and o.name.startswith('Giant_') and 'leftweapon_model' in o.name)
    weapon_floor=[]
    giant_meshes=[o for o in sc.objects if o.type=='MESH' and o.name.startswith(('Giant_','Dropped_')) and 'hitbox' not in o.name]
    fall_floor=[]
    for frame in range(meta['count']):
        sc.frame_set(frame)
        deps=bpy.context.evaluated_depsgraph_get()
        he=head.evaluated_get(deps);be=body.evaluated_get(deps);hm=he.to_mesh();bm=be.to_mesh()
        gap=max((he.matrix_world@hm.vertices[i].co-be.matrix_world@bm.vertices[j].co).length for i,j in seam_pairs)
        he.to_mesh_clear();be.to_mesh_clear();neck_gaps.append(dict(frame=frame,gap=gap))
        if gap>1e-4:failures.append(dict(frame=frame,issue='open neck junction',gap=gap))
        position = giant_root.matrix_world.translation.copy()
        if previous_giant is not None and frame >= 429:
            support_steps.append(dict(frame=frame, distance=(position-previous_giant).length))
            if support_steps[-1]['distance'] > .35:
                failures.append(dict(**support_steps[-1], issue='giant placement support jumps'))
        previous_giant = position
        if 290<=frame<=353:
            ev=cleaver.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh()
            lowest=min((ev.matrix_world@v.co for v in mesh.vertices),key=lambda v:v.z);ev.to_mesh_clear()
            weapon_floor.append(dict(frame=frame,point=list(lowest)))
            if lowest.z<-.04:failures.append(dict(frame=frame,issue='cleaver below ground',point=list(lowest)))
        if frame>=429:
            deps=bpy.context.evaluated_depsgraph_get()
            for obj in giant_meshes:
                if obj.hide_render:continue
                ev=obj.evaluated_get(deps);mesh=ev.to_mesh()
                lowest=min((ev.matrix_world@v.co for v in mesh.vertices),key=lambda v:v.z);ev.to_mesh_clear()
                sample=dict(frame=frame,object=obj.name,point=list(lowest));fall_floor.append(sample)
                if lowest.z<-.05:failures.append(dict(**sample,issue='fallen giant below ground'))
        for root in roots:
            position = root.matrix_world.translation.copy()
            rotation = root.matrix_world.to_quaternion()
            if not all(math.isfinite(x) for x in (*position, *rotation)):
                failures.append(dict(frame=frame, actor=root.name, issue='nonfinite transform'))
            if root.name in previous:
                p, q = previous[root.name]
                angle = math.degrees(q.rotation_difference(rotation).angle)
                angle = min(angle, 360-angle)
                distance = (position-p).length
                jumps.append(dict(frame=frame, actor=root.name, angle_deg=angle, distance=distance))
                if angle > 30 or distance > 1.2:
                    failures.append(jumps[-1])
            previous[root.name] = (position, rotation)
    report = dict(
        scene_sha256=hashlib.sha256(scene_path.read_bytes()).hexdigest(),
        checked_frames=meta['count'], actors=len(roots),
        max_angular_step=max(jumps,key=lambda x:x['angle_deg']),
        max_position_step=max(jumps,key=lambda x:x['distance']),
        failures=failures, passed=not failures,
        lowest_cleaver=min(weapon_floor,key=lambda x:x['point'][2]),
        lowest_fall_surface=min(fall_floor,key=lambda x:x['point'][2]),
        max_giant_support_step=max(support_steps,key=lambda x:x['distance']),
        max_neck_gap=max(neck_gaps,key=lambda x:x['gap']),
        scope='Placement continuity, split neck seam, cleaver/ground during counterattack and evaluated giant meshes/ground during fall. Does not certify self-intersections, actor contacts, framing, sound or acting.',
    )
    destination=Path(os.environ.get('FLEET_CHECK_REPORT',str(OUT/'continuity.json')))
    destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    if failures:
        raise RuntimeError('Placement continuity failed')


if __name__ == '__main__':
    main()
