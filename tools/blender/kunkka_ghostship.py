"""Stage Kunkka summoning a ghost ship; native sources, isolated scene.

Blender -b --factory-startup -P tools/blender/kunkka_ghostship.py -- inspect
The first inspection checks native cast, equipped sword and ship geometry.
"""
import ast
import json
import math
import random
import shutil
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/skits/kunkka_ghostship'
ASSETS = ROOT / '_game/models/render'
COUNT = 240


def helpers():
    source = ROOT / 'tools/blender/render_scene.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    wanted = {'imp', 'fix_hero_mats'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    namespace = dict(bpy=bpy, HERO=dict(sat=1., val=1., hue=0.))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['imp'], namespace['fix_hero_mats']


def aim(obj, point):
    obj.rotation_euler = (Vector(point) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def bounds(objects):
    points = [o.matrix_world @ Vector(p) for o in objects if o.type == 'MESH' for p in o.bound_box]
    return dict(min=[min(p[i] for p in points) for i in range(3)],
                max=[max(p[i] for p in points) for i in range(3)])


def light(name, position, power, color, size, target=(0, 0, 2)):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = power; data.color = color; data.shape = 'DISK'; data.size = size
    obj = bpy.data.objects.new(name, data); bpy.context.scene.collection.objects.link(obj)
    obj.location = position; aim(obj, target)


def inspect():
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = 576; sc.render.resolution_y = 720
    sc.render.resolution_percentage = 100; sc.render.fps = 30
    sc.eevee.taa_render_samples = 16
    sc.render.image_settings.file_format = 'PNG'; sc.render.film_transparent = False
    sc.view_settings.view_transform = 'AgX'
    world = bpy.data.worlds.new('Studio'); world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.12, .16, .22, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = .5
    sc.world = world
    imp, fix = helpers()
    info = json.loads((ROOT / '_game/data/troupe.json').read_text(encoding='utf-8'))['kunkka']
    objects, actions = imp(str(ASSETS / Path(info['glb']).name)); fix(objects)
    arm = next(o for o in objects if o.type == 'ARMATURE'); arm.name = 'KunkkaRig'
    for rel in info['parts']:
        part, _ = imp(str(ASSETS / (rel.replace('/', '_').replace('.vmdl', '.glb')))); fix(part)
        for obj in part:
            if obj.type != 'ARMATURE': continue
            obj.animation_data_clear(); obj.matrix_world = arm.matrix_world.copy()
            for bone in obj.pose.bones:
                if bone.name in arm.pose.bones:
                    c = bone.constraints.new('COPY_TRANSFORMS'); c.target = arm; c.subtarget = bone.name
        objects += part
    cast = next(a for a in actions if a.name in ('ghostship', 'ghostship_anim'))
    arm.animation_data_create(); arm.animation_data.action = cast; arm.animation_data.action_slot = cast.slots[0]
    ship, ship_actions = imp(str(ASSETS / 'models_heroes_kunkka_ghostship.glb'))
    for obj in ship:
        obj.hide_render = True
    sc.frame_set(0); bpy.context.view_layer.update()
    report = dict(hero_bounds=bounds(objects), ship_bounds=bounds(ship),
        cast=dict(name=cast.name, frames=list(cast.frame_range)),
        actions=[dict(name=a.name, frames=list(a.frame_range)) for a in actions],
        ship_objects=[dict(name=o.name, type=o.type) for o in ship],
        ship_actions=[a.name for a in ship_actions],
        hero_objects=[o.name for o in objects], bones=[b.name for b in arm.pose.bones])
    (OUT / 'source_inspection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    bpy.ops.mesh.primitive_plane_add(size=200)
    ground = bpy.context.object; ground.name = 'InspectionGround'
    material = bpy.data.materials.new('Ground'); material.diffuse_color = (.12, .14, .17, 1)
    ground.data.materials.append(material)
    light('Key', (4, -5, 8), 1500, (1, .83, .65), 5)
    light('Fill', (-4, -3, 5), 900, (.55, .75, 1), 5)
    light('Rim', (0, 5, 6), 1700, (.3, .8, 1), 4)
    camera_data = bpy.data.cameras.new('Inspection'); camera = bpy.data.objects.new('Inspection', camera_data)
    sc.collection.objects.link(camera); sc.camera = camera; camera_data.lens = 50
    camera.location = (5, -9, 4); aim(camera, (0, 0, 1.6))
    sc.frame_start = 0; sc.frame_end = int(cast.frame_range[1])
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'sources.blend'))
    for frame in (0, 10, 20, 30):
        sc.frame_set(frame); sc.render.filepath = str(OUT / f'cast_{frame:03d}.png')
        bpy.ops.render.render(write_still=True)
    for obj in objects: obj.hide_render = True
    for obj in ship: obj.hide_render = False
    box = bounds(ship); mid = Vector([(a+b)/2 for a,b in zip(box['min'],box['max'])])
    extent = max(b-a for a,b in zip(box['min'],box['max']))
    camera.location = mid + Vector((.9, -1.3, .7))*extent; aim(camera, mid)
    sc.render.filepath = str(OUT / 'ship.png'); bpy.ops.render.render(write_still=True)
    print('INSPECTION_SAVED', OUT / 'source_inspection.json')


def smooth(t):
    t = max(0., min(1., t))
    return t*t*(3-2*t)


def linear_keys(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points: key.interpolation = 'LINEAR'


def stage():
    """Bake a native whole-body cast before adding environment or effects."""
    bpy.ops.wm.open_mainfile(filepath=str(OUT / 'sources.blend'), use_scripts=False)
    sc = bpy.context.scene; arm = bpy.data.objects['KunkkaRig']
    inspection = json.loads((OUT / 'source_inspection.json').read_text())
    cast = arm.animation_data.action
    idle = bpy.data.actions['idle']
    poses = []
    for frame in range(COUNT):
        phase = max(0., min(1., (frame-15)/39)) * cast.frame_range[1]
        arm.animation_data.action = cast; arm.animation_data.action_slot = cast.slots[0]
        sc.frame_set(int(phase), subframe=phase-int(phase)); bpy.context.view_layer.update()
        cast_pose = {b.name:b.matrix_basis.copy() for b in arm.pose.bones}
        arm.animation_data.action = idle; arm.animation_data.action_slot = idle.slots[0]
        idle_phase = frame % int(idle.frame_range[1])
        sc.frame_set(idle_phase); bpy.context.view_layer.update()
        weight = smooth((frame-3)/12) if frame < 15 else 1-smooth((frame-54)/18) if frame > 54 else 1.
        poses.append({b.name:b.matrix_basis.lerp(cast_pose[b.name], weight) for b in arm.pose.bones})
    arm.animation_data_clear()
    for frame, pose in enumerate(poses):
        for bone in arm.pose.bones:
            bone.matrix_basis = pose[bone.name]; bone.rotation_mode = 'QUATERNION'
            bone.keyframe_insert('location', frame=frame)
            bone.keyframe_insert('rotation_quaternion', frame=frame)
            bone.keyframe_insert('scale', frame=frame)
    linear_keys(arm.animation_data.action)
    hero_root = bpy.data.objects.new('KunkkaPlacement', None); sc.collection.objects.link(hero_root)
    for name in inspection['hero_objects']:
        obj = bpy.data.objects[name]
        if obj.parent is None: obj.parent = hero_root
    hero_root.location = (-3.8, 0, .06)
    ship_root = bpy.data.objects.new('ShipCourse', None); sc.collection.objects.link(ship_root)
    for entry in inspection['ship_objects']:
        obj = bpy.data.objects[entry['name']]; obj.hide_render = False
        if obj.parent is None: obj.parent = ship_root
    ship_root.scale = (2.4,)*3
    for frame in range(COUNT):
        ship_root.location = (5.8, 40-(frame-44)*.40, -13+11.4*smooth((frame-43)/45))
        ship_root.rotation_euler = (math.radians(1.2*math.sin(frame*.035)), 0, 0)
        ship_root.keyframe_insert('location', frame=frame)
        ship_root.keyframe_insert('rotation_euler', frame=frame)
    linear_keys(ship_root.animation_data.action)
    for old in list(sc.objects):
        if old.type == 'CAMERA': bpy.data.objects.remove(old, do_unlink=True)
    def camera(name, location, target, lens):
        data = bpy.data.cameras.new(name); data.lens = lens; data.clip_end = 600
        obj = bpy.data.objects.new(name, data); sc.collection.objects.link(obj)
        obj.location = location; aim(obj, target); return obj
    close = camera('01_Command', (2.2, -13, 4.4), (-4.2, 0, 2.7), 32)
    wide = camera('02_Reveal', (12, -30, 8), (-1, 8, 5), 26)
    for name,frame,cam in [('Command',0,close),('Ship reveal',65,wide),('After passage',200,close)]:
        marker = sc.timeline_markers.new(name, frame=frame); marker.camera = cam
    sc.camera = close; sc.frame_start = 0; sc.frame_end = COUNT-1
    sc.render.resolution_x = 540; sc.render.resolution_y = 960
    sc.frame_set(0); bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'blocking.blend'))
    print('BLOCKING_SAVED')


def surface(name, color, roughness=.5, metallic=0):
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    b = mat.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*color,1)
    b.inputs['Roughness'].default_value = roughness; b.inputs['Metallic'].default_value = metallic
    return mat


def dress():
    """Storm coast; purpose-built stage rather than an empty neutral background."""
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'blocking.blend'), use_scripts=False)
    sc = bpy.context.scene
    ground = bpy.data.objects.get('InspectionGround'); bpy.data.objects.remove(ground, do_unlink=True)
    for obj in list(sc.objects):
        if obj.type == 'LIGHT': bpy.data.objects.remove(obj, do_unlink=True)
    ocean = surface('Cold sea', (.014,.075,.10), .23, .35)
    nt = ocean.node_tree; b = nt.nodes.get('Principled BSDF')
    noise = nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 1.6
    noise.inputs['Detail'].default_value = 3
    coord = nt.nodes.new('ShaderNodeTexCoord'); nt.links.new(coord.outputs['Object'],noise.inputs['Vector'])
    bump = nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = .45; bump.inputs['Distance'].default_value = .20
    nt.links.new(noise.outputs['Fac'],bump.inputs['Height']); nt.links.new(bump.outputs['Normal'],b.inputs['Normal'])
    vertices=[]; faces=[]; n=100
    for y in range(n+1):
        for x in range(n+1):
            xx=-160+x*3.2; yy=-120+y*3.2
            vertices.append((xx,yy,-.48+.14*math.sin(xx*.50+yy*.28)+.08*math.sin(yy*.9-xx*.18)))
    for y in range(n):
        for x in range(n):
            a=y*(n+1)+x; faces.append((a,a+1,a+n+2,a+n+1))
    mesh=bpy.data.meshes.new('Sea geometry'); mesh.from_pydata(vertices,[],faces); mesh.update()
    obj=bpy.data.objects.new('Ocean',mesh); sc.collection.objects.link(obj); obj.data.materials.append(ocean)
    for poly in mesh.polygons: poly.use_smooth=True
    rock=surface('Wet dark basalt',(.055,.065,.072),.42)
    nt=rock.node_tree; noise=nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value=5
    bump=nt.nodes.new('ShaderNodeBump'); bump.inputs['Distance'].default_value=.16
    nt.links.new(noise.outputs['Fac'],bump.inputs['Height']); nt.links.new(bump.outputs['Normal'],nt.nodes['Principled BSDF'].inputs['Normal'])
    # Broad broken coastline; calm support patch is surrounded by layered rock.
    rng=random.Random(17); rings=[]; fs=[]; count=55
    for j in range(count):
        y=-27+j*.6
        edge=-1.5+.5*math.sin(y*.8)+.25*math.sin(y*2.2)
        for i in range(count):
            x=-32+(edge+32)*i/(count-1)
            distance=math.sqrt(((x+3.8)/2.6)**2+(y/2.4)**2)
            w=smooth((distance-1)/1.4)
            z=.025+w*(.24*math.sin(x*1.7)+.16*math.sin(y*2.3)+.22*math.sin(x*.8+y*1.2))
            z+=max(0,-x-9)*.09
            rings.append((x,y,z))
    for j in range(count-1):
        for i in range(count-1):
            a=j*count+i; fs.extend([(a,a+1,a+count),(a+1,a+count+1,a+count)])
    for j in range(count-1):
        a=j*count+count-1; b=(j+1)*count+count-1; lower=len(rings)
        rings.extend([(rings[a][0]-.6,rings[a][1],-8),(rings[b][0]-.6,rings[b][1],-8)])
        fs.append((a,b,lower+1,lower))
    mesh=bpy.data.meshes.new('Ledge'); mesh.from_pydata(rings,[],fs); mesh.update()
    obj=bpy.data.objects.new('Cliff ledge',mesh); sc.collection.objects.link(obj); obj.data.materials.append(rock)
    for polygon in mesh.polygons: polygon.use_smooth=True
    imp,fix=helpers()
    rocks,_=imp(str(ASSETS/'models_props_rock_riveredge_rock_wall001a.glb')); fix(rocks)
    rock_mesh=next(o for o in rocks if o.type=='MESH')
    native_box=bounds([rock_mesh]); native_mid=Vector([(a+b)/2 for a,b in zip(native_box['min'],native_box['max'])])
    # Bake the import transform once so copies retain the source geometry and UVs.
    rock_mesh.data.transform(rock_mesh.matrix_world); rock_mesh.matrix_world.identity(); rock_mesh.parent=None
    for vert in rock_mesh.data.vertices: vert.co-=native_mid
    size=Vector(native_box['max'])-Vector(native_box['min'])
    rock_mesh.hide_render=True
    # Distant coastline gives the ship a scale reference and closes the horizon.
    for i in range(17):
        x=-100+i*12; y=105+rng.uniform(-15,20)
        cliff=rock_mesh.copy(); cliff.data=rock_mesh.data; sc.collection.objects.link(cliff)
        cliff.hide_render=False; cliff.name='Coast'; cliff.location=(x,y,4)
        cliff.scale=tuple(a/b for a,b in zip((rng.uniform(15,25),rng.uniform(10,18),rng.uniform(12,30)),size))
        cliff.rotation_euler.z=rng.uniform(-.4,.4)
    bpy.ops.mesh.primitive_cube_add(size=1,location=(0,90,14))
    mist=bpy.context.object; mist.name='Distant sea mist'; mist.scale=(270,130,30)
    fog=bpy.data.materials.new('Salt haze'); fog.use_nodes=True; fog.node_tree.nodes.clear()
    volume=fog.node_tree.nodes.new('ShaderNodeVolumePrincipled'); volume.inputs['Density'].default_value=.018
    volume.inputs['Color'].default_value=(.35,.47,.54,1); volume.inputs['Anisotropy'].default_value=.25
    output=fog.node_tree.nodes.new('ShaderNodeOutputMaterial'); fog.node_tree.links.new(volume.outputs['Volume'],output.inputs['Volume'])
    mist.data.materials.append(fog)
    world=sc.world; nt=world.node_tree; nt.nodes.clear()
    out=nt.nodes.new('ShaderNodeOutputWorld'); bg=nt.nodes.new('ShaderNodeBackground'); bg.inputs['Strength'].default_value=.32
    coord=nt.nodes.new('ShaderNodeTexCoord'); noise=nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value=4
    noise.inputs['Detail'].default_value=4
    ramp=nt.nodes.new('ShaderNodeValToRGB'); ramp.color_ramp.elements[0].color=(.015,.028,.055,1)
    ramp.color_ramp.elements[1].color=(.25,.34,.43,1)
    nt.links.new(coord.outputs['Normal'],noise.inputs['Vector']); nt.links.new(noise.outputs['Fac'],ramp.inputs[0]); nt.links.new(ramp.outputs[0],bg.inputs[0]); nt.links.new(bg.outputs[0],out.inputs['Surface'])
    light('Warm command light',(-7,-6,10),2400,(1,.79,.54),7,(-3.8,0,2))
    light('Sky fill',(3,-10,9),1800,(.45,.69,1),9,(-3.8,0,2))
    light('Ship rim',(0,18,20),14000,(.19,.77,1),15,(5,14,5))
    sun_data=bpy.data.lights.new('Cloud break','SUN'); sun_data.energy=1.5; sun_data.angle=.35; sun_data.color=(.62,.77,1)
    sun=bpy.data.objects.new('Cloud break',sun_data); sc.collection.objects.link(sun); sun.rotation_euler=(.4,-.5,-.6)
    inspection=json.loads((OUT/'source_inspection.json').read_text())
    for entry in inspection['ship_objects']:
        obj=bpy.data.objects[entry['name']]
        for slot in obj.material_slots:
            mat=slot.material
            if not mat or not mat.use_nodes or mat.get('ghost_tint'): continue
            mat['ghost_tint']=True; nt=mat.node_tree; b=nt.nodes.get('Principled BSDF')
            if not b: continue
            base=b.inputs['Base Color']; color=base.links[0].from_socket if base.links else None
            mix=nt.nodes.new('ShaderNodeMixRGB'); mix.blend_type='MULTIPLY'; mix.inputs[0].default_value=1
            mix.inputs[2].default_value=(.20,.63,.76,1)
            if color:
                mono=nt.nodes.new('ShaderNodeRGBToBW'); nt.links.new(color,mono.inputs[0]); nt.links.new(mono.outputs[0],mix.inputs[1])
            else: mix.inputs[1].default_value=(.55,.55,.55,1)
            nt.links.new(mix.outputs[0],base); nt.links.new(mix.outputs[0],b.inputs['Emission Color']); b.inputs['Emission Strength'].default_value=.55
            for input_name,value in [('Alpha',1),('Roughness',.56),('Metallic',0)]:
                socket=b.inputs[input_name]
                for link in list(socket.links): nt.links.remove(link)
                socket.default_value=value
    sc.render.image_settings.color_mode='RGB'; sc.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
    print('SCENE_SAVED')


def preview(mode):
    source='blocking.blend' if mode in ('blocking-probe','motion') else 'scene.blend'
    bpy.ops.wm.open_mainfile(filepath=str(OUT/source),use_scripts=False)
    sc=bpy.context.scene
    sys.path.insert(0,str(ROOT/'tools/blender'))
    from study_head_target import gpu_guard
    gpu_guard()
    frames=(0,33,68,100,145,185)
    if mode in ('render','motion'):
        if shutil.disk_usage(OUT).free < 350_000_000: raise RuntimeError('Insufficient space for checked preview')
        folder=OUT/('motion_frames' if mode=='motion' else 'frames'); folder.mkdir(exist_ok=True)
        if mode=='motion':
            sc.render.resolution_percentage=50; sc.eevee.taa_render_samples=8
        sc.render.filepath=str(folder/'frame_'); bpy.ops.render.render(animation=True)
    else:
        for frame in frames:
            sc.frame_set(frame); sc.render.filepath=str(OUT/f'{mode}_{frame:03d}.png')
            bpy.ops.render.render(write_still=True)


def audit():
    """Narrow all-frame staging checks; not a skin or acting quality certificate."""
    from bpy_extras.object_utils import world_to_camera_view
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'blocking.blend'),use_scripts=False)
    sc=bpy.context.scene; arm=bpy.data.objects['KunkkaRig']; ship=bpy.data.objects['ShipCourse']
    names=('head','wrist_L','wrist_R','ankle_L','ankle_R'); previous=None; peak=0.; errors=[]
    for f in range(COUNT):
        sc.frame_set(f); bpy.context.view_layer.update()
        points={n:arm.matrix_world@arm.pose.bones[n].matrix.translation for n in names}
        if not all(math.isfinite(v) for p in points.values() for v in p): errors.append([f,'nonfinite'])
        if previous: peak=max(peak,max((points[n]-previous[n]).length for n in names))
        if f<155:
            for name,p in points.items():
                q=world_to_camera_view(sc,sc.camera,p)
                if not (0<=q.x<=1 and 0<=q.y<=1 and q.z>0): errors.append([f,name,'outside'])
        previous=points
    # Initial-pose bounding corridor only; it does not certify every deformed surface.
    report=json.loads((OUT/'source_inspection.json').read_text())
    left=report['ship_bounds']['min'][0]*ship.scale.x+ship.location.x
    right=report['hero_bounds']['max'][0]-3.8
    if left-right<1: errors.append(['ship course clearance',left-right])
    if peak>.65: errors.append(['landmark discontinuity',peak])
    result=dict(passed=not errors,frames=COUNT,max_landmark_step=peak,errors=errors,
        ship_hero_x_clearance=left-right,
        scope='Finite joints, adjacent joint displacement, camera landmarks before intentional bow wipe, initial-pose X corridor. Not a whole-motion mesh collision, skin, gaze or aesthetic certificate.')
    (OUT/'audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    if errors: raise RuntimeError('Staging audit failed')


if __name__ == '__main__':
    mode=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'inspect'
    if mode=='inspect': inspect()
    elif mode=='stage': stage()
    elif mode=='dress': dress()
    elif mode=='audit': audit()
    else: preview(mode)
