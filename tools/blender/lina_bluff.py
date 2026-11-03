"""Authored action: command an approaching threat to stop, then choose to flee.

This scene is not a general gesture preset. The accepted attention scene is
read-only; models, facial safeguards and forest preparation are reused.
Blender -b -P tools/blender/lina_bluff.py -- build|probe|review|render
"""
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/blender'))
from lina_attention import SOURCE, restage_existing_forest, native_phases
from contact_reaction import _curves
from study_face_hold import head_object
from study_head_target import gpu_guard
from face import unfold
from workshop_materials import apply_verified

OUT = ROOT / '_game/study/lina_bluff/v3'
COUNT = 180
# frame, retreat, torso/head pitch, left/right hand offset from chest, palm stop, face.
BEATS = [
 (0,.20,-4,30,(.58,-.45,-.28),(-.55,-.50,-.20),0,'notice'),
 (22,.22,-6,32,(.58,-.45,-.28),(-.55,-.50,-.20),0,'notice'),
 (32,.18,-8,20,(.56,-.50,-.10),(-.53,-.55,-.15),.3,'collect'),
 (45,-.35,12,15,(.65,-1.12,.48),(-.72,-.65,-.12),1,'brave'),
 (62,-.32,9,18,(.67,-1.06,.45),(-.65,-.65,-.16),1,'brave'),
 (76,-.25,5,32,(.62,-1.00,.38),(-.48,-.77,.08),.9,'notice'),
 (88,.75,-18,32,(.49,-.57,.18),(-.43,-.70,.17),.15,'alarm'),
 (100,1.0,-12,24,(.55,-.65,.25),(-.45,-.68,.10),.1,'worry'),
 (112,1.05,-5,14,(.57,-.65,.10),(-.48,-.68,.05),0,'worry'),
 (126,1.10,9,6,(.60,-.55,-.12),(-.55,-.60,-.10),0,'worry'),
 (145,1.10,20,2,(.60,-.55,-.12),(-.55,-.60,-.10),0,'worry'),
 (160,1.10,24,0,(.60,-.55,-.12),(-.55,-.60,-.10),0,'worry'),
 (179,1.10,24,0,(.60,-.55,-.12),(-.55,-.60,-.10),0,'worry'),
]
# Whole-body intention: gather, press forward, flinch away, choose an exit.
# Lina is levitating in this staging; the trailing legs follow acceleration.
BODY = {
 0:(0,0,0),22:(0,0,0),32:(-9,-.04,3),45:(10,.10,-5),62:(8,.04,-2),
 76:(5,0,0),88:(-13,.12,8),100:(-10,.04,5),112:(-25,0,2),
 126:(-65,.08,-4),145:(-90,.12,-2),160:(-90,.15,0),179:(-90,.15,0),
}
TRAVEL={112:0,126:-.25,145:-2.0,160:-4.5,179:-8.5}
FACES = {
 'worry':{'innerBrowRaiser':.8,'upperLidRaiser':.4,'jawOpen':.25,'lipCornerDepressor':.4},
 'collect':{'innerBrowRaiser':.35,'lipPressor':.3,'jawOpen':.05},
 'brave':{'browLowerer':.45,'lipPressor':.35,'squint':.18,'eyeDown':.15},
 'notice':{'innerBrowRaiser':.55,'upperLidRaiser':.45,'jawOpen':.15,'eyeDown':.15},
 'alarm':{'innerBrowRaiser':.95,'outerBrowRaiser':.4,'upperLidRaiser':.7,'jawOpen':.7,'lipStretcher':.3},
 'forced':{'lipCornerPuller_L':.25,'innerBrowRaiser':.65,'upperLidRaiser':.4,'lipPressor':.1},
}


def build():
 OUT.mkdir(parents=True,exist_ok=True)
 bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
 materials=apply_verified(ROOT/'_game/models/workshop',['lina'])
 sc=bpy.context.scene;sc.frame_set(0);root=bpy.data.objects['lina_root'];face=head_object()
 arm=next(m.object for m in face.modifiers if m.type=='ARMATURE')
 for obj in [root,*root.children_recursive]:
  obj.animation_data_clear()
  if obj.type=='MESH' and obj.data.shape_keys:
   obj.data.shape_keys.animation_data_clear()
   for key in obj.data.shape_keys.key_blocks:key.value=0
 base={b.name:arm.matrix_world@b.matrix for b in arm.pose.bones}
 rest={b.name:b.matrix_basis.copy() for b in arm.pose.bones};inverse=arm.matrix_world.inverted()
 def rotate(d,name,axis,angle):
  pivot=d[name].translation
  transform=Matrix.Translation(pivot)@Quaternion(Vector(axis),math.radians(angle)).to_matrix().to_4x4()@Matrix.Translation(-pivot)
  for b in [arm.pose.bones[name],*arm.pose.bones[name].children_recursive]:d[b.name]=transform@d[b.name]
 def hand(d,side,target):
  names=[n+'_'+side for n in ('bicep','elbow','wrist')]
  h,k,w=(d[n].translation.copy() for n in names);upper=(k-h).length;lower=(w-k).length
  direction=target-h;distance=direction.length;direction.normalize()
  if not abs(upper-lower)<distance<upper+lower:raise ValueError(f'Unreachable hand on {side}')
  pole=Vector((.85 if side=='L' else -.85,.05,-.6));pole-=direction*pole.dot(direction);pole.normalize()
  along=(upper*upper-lower*lower+distance*distance)/(2*distance)
  elbow=h+direction*along+pole*math.sqrt(max(0,upper*upper-along*along))
  for name,old,new in [(names[0],k-h,elbow-h),(names[1],None,None)]:
   if old is None:old=d[names[2]].translation-d[name].translation;new=target-d[name].translation
   q=old.rotation_difference(new);axis,angle=q.to_axis_angle();rotate(d,name,axis,math.degrees(angle))
 def palm_stop(d,weight):
  wrist=d['wrist_L'].translation
  forward=((d['Index_0_L'].translation+d['Mid_0_L'].translation)*.5-wrist).normalized()
  across=d['Index_0_L'].translation-d['Mid_0_L'].translation;across-=forward*across.dot(forward);across.normalize()
  current=Matrix((across,forward,across.cross(forward))).transposed()
  goal=Matrix((Vector((1,0,0)),Vector((0,0,1)),Vector((0,-1,0)))).transposed()
  q=(goal@current.inverted()).to_quaternion();q=Quaternion().slerp(q,weight)
  axis,angle=q.to_axis_angle();rotate(d,'wrist_L',axis,math.degrees(angle))
  # Open the proximal and middle joints along the palm, not just the tip.
  palm_forward=((d['Index_0_L'].translation+d['Mid_0_L'].translation)*.5-d['wrist_L'].translation).normalized()
  for finger in ('Index','Mid'):
   for joint in (0,1):
    start=d[f'{finger}_{joint}_L'].translation
    end=d[f'{finger}_{joint+1}_L'].translation
    extension=(end-start).rotation_difference(palm_forward)
    axis,angle=extension.to_axis_angle()
    rotate(d,f'{finger}_{joint}_L',axis,math.degrees(angle)*.9*weight)
 previous={}
 for frame,back,pitch,hp,left,right,stop,expression in BEATS:
  for b in arm.pose.bones:b.matrix_basis=rest[b.name]
  d={name:m.copy() for name,m in base.items()}
  yaw,lift,trail=BODY[frame]
  for m in d.values():m.translation+=Vector((TRAVEL.get(frame,0),back,lift))
  rotate(d,'Spine_0',(1,0,0),pitch*.55);rotate(d,'Spine_1',(1,0,0),pitch*.45)
  rotate(d,'Head_0',(1,0,0),hp)
  rotate(d,'Head_0',(0,0,1),-35 if frame==112 else -15 if frame==126 else -yaw if frame<112 else 0)
  for side,factor in [('L',1),('R',.7)]:rotate(d,'thigh_'+side,(1,0,0),trail*factor)
  chest=d['Spine_1'].translation.copy()
  hand(d,'L',chest+Vector(left));hand(d,'R',chest+Vector(right));palm_stop(d,stop)
  # Turn the whole posed figure, including the hand targets, toward the exit.
  rotate(d,'Root_0',(0,0,1),yaw)
  lag={45:-3,62:2,76:0,88:-6,100:4,126:-3,145:2}.get(frame,0)
  for name in ('hair_L','hair_R','hair_back'):rotate(d,name,(1,0,0),lag)
  for b in arm.pose.bones:
   b.rotation_mode='QUATERNION';b.matrix=inverse@d[b.name];bpy.context.view_layer.update()
   if b.name in previous and b.rotation_quaternion.dot(previous[b.name])<0:b.rotation_quaternion.negate()
   previous[b.name]=b.rotation_quaternion.copy()
   for channel in ('location','rotation_quaternion','scale'):b.keyframe_insert(channel,frame=frame)
  for key in face.data.shape_keys.key_blocks:
   if key.name!='Basis':key.value=FACES[expression].get(key.name,0);key.keyframe_insert('value',frame=frame)
 for data in (arm,face.data.shape_keys):
  for curve in _curves(data.animation_data.action):
   for key in curve.keyframe_points:key.interpolation='BEZIER';key.handle_left_type=key.handle_right_type='AUTO_CLAMPED'
 track={k.name:[] for k in face.data.shape_keys.key_blocks if k.name!='Basis'}
 for f in range(COUNT):
  sc.frame_set(f)
  for name in track:track[name].append(face.data.shape_keys.key_blocks[name].value)
 unfold(face,track,COUNT,30,'lina_bluff')
 for name,values in track.items():
  key=face.data.shape_keys.key_blocks[name]
  for f,value in enumerate(values):key.value=value;key.keyframe_insert('value',frame=f)
 native_phases(sc,arm)
 for name in ('Fire in palm','Palm fire light'):
  obj=bpy.data.objects[name]
  for child in [obj,*obj.children_recursive]:child.animation_data_clear();child.hide_render=True
 shadow=bpy.data.objects['Looming shadow'];shadow.animation_data_clear();shadow.rotation_euler.z=-math.pi/2
 for f,y in ((0,-9),(22,-7),(62,-7),(76,-4.3),(90,-3.2),(179,-3.2)):
  shadow.location=(0,y,.018);shadow.keyframe_insert('location',frame=f)
 restage_existing_forest(sc);sc.timeline_markers.clear()
 for f,name,pos,target,size in [(0,'cause',(0,-10,11),(0,-1.8,2.0),11.5),(28,'stop',(-3,-11,6),(0,0,3.6),6.2),(62,'consequence',(0,-10,11),(0,-1.8,2.0),11.5),(82,'recoil',(-2,-10,6),(0,.8,3.7),6.2),(112,'exit',(0,-10,11),(0,-1.8,2.0),11.5)]:
  cam=bpy.data.objects.new('bluff_'+name,bpy.data.cameras.new('bluff_'+name));sc.collection.objects.link(cam)
  cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
  cam.data.type='ORTHO';cam.data.ortho_scale=size;sc.timeline_markers.new(name,frame=f).camera=cam
 sc.camera=bpy.data.objects['bluff_cause'];sc.frame_start=0;sc.frame_end=COUNT-1
 sc.render.fps=30;sc.render.resolution_x=540;sc.render.resolution_y=960;sc.render.resolution_percentage=100
 sc.render.use_overwrite=True;sc.eevee.taa_render_samples=16;sc.render.use_motion_blur=False;sc.render.use_compositing=False
 sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
 (OUT/'recipe.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
  scene_sha256=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest(),beats=BEATS,body=BODY,faces=FACES,materials=materials,
  intention='See approaching shadow; command it to stop; it ignores the gesture; recoil, choose an exit and leave',
  status='Unaccepted acting transfer; inspect hands, shoulders, gaze and whole performance'),indent=2),encoding='utf-8')


def main(mode):
 if mode=='build':build();return
 bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False);sc=bpy.context.scene
 if mode=='audit':
  from bpy_extras.object_utils import world_to_camera_view
  face=head_object();arm=next(m.object for m in face.modifiers if m.type=='ARMATURE')
  names=('Head_0','wrist_L','wrist_R','Root_0');previous=None;peak=0.;errors=[];samples=[]
  for f in range(COUNT):
   sc.frame_set(f);bpy.context.view_layer.update()
   points={n:arm.matrix_world@arm.pose.bones[n].matrix.translation for n in names}
   if not all(math.isfinite(v) for p in points.values() for v in p):errors.append([f,'nonfinite'])
   if previous:peak=max(peak,max((points[n]-previous[n]).length for n in names))
   if f<=112:
    for n,p in points.items():
     if n=='Root_0':continue
     q=world_to_camera_view(sc,sc.camera,p)
     if not (0<=q.x<=1 and 0<=q.y<=1 and q.z>0):errors.append([f,n,'out of frame'])
   samples.append(dict(frame=f,points={n:list(p) for n,p in points.items()}));previous=points
  report=dict(frames=COUNT,max_landmark_step=peak,errors=errors,passed=not errors,
   scope='Finite landmarks and head/hands in camera before intentional departure; not a skin, gaze or acting certificate',
   scene_sha256=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest())
  (OUT/'audit.json').write_text(json.dumps(report,indent=2));(OUT/'landmarks.json').write_text(json.dumps(samples))
  print(json.dumps(report))
  if errors:raise ValueError('Staging audit failed')
  return
 gpu_guard()
 if mode=='probe':
  for f in (18,45,76,88,112,145):
   sc.frame_set(f);sc.render.filepath=str(OUT/f'pose_{f}.png');bpy.ops.render.render(write_still=True)
 elif mode=='review':
  sc.timeline_markers.clear();cam=sc.camera;cam.location=(8,.4,5);target=Vector((0,.4,3.6))
  cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=8
  for f in (45,88,126):
   sc.frame_set(f);sc.render.filepath=str(OUT/f'side_{f}.png');bpy.ops.render.render(write_still=True)
 elif mode=='render':
  sc.render.filepath=str(OUT/'frames/frame_');bpy.ops.render.render(animation=True)
 elif mode=='detail':
  sc.frame_set(45);sc.render.resolution_x=1080;sc.render.resolution_y=1920;sc.eevee.taa_render_samples=64
  sc.render.filepath=str(OUT/'detail_1080.png');bpy.ops.render.render(write_still=True)
 else:raise ValueError(mode)


if __name__=='__main__':main(sys.argv[sys.argv.index('--')+1])
