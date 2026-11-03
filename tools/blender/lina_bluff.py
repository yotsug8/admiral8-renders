"""Authored acting transfer: attempting a confident stop while feeling afraid.

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
from lina_attention import SOURCE, restage_existing_forest
from contact_reaction import _curves
from study_face_hold import head_object
from study_head_target import gpu_guard
from face import unfold

OUT = ROOT / '_game/study/lina_bluff'
COUNT = 180
# frame, retreat, torso/head pitch, left/right hand offset from chest, palm stop, face.
BEATS = [
 (0,.35,-10,25,(.56,-.72,.22),(-.48,-.77,.08),0,'worry'),
 (18,.32,-4,12,(.60,-.40,-.15),(-.55,-.50,-.20),0,'collect'),
 (38,.20,2,2,(.65,-.95,.40),(-.48,-.77,.08),1,'brave'),
 (65,.10,4,-3,(.65,-1.02,.40),(-.48,-.77,.08),1,'brave'),
 (82,.10,3,15,(.65,-1.02,.40),(-.48,-.77,.08),1,'notice'),
 (94,.46,-12,28,(.53,-.62,.23),(-.43,-.70,.08),.15,'alarm'),
 (108,.52,-9,24,(.55,-.65,.25),(-.45,-.68,.05),.1,'worry'),
 (132,.43,-4,8,(.65,-.83,.35),(-.45,-.65,.00),.85,'forced'),
 (158,.46,-5,7,(.65,-.85,.35),(-.45,-.65,.00),.85,'forced'),
 (179,.46,-5,9,(.65,-.85,.35),(-.45,-.65,.00),.85,'forced'),
]
FACES = {
 'worry':{'innerBrowRaiser':.8,'upperLidRaiser':.4,'jawOpen':.25,'lipCornerDepressor':.4},
 'collect':{'innerBrowRaiser':.35,'lipPressor':.3,'jawOpen':.05},
 'brave':{'lipCornerPuller_L':.4,'outerBrowRaiser_L':.2,'squint_R':.12},
 'notice':{'innerBrowRaiser':.55,'upperLidRaiser':.45,'jawOpen':.15,'eyeDown':.15},
 'alarm':{'innerBrowRaiser':.95,'outerBrowRaiser':.4,'upperLidRaiser':.7,'jawOpen':.7,'lipStretcher':.3},
 'forced':{'lipCornerPuller_L':.25,'innerBrowRaiser':.65,'upperLidRaiser':.4,'lipPressor':.1},
}


def build():
 OUT.mkdir(parents=True,exist_ok=True)
 bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
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
  for m in d.values():m.translation+=Vector((0,back,0))
  rotate(d,'Spine_0',(1,0,0),pitch*.55);rotate(d,'Spine_1',(1,0,0),pitch*.45)
  rotate(d,'Head_0',(1,0,0),hp)
  chest=d['Spine_1'].translation.copy()
  hand(d,'L',chest+Vector(left));hand(d,'R',chest+Vector(right));palm_stop(d,stop)
  lag={82:0,94:-4,108:4,132:0}.get(frame,0)
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
 for name in ('Fire in palm','Palm fire light'):
  obj=bpy.data.objects[name];obj.animation_data_clear();obj.hide_render=True
 shadow=bpy.data.objects['Looming shadow'];shadow.animation_data_clear();shadow.rotation_euler.z=-math.pi/2
 for f,y in ((0,-7),(65,-7),(90,-5),(179,-5)):
  shadow.location=(0,y,.018);shadow.keyframe_insert('location',frame=f)
 restage_existing_forest(sc);sc.timeline_markers.clear()
 for f,name,pos,target,size in [(0,'attempt',(-3,-11,6),(0,.2,3.35),6.7),(70,'threat_advances',(1,1,7),(0,-4,0),8),(84,'mask_slips',(-2,-10,5.4),(0,.3,4.1),4.6)]:
  cam=bpy.data.objects.new('bluff_'+name,bpy.data.cameras.new('bluff_'+name));sc.collection.objects.link(cam)
  cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
  cam.data.type='ORTHO';cam.data.ortho_scale=size;sc.timeline_markers.new(name,frame=f).camera=cam
 sc.camera=bpy.data.objects['bluff_attempt'];sc.frame_start=0;sc.frame_end=COUNT-1
 sc.render.fps=30;sc.render.resolution_x=432;sc.render.resolution_y=768;sc.render.resolution_percentage=100
 sc.render.use_overwrite=True;sc.eevee.taa_render_samples=16;sc.render.use_motion_blur=False;sc.render.use_compositing=False
 sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
 (OUT/'recipe.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
  scene_sha256=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest(),beats=BEATS,faces=FACES,
  intention='Try to stop the threat confidently; recoil betrays fear; resume a weaker confident gesture',
  status='Unaccepted acting transfer; inspect hands, shoulders, gaze and whole performance'),indent=2),encoding='utf-8')


def main(mode):
 if mode=='build':build();return
 bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False);gpu_guard();sc=bpy.context.scene
 if mode=='probe':
  for f in (0,38,65,94,132):
   sc.frame_set(f);sc.render.filepath=str(OUT/f'pose_{f}.png');bpy.ops.render.render(write_still=True)
 elif mode=='review':
  sc.timeline_markers.clear();cam=sc.camera;cam.location=(8,0,5);target=Vector((0,.3,3.6))
  cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=6
  for f in (38,94,132):
   sc.frame_set(f);sc.render.filepath=str(OUT/f'side_{f}.png');bpy.ops.render.render(write_still=True)
 elif mode=='render':
  sc.render.filepath=str(OUT/'frames/frame_');bpy.ops.render.render(animation=True)
 else:raise ValueError(mode)


if __name__=='__main__':main(sys.argv[sys.argv.index('--')+1])
