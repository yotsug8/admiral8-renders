"""Replacement look probe: detailed licensed tank, bone-bound launcher, native set.

Run on the preserved storyboard.blend. Saves a distinct scene and stills only.
"""
import ast
import json
import math
import random
from pathlib import Path
import sys
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'_game/skits/pudge_tank/revision'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT/'tools/blender'))
sc = bpy.context.scene
sc.frame_set(0)
hero = bpy.data.objects['pudge_root']
old_launcher = bpy.data.objects['rocket_launcher']
remove = {old_launcher, *old_launcher.children_recursive}
keep = {hero, *hero.children_recursive}-remove
for ob in list(sc.objects):
    if ob not in keep: bpy.data.objects.remove(ob, do_unlink=True)
hero.animation_data_clear()
hero.location = (-2, -1, 0)
hero.rotation_euler = (0, 0, math.radians(-8))
arm = max((o for o in hero.children_recursive if o.type == 'ARMATURE'), key=lambda o: len(o.pose.bones))
sc.animation_data_clear()
sc.frame_start, sc.frame_end = 0, 89
sc.render.fps = 30
sc.render.engine = 'BLENDER_EEVEE'
sc.eevee.taa_render_samples = 64
sc.render.resolution_x, sc.render.resolution_y = 540, 960
sc.render.resolution_percentage = 100
sc.render.use_sequencer = False
sc.view_settings.view_transform = 'Khronos PBR Neutral'
sc.view_settings.exposure = .25
sc.render.image_settings.file_format = 'PNG'

def empty(name):
    ob = bpy.data.objects.new(name, None)
    sc.collection.objects.link(ob)
    return ob

def imported(path, name, position=(0, 0, 0), scale=1, rotation=0):
    before = set(sc.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = set(sc.objects)-before
    root = empty(name)
    for ob in objects:
        if not ob.parent: ob.parent = root
    root.location, root.scale = position, (scale,)*3
    root.rotation_euler.z = math.radians(rotation)
    return root, objects

external = ROOT/'_game/external/pudge_tank'
tank, tank_objects = imported(external/'scene.gltf', 'detailed_tank', (3, 8, 0), 1.1, 0)
launcher, launcher_objects = imported(external/'launcher.glb', 'held_launcher', scale=2.6)
# Real hand attachment: the weapon bone is the native grip reference, below the
# wrist. The asset's pistol-grip center, rather than tube center, meets it.
bpy.context.view_layer.update()
# Turn the wrist and its real grip together so the carried launcher reads in
# silhouette. Moving only the prop would push its tube through the fingers.
wrist = arm.pose.bones['wrist_R']
pivot = wrist.matrix.translation.copy()
wrist_turn = Matrix.Rotation(math.radians(-45), 4, 'Z')
wrist.matrix = Matrix.Translation(pivot) @ wrist_turn @ Matrix.Translation(-pivot) @ wrist.matrix
bpy.context.view_layer.update()
grip_bone = arm.pose.bones['weapon_rt_1']
hand_world = arm.matrix_world @ grip_bone.matrix
prop_grip = Vector((0, -.075, .182))
native_axis = Vector((-.23194261, -.96044118, .15412777))
axis = wrist_turn.to_3x3() @ native_axis
y_axis = -axis.normalized()
x_axis = y_axis.cross(Vector((0, 0, 1))).normalized()
z_axis = x_axis.cross(y_axis).normalized()
orientation = Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()
grip_offset = Vector((0, 0, -.024))
desired = Matrix.Translation(hand_world.translation+grip_offset) @ orientation @ Matrix.Scale(2.6, 4) @ Matrix.Translation(-prop_grip)
launcher.matrix_world = desired
constraint = launcher.constraints.new('CHILD_OF')
constraint.name = 'native right hand grip'
constraint.target, constraint.subtarget = arm, grip_bone.name
constraint.inverse_matrix = hand_world.inverted()
bpy.context.view_layer.update()

def mat(name, color, rough=.8):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = rough
    return m

metal = mat('launcher worn blued steel', (.065, .073, .055), .38)
metal.node_tree.nodes['Principled BSDF'].inputs['Metallic'].default_value = .72
wood = mat('launcher dark wood', (.20, .065, .022), .65)
warhead = mat('launcher olive warhead', (.04, .065, .018), .65)
for m, scale in ((metal, 35), (wood, 8), (warhead, 24)):
    nt = m.node_tree
    n = nt.nodes.new('ShaderNodeTexNoise')
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = 3
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .18
    bump.inputs['Distance'].default_value = .008
    nt.links.new(n.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs[0], nt.nodes['Principled BSDF'].inputs['Normal'])
for ob in launcher_objects:
    if ob.type != 'MESH': continue
    local = launcher.matrix_world.inverted() @ ob.matrix_world
    ob.data.materials.clear()
    for m in (metal, wood, warhead): ob.data.materials.append(m)
    for p in ob.data.polygons:
        co = local @ p.center
        p.material_index = 2 if ob.name.startswith('rocket-mesh') else 1 if (co.z < .13 or .10<co.y<.43) else 0
        p.use_smooth = True
    # Carry the launcher by its tube, matching the native horizontal hook grip.
    # The hanging pistol grip is removed, rather than left outside the fist.
    if ob.name == 'launcher-body':
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        drop = [v for v in bm.verts if (local@v.co).z<.14]
        bmesh.ops.delete(bm, geom=drop, context='VERTS')
        bm.to_mesh(ob.data)
        bm.free()
    if ob.name == 'trigger-mesh': ob.hide_render = True
    old = ob.data
    rebuilt = bpy.data.meshes.new(old.name+'_clean_normals')
    rebuilt.from_pydata([tuple(v.co) for v in old.vertices], [], [tuple(p.vertices) for p in old.polygons])
    for m in old.materials: rebuilt.materials.append(m)
    for src, dst in zip(old.polygons, rebuilt.polygons):
        dst.material_index = src.material_index
        dst.use_smooth = True
    ob.data = rebuilt
    mod = ob.modifiers.new('prop edge highlights', 'BEVEL')
    mod.width, mod.segments = .0025, 3
    ob.modifiers.new('prop weighted normals', 'WEIGHTED_NORMAL')

def textured(name, texture, repeats=1):
    m = mat(name, (.2, .2, .2))
    nt = m.node_tree
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(str(ROOT/'_game/world'/texture), check_existing=True)
    coord = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeVectorMath')
    mapping.operation = 'SCALE'
    mapping.inputs[3].default_value = repeats
    nt.links.new(coord.outputs['UV'], mapping.inputs[0])
    nt.links.new(mapping.outputs[0], tex.inputs[0])
    nt.links.new(tex.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .35
    bump.inputs['Distance'].default_value = .11
    nt.links.new(tex.outputs['Color'], bump.inputs['Height'])
    nt.links.new(bump.outputs[0], nt.nodes['Principled BSDF'].inputs['Normal'])
    return m

stone = textured('native cracked stone', 'stone_path007_color_psd_22aa3f8.png', 20)
earth = textured('native earth and rock', 'dirt_cracked_patchy_00_psd_3956639e.png', 5)
bpy.ops.mesh.primitive_grid_add(x_subdivisions=90, y_subdivisions=90, size=160)
ground = bpy.context.object
ground.name = 'uneven courtyard ground'
rng = random.Random(813)
for v in ground.data.vertices:
    x, y = v.co.x, v.co.y
    # Flat contact region; rolling shoulders outside the driving corridor.
    edge = max(0, min(1, (abs(x)-7)/8))
    far = max(0, min(1, (y-28)/18))
    v.co.z = edge*(1.8+math.sin(y*.19)*1.0+math.sin(x*.25)*.6)+far*(5+math.sin(x*.09)*2.5)
ground.data.materials.append(stone)
nt = stone.node_tree
position = nt.nodes.new('ShaderNodeNewGeometry')
sep = nt.nodes.new('ShaderNodeSeparateXYZ')
nt.links.new(position.outputs['Position'], sep.inputs[0])
absolute = nt.nodes.new('ShaderNodeMath')
absolute.operation = 'ABSOLUTE'
nt.links.new(sep.outputs['X'], absolute.inputs[0])
border = nt.nodes.new('ShaderNodeMapRange')
border.interpolation_type = 'SMOOTHSTEP'
border.inputs['From Min'].default_value = 6
border.inputs['From Max'].default_value = 12
nt.links.new(absolute.outputs[0], border.inputs['Value'])
earth_tex = nt.nodes.new('ShaderNodeTexImage')
earth_tex.image = bpy.data.images.load(str(ROOT/'_game/world/dirt_cracked_patchy_00_psd_3956639e.png'), check_existing=True)
uv = next(n for n in nt.nodes if n.type=='VECT_MATH')
nt.links.new(uv.outputs[0], earth_tex.inputs[0])
blend = nt.nodes.new('ShaderNodeMixRGB')
current = nt.nodes['Principled BSDF'].inputs['Base Color'].links[0].from_socket
nt.links.new(current, blend.inputs[1])
tint = nt.nodes.new('ShaderNodeMixRGB')
tint.blend_type = 'MULTIPLY'
tint.inputs[0].default_value = 1
tint.inputs[2].default_value = (.18, .14, .085, 1)
nt.links.new(earth_tex.outputs['Color'], tint.inputs[1])
nt.links.new(tint.outputs[0], blend.inputs[2])
nt.links.new(border.outputs[0], blend.inputs[0])
nt.links.new(blend.outputs[0], nt.nodes['Principled BSDF'].inputs['Base Color'])

# Real Dire architecture creates foreground, courtyard, gateway and far layers.
source = ROOT/'tools/blender/render_scene.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
names = {'fix_hero_mats'}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='HERO' for t in n.targets)]
import os
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), globals())
rnd = ROOT/'_game/models/render'
set_objects = []
for file, position, scale, rotation in [
    ('dire_tower002', (-12, 13, 0), .85, 20),
    ('dire_tower002', (14, 17, 0), .9, -20),
    ('dire_barracks_melee001', (-16, 30, 0), 1.25, 0),
    ('dire_barracks_ranged001', (15, 32, 0), 1.3, 0),
    ('bad_wallstatue001a', (-10, 1, 0), .7, -65),
    ('dire_column001', (11, 3, 0), .8, 0),
    ('dire_column001', (-10, 25, 0), 1.3, 0),
    ('dire_column001', (10, 25, 0), 1.3, 0),
]:
    root, objects = imported(rnd/f'tank_{file}.glb', 'set_'+file, position, 1, rotation)
    bpy.context.view_layer.update()
    points = [o.matrix_world@Vector(v) for o in objects if o.type=='MESH' for v in o.bound_box]
    height = max(p.z for p in points)-min(p.z for p in points)
    target_height = 9 if 'tower' in file else 6 if 'column' in file else 4.5
    root.scale = (target_height/height,)*3
    bpy.context.view_layer.update()
    low = min((o.matrix_world@Vector(v)).z for o in objects if o.type=='MESH' for v in o.bound_box)
    root.location.z -= low
    fix_hero_mats(objects)
    set_objects.extend(objects)
ancient, objects = imported(rnd/'tank_dire_ancient.glb', 'enemy_ancient', (1, 35, .1), 1.1, 180)
fix_hero_mats(objects)

# Full trees, linked copies in irregular depth bands, rather than one exposed
# ring. The gate lane stays clear and the far canopy fills the skyline.
tree_root, trees = imported(rnd/'models_props_tree_tree_pine_01_sfm.glb', 'background_tree_source')
for ob in trees:
    if ob.type == 'MESH':
        for ms in ob.material_slots:
            if ms.material and ms.material.use_nodes:
                b = ms.material.node_tree.nodes.get('Principled BSDF')
                if b: b.inputs['Metallic'].default_value = 0
tree_root.location = (-27, 28, 0)
bpy.context.view_layer.update()
tree_points = [o.matrix_world@Vector(v) for o in trees if o.type=='MESH' for v in o.bound_box]
tree_height = max(p.z for p in tree_points)-min(p.z for p in tree_points)
tree_root.scale = (10/tree_height,)*3
for i in range(65):
    x = rng.uniform(-48, 48)
    y = rng.uniform(26, 80)
    if abs(x) < 13 and y < 50: continue
    root = empty('distant full tree')
    root.location = (x, y, 0)
    root.rotation_euler.z = rng.uniform(0, math.tau)
    root.scale = (10/tree_height*rng.uniform(1.1, 1.8),)*3
    mapping = {}
    for ob in trees:
        clone = ob.copy()
        sc.collection.objects.link(clone)
        mapping[ob] = clone
    for original, clone in mapping.items():
        clone.parent = mapping.get(original.parent, root)

# Broken roadside stones add near-scale detail without filling the actor lane.
for i in range(65):
    x = rng.choice((-1, 1))*rng.uniform(7.5, 22)
    y = rng.uniform(-9, 44)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=rng.uniform(.18, .85), location=(x, y, .25))
    ob = bpy.context.object
    ob.name = 'roadside basalt rubble'
    ob.scale = (1.4, .8, .6)
    ob.rotation_euler.z = rng.uniform(0, 6)
    ob.data.materials.append(earth)

# Sky, atmospheric separation and controlled warm/cool lighting.
world = bpy.data.worlds.new('cloudy battlefield sky')
world.use_nodes = True
nt = world.node_tree
bg = nt.nodes['Background']
sky = nt.nodes.new('ShaderNodeTexSky')
sky.sky_type = 'MULTIPLE_SCATTERING'
sky.sun_elevation = math.radians(19)
sky.sun_rotation = math.radians(125)
sky.air_density = 1.2
nt.links.new(sky.outputs[0], bg.inputs[0])
bg.inputs[1].default_value = .3
sc.world = world

def light(name, kind, location, energy, color, target=None, size=5):
    ld = bpy.data.lights.new(name, kind)
    ld.energy, ld.color = energy, color
    if kind == 'AREA': ld.shape, ld.size = 'DISK', size
    if kind == 'SUN': ld.angle = math.radians(10)
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = location
    if target: ob.rotation_euler = (Vector(target)-ob.location).to_track_quat('-Z', 'Y').to_euler()
    return ob

light('warm sun', 'SUN', (-20, -18, 35), 2.2, (1, .8, .57), (0, 0, 0))
light('large cool sky fill', 'AREA', (-9, -7, 12), 2200, (.62, .76, 1), (0, 0, 2), 13)
light('tank rim', 'AREA', (8, 9, 12), 2700, (1, .63, .32), (1, 1, 2), 9)
for x, y in ((-10, 13), (12, 17), (-8, 28), (8, 28)):
    light('Dire ember glow', 'POINT', (x, y, 3), 500, (1, .16, .025))

cam = bpy.data.objects.new('look_camera', bpy.data.cameras.new('look_camera'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.sensor_fit = 'VERTICAL'
cam.data.clip_end = 400
cam.data.dof.use_dof = True
cam.data.dof.aperture_fstop = 1.8

# One look frame is sufficient to judge the replacement materials. GPU path
# tracing is optional; no animation render is triggered here.
sc.render.engine = 'CYCLES'
sc.cycles.samples = 96
sc.cycles.use_denoising = True
preferences = bpy.context.preferences.addons['cycles'].preferences
preferences.compute_device_type = 'CUDA'
preferences.get_devices()
for device in preferences.devices: device.use = device.type == 'CUDA'
sc.cycles.device = 'GPU'

def render(name, location, target, lens, size=(540, 960)):
    cam.location = location
    cam.rotation_euler = (Vector(target)-cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = lens
    cam.data.dof.focus_distance = (Vector(target)-cam.location).length
    sc.render.resolution_x, sc.render.resolution_y = size
    if name == 'look_v2.png':
        from bpy_extras.object_utils import world_to_camera_view
        bpy.context.view_layer.update()
        points = [o.evaluated_get(dg).matrix_world@Vector(v)
                  for o in [*hero_meshes, *launcher_objects, *tank_objects]
                  if o.type=='MESH' and not o.hide_render
                  for v in o.evaluated_get(dg).bound_box]
        for _ in range(50):
            bpy.context.view_layer.update()
            projected = [world_to_camera_view(sc, cam, p) for p in points]
            if all(.06 <= p.x <= .94 and .1 <= p.y <= .88 and p.z>0 for p in projected): break
            cam.location = Vector(target)+(cam.location-Vector(target))*1.04
        else: raise ValueError('Cannot fit actor, launcher and tank in the look probe')
        cam.data.dof.focus_distance = (Vector(target)-cam.location).length
    sc.render.filepath = str(OUT/name)
    bpy.ops.render.render(write_still=True)

# A still is rejected before rendering if the actor intersects the tank.
from mathutils.bvhtree import BVHTree
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
def surface(ob):
    ev = ob.evaluated_get(dg)
    mesh = ev.to_mesh()
    vertices = [ev.matrix_world@v.co for v in mesh.vertices]
    polygons = [list(p.vertices) for p in mesh.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
hero_meshes = [o for o in hero.children_recursive if o.type=='MESH' and
               not any(t in o.name.lower() for t in ('hitbox', 'physics'))]
tank_bvh = {o:surface(o) for o in tank_objects if o.type=='MESH'}
overlap = []
for ob in hero_meshes:
    bvh = surface(ob)
    for other, other_bvh in tank_bvh.items():
        hits = bvh.overlap(other_bvh)
        if hits: overlap.append(dict(actor=ob.name, tank=other.name, triangle_pairs=len(hits)))
if overlap:
    (OUT/'rejected_overlap.json').write_text(json.dumps(overlap, indent=2))
    raise ValueError('Actor intersects tank; correct blocking before showing a still')

render('look_v2.png', (0, -12, 4.5), (-1, 3, 2.5), 24)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'look_v2.blend'))
grip = (launcher.matrix_world @ prop_grip).copy()
render('grip_front.png', grip+Vector((-1.6, -2.4, .7)), grip, 54, (700, 700))
render('grip_side.png', grip+Vector((-2.7, .2, .6)), grip, 54, (700, 700))
report = dict(stage='Replacement still only; no animation acceptance',
    grip_bone=grip_bone.name, grip_position=list(grip),
    grip_reference_offset_m=list(grip_offset),
    grip_reference_error_m=(grip-(hand_world.translation+grip_offset)).length,
    tank_meshes=sum(o.type=='MESH' for o in tank_objects),
    tank_triangles=sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in tank_objects if o.type=='MESH'),
    actor_tank_surface_overlap=overlap,
    limits='Bone reference agreement does not certify fingers or surface intersections; inspect both close views.')
(OUT/'look_v2_qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
