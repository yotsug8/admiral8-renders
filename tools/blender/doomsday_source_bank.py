"""CPU-only bank of original film poses/cameras/faces, plus contact-entry diagnosis."""
import bpy,json,sys,math,hashlib,time
import numpy as np
from pathlib import Path
from mathutils import Matrix
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'_game/skits/doomsday/v12/full_scene';OUT.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'_game/skits/doomsday/v11/live_staging.blend';NATIVE=ROOT/'_game/skits/doomsday/v12/native_pressure/native_pressure.blend'
def arm_for(scene,name):return next(o for o in scene.objects if o.type=='ARMATURE' and o.parent and o.parent.name==name+'_root' and o.name.endswith(name+'.vmdl_c'))
def pose(arm,graph):
 ev=arm.evaluated_get(graph);return {b.name:ev.matrix_world@b.matrix for b in ev.pose.bones}
def qdist(a,b):return math.degrees(2*math.acos(min(1.,abs(a.to_quaternion().normalized().dot(b.to_quaternion().normalized())))))
def diff(a,b):return {'translation':(a.translation-b.translation).length,'rotation_deg':qdist(a,b)}
def rows(m):return [list(r) for r in m]
t0=time.time();bpy.ops.wm.open_mainfile(filepath=str(SOURCE));scene=bpy.context.scene
arms={a:arm_for(scene,a) for a in ('axe','rubick')};names={a:[b.name for b in arm.pose.bones] for a,arm in arms.items()};cams=sorted((o for o in scene.objects if o.type=='CAMERA'),key=lambda o:o.name)
# Per object descriptors retain mesh-key ownership, even when key datablocks are shared.
shapes=[(o,k) for o in sorted(scene.objects,key=lambda x:x.name) if o.type=='MESH' and o.data.shape_keys for k in o.data.shape_keys.key_blocks if k.name!='Basis']
arrays={a:np.empty((420,len(names[a]),4,4),dtype=np.float64) for a in arms}
for a in arms:arrays[a+'_object_world']=np.empty((420,4,4));arrays[a+'_root_object_world']=np.empty((420,4,4))
arrays['camera_world']=np.empty((420,len(cams),4,4));fields=('lens','ortho_scale','shift_x','shift_y','clip_start','clip_end','sensor_width','sensor_height')
arrays['camera_parameters']=np.empty((420,len(cams),len(fields)));arrays['camera_active_index']=np.empty(420,dtype=np.int32);arrays['facial_values']=np.empty((420,len(shapes)))
markers=[{'name':m.name,'frame':m.frame,'camera':m.camera.name if m.camera else None} for m in scene.timeline_markers]
manifest={'source':'_game/skits/doomsday/v11/live_staging.blend','sha256':hashlib.file_digest(SOURCE.open('rb'),'sha256').hexdigest(),'npz':'source_bank.npz','pose_frames':[0,419],'camera_face_frames':[0,419],'matrix_convention':'Column-vector Blender world matrices; arrays frame,bone,row,column; float64. Evaluated pose includes constraints.','actors':{a:{'object':arm.name,'bone_names':names[a],'parent_indices':[names[a].index(b.parent.name) if b.parent else -1 for b in arm.pose.bones]} for a,arm in arms.items()},'cameras':[{'name':o.name,'type':o.data.type,'sensor_fit':o.data.sensor_fit} for o in cams],'camera_parameter_fields':fields,'timeline_markers':markers,'facial_channels':[{'object':o.name,'key_data':o.data.shape_keys.name,'shape':k.name} for o,k in shapes],'render':{'fps':scene.render.fps,'fps_base':scene.render.fps_base,'resolution':[scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage]}}
keyframes=(0,225,252,270,278,327);keys={};bone_subset={'axe':['root','spine1','spine2','head','axe_1','wrist_L','wrist_R','elbow_L','elbow_R'],'rubick':['Root_0','Spine_0','Spine_3','Head_0','wrist_R','index_1_R']}
for f in range(420):
 scene.frame_set(f);graph=bpy.context.evaluated_depsgraph_get()
 if f<420:
  current={}
  for a,arm in arms.items():
   current[a]=pose(arm,graph);arrays[a][f]=np.array([current[a][n] for n in names[a]]);arrays[a+'_object_world'][f]=np.array(arm.evaluated_get(graph).matrix_world);arrays[a+'_root_object_world'][f]=np.array(arm.parent.evaluated_get(graph).matrix_world)
  if f in keyframes:keys[str(f)]={a:{n:rows(current[a][n]) for n in bone_subset[a] if n in current[a]} for a in arms}
 for i,c in enumerate(cams):
  ce=c.evaluated_get(graph);arrays['camera_world'][f,i]=np.array(ce.matrix_world);arrays['camera_parameters'][f,i]=[getattr(ce.data,n) for n in fields]
 arrays['camera_active_index'][f]=next((i for i,c in enumerate(cams) if scene.camera and c.name==scene.camera.name),-1)
 arrays['facial_values'][f]=[k.value for o,k in shapes]
 if f%100==0:print('BANK_FRAME',f,flush=True)
np.savez_compressed(OUT/'source_bank.npz',**arrays);(OUT/'source_bank_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
print('SOURCE_BANK_SAVED',flush=True)
bpy.ops.wm.open_mainfile(filepath=str(NATIVE));scene=bpy.context.scene;scene.frame_set(0);graph=bpy.context.evaluated_depsgraph_get();native={a:pose(arm_for(scene,a),graph) for a in arms};np.savez_compressed(OUT/'native_entry_pose.npz',**{a:np.array([native[a][n] for n in names[a]]) for a in arms})
old={a:{n:Matrix(arrays[a][278,i].tolist()) for i,n in enumerate(names[a])} for a in arms};oldprev={a:{n:Matrix(arrays[a][277,i].tolist()) for i,n in enumerate(names[a])} for a in arms};alignment=native['axe']['axe_1']@old['axe']['axe_1'].inverted();comparison={}
for a in arms:
 comparison[a]={n:{'raw':diff(old[a][n],native[a][n]),'after_single_weapon_rigid_alignment':diff(alignment@old[a][n],native[a][n]),'source_last_step':diff(oldprev[a][n],old[a][n])} for n in bone_subset[a] if n in old[a]}
report={'source':'source_bank_manifest.json','native_source':'_game/skits/doomsday/v12/native_pressure/native_pressure.blend','native_frame':0,'native_entry_npz':'native_entry_pose.npz','keyframes_world_matrices':keys,'entry_world_matrices':{a:{n:rows(native[a][n]) for n in bone_subset[a] if n in native[a]} for a in arms},'boundary_278_to_native_0':comparison,'weapon_alignment_278_to_native_0':rows(alignment),'limits':['Read-only source inspection; no scene save, pose edit, rendering, splice or visual acceptance.','Bone positions are staging evidence, not actual skin contacts.','A single rigid weapon alignment preserves the old pose defects and does not by itself establish a feasible transition.'],'elapsed_seconds':time.time()-t0}
(OUT/'source_preflight.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps({'elapsed':report['elapsed_seconds'],'npz_bytes':(OUT/'source_bank.npz').stat().st_size,'camera_count':len(cams),'facial_channels':len(shapes),'boundary':comparison}),flush=True)
