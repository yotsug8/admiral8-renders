"""Measure deformed foot clearance and held wrists in the current v2 blend.

The action area is flat at z=0. This does not certify skin intersections,
the hand surface grip, framing, or artistic quality.
"""
import json
import math
import sys
from pathlib import Path

import bpy

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/doomsday/v2'
if '--out' in sys.argv:OUT=Path(sys.argv[sys.argv.index('--out')+1]).resolve()
OUT.mkdir(parents=True,exist_ok=True)
scene=bpy.context.scene
arm=next(o for o in scene.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='axe_root')
meshes=[]
for ob in scene.objects:
    if ob.type!='MESH':continue
    parent=ob.parent;owned=False
    while parent:
        if parent==arm:owned=True
        parent=parent.parent
    if not owned:continue
    surface={i for poly in ob.data.polygons for i in poly.vertices}
    by_side={}
    for side in ('L','R'):
        names={b.name for b in [arm.pose.bones['ankle_'+side],*arm.pose.bones['ankle_'+side].children_recursive]}
        groups={g.index for g in ob.vertex_groups if g.name in names}
        by_side[side]=[v.index for v in ob.data.vertices if v.index in surface and sum(g.weight for g in v.groups if g.group in groups)>.5]
    if any(by_side.values()):meshes.append((ob,by_side))
if not meshes:raise ValueError('No weighted foot vertices found')

frames=[];fixed=None;max_error=0;max_position=0;max_angle=0
density=16 if '--subframes' in sys.argv else 1
for index in range((scene.frame_end-scene.frame_start)*density+1):
    frame=scene.frame_start+index/density
    scene.frame_set(math.floor(frame),subframe=frame%1);bpy.context.view_layer.update()
    feet={'L':[],'R':[]};dg=bpy.context.evaluated_depsgraph_get()
    for ob,indices in meshes:
        evaluated=ob.evaluated_get(dg)
        for side,ids in indices.items():feet[side].extend((evaluated.matrix_world@evaluated.data.vertices[i].co).z for i in ids)
    if not all(feet.values()):raise ValueError('Incomplete foot coverage')
    entry={'frame':frame,'foot_min_z':{s:min(v) for s,v in feet.items()}}
    if frame>=44:
        wrists={s:arm.matrix_world@arm.pose.bones['wrist_'+s].matrix for s in ('L','R')}
        if fixed is None:fixed={s:m.copy() for s,m in wrists.items()}
        error=max(abs(wrists[s][i][j]-fixed[s][i][j]) for s in wrists for i in range(4) for j in range(4))
        entry['held_wrist_matrix_error']=error;max_error=max(max_error,error)
        max_position=max(max_position,max((wrists[s].translation-fixed[s].translation).length for s in wrists))
        max_angle=max(max_angle,max(math.degrees(wrists[s].to_quaternion().rotation_difference(fixed[s].to_quaternion()).angle) for s in wrists))
    frames.append(entry)

minimum=min((entry['foot_min_z'][side],entry['frame'],side) for entry in frames for side in ('L','R'))
report={'frames':frames,'minimum_foot_z':minimum,'max_held_wrist_matrix_error':max_error,
        'max_held_wrist_position_error':max_position,'max_held_wrist_angle_deg':max_angle,'samples_per_frame':density,
        'covered_foot_vertices':{ob.name:{s:len(v) for s,v in ids.items()} for ob,ids in meshes},
        'limitations':'Flat-ground foot clearance and held bone matrices only; no artistic approval.'}
(OUT/('pose_qa_subframes.json' if density>1 else 'pose_qa.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print('FOOT_MIN',minimum,'HELD_WRIST_ERROR',max_error,'POSITION',max_position,'ANGLE_DEG',max_angle,flush=True)
for f in (0,19,26,39,43,44,50,60,66,90):
    print('POSE_CHECK',frames[f*density],flush=True)
if '--enforce' in sys.argv:
    if minimum[0]<-.001:raise ValueError('Sole penetrates flat ground')
    if any(abs(entry['foot_min_z'][side]-.003)>.006 for entry in frames if entry['frame']>=60 for side in ('L','R')):raise ValueError('Unsettled final support')
    if density==1 and max_error>1e-4:raise ValueError('Held wrist drifts at a baked frame')
    if max_position>.003 or max_angle>.25:raise ValueError('Held wrist drifts between samples')
