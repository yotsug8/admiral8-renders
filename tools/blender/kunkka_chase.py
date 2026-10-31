"""Build the Kunkka/Hoodwink chase on a prepared map scene, without rendering.

Blender -b map_scene.blend -P tools/blender/kunkka_chase.py -- --out _game/skits/chase
Prepare hero assets with tools/skit/hero_render.py first. Use --preview for half-size probes; --full prepares 1080x1920 at 30 fps.
The builder never starts a render.
"""
from pathlib import Path
import bpy,sys,math,json,re,os,ast,argparse
from mathutils import Matrix,Vector
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,default=ROOT/'_game/skits/chase')
parser.add_argument('--full',action='store_true')
parser.add_argument('--preview',action='store_true')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
P=args.out.resolve();P.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools/blender'))
spec=json.loads((ROOT/'skits/kunkka_chase.json').read_text(encoding='utf-8'))
if args.full:spec.update(fps=30,resolution=[1080,1920])
if args.preview:spec['resolution']=[540,960]
SEARCH_END, FOUND_END, REVEAL_END, PANIC_END, SIDE_END, FRONT_END, CLOSE_END, STORY_END = [shot['end'] for shot in spec['shots']]
if abs(STORY_END-spec['duration'])>1e-9:raise ValueError('Storyboard duration mismatch')
if not bpy.data.filepath:
 raise ValueError('Load a prepared map .blend with -b before running this builder')
sc=bpy.context.scene
FPS=spec['fps'];END=round(spec['duration']*FPS)-1
sc.render.fps=FPS;sc.frame_start=0;sc.frame_end=END
# Clear the old cast, leaving the map, sky and accepted lighting.
for who in ('pudge','sniper','kunkka','hoodwink'):
 root=bpy.data.objects.get(who+'_root')
 if root:
  for obj in list(root.children_recursive)[::-1]:bpy.data.objects.remove(obj,do_unlink=True)
  bpy.data.objects.remove(root,do_unlink=True)
for obj in list(sc.objects):
 if obj.type=='CAMERA':
  bpy.data.objects.remove(obj,do_unlink=True)
  continue
 if obj.type=='LIGHT':
  obj.animation_data_clear();obj.constraints.clear()
if sc.animation_data:sc.animation_data_clear()
sc.frame_set(0)
source=ROOT/'tools/blender/render_scene.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
names={'imp','fix_hero_mats','close_neck','mouth_dark','dota_shade','blob_shadow'}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
nodes += [n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('HERO','DOTA') for t in n.targets)]
assert len([n for n in nodes if isinstance(n,ast.FunctionDef)])==len(names)
S=1/39.37;R=math.radians;HERO_OBJS=set();ACTORS={}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),globals())
db=json.loads((ROOT/'_game/data/troupe.json').read_text(encoding='utf-8'));rnd=ROOT/'_game/models/render'
def strip(arm,action,name,start,end,rate=1,blend=0):
 ad=arm.animation_data_create();ad.action=None
 tr=ad.nla_tracks.new();tr.name=name
 st=tr.strips.new(name,int(start),action);st.action_slot=action.slots[0]
 length=action.frame_range[1]-action.frame_range[0]
 st.scale=1/rate;st.repeat=max(1,(end-start)/(length/rate))
 st.frame_start=start;st.frame_end=end;st.extrapolation='NOTHING';st.blend_type='REPLACE'
 st.blend_in=blend;st.blend_out=0
 return st
for who in spec['cast']:
 info=db[who];objs,acts=imp(str(rnd/Path(info['glb']).name));fix_hero_mats(objs)
 arm=next(o for o in objs if o.type=='ARMATURE');root=bpy.data.objects.new(who+'_root',None);sc.collection.objects.link(root);arm.parent=root
 head=next((o for o in objs if o.type=='MESH' and o.data.shape_keys),None)
 if head:mouth_dark(head);close_neck(head,objs)
 amap={re.sub(r'\.\d{3}$','',a.name):a for a in acts}
 arm.animation_data_clear()
 for rel in info['parts']:
  path=rnd/(rel.replace('/','_').replace('.vmdl','.glb'))
  po,_=imp(str(path));fix_hero_mats(po);objs+=po
  for pa in (o for o in po if o.type=='ARMATURE'):
   pa.animation_data_clear();pa.parent=root;pa.matrix_world=arm.matrix_world.copy()
   for pb in pa.pose.bones:
    if pb.name in arm.pose.bones:
     c=pb.constraints.new('COPY_TRANSFORMS');c.target=arm;c.subtarget=pb.name
 dota_shade(objs);HERO_OBJS.update(objs)
 ACTORS[who]=dict(root=root,arm=arm,acts=amap,info=info,head=head,objs=objs)
 idle=info['idle'];act=amap.get(idle) or amap[idle+'_anim']
 strip(arm,act,'idle',0,(PANIC_END if who=='hoodwink' else FOUND_END)*FPS)
 root.location=(-81.8,108 if who=='kunkka' else 101,3.25)
 root.rotation_euler=(0,0,0 if who=='kunkka' else math.pi)
from chase_environment import prepare_forest
environment=prepare_forest(sc,HERO_OBJS)
(P/'environment.json').write_text(json.dumps(environment,indent=2))
# Cache imported actors so camera/ground corrections do not reimport large GLBs.
cache_meta={}
for who,A in ACTORS.items():
 keep={n:a for n,a in A['acts'].items() if n in (A['info']['idle'],A['info']['idle']+'_anim','mouse_run_squirrel','mouse_run_squirrel_anim','mouse_flail','mouse_flail_anim')}
 for act in keep.values():act.use_fake_user=True
 cache_meta[who]=dict(root=A['root'].name,arm=A['arm'].name,head=A['head'].name if A['head'] else None,objs=[o.name for o in A['objs']],acts={n:a.name for n,a in keep.items()},info=A['info'])
(P/'actors_cache.json').write_text(json.dumps(cache_meta))
bpy.ops.wm.save_as_mainfile(filepath=str(P/'actors_cache.blend'))

# Runners move down the open corridor. Read the audited route when available.
X=-83.;Y=78.5;SPEED=5.0
def root_at(who,t):
 progress=min(FRONT_END-PANIC_END,max(0,t-PANIC_END))*SPEED
 return Vector((X,Y+(3.5 if who=='hoodwink' else 0)+progress,3.25119+(.00885 if who=='kunkka' else .0185)))
for who,A in ACTORS.items():
 root=A['root']
 for f in range(END+1):
  t=f/FPS;root.location=root_at(who,t)
  # A cut covers the squirrel turning away before the run.
  root.rotation_euler.z=math.pi if who=='kunkka' or t>=PANIC_END else 0
  root.keyframe_insert('location',frame=f);root.keyframe_insert('rotation_euler',frame=f)
 for a in root.animation_data.action.layers:
  for st in a.strips:
   for bag in st.channelbags:
    for fc in bag.fcurves:
     for k in fc.keyframe_points:k.interpolation='CONSTANT' if fc.data_path=='rotation_euler' else 'LINEAR'
A=ACTORS['hoodwink'];run=A['acts'].get('mouse_run_squirrel') or A['acts']['mouse_run_squirrel_anim']
from chase_performance import make_seamless_run,apply_panic
run,run_report=make_seamless_run(A['arm'],run,scene=sc)
strip(A['arm'],run,'run',PANIC_END*FPS,FRONT_END*FPS,SPEED/(345.13084739699036/39.37),blend=0)
panic_report=apply_panic(ACTORS,scene=sc,FPS=FPS,start=REVEAL_END,end=PANIC_END,native_flail=A['acts'].get('mouse_flail') or A['acts'].get('mouse_flail_anim'))
from chase_ground import clear_paws
ground_report=clear_paws(A,sc,PANIC_END*FPS,FRONT_END*FPS,3.251190185546875)
(P/'ground.json').write_text(json.dumps(ground_report,indent=2))
(P/'performance.json').write_text(json.dumps(dict(run=run_report,panic=panic_report),indent=2))
# Scan with the head before the discovery cut.
from look_motion import apply_looks
apply_looks(dict(fps=FPS,frames=END+1,looks=[dict(who='kunkka',start=.15,end=1.1,yaw_deg=30,pitch_deg=0,attack=.4,release=.3),dict(who='kunkka',start=1.15,end=2.15,yaw_deg=-30,pitch_deg=0,attack=.4,release=.3)]),ACTORS,sc,FPS)
# Shared T-pose helper is added by the motion worker.
from chase_motion import apply_frozen_tpose
apply_frozen_tpose(ACTORS['kunkka']['arm'],FOUND_END*FPS,END,root=ACTORS['kunkka']['root'],scene=sc)
# Clear legacy facial actions: reveal uses a controlled expression, no silent speech.
for who,A in ACTORS.items():
 for obj in A['objs']:
  if obj.type=='MESH' and obj.data.shape_keys:
   keys=obj.data.shape_keys;keys.animation_data_clear()
   for kb in keys.key_blocks[1:]:kb.value=0
   for name in ('innerBrowRaiser','upperLidRaiser'):
    if name in keys.key_blocks:
     kb=keys.key_blocks[name]
     for f,val in [(0,0),(int(2.5*FPS),0),(int(2.9*FPS),.8),(END,.8)]:kb.value=val;kb.keyframe_insert('value',frame=f)
sc.render.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=32 if args.preview else 48;sc.eevee.use_taa_reprojection=True
sc.render.resolution_x,sc.render.resolution_y=spec['resolution'];sc.render.resolution_percentage=100
sc.render.image_settings.file_format='PNG';sc.render.film_transparent=False
sc.render.use_sequencer=False
camera=bpy.data.objects.new('chase_camera',bpy.data.cameras.new('chase_camera'));sc.collection.objects.link(camera);sc.camera=camera
camera.data.sensor_fit='VERTICAL';camera.data.clip_start=.08;camera.data.clip_end=350;camera.data.dof.use_dof=True
from bpy_extras.object_utils import world_to_camera_view

def visible(who,value):
 for obj in ACTORS[who]['objs']:
  obj.hide_render=not value
  obj.keyframe_insert('hide_render',frame=sc.frame_current)

def extent(who):
 dg=bpy.context.evaluated_depsgraph_get();points=[]
 for obj in ACTORS[who]['objs']:
  if obj.type!='MESH' or any(n in obj.name.lower() for n in ['physics','hitbox','blob']):continue
  ev=obj.evaluated_get(dg)
  points += [ev.matrix_world@Vector(v) for v in ev.bound_box]
 return points

def head_at(who):
 A=ACTORS[who];ev=A['arm'].evaluated_get(bpy.context.evaluated_depsgraph_get())
 return (ev.matrix_world@ev.pose.bones['head'].matrix).translation

FIT_FACTORS={}
SHOT_FIT={}

def place(f, forced=None):
 sc.frame_set(f);t=f/FPS;k=root_at('kunkka',t);h=root_at('hoodwink',t)
 kvis=t<SEARCH_END or FOUND_END<=t<REVEAL_END or PANIC_END<=t<CLOSE_END
 hvis=SEARCH_END<=t<FOUND_END or REVEAL_END<=t<FRONT_END
 visible('kunkka',kvis);visible('hoodwink',hvis)
 fit=[];aperture=3.2
 if t<SEARCH_END:
  target=head_at('kunkka')+Vector((0,0,-.50));pos=target+Vector((-3,6,.5));lens=43
 elif t<FOUND_END:
  target=head_at('hoodwink')+Vector((0,0,-.05));pos=target+Vector((1.9,-5.3,.4));lens=48
 elif t<REVEAL_END:
  target=k+Vector((0,0,2));pos=target+Vector((0,14,.5));lens=32;fit=['kunkka'];aperture=5.6
 elif t<PANIC_END:
  target=head_at('hoodwink')+Vector((0,0,-.05));pos=target+Vector((.9,-5.2,.3));lens=46;aperture=3.2
 elif t<SIDE_END:
  target=(k+h)/2+Vector((0,0,1.8));pos=target+Vector((-12,3,1));lens=29;fit=['kunkka','hoodwink'];aperture=5.6
 elif t<FRONT_END:
  u=min(1,max(0,(t-(FRONT_END-.35))/.35));u=u*u*(3-2*u)
  target=(h+Vector((0,-1.6,1.7))).lerp(head_at('kunkka'),u)
  pos=h+Vector((0,10,2.8));lens=27+u*9
  if t<FRONT_END-.35:fit=['kunkka','hoodwink']
  aperture=5.6
 else:
  u=min(1,max(0,(t-FRONT_END)/(CLOSE_END-FRONT_END-.2)));u=u*u*(3-2*u)
  target=head_at('kunkka')+Vector((0,0,-.05));pos=k+Vector((0,7-3.1*u,3.95));lens=38;aperture=4.0
 camera.location=pos;camera.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler();camera.data.lens=lens
 group='reveal' if FOUND_END<=t<REVEAL_END else 'side' if PANIC_END<=t<SIDE_END else 'front' if SIDE_END<=t<FRONT_END else None
 if forced is not None and group in forced:
  camera.location=target+(camera.location-target)*forced[group]
  fit=[]
 factor=1.0
 if fit:
  points=[p for who in fit for p in extent(who)]
  for attempt in range(35):
   bpy.context.view_layer.update();uv=[world_to_camera_view(sc,camera,p) for p in points]
   if all(.055<=p.x<=.945 and .055<=p.y<=.945 and p.z>.1 for p in uv):break
   camera.location=target+(camera.location-target)*1.06;factor*=1.06
  else:raise ValueError('camera cannot fit '+str((f,fit)))
 if group and forced is None:FIT_FACTORS[group]=max(FIT_FACTORS.get(group,1.0),factor)
 camera.data.dof.focus_distance=(target-camera.location).length
 camera.data.dof.aperture_fstop=aperture
 camera.data.dof.keyframe_insert('focus_distance',frame=f)
 camera.data.dof.keyframe_insert('aperture_fstop',frame=f)
for f in range(END+1):place(f)
for f in range(END+1):
 place(f,FIT_FACTORS);camera.keyframe_insert('location',frame=f);camera.keyframe_insert('rotation_euler',frame=f);camera.data.keyframe_insert('lens',frame=f)
for owner in (camera,camera.data):
 for layer in owner.animation_data.action.layers:
  for st in layer.strips:
   for bag in st.channelbags:
    for fc in bag.fcurves:
     for k in fc.keyframe_points:
      cuts={round(x['start']*FPS) for x in spec['shots'][1:]}
      k.interpolation='CONSTANT' if round(k.co.x)+1 in cuts else 'LINEAR'
# Remove only map objects that obstruct a required face from the baked cameras.
actor_objects={o for A in ACTORS.values() for o in A['objs']}
removed=[]
for f in range(END+1):
 sc.frame_set(f);t=f/FPS
 focus=[] if t>=CLOSE_END else ['kunkka'] if t<SEARCH_END or FOUND_END<=t<REVEAL_END or t>=FRONT_END else ['hoodwink'] if t<FOUND_END or REVEAL_END<=t<PANIC_END else ['kunkka','hoodwink']
 for who in focus:
  target=head_at(who)
  for attempt in range(12):
   bpy.context.view_layer.update();origin=camera.matrix_world.translation.copy();ray=target-origin;length=ray.length;ray.normalize()
   blocker=None
   for skip in range(30):
    hit,point,normal,index,obj,matrix=sc.ray_cast(bpy.context.evaluated_depsgraph_get(),origin,ray,distance=length)
    if not hit:break
    obj=obj.original
    if obj not in actor_objects:
     blocker=obj;break
    origin=point+ray*.015;length=(target-origin).dot(ray)
    if length<=.02:break
   if blocker is None:break
   if blocker.type!='MESH' or 'tree' not in blocker.name.lower():
    raise ValueError('Camera crosses solid scenery; change camera instead of hiding terrain: '+blocker.name)
   parts={blocker}
   for old,new in (('_model.','_inspector.'),('_inspector.','_model.')):
    if old in blocker.name:
     paired=bpy.data.objects.get(blocker.name.replace(old,new))
     if paired:parts.add(paired)
   for part in parts:
    removed.append(dict(frame=f,focus=who,object=part.name))
    part.hide_render=True;part.hide_viewport=True
  else:raise ValueError('Could not clear camera')
(P/'camera_clearing.json').write_text(json.dumps(removed,indent=2))

sc.frame_set(0)
bpy.ops.wm.save_as_mainfile(filepath=str(P/'scene.blend'))
(P/'build_report.json').write_text(json.dumps(dict(frames=END+1,fps=FPS,actors={n:dict(bones=len(a['arm'].pose.bones),head=a['head'].name if a['head'] else None,actions=list(a['acts'])) for n,a in ACTORS.items()}),indent=2))
print('CHASE_BUILT',flush=True)
