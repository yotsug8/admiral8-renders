"""Finite coverage audit of the saved leap scene; no aesthetic pass is inferred."""
import bpy
import json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/doomsday'
sc=bpy.context.scene
roots={n:bpy.data.objects[n+'_root'] for n in ('sven','rubick')}
arms={n:next(o for o in root.children if o.type=='ARMATURE') for n,root in roots.items()}
meshes={n:[o for o in root.children_recursive if o.type=='MESH'] for n,root in roots.items()}
sword=next(o for o in meshes['sven'] if 'sword' in o.name.lower())
report={'sample_frames':240,'wide_frames':[],'contact_frames':[],'support_frames':[],
        'limits':'Finite frame samples. No general cloth, skin, debris or continuous collision certificate.'}
for f in range(240):
    sc.frame_set(f);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
    if 45<=f<177:
        points=[]
        for name in meshes:
            for ob in meshes[name]:
                ev=ob.evaluated_get(dg)
                points.extend(world_to_camera_view(sc,sc.camera,ev.matrix_world@v.co) for v in ev.data.vertices)
        report['wide_frames'].append({'frame':f,'min_x':min(p.x for p in points),
            'max_x':max(p.x for p in points),'min_y':min(p.y for p in points),'max_y':max(p.y for p in points)})
    if f<69:
        feet={}
        for side in ('L','R'):
            name='ankle_'+side
            feet[side]=list(arms['sven'].matrix_world@arms['sven'].pose.bones[name].head)
        report['support_frames'].append({'frame':f,'ankles':feet})
    if f>=120:
        tree=BVHTree.FromObject(sword,dg)
        ev=sword.evaluated_get(dg);inv=ev.matrix_world.inverted()
        wrist=arms['rubick'].pose.bones['wrist_R']
        distances=[]
        for bone in [wrist,*wrist.children_recursive]:
            world=arms['rubick'].matrix_world@bone.head
            near,_,_,_=tree.find_nearest(inv@world)
            if near is not None:distances.append((ev.matrix_world@near-world).length)
        report['contact_frames'].append({'frame':f,'nearest_hand_bone_to_blade_m':min(distances)})
wide=report['wide_frames']
report['wide_extents']={k:(min if k.startswith('min') else max)(v[k] for v in wide) for k in ('min_x','max_x','min_y','max_y')}
report['max_contact_gap_m']=max(v['nearest_hand_bone_to_blade_m'] for v in report['contact_frames'])
(OUT/'motion_qa.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if not k.endswith('_frames')},indent=2))
