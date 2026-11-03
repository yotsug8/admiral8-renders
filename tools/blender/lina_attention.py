"""Re-stage the Lina reaction in the visually established -Y facing basis."""
import bpy,sys,math,json,hashlib
from pathlib import Path
from mathutils import Matrix,Vector,Quaternion
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools/blender'))
from study_face_hold import head_object
from contact_reaction import _curves
from study_head_target import gpu_guard
OUT=ROOT/'_game/study/lina_threat/attention_v3';SOURCE=ROOT/'_game/study/lina_threat/final/scene.blend'
COUNT=180
# f, retreat, lift, torso pitch, head pitch, R/L elbow, emotion.
POSES=[(0,0,0,0,20,15,0,'calm'),(24,0,.015,4,22,18,0,'calm'),
 (38,0,.015,4,18,4,0,'notice'),(48,.015,.015,2,34,4,0,'notice'),
 (55,.03,.015,0,38,8,4,'notice'),(65,.38,.02,-14,26,0,0,'fear'),
 (76,.48,.00,-11,27,0,0,'fear'),(89,.50,.02,-9,25,0,0,'fear'),
 (104,.52,.03,-7,18,0,0,'worry'),(120,.55,.10,8,10,30,20,'worry'),
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
 clips={name:(tracks[name].action,tracks[name].action_slot) for name in ('idle','run')}
 source.animation_data_clear();ad=source.animation_data_create();samples={}
 for name,(action,slot) in clips.items():
  ad.action=action;ad.action_slot=slot;a,z=action.frame_range;samples[name]=[]
  for f in range(COUNT):
   sample=f%max(1,int(z-a))
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
  for b in arm.pose.bones:
   held=authored[f][b.name]
   w=0 if b.name=='Root_0' or (f<38 and b.name in ('Head_0','Head_1')) else weight
   b.matrix_basis=held.lerp(samples[clip][phase][b.name],w)
   if b.name in previous and b.rotation_quaternion.dot(previous[b.name])<0:b.rotation_quaternion.negate()
   previous[b.name]=b.rotation_quaternion.copy()
   for channel in ('location','rotation_quaternion','scale'):b.keyframe_insert(channel,frame=f)
 for curve in _curves(arm.animation_data.action):
  for k in curve.keyframe_points:k.interpolation='LINEAR'

def animate_attention_face(sc,face):
 """Attention precedes recoil; the gasp releases into sustained apprehension."""
 from face import unfold
 shapes={
  'pleased':{'lipCornerPuller_L':.22,'squint':.08},
  'notice':{'innerBrowRaiser':.45,'outerBrowRaiser':.2,'upperLidRaiser':.25,'jawOpen':.12},
  'alarm':{'innerBrowRaiser':.95,'outerBrowRaiser':.45,'browLowerer':.12,'upperLidRaiser':.7,'jawOpen':.78,'lipCornerDepressor':.5,'lipStretcher':.35},
  'worry':{'innerBrowRaiser':.8,'outerBrowRaiser':.2,'browLowerer':.18,'upperLidRaiser':.4,'jawOpen':.3,'lipCornerDepressor':.4,'lipStretcher':.18}}
 beats=[(0,'pleased',{}),(18,'pleased',{}),(30,'notice',{'eyeDown':.1}),
        (42,'notice',{'eyeDown':.2}),(48,'notice',{'eyeDown':.2,'jawOpen':.22}),
        (54,'alarm',{'jawOpen':.55}),(62,'alarm',{}),(72,'alarm',{'jawOpen':.5}),
        (84,'worry',{'jawOpen':.38}),(96,'worry',{}),
        (104,'worry',{'eyeLeft':.18}),(117,'worry',{}),(145,'worry',{'jawOpen':.2}),
        (179,'worry',{'jawOpen':.14})]
 keys=face.data.shape_keys.key_blocks
 for f,name,extra in beats:
  values={**shapes[name],**extra}
  if set(values)-set(keys.keys()):raise ValueError('Expression requests missing FACS')
  for key in keys:
   if key.name!='Basis':key.value=values.get(key.name,0);key.keyframe_insert('value',frame=f)
 for curve in _curves(face.data.shape_keys.animation_data.action):
  for k in curve.keyframe_points:k.interpolation='BEZIER';k.handle_left_type=k.handle_right_type='AUTO_CLAMPED'
 track={k.name:[] for k in keys if k.name!='Basis'}
 for f in range(COUNT):
  sc.frame_set(f)
  for name,values in track.items():values.append(keys[name].value)
 # Reuse the production safeguard against combined FACS foldovers. It is not
 # a substitute for inspecting the eye direction and expression in the image.
 unfold(face,track,COUNT,30,'lina_attention')
 for name,values in track.items():
  for f,value in enumerate(values):keys[name].value=value;keys[name].keyframe_insert('value',frame=f)

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
 def place_arm(d,side,target,pole):
  names=[n+'_'+side for n in ('bicep','elbow','wrist')]
  h,k,w=(d[n].translation.copy() for n in names)
  upper,lower=(k-h).length,(w-k).length
  axis=target-h;distance=axis.length
  if not abs(upper-lower)+1e-5<distance<upper+lower-1e-5:
   raise ValueError(f'Unreachable defensive hand: {side}, {distance}')
  direction=axis.normalized();bend=pole-direction*pole.dot(direction);bend.normalize()
  along=(upper*upper-lower*lower+distance*distance)/(2*distance)
  joint=h+direction*along+bend*math.sqrt(max(0,upper*upper-along*along))
  def redirect(name,old,new):
   q=old.rotation_difference(new);pivot=d[name].translation.copy()
   transform=Matrix.Translation(pivot)@q.to_matrix().to_4x4()@Matrix.Translation(-pivot)
   for bone in [arm.pose.bones[name],*arm.pose.bones[name].children_recursive]:
    d[bone.name]=transform@d[bone.name]
  redirect(names[0],k-h,joint-h)
  redirect(names[1],d[names[2]].translation-d[names[1]].translation,target-joint)
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
  # Defensive hands in front of the chest, elbows below the wrists. Preserve
  # the initial palm/fire action; the unused arm hangs instead of presenting.
  brace=max(0,min(1,(f-48)/17))
  chest=d['Spine_1'].translation
  for side,sign in [('L',1),('R',-1)]:
   if side=='L':
    relaxed=chest+Vector((.58,.04,-.82))
    target=relaxed.lerp(chest+Vector((.56,-.72,.22)),brace)
   else:
    target=d['wrist_R'].translation.lerp(chest+Vector((-.48,-.77,.08)),brace)
   if side=='L' or brace>0:
    place_arm(d,side,target,Vector((sign*.85,.05,-.6)))
  # The legs trail the retreat, with no raised-knee falling pose.
  if 55<=f<=104:
   rotate(d,'thigh_L',(1,0,0),-4);rotate(d,'thigh_R',(1,0,0),-7)
  # Recoil bends hair a few frames after the torso; it settles once, not a loop.
  hair_lag={55:0,65:-3,76:5,89:2,104:0}.get(f,0)
  for name in ('hair_L','hair_R','hair_back'):
   rotate(d,name,(1,0,0),hair_lag)
  curl={55:0,65:5,76:10,89:7,104:5}.get(f,0)
  for side in ('L','R'):
   for finger in ('Index','Mid'):
    a,b,c=(d[f'{finger}_{j}_{side}'].translation for j in (0,1,2))
    axis=(b-a).cross(c-b)
    if curl and axis.length>1e-6:
     rotate(d,f'{finger}_1_{side}',axis.normalized(),curl*(1 if side=='L' else .7))
  rotate(d,'Root_0',(0,0,1),turn)
  for b in arm.pose.bones:
   b.rotation_mode='QUATERNION';b.matrix=inv@d[b.name];bpy.context.view_layer.update()
   if b.name in last and b.rotation_quaternion.dot(last[b.name])<0:b.rotation_quaternion.negate()
   last[b.name]=b.rotation_quaternion.copy()
  for b in arm.pose.bones:
   for c in ('location','rotation_quaternion','scale'):b.keyframe_insert(c,frame=f)
 for data in (arm,):
  for c in _curves(data.animation_data.action):
   for k in c.keyframe_points:k.interpolation='BEZIER';k.handle_left_type=k.handle_right_type='AUTO_CLAMPED'
 animate_attention_face(sc,face)
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
                 'run':'gradual departure blend 120-155; authored root travel retained'},
  facing='-Y established by four rendered face views',poses=POSES,frames=COUNT,fps=30,
  shots=[{'frame':m.frame,'purpose':m.name} for m in sc.timeline_markers if m.camera],
  status='Working movement and edit; not an accepted finished clip'),indent=2),encoding='utf-8')

def run(mode):
 if mode=='build':build();return
 bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False);gpu_guard();sc=bpy.context.scene
 if mode=='probe':
  for f in (0,48,65,89,104,135):
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
