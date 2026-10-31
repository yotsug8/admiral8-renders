"""Experimental Hoodwink run grounding on a flat floor; writes a separate action library.

Load an actor cache in background Blender, then pass --metadata actors.json
--output grounded_run.blend. No source .blend is overwritten. This is authored
contact correction, not reconstruction of the Dota animation evaluator.
Only the 24-frame mouse_run_squirrel cycle is supported. Contact phases are
explicit scene-specific choices; other actors/terrain require separate work.
"""
from pathlib import Path
import argparse,json,math,sys
import bpy
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gait_metrics import select_surfaces
from contact_reaction import _action
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--metadata',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--step',type=float,default=.0625)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.metadata=args.metadata.resolve();args.output=args.output.resolve()
if not 1/64<=args.step<=.25:raise ValueError('Sample step must be between 1/64 and 1/4 frame')
if args.output.resolve()==Path(bpy.data.filepath).resolve():raise ValueError('Cannot overwrite source scene')
m=json.loads(args.metadata.read_text())['hoodwink'];sc=bpy.context.scene
if abs(sc.render.fps/sc.render.fps_base-30)>1e-8:raise ValueError('This source cache must use 30 fps')
if abs(sc.unit_settings.scale_length-1)>1e-8:raise ValueError('This measured setup requires metre units')
arm=bpy.data.objects[m['arm']];root=bpy.data.objects[m['root']]
arm.animation_data_clear();ad=arm.animation_data_create();native=bpy.data.actions['mouse_run_squirrel']
if tuple(native.frame_range)!=(0.,24.):raise ValueError('Unexpected source cycle')
ad.action=native;ad.action_slot=native.slots[0]
root.animation_data_clear();root.location=(0,0,0);root.rotation_euler=(0,0,0)
objects=[bpy.data.objects[n] for n in m['objs'] if bpy.data.objects[n].type=='MESH']
from mathutils import Matrix,Vector
# Explicit experimental floor correction; no claim of exact engine playback.
paw_sets={}
for n in ('hand_L','hand_R','ankle_L','ankle_R'):
 names={n}|{b.name for b in arm.data.bones[n].children_recursive}
 paw_sets[n]=select_surfaces(objects,names)
def mat(n):return arm.matrix_world@arm.pose.bones[n].matrix
def put(n,m):
 arm.pose.bones[n].matrix=arm.matrix_world.inverted()@m
 bpy.context.view_layer.update()
def rotate_about(n,p,q):put(n,Matrix.Translation(p)@q.to_matrix().to_4x4()@Matrix.Translation(-p)@mat(n))
def solve_paw(n,target):
 end=arm.pose.bones[n];low=end.parent.name;up=end.parent.parent.name
 h,k,a=(mat(b).translation for b in (up,low,n));l1=(k-h).length;l2=(a-k).length
 delta=target-h;d=delta.length
 if d<1e-7:return
 d=min(l1+l2-1e-5,max(abs(l1-l2)+1e-5,d));direction=delta.normalized();target=h+direction*d
 pole=k-h-direction*(k-h).dot(direction)
 if pole.length<1e-7:return
 x=(l1*l1-l2*l2+d*d)/(2*d);y=max(0,l1*l1-x*x)**.5;newk=h+direction*x+pole.normalized()*y
 original=mat(n).copy()
 rotate_about(up,h,(k-h).rotation_difference(newk-h))
 k=mat(low).translation;a=mat(n).translation
 rotate_about(low,k,(a-k).rotation_difference(target-k))
 original.translation=mat(n).translation;put(n,original)
anchors={}
for n,selections in paw_sets.items():
 landing=0 if n.startswith('hand') else 6
 sc.frame_set(landing);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();choices=[]
 for o,ids in selections:
  ev=o.evaluated_get(dg);me=ev.to_mesh()
  try:choices.extend((float((ev.matrix_world@me.vertices[i].co).z),o,i,(ev.matrix_world@me.vertices[i].co).copy()) for i in ids)
  finally:ev.to_mesh_clear()
 _,o,i,point=min(choices,key=lambda v:v[0]);anchors[n]=(o,i,point-root.matrix_world.translation)
def smooth(x):x=min(1,max(0,x));return x*x*(3-2*x)
def correct_floor(f):
 for n,selections in paw_sets.items():
  u=(f-(0 if n.startswith('hand') else 6))%12
  stance=u<4.;weight=smooth(u/.35)*smooth((4-u)/.35) if stance else 0.
  height=.005+(0 if stance else .12*math.sin(math.pi*(u-4)/8)**2)
  for attempt in range(3):
   dg=bpy.context.evaluated_depsgraph_get();lowest=1e9;witness=None
   anchor_obj,anchor_id,anchor=anchors[n]
   for o,ids in selections:
    ev=o.evaluated_get(dg);me=ev.to_mesh()
    try:
     lowest=min(lowest,min((ev.matrix_world@me.vertices[i].co).z for i in ids))
     if o==anchor_obj:witness=ev.matrix_world@me.vertices[anchor_id].co
    finally:ev.to_mesh_clear()
   desired=root.matrix_world.translation+anchor+Vector((0,10.31508565*u/30,0))
   delta=(desired-witness)*weight;delta.z=height-lowest
   if not stance:delta.z=max(0,delta.z)
   if delta.length<.0001:break
   solve_paw(n,mat(n).translation+delta)

bones=list(arm.pose.bones);samples=[];max_length_error=0.
chains=[(n,arm.pose.bones[n].parent.name) for n in paw_sets]
chains += [(p,arm.pose.bones[p].parent.name) for _,p in chains.copy()]
frames=np.unique(np.r_[np.arange(0,24,args.step),24.])
for f in frames:
 sc.frame_set(math.floor(f),subframe=float(f%1));bpy.context.view_layer.update()
 lengths={(a,b):(mat(a).translation-mat(b).translation).length for a,b in chains}
 correct_floor(float(f))
 max_length_error=max(max_length_error,max(abs((mat(a).translation-mat(b).translation).length-lengths[a,b]) for a,b in chains))
 samples.append(dict(frame=float(f),basis={b.name:b.matrix_basis.copy() for b in bones}))
 if abs(f%6)<1e-8:print('BAKE_SAMPLE',float(f),flush=True)
action=_action(arm,bones,samples,'hoodwink_grounded_run_candidate',sc)
action.use_fake_user=True
args.output.parent.mkdir(parents=True,exist_ok=True)
bpy.data.libraries.write(str(args.output),{action},fake_user=True)
report=dict(action=action.name,source_action=native.name,samples=len(samples),step=args.step,
 source_speed_mps=10.31508565,scene_rate_at_5_mps=5/10.31508565,
 max_segment_length_error_m=max_length_error,
 limits='Experimental flat-floor contact correction. Baked playback, transitions, clothing, weapon and final camera require independent verification.')
args.output.with_suffix('.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
