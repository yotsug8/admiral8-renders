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
parser.add_argument('--frames',default='0,35,57,69,78,96,132,179')
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
def pose(t):
 for n,m in basis.items():p[n].matrix_basis=m
 update()
 lower,lean,hip_y,hip_x,step,shift,lift=values(t)
 # A step has continuous forward travel through the top of its arc.
 u=max(0,min(1,(t-2.0)/.6));u=u*u*u*(10+u*(-15+6*u))
 step=.18*u;lift=.07*math.sin(math.pi*u)
 move('MSTR-Pelvis',(hip_x,hip_y-.10,-lower))
 move('MSTR-Foot.L',(.065,-.10,0));move('MSTR-Foot.R',(-.065,.08+step,lift))
 rot('FK-Spine',(1,0,0),lean*.55);rot('FK-Chest',(1,0,0),lean*.45)
 rot('FK-Head',(1,0,0),-lean*.65);rot('FK-Scarf1',(1,0,0),-lean*.65)
 targets={}
 for side,sign in [('L',1),('R',-1)]:
  m=hands[side].copy();m.translation=Vector((sign*.20,-.4565-shift,1.0));p['IK-Hand.'+side].matrix=m;update()
  pole=p['IK-Pole-Forearm.'+side].matrix.copy();pole.translation=Vector((sign*.55,.05,.98));p['IK-Pole-Forearm.'+side].matrix=pole;update()
  targets[side]=m.translation.copy()
  gaze=p['TGT-Eye.'+side].matrix.copy();gaze.translation=Vector((0,-.8-shift,1.15));p['TGT-Eye.'+side].matrix=gaze;update()
 crate.location.y=-.715-shift
 report={'wrist_error_m':{side:(p['FK-Hand.'+side].matrix.translation-targets[side]).length for side in targets},
  'native_positions':{n:list(p[n].matrix.translation) for n in ('IK-Hand.L','IK-Hand_Loc.L','FK-Hand.L','IK-Upperarm.L','IK-Forearm.L')},
  'feet':{side:list(p['IK-Foot.'+side].matrix.translation) for side in targets},
  'ankle_error_m':{side:(p['IK-Shin.'+side].tail-p['IK-Foot.'+side].matrix.translation).length for side in targets},
  'hips':list(p['MSTR-Pelvis'].matrix.translation),'box_y':crate.location.y,'foot_lift_m':lift,'body_bounds':{}}
 dg=bpy.context.evaluated_depsgraph_get()
 for n in ('GEO-rain-shoes','GEO-rain-top','GEO-rain-body','GEO-rain-jeans'):
  ob=bpy.data.objects[n];ev=ob.evaluated_get(dg);me=ev.to_mesh();points=[ev.matrix_world@v.co for v in me.vertices]
  report['body_bounds'][n]={'min':[min(v[i] for v in points) for i in range(3)],'max':[max(v[i] for v in points) for i in range(3)]}
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
def aim(ob,target):ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(4,2,2.3));cam=bpy.context.object;cam.data.type='ORTHO';cam.data.ortho_scale=2.1;aim(cam,(0,-.25,.8));s.camera=cam
for loc,power,size in [((2,1,5),650,4),((-3,-2,3),450,3),((1,-4,4),550,3)]:
 bpy.ops.object.light_add(type='AREA',location=loc);l=bpy.context.object;l.data.energy=power;l.data.size=size;aim(l,(0,-.3,1))
s.world=bpy.data.worlds.new('world');s.world.use_nodes=True;s.world.node_tree.nodes['Background'].inputs[0].default_value=(.16,.21,.28,1);s.world.node_tree.nodes['Background'].inputs[1].default_value=.35
s.render.engine='BLENDER_EEVEE';s.render.resolution_x=640;s.render.resolution_y=640;s.render.resolution_percentage=100;s.render.image_settings.file_format='PNG';s.view_settings.view_transform='AgX';s.render.fps=30
report={}
frames=list(range(180)) if args.render else [int(f) for f in args.frames.split(',')]
cached={}; previous=None
for f in frames:
 report[f]=pose(f/30)
 item=report[f]
 if max(item['wrist_error_m'].values())>.002 or max(item['ankle_error_m'].values())>.002:
  (OUT/'failed.json').write_text(json.dumps({'frame':f,'data':item},indent=2));raise RuntimeError(f'Unreachable contact at {f}')
 if min(item['hand_surface_gap_m'].values())<-.001 or max(item['hand_surface_gap_m'].values())>.003:
  raise RuntimeError(f'Hand skin loses contact at {f}: {item["hand_surface_gap_m"]}')
 if abs(item['sole_gap_m']['L'])>.002 or abs(item['sole_gap_m']['R']-item['foot_lift_m'])>.002:
  raise RuntimeError(f'Sole loses expected support at {f}: {item["sole_gap_m"]}')
 cached[f]={n:p[n].matrix_basis.copy() for n in names}
 if f%30==0:print('CHECK',f,flush=True)
(OUT/'preflight.json').write_text(json.dumps(report,indent=2))
for f in frames:
 for n,m in cached[f].items():p[n].matrix_basis=m
 crate.location.y=report[f]['box_y'];update()
 for view,location in ([('three_quarter',(4,2,2.3))] if args.render else [('three_quarter',(4,2,2.3)),('side',(5,0,1.9))]):
  cam.location=location;aim(cam,(0,-.25,.8));s.render.filepath=str(OUT/(f'{f:04d}.png' if args.render else f'{f:04d}_{view}.png'));bpy.ops.render.render(write_still=True)
(OUT/'complete.json').write_text(json.dumps({'frames':len(frames),'fps':30,'source':'Rain v3.3, CC BY 4.0, Blender Foundation','source_sha256':source_hash,'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==source_hash,'scope':'Body push study, not a universal action preset'},indent=2))
print('PUSH_STUDY_DONE',len(frames))
