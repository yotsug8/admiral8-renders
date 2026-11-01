"""Build isolated Pudge tank storyboard probes using local Dota assets.

No full animation render is started. Tank and launcher are original prop meshes;
the hero, Dire base and Ancient are native game resources kept outside Git.
"""
import ast
import json
import math
import os
import random
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/blender'))
OUT = ROOT / '_game/skits/pudge_tank'
OUT.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = 30
sc.render.engine = 'BLENDER_EEVEE'
sc.eevee.taa_render_samples = 48
sc.render.resolution_x, sc.render.resolution_y = 540, 960
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = 'Khronos PBR Neutral'
sc.render.image_settings.file_format = 'PNG'
sc.render.film_transparent = False

# Reuse the accepted importer and hero shader without executing its CLI.
source = ROOT / 'tools/blender/render_scene.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
names = {'imp', 'fix_hero_mats', 'dota_shade', 'close_neck', 'mouth_dark'}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
nodes += [n for n in tree.body if isinstance(n, ast.Assign) and
          any(isinstance(t, ast.Name) and t.id in ('HERO', 'DOTA') for t in n.targets)]
R = math.radians
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), globals())

def empty(name, parent=None):
    ob = bpy.data.objects.new(name, None)
    sc.collection.objects.link(ob)
    ob.parent = parent
    return ob

def material(name, color, metal=0, rough=.5):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    if metal > .3:
        nt = m.node_tree
        noise = nt.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 18
        noise.inputs['Detail'].default_value = 3
        bump = nt.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = .16
        bump.inputs['Distance'].default_value = .035
        nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m

olive = material('worn olive armor', (.14, .19, .095), .55, .42)
edge = material('armor edges', (.24, .28, .15), .6, .4)
steel = material('dark steel', (.055, .065, .06), .8, .38)
rubber = material('track dark', (.026, .029, .023), .35, .66)
red = material('warning red', (.48, .055, .025), .35)
black = material('bore interior', (.005, .006, .004))

def box(name, loc, size, mat, parent=None, bevel=.06):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    ob = bpy.context.object
    ob.name = name
    ob.parent = parent
    ob.location = loc
    ob.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    ob.data.materials.append(mat)
    if bevel:
        mod = ob.modifiers.new('machined edges', 'BEVEL')
        mod.width, mod.segments = bevel, 3
        ob.modifiers.new('weighted normals', 'WEIGHTED_NORMAL')
    return ob

def cylinder(name, loc, radius, depth, mat, parent=None, axis='Z', vertices=32):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth)
    ob = bpy.context.object
    ob.name, ob.parent, ob.location = name, parent, loc
    if axis == 'X': ob.rotation_euler.y = math.pi/2
    if axis == 'Y': ob.rotation_euler.x = math.pi/2
    ob.data.materials.append(mat)
    mod = ob.modifiers.new('rim bevel', 'BEVEL')
    mod.width, mod.segments = .025, 2
    ob.modifiers.new('weighted normals', 'WEIGHTED_NORMAL')
    return ob

tank = empty('tank')
box('lower hull', (0, 0, 1), (3.8, 6.3, 1.1), olive, tank, .22)
box('upper deck', (0, -.1, 1.8), (4, 6, .65), olive, tank, .18)
glacis = box('sloping front armor', (0, -2.8, 1.65), (3.8, .7, 1), edge, tank)
glacis.rotation_euler.x = R(-25)
for side in (-1, 1):
    x = side*2.05
    box('track belt', (x, 0, .85), (.8, 6.45, 1.5), rubber, tank, .48)
    for y in (-2.4, -1.45, -.5, .5, 1.45, 2.4):
        cylinder('roadwheel', (x+side*.4, y, .85), .62, .12, steel, tank, 'X')
        cylinder('wheel hub', (x+side*.48, y, .85), .22, .14, edge, tank, 'X')
    for j in range(26):
        y = -3.05+j*.244
        for z in (.12, 1.58):
            box('individual tread', (x, y, z), (.84, .14, .12), steel, tank, .015)
    box('fender', (x, 0, 1.75), (1, 6.8, .14), edge, tank)
    for y in (-2, 0, 2):
        box('side armor panel', (side*2.5, y, 1.45), (.13, 1.85, .7), olive, tank)
        for yy in (y-.65, y+.65):
            cylinder('armor bolt', (side*2.59, yy, 1.55), .065, .05, steel, tank, 'X', 12)
    cylinder('rear fuel drum', (side*1.35, 2.95, 2.12), .37, 1.25, steel, tank, 'X')
    box('lamp housing', (side*1.45, -3.12, 1.96), (.42, .2, .35), steel, tank)
    cylinder('lamp lens', (side*1.45, -3.24, 1.96), .14, .035, edge, tank, 'Y')
turret = empty('turret', tank)
cylinder('turret ring', (0, -.15, 2.2), 1.5, .25, steel, turret)
# Four walls leave a genuine open hatch; the hero is never cut with a plane.
box('turret front', (0, -1.3, 2.65), (2.8, .5, .95), olive, turret, .15)
box('turret rear', (0, 1.1, 2.65), (2.8, .5, .95), olive, turret, .15)
for x in (-1.2, 1.2):
    box('turret wall', (x, -.1, 2.65), (.45, 2.4, .95), olive, turret, .12)
cylinder('gun mantlet', (0, -1.62, 2.6), .46, .6, edge, turret, 'Y')
cylinder('cannon', (0, -3.3, 2.6), .22, 3.2, steel, turret, 'Y')
cylinder('muzzle brake', (0, -4.95, 2.6), .33, .55, olive, turret, 'Y')
cylinder('dark open muzzle', (0, -5.235, 2.6), .21, .01, black, turret, 'Y')
lid = cylinder('open hatch lid', (0, 1.2, 3.35), 1.05, .12, edge, turret)
lid.rotation_euler.x = R(-75)
for x in (-1.05, 1.05):
    box('grab rail support', (x, 0, 3.16), (.08, 1.1, .1), steel, turret)

info = json.loads((ROOT/'_game/data/troupe.json').read_text())['pudge']
rnd = ROOT/'_game/models/render'
objs, actions = imp(str(rnd/'models_heroes_pudge_pudge.glb'))
fix_hero_mats(objs)
arm = next(o for o in objs if o.type == 'ARMATURE')
hero = empty('pudge_root')
arm.parent = hero
idle = next(a for a in actions if a.name in ('pudge_idle', 'pudge_idle_anim'))
arm.animation_data_create().action = idle
arm.animation_data.action_slot = idle.slots[0]
sc.frame_set(5)
basis = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
arm.animation_data_clear()
for b in arm.pose.bones: b.matrix_basis = basis[b.name]
for rel in info['parts']:
    if 'leftweapon' in rel or 'righthook' in rel: continue
    parts, _ = imp(str(rnd/rel.replace('/', '_').replace('.vmdl', '.glb')))
    fix_hero_mats(parts)
    objs += parts
    for pa in (o for o in parts if o.type == 'ARMATURE'):
        pa.animation_data_clear()
        pa.parent = hero
        pa.matrix_world = arm.matrix_world.copy()
        for b in pa.pose.bones:
            if b.name in arm.pose.bones:
                c = b.constraints.new('COPY_TRANSFORMS')
                c.target, c.subtarget = arm, b.name
head = next((o for o in objs if o.type == 'MESH' and o.data.shape_keys), None)
if head:
    mouth_dark(head)
    close_neck(head, objs)
dota_shade(objs)

# The launcher grip is staged against the native hand. Finger contact is reviewed
# in the probes before this prop can be used for animation.
sc.frame_set(0)
bpy.context.view_layer.update()
hand = next(b for b in arm.pose.bones if b.name.lower() in ('wrist_r', 'hand_r'))
grip = arm.matrix_world @ hand.matrix.translation
launcher = empty('rocket_launcher', hero)
launcher.location = grip
cylinder('launcher tube', (0, 0, .45), .25, 2.5, olive, launcher, 'Y')
for y in (-1.22, 1.22):
    cylinder('launcher rim', (0, y, .45), .31, .12, steel, launcher, 'Y')
cylinder('launcher bore', (0, -1.29, .45), .22, .015, black, launcher, 'Y')
box('pistol grip', (0, .15, .13), (.16, .2, .55), steel, launcher)
box('sight bracket', (.23, -.15, .75), (.12, .7, .15), steel, launcher)
cylinder('optical sight', (.26, -.15, .88), .09, .55, steel, launcher, 'Y')
for y in (.65, .83): cylinder('red identification stripe', (0, y, .45), .254, .12, red, launcher, 'Y')

# Native Dire base, translated as a unit into local shot coordinates.
import dota_map
mapobjs = dota_map.load(str(ROOT/'_game/maps/dire_tank_base_v2.glb'), str(ROOT/'_game/world'), ground_z=6.3)
origin = Vector((4999.998047/39.37, -5527.997070/39.37, 248/39.37))
for ob in mapobjs:
    if not ob.parent: ob.location -= origin
bpy.context.view_layer.update()
# A purpose-built battlefield uses native distant trees and original textured
# paving. It is a film set, not a claim to reproduce a playable map location.
for ob in mapobjs:
    if ob.type != 'MESH': continue
    center = ob.matrix_world @ (sum((Vector(v) for v in ob.bound_box), Vector())/8)
    keep = 'tree' in ob.name.lower() and center.xy.length > 27
    ob.hide_render = ob.hide_render or not keep
trees = [o for o in mapobjs if o.type == 'MESH' and
         o.name.startswith('tree_oak_01b.') and 'stump' not in o.name]
if trees:
    base = trees[0].matrix_world.translation.copy()
    low = min((o.matrix_world @ Vector(c)).z for o in trees for c in o.bound_box)
    for ring, count in ((39, 30), (56, 36)):
        for i in range(count):
            angle = i*math.tau/count
            position = Vector((math.cos(angle)*ring, -8+math.sin(angle)*ring, -low))
            for original in trees:
                ob = original.copy()
                ob.data = original.data
                ob.parent = None
                sc.collection.objects.link(ob)
                ob.matrix_world = original.matrix_world.copy()
                ob.location += position-Vector((base.x, base.y, 0))
                ob.hide_render = False
ground_mat = material('Dire basalt paving', (.15, .14, .12), 0, .88)
nt = ground_mat.node_tree
im = nt.nodes.new('ShaderNodeTexImage')
im.image = bpy.data.images.load(str(ROOT/'_game/world/stone_path007_color_psd_22aa3f8.png'))
uv = nt.nodes.new('ShaderNodeTexCoord')
mapping = nt.nodes.new('ShaderNodeVectorMath')
mapping.operation = 'SCALE'
mapping.inputs[3].default_value = 30
nt.links.new(uv.outputs['UV'], mapping.inputs[0])
nt.links.new(mapping.outputs[0], im.inputs['Vector'])
nt.links.new(im.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
bpy.ops.mesh.primitive_plane_add(size=240, location=(0, 0, 0))
bpy.context.object.name = 'battlefield native stone paving'
bpy.context.object.data.materials.append(ground_mat)

ancient_objs, ancient_actions = imp(str(rnd/'tank_dire_ancient.glb'))
fix_hero_mats(ancient_objs)
ancient = empty('enemy_ancient')
for ob in ancient_objs:
    if not ob.parent: ob.parent = ancient
ancient.location = (0, -34, 0)

world = bpy.data.worlds.new('overcast battlefield')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (.27, .34, .43, 1)
world.node_tree.nodes['Background'].inputs[1].default_value = .65
sc.world = world
for name, energy, color, rot in [('warm key', 2.4, (1, .83, .64), (32, -25, -35)),
                                  ('sky fill', 1.5, (.6, .75, 1), (50, 20, 140))]:
    ld = bpy.data.lights.new(name, 'SUN')
    ld.energy, ld.color, ld.angle = energy, color, R(12)
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.rotation_euler = tuple(R(a) for a in rot)

cam = bpy.data.objects.new('story_camera', bpy.data.cameras.new('story_camera'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.sensor_fit = 'VERTICAL'
cam.data.clip_end = 300
cam.data.lens = 38

def shot(frame, tankpos, heropos, camera, target, lens):
    tank.location = tankpos
    hero.location = heropos
    cam.location = camera
    cam.rotation_euler = (Vector(target)-cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = lens
    for ob in (tank, hero, cam):
        ob.keyframe_insert('location', frame=frame)
        ob.keyframe_insert('rotation_euler', frame=frame)
    cam.data.keyframe_insert('lens', frame=frame)

shot(0, (0, 10, .02), (-3.8, 9.6, .02), (-16, -9, 8), (-1.4, 9.7, 2), 29)
shot(90, (0, 10, .15), (0, 9.85, .65), (-9, -3, 7.8), (0, 9.9, 3), 33)
shot(180, (0, -3, .15), (0, -3.15, .15), (-14, -19, 7), (0, -4, 2.5), 32)
shot(270, (0, -9, .02), (0, -9.15, .15), (27, 24, 16), (0, -20, 4), 26)
sc.frame_start, sc.frame_end = 0, 359

# A single staged explosion keyframe establishes the ending composition.
# Dynamics and destruction continuity remain for the approved animation pass.
rng = random.Random(71)
fire = material('orange fire', (.8, .12, .008), 0, .9)
bs = fire.node_tree.nodes['Principled BSDF']
bs.inputs['Emission Color'].default_value = (1, .16, .005, 1)
bs.inputs['Emission Strength'].default_value = 2.4
smoke = material('hot dark smoke', (.085, .07, .055), 0, 1)
for m, hot in ((fire, True), (smoke, False)):
    nt = m.node_tree
    nt.nodes.clear()
    output = nt.nodes.new('ShaderNodeOutputMaterial')
    volume = nt.nodes.new('ShaderNodeVolumePrincipled')
    volume.inputs['Color'].default_value = (.16, .12, .08, 1)
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 4.5
    noise.inputs['Detail'].default_value = 4
    density = nt.nodes.new('ShaderNodeMath')
    density.operation = 'MULTIPLY'
    density.inputs[1].default_value = 3 if hot else 5
    nt.links.new(noise.outputs['Fac'], density.inputs[0])
    nt.links.new(density.outputs[0], volume.inputs['Density'])
    if hot:
        temperature = nt.nodes.new('ShaderNodeMapRange')
        temperature.inputs['To Min'].default_value = 850
        temperature.inputs['To Max'].default_value = 2100
        nt.links.new(noise.outputs['Fac'], temperature.inputs['Value'])
        nt.links.new(temperature.outputs['Result'], volume.inputs['Temperature'])
        volume.inputs['Blackbody Intensity'].default_value = 1.7
        volume.inputs['Temperature Attribute'].default_value = ''
        volume.inputs['Emission Color'].default_value = (1, .19, .008, 1)
        volume.inputs['Emission Strength'].default_value = 3
    nt.links.new(volume.outputs['Volume'], output.inputs['Volume'])
blast_objects = []
for i in range(22):
    is_smoke = i > 10
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1)
    ob = bpy.context.object
    ob.name = 'blast smoke' if is_smoke else 'blast fire'
    ob.location = (rng.uniform(-3.7, 3.7), -34+rng.uniform(-2, 2), rng.uniform(6, 12) if is_smoke else rng.uniform(1, 5.5))
    ob.scale = (rng.uniform(1, 2.3), rng.uniform(1, 2.3), rng.uniform(1.5, 3))
    for v in ob.data.vertices: v.co *= rng.uniform(.87, 1.13)
    ob.data.materials.append(smoke if is_smoke else fire)
    for p in ob.data.polygons: p.use_smooth = True
    blast_objects.append(ob)
for ob in blast_objects:
    for f, hidden in ((0, True), (299, True), (300, False)):
        ob.hide_render = hidden
        ob.keyframe_insert('hide_render', frame=f)
for ob in ancient_objs:
    for f, hidden in ((0, False), (299, False), (300, True)):
        ob.hide_render = hidden
        ob.keyframe_insert('hide_render', frame=f)
for i in range(26):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=rng.uniform(.15, .55))
    ob = bpy.context.object
    ob.name = 'flying basalt rubble'
    ob.location = (rng.uniform(-7, 7), -34+rng.uniform(-5, 5), rng.uniform(.7, 12))
    ob.scale = (1, .65, 1.7)
    ob.rotation_euler = tuple(rng.uniform(0, 6) for _ in range(3))
    ob.data.materials.append(steel)
    for f, hidden in ((0, True), (299, True), (300, False)):
        ob.hide_render = hidden
        ob.keyframe_insert('hide_render', frame=f)
shot(330, (0, -9, .02), (0, -9.15, .15), (27, 24, 16), (0, -20, 4), 26)

# Inspect source scale/bones and candidate shot projections before approval.
report = {'stage': 'storyboard only; boarding and explosion not yet animated',
          'hand': hand.name, 'grip': list(grip),
          'hero_meshes': [o.name for o in objs if o.type == 'MESH'],
          'ancient_actions': [a.name for a in ancient_actions]}
(OUT/'build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
sc.frame_set(0)
for frame in (0, 90, 180, 270, 330):
    sc.frame_set(frame)
    tank.location.z = -.06
    tank.keyframe_insert('location', frame=frame)
sc.frame_set(0)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'storyboard.blend'))
for frame in (0, 90, 180, 270, 330):
    sc.frame_set(frame)
    sc.render.filepath = str(OUT/f'probe_{frame:03d}.png')
    bpy.ops.render.render(write_still=True)
