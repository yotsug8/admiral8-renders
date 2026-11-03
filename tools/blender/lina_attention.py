"""Re-stage the Lina reaction in the visually established -Y facing basis."""
import bpy,sys,math,json,hashlib
from pathlib import Path
from mathutils import Matrix,Vector,Quaternion
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools/blender'))
from study_face_hold import head_object
from contact_reaction import _curves
from study_head_target import gpu_guard
OUT=ROOT/'_game/study/lina_threat/attention_v2';SOURCE=ROOT/'_game/study/lina_threat/final/scene.blend'
COUNT=180
# f, retreat, lift, torso pitch, head pitch, R/L elbow, emotion.
POSES=[(0,0,0,0,20,15,0,'calm'),(24,0,.015,4,22,18,0,'calm'),
 (38,0,.015,4,18,4,0,'notice'),(48,.015,.015,2,34,4,0,'notice'),
 (55,.03,.015,0,38,8,4,'notice'),(65,.35,.10,-10,42,45,24,'fear'),
 (76,.48,.08,-6,40,42,21,'fear'),(89,.48,.06,-4,38,40,20,'fear'),
 (104,.5,.06,-2,15,35,18,'worry'),(120,.55,.10,8,10,30,20,'worry'),
 (135,.55,.22,18,5,22,12,'worry'),(160,.55,.5,24,0,12,8,'worry'),
 (185,.55,.8,20,0,10,8,'worry'),(209,.55,1,18,0,10,8,'worry')]
TRAVEL={104:(0,0,-35),120:(-.35,-60,-15),135:(-1.4,-90,0),160:(-4.6,-90,0),185:(-9,-90,0),209:(-13,-90,0)}

def story_cameras(sc):
 """Native cuts: establish the act, show its cause, read the response, leave."""
 for marker in list(sc.timeline_markers):
  if marker.camera:sc.timeline_markers.remove(marker)
 shots=[(0,'fire',(-4,-12,6),(0,-.15,3.4),6.8),
        (36,'noticed_shadow',(1,1,7),(0,-4,0),8),
        (52,'startle',(-3,-10,7),(0,.25,3.3),7.8),
        (84,'decision',(-2,-9,5.2),(0,.25,4.15),4.0),
        (104,'exit',(7,-14,7),(0,-.5,3),9)]
 for frame,name,position,target,size in shots:
  camera=bpy.data.objects.new('attention_'+name,bpy.data.cameras.new('attention_'+name))
  sc.collection.objects.link(camera);camera.location=position
  camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
  camera.data.type='ORTHO';camera.data.ortho_scale=size;camera.data.clip_end=2000
  sc.timeline_markers.new(name,frame=frame).camera=camera
 sc.camera=bpy.data.objects['attention_fire']

def restage_existing_forest(sc):
 """The former +X camera had trees at -X; the new front cameras face +Y."""
 turn=Matrix.Rotation(-math.pi/2,4,'Z')
 trees=[o for o in sc.objects if o.type=='MESH' and 'tree_pine_01_' in o.name]
 if not trees:raise ValueError('Expected the preserved native forest meshes')
 for ob in trees:ob.matrix_world=turn@ob.matrix_world
 # Fill the rear sightline of the low reaction camera with a second tree layer.
 def center(ob):return sum((ob.matrix_world@Vector(c) for c in ob.bound_box),Vector())/8
 trunk=min((o for o in trees if '_model' in o.name),key=lambda o:abs(center(o).x))
 leaf=min((o for o in trees if '_inspector' in o.name),key=lambda o:(center(o).xy-center(trunk).xy).length)
 for offset in ((-3,5,0),(4,8,0)):
  for ob in (trunk,leaf):
   clone=ob.copy();sc.collection.objects.link(clone)
   clone.matrix_world=Matrix.Translation(offset)@ob.matrix_world
 fill=bpy.data.objects.get('Forest fill')
 if fill:fill.matrix_world=turn@fill.matrix_world

def native_phases(sc,arm):
 """Blend compatible native local poses; retain authored travel and attention.

 Native clips supply compatible body poses. Their selected phases serve the
 authored attention/recoil/departure; source loops do not define the acting.
 """
 authored=[]
 for f in range(COUNT):
  sc.frame_set(f);bpy.context.view_layer.update()
  authored.append({b.name:b.matrix_basis.copy() for b in arm.pose.bones})
 objects=set(bpy.data.objects);actions=set(bpy.data.actions)
 bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/models/models_heroes_lina_lina.glb'))
 added=set(bpy.data.objects)-objects;source=next(o for o in added if o.type=='ARMATURE')
 missing=set(arm.pose.bones.keys())-set(source.pose.bones.keys())
 if missing:raise ValueError(f'Native clip skeleton missing bones: {sorted(missing)}')
 for bone in arm.data.bones:
  other=source.data.bones[bone.name]
  if max(abs(bone.matrix_local[i][j]-other.matrix_local[i][j]) for i in range(4) for j in range(4))>1e-5:
   raise ValueError(f'Native bind differs: {bone.name}')
 tracks={t.name:t.strips[0] for t in source.animation_data.nla_tracks if t.strips}
 clips={name:(tracks[name].action,tracks[name].action_slot) for name in ('idle','run','flail_new')}
 source.animation_data_clear();ad=source.animation_data_create();samples={}
 for name,(action,slot) in clips.items():
  ad.action=action;ad.action_slot=slot;a,z=action.frame_range;samples[name]=[]
  for f in range(COUNT):
   sample=min(f,int(z-a)) if name=='flail_new' else f%max(1,int(z-a))
   sc.frame_set(int(a+sample));bpy.context.view_layer.update()
   samples[name].append({b.name:b.matrix_basis.copy() for b in source.pose.bones})
 for ob in added:bpy.data.objects.remove(ob,do_unlink=True)
 for action in set(bpy.data.actions)-actions:
  bpy.data.actions.remove(action)
 previous={}
 for f in range(COUNT):
  # No ambient loop under fear: the action must retain its specific purpose.
  weight=.5*max(0,min(1,(38-f)/14)) if f<38 else max(0,min(1,(f-120)/35))
  clip='idle' if f<38 else 'run';phase=f if clip=='idle' else max(0,f-120)
  startled=max(0,min(1,(f-55)/13)) if f>=55 else 0
  startled=startled*startled*(3-2*startled)
  # Only the first recoil. The rest of flail alternates waving arms and reads
  # as repeated panic rather than one reaction to the advancing shadow.
  startle_phase=min(6,max(0,round((f-55)*6/13)))
  recovery=max(0,min(1,(f-73)/31))
  recovery=recovery*recovery*(3-2*recovery)
  for b in arm.pose.bones:
   held=authored[f][b.name]
   if f>=55 and b.name not in ('Root_0','Head_0','Head_1'):
    held=held.lerp(samples['flail_new'][startle_phase][b.name],startled)
    held=held.lerp(samples['idle'][24][b.name],recovery)
   w=0 if b.name=='Root_0' or (f<38 and b.name in ('Head_0','Head_1')) else weight
   b.matrix_basis=held.lerp(samples[clip][phase][b.name],w)
   if b.name in previous and b.rotation_quaternion.dot(previous[b.name])<0:b.rotation_quaternion.negate()
   previous[b.name]=b.rotation_quaternion.copy()
   for channel in ('location','rotation_quaternion','scale'):b.keyframe_insert(channel,frame=f)
 for curve in _curves(arm.animation_data.action):
  for k in curve.keyframe_points:k.interpolation='LINEAR'

def build():
 OUT.mkdir(parents=True,exist_ok=True);bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
 sc=bpy.context.scene;sc.frame_set(0);bpy.context.view_layer.update()
 root=bpy.data.objects['lina_root'];face=head_object();arm=next(m.object for m in face.modifiers if m.type=='ARMATURE')
 for o in [root,*root.children_recursive]:
  o.animation_data_clear()
  if o.type=='MESH' and o.data.shape_keys:
   o.data.shape_keys.animation_data_clear()
   for k in o.data.shape_keys.key_blocks:k.value=0
 base={b.name:arm.matrix_world@b.matrix for b in arm.pose.bones}
 rest={b.name:b.matrix_basis.copy() for b in arm.pose.bones};inv=arm.matrix_world.inverted()
 def rotate(d,name,axis,deg):
  bone=arm.pose.bones[name];p=d[name].translation
  t=Matrix.Translation(p)@Quaternion(Vector(axis),math.radians(deg)).to_matrix().to_4x4()@Matrix.Translation(-p)
  for b in [bone,*bone.children_recursive]:d[b.name]=t@d[b.name]
 def flex(d,side,deg):
  p=d['elbow_'+side].translation
  axis=(p-d['bicep_'+side].translation).cross(d['wrist_'+side].translation-p).normalized()
  rotate(d,'elbow_'+side,axis,deg)
 last={}
 for f,back,lift,pitch,hp,er,el,emotion in POSES:
  for b in arm.pose.bones:b.matrix_basis=rest[b.name]
  d={n:m.copy() for n,m in base.items()}
  travel,turn,head_yaw=TRAVEL.get(f,(0,0,0))
  if f<=24:
   hand=base['wrist_R'].translation+Vector((0,0,.28))
   face_pos=base['Head_1'].translation+Vector((0,-.16,.15))
   delta=hand-face_pos
   head_yaw=max(-50,min(50,math.degrees(math.atan2(delta.x,-delta.y))))
  for m in d.values():m.translation+=Vector((travel,back,lift))
  rotate(d,'Spine_0',(1,0,0),pitch*.55);rotate(d,'Spine_1',(1,0,0),pitch*.45)
  # The skin/hair bridge spans Head_0 and Head_1: preserve their relative pose.
  rotate(d,'Head_0',(1,0,0),hp)
  rotate(d,'Head_0',(0,0,1),head_yaw)
  # The unused arm rests; when threatened both upper arms lower before folding.
  # This changes the entire arm silhouette instead of bending elbows in a fixed spread pose.
  rotate(d,'bicep_L',(0,1,0),30 if f<65 else 50)
  if f>=65:rotate(d,'bicep_R',(0,1,0),-45)
  flex(d,'R',er+25 if f>=65 else er);flex(d,'L',el+40 if f>=65 else el+15)
  if f>=65:
   rotate(d,'bicep_R',(0,0,1),25);rotate(d,'bicep_L',(0,0,1),-30)
   rotate(d,'thigh_L',(1,0,0),4);rotate(d,'thigh_R',(1,0,0),-3)
  if f>=120:
   rotate(d,'thigh_L',(1,0,0),8);rotate(d,'thigh_R',(1,0,0),5)
  rotate(d,'Root_0',(0,0,1),turn)
  for b in arm.pose.bones:
   b.rotation_mode='QUATERNION';b.matrix=inv@d[b.name];bpy.context.view_layer.update()
   if b.name in last and b.rotation_quaternion.dot(last[b.name])<0:b.rotation_quaternion.negate()
   last[b.name]=b.rotation_quaternion.copy()
  for b in arm.pose.bones:
   for c in ('location','rotation_quaternion','scale'):b.keyframe_insert(c,frame=f)
  values={'calm':{'lipCornerPuller_L':.18},'notice':{'innerBrowRaiser':.25,'lipPressor':.20},
          'fear':{'innerBrowRaiser':.65,'outerBrowRaiser':.25,'upperLidRaiser':.45,'jawOpen':.42,'lipCornerDepressor':.45,'lipStretcher':.25},
          'worry':{'innerBrowRaiser':.3,'lipCornerDepressor':.2,'lipPressor':.15,'eyeLeft':.15 if f==104 else 0}}[emotion]
  for k in face.data.shape_keys.key_blocks:
   if k.name!='Basis':k.value=values.get(k.name,0);k.keyframe_insert('value',frame=f)
 for data in (arm,face.data.shape_keys):
  for c in _curves(data.animation_data.action):
   for k in c.keyframe_points:k.interpolation='BEZIER';k.handle_left_type=k.handle_right_type='AUTO_CLAMPED'
 native_phases(sc,arm)
 shadow=bpy.data.objects['Looming shadow'];shadow.animation_data_clear();shadow.rotation_euler.z=-math.pi/2
 for f,y in [(0,-13),(24,-13),(38,-8),(55,-5.4),(209,-5.4)]:
  shadow.location=(0,y,.018);shadow.keyframe_insert('location',frame=f)
 fire=bpy.data.objects['Fire in palm'];fire.animation_data_clear();lamp=bpy.data.objects['Palm fire light'];lamp.animation_data_clear();lamp.data.animation_data_clear()
 for f in range(COUNT):
  sc.frame_set(f);bpy.context.view_layer.update();w=arm.matrix_world@arm.pose.bones['wrist_R'].matrix
  e=arm.matrix_world@arm.pose.bones['elbow_R'].matrix;fire.location=w.translation+(w.translation-e.translation).normalized()*.24+Vector((0,0,.28))
  level=min(1,.2+f/24)*max(0,min(1,(62-f)/9));fire.scale=(level,level,level)
  fire.keyframe_insert('location',frame=f);fire.keyframe_insert('scale',frame=f)
  lamp.location=fire.location;lamp.keyframe_insert('location',frame=f);lamp.data.energy=80*level;lamp.data.keyframe_insert('energy',frame=f)
 restage_existing_forest(sc);story_cameras(sc)
 sc.frame_start=0;sc.frame_end=COUNT-1;sc.render.fps=30;sc.render.resolution_x=432;sc.render.resolution_y=768;sc.render.resolution_percentage=100
 sc.render.use_overwrite=True
 sc.eevee.taa_render_samples=16;sc.render.use_motion_blur=False;sc.render.use_compositing=False
 sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
 (OUT/'recipe.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
  scene_sha256=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest(),
  native_source='_game/models/models_heroes_lina_lina.glb',
  native_sha256=hashlib.sha256((ROOT/'_game/models/models_heroes_lina_lina.glb').read_bytes()).hexdigest(),
  native_phases={'idle':'half influence, frames 0-24; out by 38; authored head retained',
                 'flail_new':'source frames 0-6 only over 55-68; recover over 73-104; authored head/root retained',
                 'run':'gradual departure blend 120-155; authored root travel retained'},
  facing='-Y established by four rendered face views',poses=POSES,frames=COUNT,fps=30,
  shots=[{'frame':m.frame,'purpose':m.name} for m in sc.timeline_markers if m.camera],
  status='Working movement and edit; not an accepted finished clip'),indent=2),encoding='utf-8')

def run(mode):
 if mode=='build':build();return
 bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False);gpu_guard();sc=bpy.context.scene
 if mode=='probe':
  for f in (0,36,52,65,104,135):
   sc.frame_set(f);sc.render.filepath=str(OUT/f'pose_{f:03}.png');bpy.ops.render.render(write_still=True)
 elif mode=='render':
  sc.render.filepath=str(OUT/'frames/frame_');bpy.ops.render.render(animation=True)
 elif mode=='review':
  # Separate inspection cameras do not change the saved story scene.
  sc.timeline_markers.clear();cam=sc.camera;cam.data.ortho_scale=7
  face=head_object();arm=next(m.object for m in face.modifiers if m.type=='ARMATURE')
  for f in (68,92,135):
   sc.frame_set(f);bpy.context.view_layer.update()
   target=(arm.matrix_world@arm.pose.bones['Spine_0'].matrix).translation
   for name,offset in [('side',Vector((8,0,1.5))),('reverse',Vector((0,8,1.5)))]:
    cam.location=target+offset;cam.rotation_euler=(-offset).to_track_quat('-Z','Y').to_euler()
    sc.render.filepath=str(OUT/f'review_{f}_{name}.png');bpy.ops.render.render(write_still=True)
 else:raise ValueError(mode)
if __name__=='__main__':run(sys.argv[sys.argv.index('--')+1])
