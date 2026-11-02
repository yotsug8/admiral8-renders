"""Rain rising study: shift support from seat and palms onto both feet."""
from pathlib import Path
import bpy, math, json, sys, argparse, hashlib, os, shutil
from mathutils import Vector,Matrix,Quaternion
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/blender'))
from study_lift import material,cube
parser=argparse.ArgumentParser()
parser.add_argument('--out',required=True)
parser.add_argument('--render',action='store_true')
parser.add_argument('--diagnostic',action='store_true')
parser.add_argument('--check-only',action='store_true')
parser.add_argument('--frames',default='0,24,42,54,69,90,119')
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
 q1=direction.rotation_difference(Vector((0,-1,0)));n=q1@normal
 theta=math.atan2(Vector((0,-1,0)).dot(n.cross(Vector((0,0,1)))),n.dot(Vector((0,0,1))))
 q=Quaternion(Vector((0,-1,0)),theta)@q1
 hands[side]=q.to_matrix().to_4x4()@rest['IK-Hand.'+side]
# time, pelvis down/back, forward lean, hand lift/back, elbows out
KEYS=[(0,(.43,.20,8,0,0)),(.35,(.43,.20,8,0,0)),
 (.85,(.43,.13,30,0,0)),(1.25,(.38,.05,35,0,0)),
 (1.65,(.27,-.025,27,.12,-.04)),(2.25,(.08,-.07,8,.35,-.04)),
 (2.65,(.015,-.07,-3,.39,-.02)),(3.1,(.025,-.07,0,.37,0)),(4,(.025,-.07,0,.37,0))]
SEAT=.46
ARMREST=.60

def values(t):
 for (a,va),(b,vb) in zip(KEYS,KEYS[1:]):
  if t<=b:
   x=max(0,min(1,(t-a)/(b-a)));x=x*x*x*(10+x*(-15+6*x))
   return [u+(v-u)*x for u,v in zip(va,vb)]
 return KEYS[-1][1]

def pose(t):
 for n,m in basis.items():p[n].matrix_basis=m
 update()
 lower,back,lean,lift,hand_back=values(t)
 correction=.134*(1-max(0,min(1,(t-1.25)/1.4)))
 correction+=.004*(1-min(1,t/.85))
 move('MSTR-Pelvis',(0,back,-lower+correction))
 move('MSTR-Foot.L',(.055,-.15,0));move('MSTR-Foot.R',(-.055,-.15,0))
 rot('FK-Spine',(1,0,0),lean*.45);rot('FK-Chest',(1,0,0),lean*.55)
 rot('FK-Head',(1,0,0),-lean*.65);rot('FK-Scarf1',(1,0,0),-lean*.65)
 targets={}
 for side,sign in [('L',1),('R',-1)]:
  release=max(0,min(1,(t-.90)/.80));release=release*release*(3-2*release)
  relax=max(0,min(1,(t-1.65)/1.25));relax=relax*relax*(3-2*relax)
  m=Quaternion(Vector((1,0,0)),math.radians(90)*relax).to_matrix().to_4x4()@hands[side]
  initial=Vector((sign*(.29-.05*release),.12+hand_back-.30*release,ARMREST+.0335+lift+.02*release+.10*math.sin(math.pi*release)))
  m.translation=initial.lerp(Vector((sign*.24,-.15,.86)),relax);p['IK-Hand.'+side].matrix=m;update()
  pole=p['IK-Pole-Forearm.'+side].matrix.copy();pole.translation=Vector((sign*.55,.05,.9));p['IK-Pole-Forearm.'+side].matrix=pole;update()
  targets[side]=m.translation.copy()
  gaze=p['TGT-Eye.'+side].matrix.copy();gaze.translation=Vector((0,-1,1.2));p['TGT-Eye.'+side].matrix=gaze;update()
 report={'wrist_error_m':{side:(p['FK-Hand.'+side].matrix.translation-targets[side]).length for side in targets},
  'ankle_error_m':{side:(p['IK-Shin.'+side].tail-p['IK-Foot.'+side].matrix.translation).length for side in targets},
  'hips':list(p['MSTR-Pelvis'].matrix.translation),'chest':list(p['FK-Chest'].matrix.translation),
  'contact_hands':t<=.90,'contact_seat':t<=.85,'hand_lift_m':lift,
  'controls':{n:[list(row) for row in p[n].matrix] for n in names},'body_bounds':{}}
 dg=bpy.context.evaluated_depsgraph_get()
 for n in ('GEO-rain-shoes','GEO-rain-body','GEO-rain-jeans'):
  ob=bpy.data.objects[n];ev=ob.evaluated_get(dg);me=ev.to_mesh();points=[ev.matrix_world@v.co for v in me.vertices]
  report['body_bounds'][n]={'min':[min(v[i] for v in points) for i in range(3)],'max':[max(v[i] for v in points) for i in range(3)]}
  if n=='GEO-rain-body':
   report['hand_surface_gap_m']={}
   for side in ('L','R'):
    groups={g.index for g in ob.vertex_groups if g.name.endswith('.'+side) and any(x in g.name for x in ('Hand','Index','Middle','Ring','Pinky','Thumb'))}
    selected=[points[v.index] for v in me.vertices if any(g.group in groups and g.weight>.5 for g in v.groups)]
    report['hand_surface_gap_m'][side]=min(v.z for v in selected)-ARMREST
  if n=='GEO-rain-shoes':
   report['sole_gap_m']={}
   for side in ('L','R'):
    groups={g.index for g in ob.vertex_groups if g.name.endswith('.'+side)}
    selected=[points[v.index] for v in me.vertices if any(g.group in groups and g.weight>.5 for g in v.groups)]
    report['sole_gap_m'][side]=min(v.z for v in selected)-.00115
  if n=='GEO-rain-jeans':
   above=[v for v in points if abs(v.x)<.42 and .04<v.y<.54]
   report['seat_gap_m']=min((v.z-SEAT for v in above),default=1)
  ev.to_mesh_clear()
 return report

for ob in list(s.objects):
 if ob.type in ('LIGHT','CAMERA'):bpy.data.objects.remove(ob,do_unlink=True)
floor=cube('floor',(0,0,-.02385),(200,200,.05),material('floor',(.06,.08,.10)))
seat=cube('Seat',(0,.29,SEAT-.04),(.84,.5,.08),material('wood',(.22,.12,.06),.5),.015)
for x in (-.29,.29):
 cube('Armrest',(x,.12,ARMREST-.025),(.13,.4,.05),material('armrest',(.22,.12,.06),.5),.01)
 cube('Armrest support',(x,.27,(SEAT+ARMREST)/2),(.045,.045,ARMREST-SEAT),material('metal',(.06,.07,.08)))
for x in (-.34,.34):
 for y in (.10,.48):cube('Leg',(x,y,(SEAT-.08)/2),(.06,.06,SEAT-.08),material('dark metal',(.06,.07,.08)))
def aim(ob,target):ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(4,-3,2.2));cam=bpy.context.object;cam.data.type='ORTHO';cam.data.ortho_scale=2.05;aim(cam,(0,.1,.8));s.camera=cam
for loc,power,size in [((2,-1,5),650,4),((-3,-2,3),450,3),((1,4,4),550,3)]:
 bpy.ops.object.light_add(type='AREA',location=loc);l=bpy.context.object;l.data.energy=power;l.data.size=size;aim(l,(0,0,1))
s.world=bpy.data.worlds.new('world');s.world.use_nodes=True;s.world.node_tree.nodes['Background'].inputs[0].default_value=(.16,.21,.28,1);s.world.node_tree.nodes['Background'].inputs[1].default_value=.35
s.render.engine='BLENDER_EEVEE';s.render.resolution_x=640;s.render.resolution_y=640;s.render.resolution_percentage=100;s.render.image_settings.file_format='PNG';s.view_settings.view_transform='AgX';s.render.fps=30
frames=list(range(120)) if args.render or args.check_only else [int(f) for f in args.frames.split(',')]
report={};cached={}
for f in frames:
 item=report[f]=pose(f/30)
 failures=[]
 if max(item['wrist_error_m'].values())>.002 or max(item['ankle_error_m'].values())>.002:failures.append('Unreachable IK')
 if max(abs(v) for v in item['sole_gap_m'].values())>.002:failures.append('Sole contact')
 if min(item['hand_surface_gap_m'].values())<-.001:failures.append('Hand penetrates seat plane')
 if item['contact_hands'] and max(item['hand_surface_gap_m'].values())>.003:failures.append('Hand floats')
 if item['seat_gap_m']<-.002:failures.append('Jeans penetrate seat')
 if item['contact_seat'] and item['seat_gap_m']>.006:failures.append('Pelvis floats above seat')
 item['failures']=failures
 cached[f]={n:p[n].matrix_basis.copy() for n in names}
 if f%30==0:print('CHECK',f,flush=True)
(OUT/'preflight.json').write_text(json.dumps(report,indent=2))
failed={f:v['failures'] for f,v in report.items() if v['failures']}
if failed:
 (OUT/'failed.json').write_text(json.dumps(failed,indent=2))
 if not args.diagnostic:raise RuntimeError(f'Contact checks failed: {failed}')
if args.check_only:
 print('CHECK_ONLY',len(frames),'failures',failed,flush=True);sys.exit(0)
max_cache_error=0
for f in frames:
 for n,m in cached[f].items():p[n].matrix_basis=m
 update()
 err=max(abs(p[n].matrix[i][j]-report[f]['controls'][n][i][j]) for n in names for i in range(4) for j in range(4))
 max_cache_error=max(max_cache_error,err)
 if err>1e-5:raise RuntimeError(f'Pose cache mismatch at {f}: {err}')
 for view,location in ([('three_quarter',(4,-3,2.2))] if args.render else [('three_quarter',(4,-3,2.2)),('side',(5,0,1.7))]):
  cam.location=location;aim(cam,(0,.1,.8));s.render.filepath=str(OUT/(f'{f:04d}.png' if args.render else f'{f:04d}_{view}.png'));bpy.ops.render.render(write_still=True)
(OUT/'complete.json').write_text(json.dumps({'frames':len(frames),'fps':30,'source':'Rain v3.3, CC BY 4.0, Blender Foundation','source_sha256':source_hash,'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==source_hash,'max_cache_error':max_cache_error,'diagnostic':args.diagnostic},indent=2))
print('RISE_STUDY_DONE',len(frames))


