"""Dota adaptation of the leap/block scene. Native assets stay in _game.

blender -b --python tools/blender/doomsday_scene.py -- probe|build
"""
import bpy
import json
import math
import random
import re
import sys
from mathutils import Matrix
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/skits/doomsday'
OUT.mkdir(parents=True, exist_ok=True)
RND = ROOT / '_game/models/render'
DB = json.loads((ROOT / '_game/data/troupe.json').read_text(encoding='utf-8'))
MODE = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'probe'
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.samples = 24
sc.cycles.use_denoising = True
prefs=bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type='CUDA'
prefs.get_devices()
for device in prefs.devices:
    device.use=device.type=='CUDA'
if any(d.type=='CUDA' for d in prefs.devices):
    sc.cycles.device='GPU'
sc.render.fps = 30
sc.render.resolution_x = 540
sc.render.resolution_y = 960
sc.render.resolution_percentage = 100
sc.world = bpy.data.worlds.new('Dusk')
sc.world.use_nodes = True
sc.world.node_tree.nodes['Background'].inputs[0].default_value = (.09, .13, .22, 1)
sc.world.node_tree.nodes['Background'].inputs[1].default_value = .5
sc.view_settings.view_transform = 'AgX'


def imported(path):
    before = set(bpy.data.objects)
    acts = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(path), bone_heuristic='BLENDER')
    obs = list(set(bpy.data.objects) - before)
    for o in list(obs):
        if o.type == 'MESH' and o.name.startswith('Icosphere'):
            bpy.data.objects.remove(o, do_unlink=True)
            obs.remove(o)
    return obs, list(set(bpy.data.actions) - acts)


def material_fix(obs):
    for o in obs:
        for slot in getattr(o, 'material_slots', []):
            m = slot.material
            if not m or not m.use_nodes or m.get('doomsday_fixed'):
                continue
            nt = m.node_tree
            p = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if p is None:
                continue
            for k,v in [('Alpha',1),('Metallic',.12),('Roughness',.53)]:
                for link in list(p.inputs[k].links):
                    nt.links.remove(link)
                p.inputs[k].default_value = v
            if p.inputs['Base Color'].links:
                source = p.inputs['Base Color'].links[0].from_socket
                hs = nt.nodes.new('ShaderNodeHueSaturation')
                hs.inputs['Saturation'].default_value = 1.18
                nt.links.new(source, hs.inputs['Color'])
                nt.links.new(hs.outputs['Color'], p.inputs['Base Color'])
            m['doomsday_fixed'] = True
        if o.type == 'MESH':
            for face in o.data.polygons:
                face.use_smooth = True


def hero(name, pos, yaw):
    d = DB[name]
    obs, actions = imported(RND / Path(d['glb']).name)
    material_fix(obs)
    arm = next(o for o in obs if o.type == 'ARMATURE')
    root = bpy.data.objects.new(name + '_root', None)
    sc.collection.objects.link(root)
    arm.parent = root
    root.location = pos
    root.rotation_euler.z = math.radians(yaw)
    root.scale = (.6,) * 3
    for path in d['parts']:
        po, _ = imported(RND / path.replace('/', '_').replace('.vmdl','.glb'))
        material_fix(po)
        for pa in [o for o in po if o.type == 'ARMATURE']:
            pa.animation_data_clear()
            pa.parent = root
            pa.matrix_basis = arm.matrix_basis.copy()
            for pb in pa.pose.bones:
                if pb.name in arm.pose.bones:
                    c = pb.constraints.new('COPY_TRANSFORMS')
                    c.target = arm
                    c.subtarget = pb.name
        obs += po
    arm.animation_data_create()
    for track in list(arm.animation_data.nla_tracks):
        arm.animation_data.nla_tracks.remove(track)
    acts = {re.sub(r'\.\d{3}$','',a.name): a for a in actions}
    arm.animation_data.action = acts[d['idle']]
    return {'arm':arm, 'root':root, 'acts':acts, 'objects':obs}


def camera(pos, target, lens=45):
    if sc.camera is None:
        bpy.ops.object.camera_add()
        sc.camera = bpy.context.object
    cam = sc.camera
    cam.location = pos
    cam.rotation_euler = (Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.lens = lens
    return cam


def area(name, pos, color, power, size, target=(0,0,1.5)):
    data = bpy.data.lights.new(name,'AREA')
    data.energy = power
    data.color = color
    data.shape = 'DISK'
    data.size = size
    obj = bpy.data.objects.new(name,data)
    sc.collection.objects.link(obj)
    obj.location = pos
    obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
    return obj


def flatmat(name, color, rough=.7, metal=0):
    m=bpy.data.materials.new(name)
    m.diffuse_color=(*color,1)
    m.use_nodes=True
    p=m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value=(*color,1)
    p.inputs['Roughness'].default_value=rough
    p.inputs['Metallic'].default_value=metal
    return m


def render(path,frame):
    sc.frame_set(frame)
    sc.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)


def probe():
    sc.render.resolution_x=480
    sc.render.resolution_y=600
    area('soft key',(3,-5,7),(.7,.82,1),1600,5)
    area('warm edge',(-4,3,6),(1,.45,.16),1900,3)
    bpy.ops.mesh.primitive_plane_add(size=200)
    bpy.context.object.data.materials.append(flatmat('floor',(.09,.11,.14)))
    report={}
    for who,clips in [('sven',['idle','attack01','attack02','attack03','sven_cast_stormbolt_aghs']),
                      ('rubick',['rubick_idle','rubick_cast_telekinesis'])]:
        h=hero(who,(0,0,0),0)
        camera((6,-8,4),(0,0,1.4),45)
        report[who]={'bones':{b.name:list(b.head) for b in h['arm'].data.bones},'clips':{}}
        for clip in clips:
            act=h['acts'][clip]
            h['arm'].animation_data.action=act
            report[who]['clips'][clip]=list(act.frame_range)
            for part,t in enumerate([.2,.5,.8]):
                f=act.frame_range[0]+t*(act.frame_range[1]-act.frame_range[0])
                render(OUT/f'probe_{who}_{clip}_{part}.png',round(f))
        for o in h['objects']:
            o.hide_render=True
    (OUT/'rig_report.json').write_text(json.dumps(report,indent=2))


def environment():
    """Reuse native Dire masonry and props; stage them around a clear action lane."""
    sys.path.insert(0,str(ROOT/'tools/blender'))
    import dota_map
    dota_map.TEX=str(ROOT/'_game/world')
    obs,_=imported(ROOT/'_game/maps/dire_tank_base_v2.glb')
    selected=[]
    for o in obs:
        if o.type=='MESH' and any(t in o.name for t in ['statue001','ground_rock001','dire_tower002','river_rocks001']):
            selected.append(o)
        else:
            bpy.data.objects.remove(o,do_unlink=True)
    positions=[(-10,15,0),(12,18,0),(-9,7,0),(10,8,0),(-6,14,0),(7,17,0),(-14,22,0),(16,25,0)]
    for i,o in enumerate(selected):
        mw=o.matrix_world.copy()
        o.parent=None
        o.data=o.data.copy()
        o.data.transform(mw)
        o.matrix_world=Matrix.Identity(4)
        points=[v.co for v in o.data.vertices]
        lo=Vector(tuple(min(v[j] for v in points) for j in range(3)))
        hi=Vector(tuple(max(v[j] for v in points) for j in range(3)))
        center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z))
        height=hi.z-lo.z
        target=10 if 'tower' in o.name else 6 if 'statue' in o.name else 1.2
        factor=target/max(height,.1)
        for v in o.data.vertices:
            v.co=(v.co-center)*factor
        o.location=positions[i%len(positions)]
        for slot in o.material_slots:
            m=slot.material
            if m and m.get('vmat'):
                v=m['vmat']; v=v.to_dict() if hasattr(v,'to_dict') else v
                dota_map.fix_prop(m,v)
    bpy.ops.mesh.primitive_plane_add(size=180)
    floor=bpy.context.object
    floor.name='Dire stone court'
    m=flatmat('Dire paving',(.13,.15,.18),.75)
    floor.data.materials.append(m)
    nt=m.node_tree;p=nt.nodes.get('Principled BSDF')
    tex=nt.nodes.new('ShaderNodeTexImage')
    tex.image=bpy.data.images.load(str(ROOT/'_game/world/bad_base_stone_tintable_000_color_psd_1623f737.png'))
    coord=nt.nodes.new('ShaderNodeTexCoord');mp=nt.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value=(.32,.32,.32)
    nt.links.new(coord.outputs['Object'],mp.inputs['Vector']);nt.links.new(mp.outputs[0],tex.inputs[0])
    paving=nt.nodes.new('ShaderNodeValToRGB')
    paving.color_ramp.elements[0].color=(.028,.04,.055,1)
    paving.color_ramp.elements[1].color=(.09,.12,.15,1)
    nt.links.new(tex.outputs[0],paving.inputs[0]);nt.links.new(paving.outputs[0],p.inputs['Base Color'])
    bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.35;bump.inputs['Distance'].default_value=.08
    nt.links.new(tex.outputs[0],bump.inputs['Height']);nt.links.new(bump.outputs[0],p.inputs['Normal'])
    # Broken masonry keeps the space legible without covering the action lane.
    rng=random.Random(491)
    stone=flatmat('Rubble',(.12,.14,.18),.86)
    for i in range(75):
        x=rng.uniform(-14,14);y=rng.uniform(-5,18)
        if abs(y)<2.2 and abs(x)<6:continue
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=(x,y,.02))
        o=bpy.context.object;o.name='Broken masonry'
        o.scale=(rng.uniform(.08,.55),rng.uniform(.1,.5),rng.uniform(.05,.25))
        o.rotation_euler=(rng.random(),rng.random(),rng.random()*6)
        o.data.materials.append(stone)
    # Storm clouds are world shading, so every camera sees a continuous sky.
    nt=sc.world.node_tree;bg=nt.nodes.get('Background')
    tc=nt.nodes.new('ShaderNodeTexCoord');noise=nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value=3.4;noise.inputs['Detail'].default_value=5
    nt.links.new(tc.outputs['Normal'],noise.inputs['Vector'])
    ramp=nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position=.27;ramp.color_ramp.elements[0].color=(.012,.024,.046,1)
    ramp.color_ramp.elements[1].position=.75;ramp.color_ramp.elements[1].color=(.18,.24,.32,1)
    nt.links.new(noise.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs[0],bg.inputs[0])
    bg.inputs[1].default_value=.32
    area('Moon soft key',(1,-6,9),(.40,.65,1),1100,5)
    area('Sun breaking clouds',(-3,7,8),(1,.43,.12),2500,5)
    area('Camera fill',(0,-8,4),(.58,.76,1),220,5)
    # Low density aerial perspective separates the ruins from the characters.
    bpy.ops.mesh.primitive_cube_add(size=2,location=(0,10,8))
    mist=bpy.context.object;mist.name='Atmospheric perspective';mist.scale=(45,40,12)
    m=bpy.data.materials.new('Cold mist');m.use_nodes=True
    nt=m.node_tree;nt.nodes.clear();v=nt.nodes.new('ShaderNodeVolumePrincipled')
    v.inputs['Density'].default_value=.012;v.inputs['Color'].default_value=(.22,.32,.47,1)
    nt.links.new(v.outputs['Volume'],nt.nodes.new('ShaderNodeOutputMaterial').inputs['Volume'])
    mist.data.materials.append(m)


def cached_pose(h,clip,frame):
    h['arm'].animation_data.action=h['acts'][clip]
    sc.frame_set(int(frame),subframe=frame-int(frame))
    return {b.name:(b.location.copy(),b.rotation_quaternion.copy(),b.scale.copy()) for b in h['arm'].pose.bones}


def blend_pose(a,b,t):
    return {n:(v[0].lerp(b[n][0],t),v[1].slerp(b[n][1],t),v[2].lerp(b[n][2],t)) for n,v in a.items()}


def smooth(t):
    t=max(0,min(1,t));return t*t*(3-2*t)


def bake(h,poses):
    h['arm'].animation_data.action=None
    for f,pose in enumerate(poses):
        for b in h['arm'].pose.bones:
            b.rotation_mode='QUATERNION'
            b.location,b.rotation_quaternion,b.scale=pose[b.name]
            for key in ['location','rotation_quaternion','scale']:
                b.keyframe_insert(key,frame=f)


def beam(name,pts,color,width=.012):
    cu=bpy.data.curves.new(name,'CURVE');cu.dimensions='3D';cu.bevel_depth=width;cu.bevel_resolution=2
    s=cu.splines.new('POLY');s.points.add(len(pts)-1)
    for p,co in zip(s.points,pts):p.co=(*co,1)
    ob=bpy.data.objects.new(name,cu);sc.collection.objects.link(ob)
    m=bpy.data.materials.get(name+'_glow')
    if m is None:
        m=bpy.data.materials.new(name+'_glow');m.use_nodes=True
        nt=m.node_tree;nt.nodes.clear();e=nt.nodes.new('ShaderNodeEmission');e.inputs[0].default_value=(*color,1);e.inputs[1].default_value=7
        nt.links.new(e.outputs[0],nt.nodes.new('ShaderNodeOutputMaterial').inputs[0])
    ob.data.materials.append(m)
    return ob


def animated_bolt(index,start,end,start_frame,end_frame,color):
    rng=random.Random(index+740)
    a,b=Vector(start),Vector(end)
    points=[]
    for j in range(9):
        t=j/8
        p=a.lerp(b,t)
        if 0<j<8:p+=Vector((rng.uniform(-.17,.17),rng.uniform(-.17,.17),rng.uniform(-.17,.17)))
        points.append(p)
    ob=beam('Blue arc' if color[2]>.5 else 'Green arrest',points,color)
    for f,hide in [(0,True),(start_frame-1,True),(start_frame,False),(end_frame,False),(end_frame+1,True),(239,True)]:
        ob.hide_render=hide;ob.keyframe_insert('hide_render',frame=f)
    return ob


def tuck_and_support(h):
    from contact_reaction import _solve_leg, _basis
    arm=h['arm'];samples=[];poles=[None,None]
    legs=[tuple(n+'_'+side for n in ('thigh','knee','ankle')) for side in ('L','R')]
    for f in range(43,240):
        sc.frame_set(f);bpy.context.view_layer.update()
        mw=arm.matrix_world.copy();inv=mw.inverted()
        base={b.name:mw@b.matrix for b in arm.pose.bones}
        desired={n:m.copy() for n,m in base.items()}
        if f<69:
            dz=.17*math.sin((f-43)/26*math.pi/2);back=0
        elif f<120:
            t=(f-69)/51;dz=.17*(1-t)+.36*math.sin(math.pi*t);back=.20*math.sin(math.pi*t)
        else:dz=0;back=0
        for i,leg in enumerate(legs):
            target=base[leg[2]].copy();target.translation+=Vector((-back,0,dz))
            poles[i]=_solve_leg(base,desired,leg,Vector(),poles[i],Vector((1,0,0)),target)
        values={}
        for leg in legs:
            for name in leg:
                b=arm.pose.bones[name]
                values[name]=_basis(b,inv@desired[name],inv@desired[b.parent.name]).decompose()
        samples.append((f,values))
    for f,values in samples:
        for name,(loc,rot,scale) in values.items():
            b=arm.pose.bones[name];b.location=loc;b.rotation_quaternion=rot;b.scale=scale
            for key in ('location','rotation_quaternion','scale'):b.keyframe_insert(key,frame=f)


def build():
    N=240
    environment()
    s=hero('sven',(-3.4,0,0),90)
    r=hero('rubick',(1.6,0,0),-90)
    # Source poses are sampled before authoring any output action.
    sv=[];ru=[]
    for f in range(N):
        idle=cached_pose(s,'idle',f%59)
        if f<43:p=idle
        elif f<69:p=blend_pose(idle,cached_pose(s,'attack01',0),smooth((f-43)/26))
        elif f<96:p=cached_pose(s,'attack01',(f-69)/27*6)
        elif f<116:p=cached_pose(s,'attack01',6+smooth((f-96)/20)*1.0)
        elif f<120:p=cached_pose(s,'attack01',7+(f-116)/4*4.0)
        else:p=cached_pose(s,'attack01',11+math.sin((f-120)*.16)*.10)
        sv.append(p)
        ri=cached_pose(r,'rubick_idle',f%59)
        if f<96:q=ri
        elif f<120:q=blend_pose(ri,cached_pose(r,'rubick_cast_telekinesis',7),smooth((f-96)/24))
        else:q=cached_pose(r,'rubick_cast_telekinesis',7+min(1,(f-120)/100))
        ru.append(q)
    bake(s,sv);bake(r,ru)
    for f in range(N):
        if f<69:x=-3.4;z=-.17*math.sin(max(0,(f-43)/26)*math.pi/2)
        elif f<120:
            t=(f-69)/51;x=-3.4+1.9*t;z=2.1*math.sin(t*math.pi)+.58*t
        else:x=-1.5;z=.58-.10*smooth((f-120)/13)
        s['root'].location=(x,0,z);s['root'].keyframe_insert('location',frame=f)
    tuck_and_support(s)
    # Contact is measured from evaluated blade geometry, then the caster is positioned.
    sc.frame_set(120);bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get()
    sword=next(o for o in s['objects'] if o.type=='MESH' and 'sword' in o.name.lower())
    ev=sword.evaluated_get(dg);verts=[ev.matrix_world@v.co for v in ev.data.vertices]
    tip=max(verts,key=lambda v:v.x)
    hand_names=[b.name for b in r['arm'].pose.bones if 'hand' in b.name.lower() or 'wrist' in b.name.lower()]
    hands={n:r['arm'].matrix_world@r['arm'].pose.bones[n].head for n in hand_names}
    print('CONTACT',list(tip),'HANDS', {n:list(v) for n,v in hands.items()},flush=True)
    # Emit effects from sampled moving blade endpoints, never from a static world origin.
    for f in range(12,174,3):
        sc.frame_set(f);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
        ev=sword.evaluated_get(dg);vs=[ev.matrix_world@v.co for v in ev.data.vertices]
        top=max(vs,key=lambda v:v.z)
        near=s['arm'].matrix_world@s['arm'].pose.bones['wrist_R'].head
        animated_bolt(f,near,top,f,min(f+2,173),(.08,.42,1))
        if f>69:
            offset=Vector((-.6,.25,.5))
            animated_bolt(f+500,top,top+offset,f,min(f+2,173),(.06,.34,1))
    for j in range(18):
        a=j*2.399
        end=tip+Vector((math.cos(a)*.8,math.sin(a)*.65,.45*math.sin(a*2)))
        animated_bolt(900+j,tip,end,120+j%4,124+j%4,(.16,1,.08))
    charge=area('Electric weapon light',(-4,-1,3),(.08,.42,1),0,1.3,(-4,0,2))
    for f in range(N):
        sc.frame_set(f)
        charge.location=s['root'].location+Vector((.3,-.8,2.7))
        charge.keyframe_insert('location',frame=f)
        charge.data.energy=80*smooth((f-10)/30) if f<120 else 35
        charge.data.keyframe_insert('energy',frame=f)
    # A low green contact light gives the stopping hand and blade matching illumination.
    contact_light=area('Green contact',tip+Vector((0,-.4,.4)),(.18,1,.07),0,1,tip)
    for f,power in [(0,0),(119,0),(121,650),(127,250),(239,250)]:
        contact_light.data.energy=power;contact_light.data.keyframe_insert('energy',frame=f)
    cam=camera((-1,-10,3),(0,0,1.8),45)
    for f in range(N):
        sc.frame_set(f)
        if f<45:pos=(-.6,-5.4,2.9);target=(-3.4,0,1.8);lens=55
        elif f<120:pos=(-.8,-18.4,3.4);target=(-1,0,2.7);lens=40
        elif f<177:pos=(.2,-13.8,3.4);target=(.4,0,2.3);lens=46
        elif f<210:pos=(-2.8,-4.6,3.2);target=(1.6,0,2.8);lens=55
        else:pos=(2.1,-6.5,3.2);target=(-.65,0,2.7);lens=50
        camera(pos,target,lens)
        for key in ['location','rotation_euler']:cam.keyframe_insert(key,frame=f)
        cam.data.keyframe_insert('lens',frame=f)
    sc.frame_start=0;sc.frame_end=N-1
    sc.render.image_settings.file_format='PNG'
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'doomsday_v1.blend'))
    if MODE=='build':
        for f in [20,65,90,108,120,150,190,225]:render(OUT/f'shot_{f:03d}.png',f)
    else:
        frames=OUT/'draft_v1/frames';frames.mkdir(parents=True,exist_ok=True)
        for f in range(0,N,2):render(frames/f'{f:04d}.png',f)


if __name__ == '__main__':
    if MODE == 'probe':
        probe()
    elif MODE in ('build','draft'):
        build()
