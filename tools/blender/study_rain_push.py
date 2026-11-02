"""Rain pushing study: native IK contacts, loaded step and delayed prop motion."""
from pathlib import Path
import bpy, math, json, sys, argparse, hashlib, os, shutil
from mathutils import Vector,Matrix,Quaternion
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/blender'))
from study_lift import material,cube
parser=argparse.ArgumentParser()
parser.add_argument('--out',required=True)
parser.add_argument('--render',action='store_true')
parser.add_argument('--story',action='store_true',help='Authored confidence, setback and effort scene')
parser.add_argument('--check-only',action='store_true')
parser.add_argument('--overview',action='store_true',help='Also render a fixed 320px overview for motion review')
parser.add_argument('--frames',help='Explicit frames for a pose probe or partial rerender')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
OUT=Path(args.out).resolve()
study_root=Path(os.environ.get('A8_STUDY_ROOT',str(ROOT/'_game/study'))).resolve()
if not OUT.is_relative_to(study_root):raise ValueError('Output outside configured study directory')
OUT.mkdir(parents=True,exist_ok=True)
if shutil.disk_usage(OUT).free<128*1024**2:raise RuntimeError('Less than 128 MiB available')
source=ROOT/'_game/external/rain_v33/Rain v3.3/rain_v3.2.blend'
source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'_game/external/rain_v33/Rain v3.3/rain_v3.2.blend'),use_scripts=False)
if bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
s=bpy.context.scene;r=bpy.data.objects['RIG-rain'];p=r.pose.bones
for k,v in {'ik_arm_left':1,'ik_arm_right':1,'ik_leg_left':1,'ik_leg_right':1,'ik_fingers_left':0,'ik_fingers_right':0,'ik_spine':0,'ik_stretch_arms':0,'ik_stretch_legs':0}.items():p['Properties_IKFK'][k]=v
r.update_tag();bpy.context.view_layer.update()
names=['MSTR-Pelvis','MSTR-Foot.L','MSTR-Foot.R','FK-Spine','FK-Chest','FK-Head','FK-Scarf1',
 'IK-Hand.L','IK-Hand.R','IK-Pole-Forearm.L','IK-Pole-Forearm.R','TGT-Eye.L','TGT-Eye.R']
if args.story:
 names+=['MSTR-Eyebrow.L','MSTR-Eyebrow.R','MSTR-Jaw']+[f'FK-Hair_Ponytail{i}' for i in range(1,5)]
 names+=[f'ACT-Lips_Corner.{side}' for side in ('L','R')]
basis={n:p[n].matrix_basis.copy() for n in names}
rest={n:b.matrix.copy() for n,b in p.items()}
def update():bpy.context.view_layer.update()
def move(n,delta):
 m=p[n].matrix.copy();m.translation+=Vector(delta);p[n].matrix=m;update()
def rot(n,axis,degrees):
 m=p[n].matrix.copy();x=m.translation;p[n].matrix=Matrix.Translation(x)@Quaternion(Vector(axis),math.radians(degrees)).to_matrix().to_4x4()@Matrix.Translation(-x)@m;update()
hands={}
for side in ('L','R'):
 wrist=rest['IK-Hand.'+side].translation
 direction=(rest['FK-Middle3.'+side].translation-wrist).normalized()
 normal=(rest['FK-Index1.'+side].translation-wrist).cross(rest['FK-Pinky1.'+side].translation-wrist).normalized()
 if normal.z<0:normal=-normal
 q1=direction.rotation_difference(Vector((0,0,1)));n=q1@normal
 theta=math.atan2(Vector((0,0,1)).dot(n.cross(Vector((0,1,0)))),n.dot(Vector((0,1,0))))
 q=Quaternion(Vector((0,0,1)),theta)@q1
 hands[side]=q.to_matrix().to_4x4()@rest['IK-Hand.'+side]
KEYS=[
 (0,(.06,8,0,0,0,0,0)),(.35,(.06,8,0,0,0,0,0)),
 (1.15,(.09,18,-.025,0,0,0,0)),(1.55,(.09,18,-.025,0,0,0,0)),
 (1.9,(.07,9,0,.085,0,0,0)),(2.0,(.07,9,0,.085,0,0,0)),
 (2.3,(.10,13,.015,.085,.09,0,.07)),(2.6,(.14,16,.015,.085,.18,0,0)),
 (2.95,(.16,16,.015,0,.18,0,0)),(3.2,(.17,22,-.015,0,.18,0,0)),
 (4.4,(.18,24,-.10,0,.18,.12,0)),(4.8,(.18,24,-.10,0,.18,.12,0)),
 (5.2,(.18,16,-.10,0,.18,.12,0)),(6,(.18,16,-.10,0,.18,.12,0))]
def values(t):
 for (a,va),(b,vb) in zip(KEYS,KEYS[1:]):
  if t<=b:
   x=max(0,min(1,(t-a)/(b-a)));x=x*x*x*(10+x*(-15+6*x))
   return [u+(v-u)*x for u,v in zip(va,vb)]
 return KEYS[-1][1]
def ease(t,a,b):
 x=max(0,min(1,(t-a)/(b-a)))
 return x*x*x*(10+x*(-15+6*x))

def story_beats(t):
 glance=ease(t,1.55,1.95)*(1-ease(t,2.30,2.65))
 effort=ease(t,3.7,4.3)*(1-ease(t,5.8,6.4))
 fatigue=ease(t,6.25,7.15)
 return glance,effort,fatigue

def head_yaw(t):
 glance,_,fatigue=story_beats(t)
 return 70*glance+15*fatigue

def pose(t):
 story_time=t
 if args.story:t=t if t<1.5 else (1.5 if t<2.7 else t-1.2)
 for n,m in basis.items():p[n].matrix_basis=m
 update()
 lower,lean,hip_y,hip_x,step,shift,lift=values(t)
 if args.story:
  glance,effort,fatigue=story_beats(story_time)
  attempt=ease(story_time,.08,.65)*(1-ease(story_time,.85,1.35))
  lean+=22*effort+17*attempt-6*glance
  hip_y+=.10*effort+.07*attempt
  lower+=.015*attempt-.025*glance+.015*fatigue
  hip_x+=.015*glance+.01*fatigue
  release=ease(story_time,6.55,7.25)
 # A step has continuous forward travel through the top of its arc.
 u=max(0,min(1,(t-2.0)/.6));u=u*u*u*(10+u*(-15+6*u))
 step=.18*u;lift=.07*math.sin(math.pi*u)
 move('MSTR-Pelvis',(hip_x,hip_y-.10,-lower))
 move('MSTR-Foot.L',(.065,-.10,0));move('MSTR-Foot.R',(-.065,.08+step,lift))
 rot('FK-Spine',(1,0,0),lean*.55);rot('FK-Chest',(1,0,0),lean*.45)
 rot('FK-Head',(1,0,0),-lean*.65);rot('FK-Scarf1',(1,0,0),-lean*.65)
 if args.story:
  glance,effort,fatigue=story_beats(story_time)
  rot('FK-Head',(0,0,1),head_yaw(story_time))
  rot('FK-Head',(1,0,0),-8*(1-ease(story_time,.3,1.1))+24*fatigue-12*effort)
  move('MSTR-Eyebrow.L',(0,0,.012*(1-ease(story_time,.4,1.0))+.013*glance-.008*effort+.006*fatigue))
  move('MSTR-Eyebrow.R',(0,0,-.004*glance-.008*effort+.003*fatigue))
  rot('MSTR-Jaw',(1,0,0),4*effort+5*fatigue)
  for side in ('L','R'):
   p[f'ACT-Lips_Corner.{side}'].location.y+=.003*glance-.008*fatigue
  update()
  # Authored drag follows the head turn, with progressively delayed tips.
  head_delta=p['FK-Head'].matrix.to_quaternion()@rest['FK-Head'].to_quaternion().inverted()
  for i,droop in enumerate((10,25,20,10),1):
   delay=.045*i
   lag=(head_yaw(story_time-delay)-head_yaw(story_time))*.30
   rot(f'FK-Hair_Ponytail{i}',head_delta@Vector((1,0,0)),-droop)
   rot(f'FK-Hair_Ponytail{i}',(0,0,1),lag)
 targets={}
 for side,sign in [('L',1),('R',-1)]:
  m=hands[side].copy();m.translation=Vector((sign*.20,-.4565-shift,1.0))
  if args.story and side=='L':
   # Peel away from the surface before lowering; the other hand stays planted.
   peel=ease(story_time,6.55,6.85)
   m.translation+=Vector((.20*release,.10*peel+.23*release,-.15*release))
   q=Quaternion(Vector((0,1,0)),math.radians(140*release))@m.to_quaternion()
   m=Matrix.LocRotScale(m.translation,q,Vector((1,1,1)))
  p['IK-Hand.'+side].matrix=m;update()
  pole=p['IK-Pole-Forearm.'+side].matrix.copy();pole.translation=Vector((sign*.55,.05,.98));p['IK-Pole-Forearm.'+side].matrix=pole;update()
  targets[side]=m.translation.copy()
  gaze=p['TGT-Eye.'+side].matrix.copy();gaze.translation=Vector((0,-.8-shift,1.15))
  if args.story:
   eye_lead=ease(story_time,1.45,1.75)*(1-ease(story_time,2.22,2.48))
   gaze.translation=gaze.translation.lerp(Vector((3,.3,1.6)),eye_lead).lerp(Vector((.1,-.7-shift,.85)),fatigue)
  p['TGT-Eye.'+side].matrix=gaze;update()
 crate.location.y=-.715-shift
 report={'wrist_error_m':{side:(p['FK-Hand.'+side].matrix.translation-targets[side]).length for side in targets},
  'native_positions':{n:list(p[n].matrix.translation) for n in ('IK-Hand.L','IK-Hand_Loc.L','FK-Hand.L','IK-Upperarm.L','IK-Forearm.L')},
  'feet':{side:list(p['IK-Foot.'+side].matrix.translation) for side in targets},
  'ankle_error_m':{side:(p['IK-Shin.'+side].tail-p['IK-Foot.'+side].matrix.translation).length for side in targets},
  'contact_sides':['R'] if args.story and release>0 else ['L','R'],
  'controls':{n:[list(row) for row in p[n].matrix] for n in names},'hips':list(p['MSTR-Pelvis'].matrix.translation),'box_y':crate.location.y,'foot_lift_m':lift,'body_bounds':{}}
 dg=bpy.context.evaluated_depsgraph_get()
 for n in ('GEO-rain-shoes','GEO-rain-top','GEO-rain-body','GEO-rain-jeans','GEO-rain-head'):
  ob=bpy.data.objects[n];ev=ob.evaluated_get(dg);me=ev.to_mesh();points=[ev.matrix_world@v.co for v in me.vertices]
  report['body_bounds'][n]={'min':[min(v[i] for v in points) for i in range(3)],'max':[max(v[i] for v in points) for i in range(3)]}
  if n=='GEO-rain-head':
   relevant=[v for v in points if abs(v.x)<=.34 and 0<=v.z<=1.25]
   report['head_crate_gap_m']=min((v.y-(crate.location.y+.225) for v in relevant),default=1)
  if n=='GEO-rain-body':
   report['hand_surface_gap_m']={}
   for side in ('L','R'):
    groups={g.index for g in ob.vertex_groups if g.name.endswith('.'+side) and any(x in g.name for x in ('Hand','Index','Middle','Ring','Pinky','Thumb'))}
    selected=[points[v.index] for v in me.vertices if any(g.group in groups and g.weight>.5 for g in v.groups)]
    report['hand_surface_gap_m'][side]=min(v.y for v in selected)-(crate.location.y+.225)
  if n=='GEO-rain-shoes':
   report['sole_gap_m']={}
   for side in ('L','R'):
    groups={g.index for g in ob.vertex_groups if g.name.endswith('.'+side)}
    selected=[points[v.index] for v in me.vertices if any(g.group in groups and g.weight>.5 for g in v.groups)]
    report['sole_gap_m'][side]=min(v.z for v in selected)-.00115
  ev.to_mesh_clear()
 return report
for ob in list(s.objects):
 if ob.type in ('LIGHT','CAMERA'):bpy.data.objects.remove(ob,do_unlink=True)
floor=cube('floor',(0,0,-.02385),(200,200,.05),material('floor',(.06,.08,.10)))
crate=cube('Crate',(0,-.715,.625),(.68,.45,1.25),material('heavy painted metal',(.12,.22,.18),.4),.015)
if args.story:
 metal=material('crate dark framing',(.045,.065,.06),.45)
 for x in (-.323,.323):
  for y in (-.208,.208):
   ob=cube('CrateCorner',(x,crate.location.y+y,.625),(.034,.034,1.25),metal,.005)
   ob.parent=crate;ob.matrix_parent_inverse=crate.matrix_world.inverted()
 wall=cube('Workshop wall',(0,-3,1.6),(12,.15,3.2),material('blue plaster',(.12,.18,.21)))
 cube('Wall skirting',(0,-2.9,.13),(12,.08,.26),material('skirting',(.055,.085,.095)))
 mark=material('worn floor mark',(.35,.32,.22))
 cube('Original box back edge',(0,-.473,.005),(.75,.03,.008),mark)
 for x in (-.365,.365):cube('Original box side edge',(x,-.70,.005),(.03,.48,.008),mark)

def aim(ob,target):ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(4,2,2.3));cam=bpy.context.object;cam.data.type='ORTHO';cam.data.ortho_scale=2.1;aim(cam,(0,-.25,.8));s.camera=cam
for loc,power,size in [((2,1,5),650,4),((-3,-2,3),450,3),((1,-4,4),550,3)]:
 bpy.ops.object.light_add(type='AREA',location=loc);l=bpy.context.object;l.data.energy=power;l.data.size=size;aim(l,(0,-.3,1))
s.world=bpy.data.worlds.new('world');s.world.use_nodes=True;s.world.node_tree.nodes['Background'].inputs[0].default_value=(.16,.21,.28,1);s.world.node_tree.nodes['Background'].inputs[1].default_value=.35
s.render.engine='BLENDER_EEVEE';s.render.resolution_x=640;s.render.resolution_y=640;s.render.resolution_percentage=100;s.render.image_settings.file_format='PNG';s.view_settings.view_transform='AgX';s.render.fps=30
report={}
total=240 if args.story else 180
frames=[int(f) for f in args.frames.split(',')] if args.frames else (list(range(total)) if args.render or args.check_only else ([0,18,40,60,100,150,210,239] if args.story else [0,35,57,69,78,96,132,179]))
if not frames or len(set(frames))!=len(frames) or any(f<0 or f>=total for f in frames):raise ValueError('Frames must be unique and inside the scene')
cached={}; previous=None
for f in frames:
 report[f]=pose(f/30)
 item=report[f]
 if item['head_crate_gap_m']<.005:raise RuntimeError(f'Head too close to crate at {f}: {item["head_crate_gap_m"]}')
 if max(item['wrist_error_m'].values())>.002 or max(item['ankle_error_m'].values())>.002:
  (OUT/'failed.json').write_text(json.dumps({'frame':f,'data':item},indent=2));raise RuntimeError(f'Unreachable contact at {f}')
 if min(item['hand_surface_gap_m'].values())<-.001 or max(item['hand_surface_gap_m'][side] for side in item['contact_sides'])>.003:
  raise RuntimeError(f'Hand skin loses contact at {f}: {item["hand_surface_gap_m"]}')
 if abs(item['sole_gap_m']['L'])>.002 or abs(item['sole_gap_m']['R']-item['foot_lift_m'])>.002:
  raise RuntimeError(f'Sole loses expected support at {f}: {item["sole_gap_m"]}')
 cached[f]={n:p[n].matrix_basis.copy() for n in names}
 if f%30==0:print('CHECK',f,flush=True)
(OUT/'preflight.json').write_text(json.dumps(report,indent=2))
if args.check_only:
 print('CHECK_ONLY',len(frames));sys.exit(0)
max_cache_error=0
for f in frames:
 for n,m in cached[f].items():p[n].matrix_basis=m
 crate.location.y=report[f]['box_y'];update()
 err=max(abs(p[n].matrix[i][j]-report[f]['controls'][n][i][j]) for n in names for i in range(4) for j in range(4))
 max_cache_error=max(max_cache_error,err)
 if err>1e-5:raise RuntimeError(f'Cached pose mismatch at {f}: {err}')
 views=[('three_quarter',(4,2,2.3))] if args.render else [('three_quarter',(4,2,2.3)),('side',(5,0,1.9))]
 if args.render and args.overview:views.append(('overview',(4,1.2,2.2)))
 for view,location in views:
  target=(0,-.25,.8);cam.data.ortho_scale=2.1
  s.render.resolution_percentage=50 if view=='overview' else 100
  if view=='overview':cam.data.ortho_scale=2.25
  if args.story and view=='three_quarter':
   close=48<=f<80 or f>=195
   location=(3,.3,1.9) if close else (4,1.2,2.2)
   target=((.08,-.25,1.13) if f>=195 else (.05,-.13,1.27)) if close else (0,-.25,.8)
   cam.data.ortho_scale=(1.25 if f>=195 else .88) if close else 2.25
   if 174<=f<195:
    location=(3,1,1.0);target=(0,-.55,.18);cam.data.ortho_scale=1.05
  cam.location=location;aim(cam,target);s.render.filepath=str(OUT/(f'{f:04d}.png' if args.render and view=='three_quarter' else f'{f:04d}_{view}.png'));bpy.ops.render.render(write_still=True)
(OUT/'complete.json').write_text(json.dumps({'frames':len(frames),'fps':30,'source':'Rain v3.3, CC BY 4.0, Blender Foundation','source_sha256':source_hash,'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==source_hash,'max_cache_error':max_cache_error,'story':args.story,'scope':'Authored scene study, not a universal action preset'},indent=2))
print('PUSH_STUDY_DONE',len(frames))
