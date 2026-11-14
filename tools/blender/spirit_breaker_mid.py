"""Local Spirit Breaker blocking. Blender -b -P this_file -- [--probes]."""
import bpy
import argparse
import json
import math
import random
import sys
from pathlib import Path
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from resource_paths import RESOURCES
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, default=ROOT / 'out/spirit-breaker-mid/v8')
parser.add_argument('--probes', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
OUT = args.out.resolve()
if (OUT / 'draft.blend').exists():
    raise RuntimeError('Scene already exists; choose a new --out folder to preserve it')
QA = OUT / 'qa'
GAME = ROOT / '_game/models/render'
OUT.mkdir(parents=True, exist_ok=True)
QA.mkdir(parents=True, exist_ok=True)
FPS, END = 30, 210


def aim(obj, point):
    obj.rotation_euler = (Vector(point)-obj.location).to_track_quat('-Z', 'Y').to_euler()


def import_model(path):
    before, acts = set(bpy.data.objects), set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(path), bone_heuristic='BLENDER')
    objects = list(set(bpy.data.objects)-before)
    for o in objects[:]:
        if o.name.startswith('Icosphere') or 'hitbox' in o.name.lower():
            objects.remove(o)
            bpy.data.objects.remove(o, do_unlink=True)
    return objects, list(set(bpy.data.actions)-acts)


def actor(name, path, parts=(), scale=.8):
    objects, actions = import_model(path)
    arm = next(o for o in objects if o.type == 'ARMATURE')
    body = [o for o in objects if o.type == 'MESH']
    arm.animation_data_clear()
    root = bpy.data.objects.new(name, None)
    scene.collection.objects.link(root)
    for o in objects:
        if not o.parent:
            o.parent = root
    for path in parts:
        obs, _ = import_model(path)
        for a in [o for o in obs if o.type == 'ARMATURE']:
            a.animation_data_clear()
            for b in a.pose.bones:
                match = next((n for n in arm.pose.bones.keys() if n.lower() == b.name.lower()), None)
                if match:
                    c = b.constraints.new('COPY_TRANSFORMS')
                    c.target, c.subtarget = arm, match
        for o in obs:
            if not o.parent:
                o.parent = root
        objects.extend(obs)
    for o in objects:
        if o.type == 'MESH' and o.data.shape_keys:
            o.data.shape_keys.animation_data_clear()
            for k in o.data.shape_keys.key_blocks:
                k.value = 0
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.use_deform_preserve_volume = True
        for slot in getattr(o, 'material_slots', []):
            m = slot.material
            if not m or not m.use_nodes:
                continue
            for n in m.node_tree.nodes:
                if n.type != 'BSDF_PRINCIPLED':
                    continue
                for field, value in [('Alpha', 1), ('Metallic', 0), ('Roughness', .63), ('Emission Strength', 0)]:
                    for link in list(n.inputs[field].links):
                        m.node_tree.links.remove(link)
                    n.inputs[field].default_value = value
    root.scale = (scale,)*3
    return dict(root=root, arm=arm, body=body, objects=objects, actions=actions, scale=scale)


def sample(a, action_name, count=40):
    arm = a['arm']
    act = next(x for x in a['actions'] if x.name == action_name or x.name.startswith(action_name+'.'))
    arm.animation_data_create()
    arm.animation_data.action = act
    arm.animation_data.action_slot = act.slots[0]
    start, end = act.frame_range
    poses = []
    for i in range(count):
        f = start+(end-start)*i/(count-1)
        scene.frame_set(int(f), subframe=f-int(f))
        pose = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
        # Native locomotion includes forward root displacement. The world route
        # supplies that displacement; preserve vertical gait, remove double travel.
        root_bone = next(b for b in arm.pose.bones if b.parent is None)
        correction = root_bone.bone.matrix_local.to_3x3().inverted() @ Vector((0, -root_bone.head.y, 0))
        pose[root_bone.name].translation += correction
        poses.append(pose)
    arm.animation_data_clear()
    return poses


def pose_at(poses, fraction):
    t = max(0, min(1, fraction))*(len(poses)-1)
    i, j = int(t), min(int(t)+1, len(poses)-1)
    return {n: poses[i][n].lerp(poses[j][n], t-i) for n in poses[i]}


def mix(a, b, t):
    return {n: a[n].lerp(b[n], max(0, min(1, t))) for n in a}


def set_pose(a, pose, frame=None):
    for bone in a['arm'].pose.bones:
        bone.matrix_basis = pose[bone.name]
        if frame is not None:
            bone.keyframe_insert('location', frame=frame)
            bone.keyframe_insert('rotation_quaternion', frame=frame)
            bone.keyframe_insert('scale', frame=frame)


def smooth(x):
    x = max(0, min(1, x))
    return x*x*(3-2*x)


def ground(x, y):
    hit = terrain.ray_cast(Vector((x, y, 60)), Vector((0, 0, -1)), 100)[0]
    if hit is None:
        raise RuntimeError(f'No terrain at {x}, {y}')
    return hit.z


def path(frame):
    if frame < 8:
        distance = 1.5
    elif frame < 35:
        t = (frame-8)/30
        distance = 1.5+3*t+(13/3)*t*t
    elif frame < 130:
        distance = 7.71+(frame-35)/30*10.8
    else:
        t = min((frame-130)/30, .8)
        distance = 41.91+10.8*t-6.75*t*t
    y = -38+distance
    x = -6.6+.08*(y+38)
    return Vector((x, y, ground(x, y)))


bpy.ops.wm.open_mainfile(filepath=str(RESOURCES/'sets/radiant-mid-base.blend'), use_scripts=False)
scene = bpy.context.scene
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, END
scene.timeline_markers.clear()
map_root = bpy.data.objects['Actual Dota map / expanded Radiant mid']
map_root.location *= 1.6
map_root.scale *= 1.6
for o in list(bpy.data.objects):
    if o.type in {'CAMERA', 'LIGHT'}:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.update()
# Clear the foreground camera corridor by relocating complete tree meshes;
# retain the actual lane, architecture and the opposite forest edge.
relocated=[]
for o in map_root.children_recursive:
    if o.type!='MESH': continue
    points=[o.matrix_world@Vector(p) for p in o.bound_box]
    if max(p.x for p in points)<-70 or min(p.x for p in points)>70 or max(p.y for p in points)<-100 or min(p.y for p in points)>70:
        pass  # Keep the full far environment; do not expose the edge of the map.
    if not any(w in o.name.lower() for w in ['tree','pine']):continue
    center=sum(points,Vector())/8
    lane_x=-6.6+.08*(center.y+38)
    if -48<center.y<25 and lane_x+2<center.x<lane_x+20:
        matrix=o.matrix_world.copy();matrix.translation.x+=22;o.matrix_world=matrix
        relocated.append(o.name)
(QA/'relocated-foreground-trees.json').write_text(json.dumps(relocated,indent=2))
bpy.context.view_layer.update()
vertices, faces = [], []
for o in map_root.children_recursive:
    if o.type != 'MESH':
        continue
    if not any(m and m.get('vmat', {}).get('ShaderName') == 'multiblend.vfx' for m in o.data.materials):
        continue
    offset = len(vertices)
    vertices.extend(o.matrix_world@v.co for v in o.data.vertices)
    faces.extend(tuple(offset+i for i in p.vertices) for p in o.data.polygons)
terrain = BVHTree.FromPolygons(vertices, faces)

base = 'models_heroes_spirit_breaker_spirit_breaker'
hero = actor('BARATHRUM', GAME/(base+'.glb'),
             [GAME/(base+'_'+p+'.glb') for p in ['bracers', 'head', 'horns', 'lower_armor', 'shoulders', 'tail', 'weapon']], .82)
charge, finish = [sample(hero, name) for name in ['charge', 'charge_finish']]
idle = sample(hero, 'idle')
# Match each posed hoof to the real terrain, including the slope under it.
foot_vertices = {}
for obj in hero['body']:
    groups = {g.index for g in obj.vertex_groups if any(n in g.name.lower() for n in ('ankle','toeball','knee'))}
    foot_vertices[obj] = [v.index for v in obj.data.vertices if sum(g.weight for g in v.groups if g.group in groups) > .55]
hoof_report=[]
for f in range(1, END+1):
    scene.frame_set(f)
    phase=((path(f).y-path(8).y)/5.4+.67)%1
    # An immediate lean is followed by continuous acceleration, not an idle hold.
    if f < 8:
        pose=mix(pose_at(idle,.2),pose_at(charge,.67),smooth((f-1)/7))
    elif f < 143:
        pose=pose_at(charge,phase)
    else:
        pose=mix(pose_at(charge,phase),pose_at(finish,(f-143)/22),smooth((f-143)/7))
        if f>165:
            pose=mix(pose_at(finish,1),pose_at(idle,(f-165)/100),smooth((f-165)/24))
    set_pose(hero,pose,f)
    r=hero['root'];r.location=path(f);r.rotation_euler.z=math.pi+.7*smooth((f-175)/30)
    bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get()
    points=[obj.matrix_world@obj.evaluated_get(dg).data.vertices[i].co for obj,indices in foot_vertices.items() for i in indices]
    penetration=max(ground(p.x,p.y)-p.z for p in points)
    correction=max(0,penetration+.018);r.location.z+=correction
    hoof_report.append({'frame':f,'correction':correction,'minimum_clearance':-penetration+correction})
    r.keyframe_insert('location',frame=f);r.keyframe_insert('rotation_euler',frame=f)
(QA/'hoof-contact.json').write_text(json.dumps(hoof_report,indent=2))

impacts = [54, 87, 120]
victims = []
for index, contact in enumerate(impacts):
    spec=[
        ('Invoker','invoker','idle','cast','death2',.86,['bracer','cape','dress','hair','head','shoulder']),
        ('Kunkka','kunkka','idle','attack1','death',.88,['feet','hair','hands','shoulders','sword']),
        ('Pudge','pudge','pudge_idle_anim','pudge_attack1_anim','pudge_death',.85,['back','belt','bracer','hair','leftarm','leftweapon','righthook'])
    ][index]
    label,kind,idle_name,attack_name,rest_name,scale,parts=spec
    prefix=f'models_heroes_{kind}_'
    partpaths=[GAME/(prefix+(kind+'_' if kind!='pudge' else '')+part+'.glb') for part in parts]
    v=actor(label,GAME/(prefix+kind+'.glb'),partpaths,scale=scale)
    wait=sample(v,idle_name);ready=sample(v,attack_name)
    rest=pose_at(sample(v,rest_name),1)
    origin=path(contact)+Vector(([1.35,-1.3,1.5][index],3.5,0))
    side=1 if index%2==0 else -1
    v['contact'],v['origin']=contact,origin.copy()
    names=list(v['arm'].pose.bones.keys())
    aliases={}
    for role,candidates in {'root':['root','root_0','Root_0'],'head':['head','Head_0'],'spine1':['spine1','Spine_0'],'spine2':['spine2','Spine_1']}.items():
        aliases[role]=next((n for n in candidates if n in names),names[0])
    neutral = pose_at(wait, .3)
    final = {n:m.copy() for n,m in neutral.items()}
    for n, ax, amount in [('spine1','X',-.4),('spine2','Y',side*.32),('head','X',-.25),
                         ('bicep_L','Z',.5),('bicep_R','Z',-.65),('elbow_L','X',.7),('elbow_R','X',1),
                         ('thigh_L','X',.45),('thigh_R','X',-.3),('knee_L','X',.9),('knee_R','X',.6)]:
        n=aliases.get(n,n)
        if n in final:
            final[n] = final[n] @ Matrix.Rotation(amount,4,ax)
    # Use distinct anatomical rest poses as endpoints, not generic death clips.
    # The impulse, limb lag, flight and landing timing remain authored here.
    set_pose(v,rest)
    bpy.context.view_layer.update()
    arm=v['arm']
    hip=arm.pose.bones[aliases.get('root','root')].head
    origin_bone=next(b for b in arm.pose.bones if b.parent is None)
    rest[origin_bone.name].translation+=origin_bone.bone.matrix_local.to_3x3().inverted()@Vector((-hip.x,-hip.y,0))
    target_forward=Vector((side*.3,1,0)).normalized()
    landing=Quaternion((0,0,1),side*(.5+index*.4))
    initial=Quaternion((0,0,1),.12*side)
    v['root'].rotation_mode='QUATERNION'
    for f in range(1, END+1):
        scene.frame_set(f)
        t = (f-contact)/FPS
        if t < 0:
            p = mix(pose_at(wait, ((f+index*19)/180)%1), pose_at(ready, min(.35,max(0,(f-contact+20)/45))), smooth((f-contact+22)/18))
            xy = origin+Vector((side*.18*math.sin(f/23+index), max(0,(contact-f)/30)*.2,0))
            rotation = initial.copy()
            z_flight = 0
        else:
            p = mix(pose_at(ready,.35), final, smooth(t/.42))
            # Torso reacts first; loose arms and legs follow the impulse.
            for n, ax, strength in [('spine1','X',-.65),('head','Y',side*.5),('bicep_L','Z',-.7),('bicep_R','Z',.8),('thigh_L','X',.6)]:
                n=aliases.get(n,n)
                if n in p:
                    impulse = math.sin(min(t/.65,1)*math.pi)*strength
                    p[n] = p[n] @ Matrix.Rotation(impulse,4,ax)
            p=mix(p,rest,smooth((t-.12)/.58))
            travel = min(t,1.05)+(1-math.exp(-max(0,t-1.05)*5))*.16
            xy = origin+Vector((side*(8.7+index*.35)*travel,(13.8+index*.25)*travel,0))
            z_flight = max(0,(4.7+index*.2)*t-4.905*t*t)
            q = min(t/.8,1)
            rotation = Quaternion((1,0,0), -1.2*math.sin(math.pi*min(t/1.05,1))) @ initial.slerp(landing,q)
            if t > 1.05:
                rotation = Quaternion(target_forward,.07*math.exp(-(t-1.05)*7)*math.sin((t-1.05)*20))@rotation
        set_pose(v,p,f)
        r = v['root'];r.location=(xy.x,xy.y,ground(xy.x,xy.y)+z_flight);r.rotation_quaternion=rotation
        bpy.context.view_layer.update()
        dg=bpy.context.evaluated_depsgraph_get()
        # Contact is measured on the posed mesh, not a rotated box.
        low=min((o.matrix_world@vert.co).z for o in v['body'] for vert in o.evaluated_get(dg).data.vertices)
        r.location.z += ground(xy.x,xy.y)+z_flight-low+.015
        r.keyframe_insert('location',frame=f);r.keyframe_insert('rotation_quaternion',frame=f)
    victims.append(v)

# Native Charge uses animated model afterimages. Reconstruct that silhouette
# effect in Blender, with delayed complete rigs rather than arbitrary rings.
ghostmat=bpy.data.materials.new('Charge afterimage');ghostmat.use_nodes=True
nt=ghostmat.node_tree;nt.nodes.clear()
out=nt.nodes.new('ShaderNodeOutputMaterial');mixnode=nt.nodes.new('ShaderNodeMixShader')
transparent=nt.nodes.new('ShaderNodeBsdfTransparent');glow=nt.nodes.new('ShaderNodeEmission');glow.inputs[0].default_value=(.035,.42,1,1);glow.inputs[1].default_value=.9
mixnode.inputs[0].default_value=.018
nt.links.new(transparent.outputs[0],mixnode.inputs[1]);nt.links.new(glow.outputs[0],mixnode.inputs[2]);nt.links.new(mixnode.outputs[0],out.inputs[0])
for delay in [4,8]:
    originals=[hero['root'],*hero['objects']];copies={}
    for source in originals:
        o=source.copy();o.name=f'Charge echo {delay} {source.name}';scene.collection.objects.link(o);copies[source]=o
        if o.animation_data and o.animation_data.action:
            action=o.animation_data.action.copy();o.animation_data.action=action
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        for fc in bag.fcurves:
                            for key in fc.keyframe_points:
                                key.co.x+=delay;key.handle_left.x+=delay;key.handle_right.x+=delay
        if o.type=='MESH':
            o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(ghostmat)
            for poly in o.data.polygons:poly.material_index=0;poly.use_smooth=True
            o.visible_shadow=False
            if source not in hero['body']:o.hide_render=True
    for source,o in copies.items():
        if source.parent in copies:o.parent=copies[source.parent]
        for mod in o.modifiers:
            if mod.type=='ARMATURE' and mod.object in copies:mod.object=copies[mod.object]
        if o.type=='ARMATURE':
            for bone in o.pose.bones:
                for c in bone.constraints:
                    if hasattr(c,'target') and c.target in copies:c.target=copies[c.target]
    root=copies[hero['root']]
    for f,scale in [(1,0),(9,0),(18,.82),(133,.82),(150,0),(END,0)]:
        root.scale=(scale,)*3;root.keyframe_insert('scale',frame=f)

rng=random.Random(37)

blood=bpy.data.materials.new('Dark impact spray');blood.diffuse_color=(.19,.003,.006,1);blood.use_nodes=True
bp=blood.node_tree.nodes.get('Principled BSDF');bp.inputs['Base Color'].default_value=(.19,.003,.006,1);bp.inputs['Roughness'].default_value=.32
for index,contact in enumerate(impacts):
    origin=victims[index]['origin']+Vector((0,0,1.3))
    for k in range(18):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=1)
        o=bpy.context.object;o.name=f'Impact spray {index+1} {k}';o.data.materials.append(blood)
        velocity=Vector((rng.uniform(-3,3),rng.uniform(3,7),rng.uniform(1,4)))
        size=rng.uniform(.015,.045)
        for f in range(contact-1,min(END,contact+47)+1):
            t=max(0,(f-contact)/FPS);p=origin+velocity*t+Vector((0,0,-4.905*t*t));floor=ground(p.x,p.y)
            p.z=max(floor+.012,p.z);o.location=p
            o.scale=(size,size,size*(2 if p.z>floor+.02 else .2)) if contact<=f<contact+46 else (0,0,0)
            o.keyframe_insert('location',frame=f);o.keyframe_insert('scale',frame=f)
        o.scale=(0,0,0);o.keyframe_insert('scale',frame=1);o.keyframe_insert('scale',frame=END)

world = bpy.data.worlds.new('Mid twilight sky')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (.52,.64,.82,1)
world.node_tree.nodes['Background'].inputs[1].default_value = .85
scene.world = world
# A camera-visible blue sky with broad cloud structure; neutral ambient stays independent.
wn=world.node_tree;bg=wn.nodes.get('Background');wo=wn.nodes.get('World Output')
lightpath=wn.nodes.new('ShaderNodeLightPath');skybg=wn.nodes.new('ShaderNodeBackground');skybg.inputs['Strength'].default_value=.8
coord=wn.nodes.new('ShaderNodeTexCoord');noise=wn.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=3.8;noise.inputs['Detail'].default_value=2.0
ramp=wn.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.49;ramp.color_ramp.elements[0].color=(.06,.2,.52,1);ramp.color_ramp.elements[1].position=.69;ramp.color_ramp.elements[1].color=(.85,.89,1,1)
wmix=wn.nodes.new('ShaderNodeMixShader');wn.links.new(coord.outputs['Normal'],noise.inputs['Vector']);wn.links.new(noise.outputs['Fac'],ramp.inputs[0]);wn.links.new(ramp.outputs['Color'],skybg.inputs['Color']);wn.links.new(lightpath.outputs['Is Camera Ray'],wmix.inputs[0]);wn.links.new(bg.outputs[0],wmix.inputs[1]);wn.links.new(skybg.outputs[0],wmix.inputs[2]);wn.links.new(wmix.outputs[0],wo.inputs[0])
# Soft directional sky fill keeps tree foliage readable without green/orange grading.
fd=bpy.data.lights.new('Open sky fill','SUN');fd.energy=.8;fd.angle=.65;fd.color=(.9,.95,1)
fo=bpy.data.objects.new('Open sky fill',fd);scene.collection.objects.link(fo);fo.rotation_euler=(.95,.35,1.8)
sun = bpy.data.lights.new('Late sun', 'SUN')
sun.energy, sun.angle = 2.4, .12
o = bpy.data.objects.new('Late sun', sun)
scene.collection.objects.link(o)
o.rotation_euler = (.55,-.45,-.7)
for name, pos, energy, color, size in [
    ('Sky bounce', (4,-15,18), 2600, (.82,.9,1), 22),
    ('Warm side', (-10,-8,10), 1800, (1,.94,.86), 16)]:
    d = bpy.data.lights.new(name, 'AREA');d.energy=energy;d.color=color;d.shape='DISK';d.size=size
    o = bpy.data.objects.new(name,d);scene.collection.objects.link(o);o.location=pos;aim(o,(-3,-15,1))

cameras = []
for name, first, last, offset, lens in [
    ('01 Immediate launch',1,18,(5,8,5.1),38),
    ('02 Three heroes',19,133,(16,3,7.0),32),
    ('03 Brake',134,170,(6,9,5.5),35),
    ('04 Aftermath',171,210,(5,8,3.9),43)]:
    d=bpy.data.cameras.new(name);d.lens=lens;d.clip_end=250
    o=bpy.data.objects.new(name,d);scene.collection.objects.link(o)
    for f in range(first,last+1):
        p=path(f);off=Vector(offset)
        if first==171: off*=1-.12*smooth((f-first)/(last-first))
        o.location=p+off;aim(o,p+Vector((0,2.0 if first==19 else .65,1.5)))
        o.keyframe_insert('location',frame=f);o.keyframe_insert('rotation_euler',frame=f)
    scene.timeline_markers.new(name,frame=first).camera=o
    cameras.append(o)
scene.camera=cameras[0]
occluders=set()
for f in range(1,END+1,3):
    scene.frame_set(f)
    bpy.context.view_layer.update()
    cam=scene.camera
    for dx,z in [(-1,1.2),(0,1.6),(1,2.1)]:
        target=path(f)+Vector((dx,0,z));direction=target-cam.location
        ray_origin=cam.location.copy()
        for _ in range(12):
            hit,loc,normal,face,obj,matrix=scene.ray_cast(bpy.context.evaluated_depsgraph_get(),ray_origin,direction.normalized(),distance=(target-ray_origin).length-.3)
            if not hit: break
            if obj in map_root.children_recursive and any(word in obj.name.lower() for word in ['tree','pine','canopy']):
                occluders.add(obj.name)
                ray_origin=loc+direction.normalized()*.05
            else: break
for name in occluders:
    bpy.data.objects[name].visible_camera=False
(QA/'camera-occluders.json').write_text(json.dumps(sorted(occluders),indent=2))
def finish_staging():
    # Support terrain below the imported map closes cut-out edges seen between trees.
    bpy.ops.mesh.primitive_plane_add(size=320, location=(0,0,-.3))
    land=bpy.context.object;land.name='Distant ground under map cutouts'
    mat=bpy.data.materials.new('Distant grass soil');mat.use_nodes=True
    nt=mat.node_tree;bs=nt.nodes.get('Principled BSDF');bs.inputs['Roughness'].default_value=1
    noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=160;noise.inputs['Detail'].default_value=3
    ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.035,.055,.016,1);ramp.color_ramp.elements[1].color=(.13,.18,.045,1)
    nt.links.new(noise.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs[0],bs.inputs['Base Color']);land.data.materials.append(mat)
    # A short opponent reaction establishes who is about to be hit.
    marker=next(m for m in scene.timeline_markers if m.frame==19);marker.frame=35
    data=bpy.data.cameras.new('02 Opponent notices');data.lens=43
    cam=bpy.data.objects.new('02 Opponent notices',data);scene.collection.objects.link(cam)
    inv=bpy.data.objects['Invoker'];arm=next(o for o in inv.children_recursive if o.type=='ARMATURE')
    for f in range(19,35):
        scene.frame_set(f);bpy.context.view_layer.update()
        head=arm.matrix_world@arm.pose.bones['Head_0'].head
        cam.location=head+Vector((3,-6,1.0))*(1-.07*smooth((f-19)/15));aim(cam,head+Vector((0,0,-.5)))
        cam.keyframe_insert('location',frame=f);cam.keyframe_insert('rotation_euler',frame=f)
    scene.timeline_markers.new('02 Opponent notices',frame=19).camera=cam
    # Track the actual animated face in the closing shot, rather than the root.
    cam=bpy.data.objects['04 Aftermath'];cam.data.lens=38
    root=bpy.data.objects['BARATHRUM'];arm=next(o for o in root.children_recursive if o.type=='ARMATURE')
    for f in range(171,211):
        scene.frame_set(f);bpy.context.view_layer.update()
        head=arm.matrix_world@arm.pose.bones['Head_0'].head
        aim(cam,head+Vector((0,0,-.45)));cam.keyframe_insert('rotation_euler',frame=f)
    # Brief impact response only, never continuous camera shake.
    cam=bpy.data.objects['02 Three heroes'];cam.data.lens=40
    for f in range(35,134):
        scene.frame_set(f);bpy.context.view_layer.update()
        cam.location=root.location+Vector((12,2,5.8));aim(cam,root.location+Vector((0,1.7,1.6)))
        cam.keyframe_insert('location',frame=f);cam.keyframe_insert('rotation_euler',frame=f)
    for hit in [54,87,120]:
        for f in range(hit,hit+9):
            scene.frame_set(f)
            amount=math.exp(-(f-hit)/2.2)*math.sin((f-hit)*2.1)
            cam.rotation_euler.x+=.009*amount;cam.rotation_euler.z+=.012*amount
            cam.keyframe_insert('rotation_euler',frame=f)

finish_staging()

fill = bpy.data.lights.new('Moving sky bounce','AREA');fill.energy=900;fill.size=7
light = bpy.data.objects.new('Moving sky bounce',fill);scene.collection.objects.link(light)
for f in range(1,END+1):
    light.location=path(f)+Vector((3,5,6));aim(light,path(f)+Vector((0,0,1.5)))
    light.keyframe_insert('location',frame=f);light.keyframe_insert('rotation_euler',frame=f)
scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True;scene.cycles.transparent_max_bounces=32
p=bpy.context.preferences.addons['cycles'].preferences;p.compute_device_type='OPTIX';p.get_devices()
for d in p.devices:d.use=d.type=='OPTIX'
scene.cycles.device='GPU'
scene.render.resolution_x=540;scene.render.resolution_y=960;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='AgX';scene.view_settings.exposure=0
scene.render.use_motion_blur=True;scene.render.motion_blur_shutter=.18
scene.use_nodes=False
scene.render.use_persistent_data=True
scene.frame_set(70)
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'draft.blend'))
(QA/'hero-bones.json').write_text(json.dumps(list(hero['arm'].pose.bones.keys()),indent=2))
if args.probes:
    for frame in [1,54,60,94,128,190]:
        scene.frame_set(frame)
        scene.render.filepath=str(OUT/f'probe-{frame:04d}.png')
        bpy.ops.render.render(write_still=True)
