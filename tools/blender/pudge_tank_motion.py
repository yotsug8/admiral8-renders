"""Stage a short tank skit from the audited two-hand pose; render shot probes."""
import ast
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/skits/pudge_tank/motion'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'tools/blender'))
from contact_reaction import _rig, _solve_leg, _basis
from pudge_tank_color import apply_color

scene = bpy.context.scene
obstruction = bpy.data.objects.get('radiant_tower002.radiant_tower002_model.004')
if obstruction:
    bpy.data.objects.remove(obstruction, do_unlink=True)
scene.frame_set(0)
bpy.context.preferences.filepaths.save_version = 0
hero = bpy.data.objects['pudge_root']
tank = bpy.data.objects['detailed_tank']
apply_color(tank)
weapon = bpy.data.objects['heavy_launcher']
arm = max((o for o in hero.children_recursive if o.type == 'ARMATURE'), key=lambda o: len(o.pose.bones))
arm.animation_data_clear()
scene.render.fps = 30
scene.frame_start, scene.frame_end = 0, 299
scene.render.resolution_x, scene.render.resolution_y = 540, 960
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 48
scene.render.use_sequencer = False
GROUND = tank.location.z
TANK_START = tank.location.copy()
START = Vector((-78.8, 87.0, GROUND))
SEAT = Vector((-83.5, 88.4, 5.8))
RIM_Z, RIM_RADIUS = 6.8, 1.5
hero.scale = (.6,) * 3
hero.location = START
bpy.context.view_layer.update()
pelvis, legs, corrected, _ = _rig(arm)
rest_basis = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
world = arm.matrix_world.copy()
base = {b.name: world @ b.matrix for b in arm.pose.bones}
shifted = {b.name for b in arm.pose.bones if b.name == pelvis or pelvis in {p.name for p in b.parent_recursive}}

def smooth(t):
    t = max(0., min(1., t))
    return t * t * (3 - 2 * t)

def empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    scene.collection.objects.link(obj)
    obj.parent = parent
    return obj

def paint(name, color, metal=0., rough=.65):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    p = mat.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Metallic'].default_value = metal
    p.inputs['Roughness'].default_value = rough
    return mat

def parent_keep(obj, parent):
    bpy.context.view_layer.update()
    matrix = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = matrix
    bpy.context.view_layer.update()

def bounds(obj):
    points = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return [min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]

# Imported armor is a collection of open surfaces. A solid Boolean invents
# long cutter walls on these surfaces; clip their triangles and preserve UVs.
def split_polygon(poly, distance):
    inside, outside = [], []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        da, db = distance(a[0]), distance(b[0])
        (inside if da >= 0 else outside).append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            cut = (a[0].lerp(b[0], t), [u.lerp(v, t) for u, v in zip(a[1], b[1])])
            inside.append(cut)
            outside.append(cut)
    return inside, outside

def open_well(obj):
    old = obj.data
    inverse = obj.matrix_world.inverted()
    vertices, faces, materials, smoothing, uvs = [], [], [], [], []
    vertex_ids = {}
    planes = [lambda p: p.z - 4.7]
    for i in range(32):
        angle = i * math.tau / 32
        normal = Vector((math.cos(angle), math.sin(angle), 0))
        planes.append(lambda p, n=normal: RIM_RADIUS * math.cos(math.pi / 32) - n.dot(p - Vector((SEAT.x, SEAT.y, 0))))
    for face in old.polygons:
        poly = [(obj.matrix_world @ old.vertices[old.loops[i].vertex_index].co,
                 [layer.data[i].uv.copy() for layer in old.uv_layers]) for i in face.loop_indices]
        lo = [min(p[0][i] for p in poly) for i in range(3)]
        hi = [max(p[0][i] for p in poly) for i in range(3)]
        if (hi[2] < 4.7 or hi[0] < SEAT.x-RIM_RADIUS or lo[0] > SEAT.x+RIM_RADIUS
                or hi[1] < SEAT.y-RIM_RADIUS or lo[1] > SEAT.y+RIM_RADIUS):
            pieces = [poly]
        else:
            pieces, pending = [], poly
            for plane in planes:
                if len(pending) < 3:
                    break
                pending, outside = split_polygon(pending, plane)
                if len(outside) >= 3:
                    pieces.append(outside)
        for piece in pieces:
            indices = []
            for position, _ in piece:
                key = tuple(round(v, 6) for v in position)
                if key not in vertex_ids:
                    vertex_ids[key] = len(vertices)
                    vertices.append(inverse @ position)
                indices.append(vertex_ids[key])
            if len(set(indices)) < 3:
                continue
            faces.append(indices)
            materials.append(face.material_index)
            smoothing.append(face.use_smooth)
            uvs.append([entry[1] for entry in piece])
    mesh = bpy.data.meshes.new(obj.name + ' opened surfaces')
    mesh.from_pydata(vertices, [], faces)
    for mat in old.materials:
        mesh.materials.append(mat)
    for face, mat, smooth_face in zip(mesh.polygons, materials, smoothing):
        face.material_index, face.use_smooth = mat, smooth_face
    for layer_index, layer in enumerate(old.uv_layers):
        dst = mesh.uv_layers.new(name=layer.name)
        for face, values in zip(mesh.polygons, uvs):
            for loop, value in zip(face.loop_indices, values):
                dst.data[loop].uv = value[layer_index]
    obj.data = mesh

# Open real space through the turret and hull; the actor is never masked away.
cut_report = []
for obj in list(tank.children_recursive):
    if obj.type != 'MESH' or obj.hide_render:
        continue
    lo, hi = bounds(obj)
    if (hi[2] < 4.7 or hi[0] < SEAT.x - RIM_RADIUS or lo[0] > SEAT.x + RIM_RADIUS
            or hi[1] < SEAT.y - RIM_RADIUS or lo[1] > SEAT.y + RIM_RADIUS):
        continue
    old_count = len(obj.data.polygons)
    open_well(obj)
    cut_report.append({'mesh': obj.name, 'before': old_count, 'after': len(obj.data.polygons)})
rim_mat = paint('painted commander collar', (.045, .075, .027), .15, .75)
bpy.ops.mesh.primitive_torus_add(major_segments=64, minor_segments=12,
                               major_radius=RIM_RADIUS+.10, minor_radius=.10,
                               location=(SEAT.x, SEAT.y, RIM_Z))
rim = bpy.context.object
rim.name = 'wide commander collar'
rim.data.materials.append(rim_mat)
parent_keep(rim, tank)
liner_vertices = [(SEAT.x + RIM_RADIUS*math.cos(i*math.tau/64),
                   SEAT.y + RIM_RADIUS*math.sin(i*math.tau/64), z)
                  for z in (4.75, RIM_Z) for i in range(64)]
liner_mesh = bpy.data.meshes.new('commander well lining')
liner_mesh.from_pydata(liner_vertices, [], [(i, (i+1)%64, (i+1)%64+64, i+64) for i in range(64)])
liner = bpy.data.objects.new('commander well lining', liner_mesh)
scene.collection.objects.link(liner)
liner_mesh.materials.append(paint('dark interior armor', (.025,.03,.02), .1,.85))
parent_keep(liner, tank)
hinge = empty('commander hatch hinge')
hinge.location = (SEAT.x, SEAT.y + RIM_RADIUS+.15, RIM_Z)
parent_keep(hinge, tank)
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=RIM_RADIUS+.09, depth=.14,
                                  location=(SEAT.x, SEAT.y, RIM_Z + .08))
lid = bpy.context.object
lid.name = 'commander hatch lid'
lid.data.materials.append(rim_mat)
parent_keep(lid, hinge)
for frame, angle in ((0, 0), (20, 0), (40, -165), (299, -165)):
    hinge.rotation_euler.x = math.radians(angle)
    hinge.keyframe_insert('rotation_euler', frame=frame)
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=RIM_RADIUS-.04, depth=.12,
                                  location=(SEAT.x, SEAT.y, SEAT.z-.066))
platform=bpy.context.object
platform.name='internal crew foot platform'
platform.data.materials.append(rim_mat)
parent_keep(platform,tank)

# Native terrain shading suppresses small contact shadows. Add a restrained
# soft occlusion footprint exactly on the independently measured ground plane.
bpy.ops.mesh.primitive_plane_add(size=2,location=(-83.3,87.2,GROUND+.008))
shadow=bpy.context.object; shadow.name='tank contact shadow'
shadow['track_footprint_v2']=True
shadow.scale=(2.8,6.0,1)
parent_keep(shadow,tank)
mat=bpy.data.materials.new('tank contact shadow'); mat.use_nodes=True
nt=mat.node_tree; nt.nodes.clear()
uv=nt.nodes.new('ShaderNodeTexCoord')
center=nt.nodes.new('ShaderNodeVectorMath'); center.operation='SUBTRACT'
center.inputs[1].default_value=(.5,.5,0)
nt.links.new(uv.outputs['UV'],center.inputs[0])
absolute=nt.nodes.new('ShaderNodeVectorMath'); absolute.operation='ABSOLUTE'
nt.links.new(center.outputs[0],absolute.inputs[0])
axes=nt.nodes.new('ShaderNodeSeparateXYZ'); nt.links.new(absolute.outputs[0],axes.inputs[0])
length=nt.nodes.new('ShaderNodeMath'); length.operation='MAXIMUM'
nt.links.new(axes.outputs[0],length.inputs[0]); nt.links.new(axes.outputs[1],length.inputs[1])
ramp=nt.nodes.new('ShaderNodeMapRange'); ramp.clamp=True; ramp.interpolation_type='SMOOTHSTEP'
ramp.inputs['From Min'].default_value=.34; ramp.inputs['From Max'].default_value=.5
ramp.inputs['To Min'].default_value=.85; ramp.inputs['To Max'].default_value=0
nt.links.new(length.outputs['Value'],ramp.inputs['Value'])
clear=nt.nodes.new('ShaderNodeBsdfTransparent')
black=nt.nodes.new('ShaderNodeEmission'); black.inputs[0].default_value=(0,0,0,1)
mix=nt.nodes.new('ShaderNodeMixShader'); output=nt.nodes.new('ShaderNodeOutputMaterial')
nt.links.new(ramp.outputs[0],mix.inputs[0]); nt.links.new(clear.outputs[0],mix.inputs[1])
nt.links.new(black.outputs[0],mix.inputs[2]); nt.links.new(mix.outputs[0],output.inputs['Surface'])
mat.surface_render_method='BLENDED'; shadow.visible_shadow=False
shadow.data.materials.append(mat)

# Preserve native geometry/UVs when splitting wheels or destruction pieces.
def subset(source, faces, name, parent):
    used = sorted({v for p in faces for v in p.vertices})
    lookup = {v: i for i, v in enumerate(used)}
    center = sum((source.data.vertices[v].co for v in used), Vector()) / len(used)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([source.data.vertices[v].co - center for v in used], [],
                     [[lookup[v] for v in p.vertices] for p in faces])
    for mat in source.data.materials:
        mesh.materials.append(mat)
    for dst, src in zip(mesh.polygons, faces):
        dst.material_index, dst.use_smooth = src.material_index, src.use_smooth
    for old_uv in source.data.uv_layers:
        new_uv = mesh.uv_layers.new(name=old_uv.name)
        for dst, src in zip(mesh.polygons, faces):
            for a, b in zip(dst.loop_indices, src.loop_indices):
                new_uv.data[a].uv = old_uv.data[b].uv
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.matrix_world = source.matrix_world @ Matrix.Translation(center)
    parent_keep(obj, parent)
    return obj

wheel_roots = []
for side in (-1, 1):
    for index in range(7):
        wheel = empty(f'road wheel {side} {index}')
        wheel.location = (-83.29 + side * 2.08, 83.7 + index * 1.17, 3.89)
        parent_keep(wheel, tank)
        wheel_roots.append(wheel)
for name in ('Object_21', 'Object_25', 'Object_30'):
    source = bpy.data.objects.get(name)
    if source is None:
        continue
    groups = defaultdict(list)
    for poly in source.data.polygons:
        center = source.matrix_world @ poly.center
        nearest = min(range(len(wheel_roots)), key=lambda i: (wheel_roots[i].matrix_world.translation - center).length_squared)
        groups[nearest].append(poly)
    for index, faces in groups.items():
        subset(source, faces, f'{name} wheel {index}', wheel_roots[index])
    bpy.data.objects.remove(source, do_unlink=True)

track_mappings = []
track_mats = {slot.material for obj in tank.children_recursive if obj.type == 'MESH'
              for slot in obj.material_slots if slot.material and 'MachWheels' in slot.material.name}
for mat in track_mats:
    nt = mat.node_tree
    uv = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeVectorMath')
    mapping.operation = 'ADD'
    nt.links.new(uv.outputs['UV'], mapping.inputs[0])
    for node in [n for n in nt.nodes if n.type == 'TEX_IMAGE']:
        nt.links.new(mapping.outputs[0], node.inputs['Vector'])
    track_mappings.append(mapping)

recoil = empty('barrel recoil', tank)
for name in ('Object_13', 'Object_3'):
    obj = bpy.data.objects.get(name)
    if obj:
        parent_keep(obj, recoil)

# The measured route is level. Clear only foliage crossing the vehicle corridor.
cleared = []
protected = {hero, tank, weapon, *hero.children_recursive, *tank.children_recursive, *weapon.children_recursive}
for obj in list(scene.objects):
    if obj in protected or obj.type != 'MESH' or obj.hide_render:
        continue
    if 'tree' not in obj.name.lower() and 'roots' not in obj.name.lower():
        continue
    lo, hi = bounds(obj)
    corridor = hi[0] > -87 and lo[0] < -80 and hi[1] > 68 and lo[1] < 94
    base_clearance = hi[0] > -90 and lo[0] < -77 and hi[1] > 55 and lo[1] < 69
    if corridor or base_clearance:
        cleared.append(obj.name)
        bpy.data.objects.remove(obj, do_unlink=True)

# Use the actual Dire Ancient, including its material boundaries and textures.
before = set(scene.objects)
bpy.ops.import_scene.gltf(filepath=str(ROOT / '_game/models/render/tank_dire_ancient.glb'))
imported = set(scene.objects) - before
ancient = empty('enemy_ancient')
for obj in imported:
    if not obj.parent:
        obj.parent = ancient
bpy.context.view_layer.update()
ancient_meshes = [o for o in imported if o.type == 'MESH']
points = [o.matrix_world @ Vector(c) for o in ancient_meshes for c in o.bound_box]
low, high = min(v.z for v in points), max(v.z for v in points)
scale = 8 / (high - low)
ancient.scale = (scale,) * 3
ancient.location = (-83.5, 62, GROUND - low * scale)
bpy.context.view_layer.update()
for obj in ancient_meshes:
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                for key, value in (('Alpha', 1), ('Metallic', 0), ('Roughness', .8)):
                    for link in list(node.inputs[key].links):
                        mat.node_tree.links.remove(link)
                    node.inputs[key].default_value = value
                # Source2 specular masks are exported as emissive textures.
                node.inputs['Emission Strength'].default_value = 0

rng = random.Random(718)
fragments = []
interior = paint('broken ancient stone interior', (.055,.045,.042), 0,.95)
for source in ancient_meshes:
    groups = defaultdict(list)
    for poly in source.data.polygons:
        p = source.matrix_world @ poly.center
        groups[(math.floor((p.x + 83.5) / 1.6), math.floor((p.y - 62) / 1.6), math.floor((p.z - GROUND) / 2.2))].append(poly)
    for cell, faces in groups.items():
        piece = subset(source, faces, f'ancient fragment {len(fragments)}', ancient)
        piece.data.materials.append(interior)
        bm = bmesh.new()
        bm.from_mesh(piece.data)
        edges = [e for e in bm.edges if e.is_boundary]
        if edges:
            result = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
            for face in result.get('faces', []):
                face.material_index = len(piece.data.materials)-1
        bm.to_mesh(piece.data)
        bm.free()
        position = piece.matrix_world.translation.copy()
        outward = position - Vector((-83.5, 62, GROUND + 3.5))
        outward.z = 0
        if outward.length:
            outward.normalize()
        speed = rng.uniform(2.2, 5.2) if cell[2] > 0 else .5
        velocity = outward * speed + Vector((0, 0, rng.uniform(2, 5) if cell[2] > 0 else 0))
        spin = Vector(tuple(rng.uniform(-1.8, 1.8) for _ in range(3)))
        lo, hi = bounds(piece)
        floor = GROUND + position.z - lo[2]
        fragments.append((piece, position, velocity, spin, piece.rotation_euler.copy(), floor))
    for frame, hide in ((0, False), (206, False), (207, True), (299, True)):
        source.hide_render = hide
        source.keyframe_insert('hide_render', frame=frame)

def volume(name, smoke=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    output = nt.nodes.new('ShaderNodeOutputMaterial')
    vol = nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value = (.09, .075, .06, 1)
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 4.5
    noise.inputs['Detail'].default_value = 4
    tex = nt.nodes.new('ShaderNodeTexCoord')
    centered = nt.nodes.new('ShaderNodeVectorMath'); centered.operation='SUBTRACT'
    centered.inputs[1].default_value=(.5,.5,.5)
    nt.links.new(tex.outputs['Generated'],centered.inputs[0])
    length=nt.nodes.new('ShaderNodeVectorMath'); length.operation='LENGTH'
    nt.links.new(centered.outputs[0],length.inputs[0])
    radial=nt.nodes.new('ShaderNodeMapRange'); radial.clamp=True
    radial.inputs['From Min'].default_value=.22; radial.inputs['From Max'].default_value=.5
    radial.inputs['To Min'].default_value=1; radial.inputs['To Max'].default_value=0
    nt.links.new(length.outputs['Value'],radial.inputs['Value'])
    shaped=nt.nodes.new('ShaderNodeMapRange'); shaped.clamp=True
    shaped.inputs['From Min'].default_value=.38; shaped.inputs['From Max'].default_value=.68
    shaped.inputs['To Max'].default_value=1.5 if smoke else 2
    nt.links.new(noise.outputs['Fac'],shaped.inputs['Value'])
    density = nt.nodes.new('ShaderNodeMath'); density.operation = 'MULTIPLY'
    nt.links.new(shaped.outputs[0], density.inputs[0])
    nt.links.new(radial.outputs[0],density.inputs[1])
    nt.links.new(density.outputs[0], vol.inputs['Density'])
    if not smoke:
        color=nt.nodes.new('ShaderNodeValToRGB')
        color.color_ramp.elements[0].position=.35
        color.color_ramp.elements[0].color=(.04,.002,0,1)
        color.color_ramp.elements[1].position=.72
        color.color_ramp.elements[1].color=(1,.55,.07,1)
        nt.links.new(noise.outputs['Fac'],color.inputs[0])
        nt.links.new(color.outputs['Color'],vol.inputs['Emission Color'])
        nt.links.new(density.outputs[0],vol.inputs['Emission Strength'])
    nt.links.new(vol.outputs[0], output.inputs['Volume'])
    return mat

fire, smoke = volume('blast flame'), volume('blast smoke', True)
clouds = []
for index in range(8):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1)
    obj = bpy.context.object
    obj.name = f'blast volume {index}'
    obj.location = (-83.5 + rng.uniform(-2.2, 2.2), 62 + rng.uniform(-1.5, 1.5), GROUND + rng.uniform(2, 5))
    obj.data.materials.append(smoke if index > 4 else fire)
    clouds.append((obj, obj.location.copy(), index > 4, rng.uniform(1.4, 2.3) if index>4 else rng.uniform(.8,1.5)))
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1)
flash = bpy.context.object
flash.name = 'muzzle fire'
flash.data.materials.append(fire)
parent_keep(flash, tank)
flash.location = (0, -7.3, 2.5)

camera = scene.camera
camera.animation_data_clear()
camera.data.animation_data_clear()
camera.data.sensor_fit = 'VERTICAL'
camera.data.shift_x = camera.data.shift_y = 0
camera.data.dof.use_dof = True
shots = [
    (0, 39, (-75.4, 81.32, 5.55), (-78.8, 86.6, 4.65), 55),
    (39, 108, (-74.0, 80.0, 8.0), (-81.7, 87.8, 6.6), 26),
    (108, 180, (-85, 66, 5.3), (-83.4, 80, 6.2), 28),
    (180, 198, (-95, 74, 14), (-83.5, 62, 7), 22),
    (198, 207, (-88, 66, 5.4), (-83.5, 70.8, 6.05), 42),
    (207, 270, (-95, 74, 14), (-83.5, 62, 7), 22),
    (270, 300, (-80, 75, 8.6), (-83.5, 80.4, 7.5), 45),
]
for start, end, position, target, lens in shots:
    for frame in (start, end - 1):
        camera.location = position
        camera.rotation_euler = (Vector(target) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.lens = lens
        camera.data.dof.focus_distance = (Vector(target) - camera.location).length
        camera.data.dof.aperture_fstop = 4 if start == 39 else 2.8
        camera.keyframe_insert('location', frame=frame)
        camera.keyframe_insert('rotation_euler', frame=frame)
        camera.data.keyframe_insert('lens', frame=frame)
        camera.data.dof.keyframe_insert('focus_distance', frame=frame)
        camera.data.dof.keyframe_insert('aperture_fstop', frame=frame)
for owner in (camera, camera.data):
    for layer in owner.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = 'CONSTANT'

inverse = world.inverted()
for frame in range(300):
    t = frame / 30
    travel = 8 * smooth((t - 3.6) / 2.6)
    tank.location = TANK_START + Vector((0, -travel, 0))
    tank.keyframe_insert('location', frame=frame)
    if t < 1.8:
        hero.location = START
        crouch = .24 * smooth((t - 1.35) / .45)
        foot_lift = 0
    elif t < 2.8:
        u = t - 1.8
        hero.location = START.lerp(SEAT, smooth(u / .75))
        hero.location.z = START.z + (SEAT.z - START.z) * u + 12.5 * u * (1 - u)
        crouch = .24 + .07 * math.sin(math.pi * u)
        foot_lift = .25 * math.sin(math.pi * u)
    else:
        hero.location = SEAT + Vector((0, -travel, 0))
        crouch = .08 + .12 * math.exp(-max(0., t - 2.8) * 7) * max(0., math.sin((t - 2.8) * 13))
        foot_lift = 0
    hero.keyframe_insert('location', frame=frame)
    desired = {name: matrix.copy() for name, matrix in base.items()}
    drop = Vector((0, 0, -crouch))
    for name in shifted:
        desired[name].translation += drop
    for leg in legs:
        target=base[leg[2]].copy()
        target.translation.z+=foot_lift
        _solve_leg(base, desired, leg, drop, None, Vector((0, -1, 0)), target)
    for bone in corrected:
        parent = inverse @ desired[bone.parent.name] if bone.parent else None
        bone.matrix_basis = _basis(bone, inverse @ desired[bone.name], parent)
        bone.rotation_mode = 'QUATERNION'
        bone.keyframe_insert('location', frame=frame)
        bone.keyframe_insert('rotation_quaternion', frame=frame)
        bone.keyframe_insert('scale', frame=frame)
    for wheel in wheel_roots:
        wheel.rotation_euler.x = travel / .53
        wheel.keyframe_insert('rotation_euler', frame=frame)
    for mapping in track_mappings:
        mapping.inputs[1].default_value = (travel * .23, 0, 0)
        mapping.inputs[1].keyframe_insert('default_value', frame=frame)
    recoil.location.y = .15 * max(0., math.sin((t - 6.6) / .25 * math.pi)) if 6.6 <= t <= 6.85 else 0
    recoil.keyframe_insert('location', frame=frame)
    flash.hide_render = not 198 <= frame <= 201
    flash.keyframe_insert('hide_render', frame=frame)
    flash.scale = (.35, .75, .35)
    flash.keyframe_insert('scale', frame=frame)
    dt = max(0., t - 6.9)
    for piece, initial, velocity, spin, rotation, floor in fragments:
        position = initial + velocity * dt + Vector((0, 0, -4.905 * dt * dt))
        position.z = max(floor, position.z)
        piece.location = ancient.matrix_world.inverted() @ position
        piece.rotation_euler = tuple(rotation[i] + spin[i] * dt for i in range(3))
        piece.hide_render = frame < 207
        piece.keyframe_insert('location', frame=frame)
        piece.keyframe_insert('rotation_euler', frame=frame)
        piece.keyframe_insert('hide_render', frame=frame)
    for obj, initial, smoky, radius in clouds:
        obj.hide_render = frame < 207 or (not smoky and dt > .85)
        obj.keyframe_insert('hide_render', frame=frame)
        gain = max(.01, smooth(dt / .32)) * radius
        if not smoky:
            gain *= max(.01, 1 - max(0., dt - .4) / .5)
        obj.scale = (gain, gain, gain * (1.25 if smoky else 1))
        obj.location = initial + Vector((0, 0, dt * (1.2 if smoky else .4)))
        obj.keyframe_insert('scale', frame=frame)
        obj.keyframe_insert('location', frame=frame)

scene.frame_set(0)
bpy.context.view_layer.update()
report = {'frames': 300, 'fps': 30, 'cuts': [s[0] for s in shots] + [300],
          'hatch_radius': RIM_RADIUS, 'hatch_cuts': cut_report, 'cleared_foliage': cleared,
          'fragments': len(fragments), 'shot_probes': [20, 65, 91, 150, 190, 199, 218, 255, 285],
          'limits': ['Draft staging; full motion/body/vehicle collision audit pending.',
                     'Tracks use scrolling surface detail; links are not individually articulated.',
                     'Ancient fragments preserve exterior faces; exposed cut interiors require review.']}
(OUT / 'build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
scene.render.filepath = str(OUT / 'frames/f#####')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'scene.blend'), compress=True)
for frame in report['shot_probes']:
    scene.frame_set(frame)
    scene.render.filepath = str(OUT / f'probe_{frame:05d}.png')
    bpy.ops.render.render(write_still=True)
print('MOTION_PROBES_COMPLETE', flush=True)
