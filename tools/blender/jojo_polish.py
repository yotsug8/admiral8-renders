"""Fourth JoJo draft: deliberate acting, framing, skin continuity and lighting.

Run against the preserved v3 scene. This pass never overwrites that source.
"""
import bpy
import json
import math
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'out/dota-jojo/v4'
OUT.mkdir(parents=True, exist_ok=True)
s = bpy.context.scene
s.frame_set(1)


def actor(name):
    root = bpy.data.objects[name]
    obs = list(root.children_recursive)
    arm = max((o for o in obs if o.type == 'ARMATURE'), key=lambda o: len(o.pose.bones))
    head = next(o for o in obs if o.type == 'MESH' and o.data.shape_keys
                and 'jawOpen' in o.data.shape_keys.key_blocks)
    return dict(root=root, arm=arm, head=head, obs=obs)


p, a, n = [actor(name) for name in ('PUDGE_DOPPIO', 'PUDGE_MUSCULAR', 'SNIPER_POLNAREFF')]


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def light(name, location, target, color, energy, size):
    obj = bpy.data.objects.get(name)
    if obj is None:
        data = bpy.data.lights.new(name, 'AREA')
        obj = bpy.data.objects.new(name, data)
        s.collection.objects.link(obj)
    obj.location = location
    obj.data.color = color
    obj.data.energy = energy
    obj.data.size = size
    aim(obj, target)
    return obj


# A clear side key, gentle fill and separate rim preserve readable shadows.
light('Moon key', (-3.7, -4.0, 6.0), (.3, -.8, 2.0), (1.0, .79, .59), 660, 3.0)
light('Face fill', (4, -5.5, 3.8), (1, -.5, 2.0), (.55, .68, 1), 115, 4.0)
light('Violet rim', (3.5, 2, 5.2), (1, -.4, 2), (.43, .63, 1), 800, 2.8)
light('Sniper key', (-1.0, -4, 5.5), (1, -6.5, 2.9), (1, .8, .58), 190, 2.3)
light('Landing rim', (4, -9, 4.4), (1, -6.5, 3), (.43, .62, 1), 210, 2.0)
light('Rear wall wash', (-4, 1.8, 4.8), (0, 4.4, 2.8), (.42, .55, .8), 75, 4)
light('Landing wall wash', (-3, -8, 4.5), (0, -10.7, 3), (.5, .62, .9), 40, 4)
for obj in s.objects:
    if obj.type == 'LIGHT' and obj.name.startswith('Neck soft fill'):
        obj.data.energy = 12

s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.028, .039, .065, 1)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .18
s.view_settings.exposure = -.15

# Continue the existing masonry behind the reverse shot instead of black void.
rear = [o for o in s.objects if o.type == 'MESH' and o.name.startswith('Rear masonry')]
for src in rear:
    if abs(src.location.x) > 7 or src.location.z > 7:
        continue
    obj = src.copy()
    obj.data = src.data
    s.collection.objects.link(obj)
    obj.name = 'Landing masonry'
    obj.location.y = -10.7
    obj.location.z += 1.2
    # The establishing camera is outside this fourth wall. Open the set for
    # that shot only; retain the wall and identical lighting in reverse shots.
    for frame, hidden in ((1,False),(90,False),(91,True),(222,True),(223,False),(504,False)):
        obj.hide_render = hidden
        obj.keyframe_insert('hide_render', frame=frame)

wall_material = bpy.data.materials['Dark weathered masonry'].copy()
wall_material.name = 'Weathered background masonry'
nodes, links = wall_material.node_tree.nodes, wall_material.node_tree.links
geometry = nodes.new('ShaderNodeNewGeometry')
for node in nodes:
    if node.type == 'TEX_NOISE':
        links.new(geometry.outputs['Position'], node.inputs['Vector'])
    if node.type == 'VALTORGB':
        for stop in node.color_ramp.elements:
            stop.color = tuple(c*.6 for c in stop.color[:3]) + (1,)
bs = next(node for node in nodes if node.type == 'BSDF_PRINCIPLED')
fine = nodes.new('ShaderNodeTexNoise')
fine.inputs['Scale'].default_value = 35
fine.inputs['Detail'].default_value = 3
links.new(geometry.outputs['Position'], fine.inputs['Vector'])
fine_bump = nodes.new('ShaderNodeBump')
fine_bump.inputs['Strength'].default_value = .2
fine_bump.inputs['Distance'].default_value = .018
if bs.inputs['Normal'].links:
    links.new(bs.inputs['Normal'].links[0].from_socket, fine_bump.inputs['Normal'])
links.new(fine.outputs['Fac'], fine_bump.inputs['Height'])
links.new(fine_bump.outputs['Normal'], bs.inputs['Normal'])
for obj in list(s.objects):
    if obj.type == 'MESH' and obj.name.startswith(('Rear masonry', 'Landing masonry')):
        # Copies need their own slot assignment, while preserving the source mesh.
        obj.data = obj.data.copy()
        obj.data.materials.clear()
        obj.data.materials.append(wall_material)

# Match the throat to a clean skin area of the same original atlas, rather
# than stretching the chest wound and apron colours under the chin.
for act in (p, a):
    head = act['head']
    uv = head.data.uv_layers.get('neck_skin_uv')
    xs = [v.co.x for v in head.data.vertices]
    zs = [v.co.z for v in head.data.vertices]
    lo_x, hi_x, lo_z, hi_z = min(xs), max(xs), min(zs), max(zs)
    for loop in head.data.loops:
        co = head.data.vertices[loop.vertex_index].co
        u = max(0, min(1, (co.x - lo_x) / (hi_x - lo_x)))
        v = max(0, min(1, (co.z - lo_z) / ((hi_z - lo_z) * .4)))
        uv.data[loop.index].uv = (.09 + .11*u, .77 + .13*v)
    body = next(o for o in act['obs'] if o.type == 'MESH' and 'upper_body' in o.name)
    source = next(node.image for node in body.data.materials[0].node_tree.nodes
                  if node.type == 'TEX_IMAGE' and node.image and 'color' in node.image.name.lower())
    bridge = bpy.data.objects['ANATOMY / fitted neck / ' + act['root'].name]
    material = bridge.data.materials[0].copy()
    bridge.data.materials[0] = material
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bs = next(node for node in nodes if node.type == 'BSDF_PRINCIPLED')
    image = nodes.new('ShaderNodeTexImage')
    image.image = source
    links.new(image.outputs['Color'], bs.inputs['Base Color'])
    for loop in bridge.data.loops:
        co = bridge.data.vertices[loop.vertex_index].co
        bridge.data.uv_layers.active.data[loop.index].uv = (.14 + .04*math.sin(co.x*2), .83)

# Snapshot the existing animation before adding small motivated gestures.
items = [(bpy.data.objects['ITEM / observer'], p, 'wrist_R'),
         (bpy.data.objects['ITEM / sentry'], p, 'wrist_L'),
         (bpy.data.objects['ITEM / dagon'], a, 'wrist_L'),
         (bpy.data.objects['ITEM / madness'], a, 'head')]
cache = {}
for f in range(1, 505):
    s.frame_set(f)
    poses = {}
    for act in (p, a, n):
        poses[act['root'].name] = {
            'bones': {b.name: b.matrix_basis.copy() for b in act['arm'].pose.bones},
            'face': {k.name: k.value for k in act['head'].data.shape_keys.key_blocks}}
    offsets = []
    for obj, act, bone in items:
        world = act['arm'].matrix_world @ act['arm'].pose.bones[bone].matrix
        offsets.append(world.inverted() @ obj.matrix_world)
    cache[f] = poses, offsets
for act in (p, a, n):
    act['arm'].animation_data_clear()
    act['head'].data.shape_keys.animation_data_clear()
for obj, _, _ in items:
    obj.animation_data_clear()


def ease(x):
    x = max(0, min(1, x))
    return x*x*(3-2*x)


def beat(f, start, peak, end):
    return ease((f-start)/(peak-start)) * (1-ease((f-peak)/(end-peak)))


def turn(act, name, axis, angle):
    arm = act['arm']
    bone = arm.pose.bones[name]
    matrix = arm.matrix_world @ bone.matrix
    pivot = matrix.translation.copy()
    bone.matrix = (arm.matrix_world.inverted() @ Matrix.Translation(pivot)
                   @ Quaternion(axis, angle).to_matrix().to_4x4()
                   @ Matrix.Translation(-pivot) @ matrix)
    bpy.context.view_layer.update()


for f in range(1, 505):
    s.frame_set(f)
    poses, offsets = cache[f]
    for act in (p, a, n):
        for b in act['arm'].pose.bones:
            b.matrix_basis = poses[act['root'].name]['bones'][b.name]
    bpy.context.view_layer.update()
    # Normal Pudge considers the ward on the first phrase, then settles.
    emphasis = beat(f, 4, 29, 75)
    turn(p, 'bicep_R', (1, 0, 0), -.14*emphasis)
    turn(p, 'bicep_L', (1, 0, 0), .045*emphasis)
    turn(p, 'head', (0, 0, 1), -.025*emphasis)
    # The larger Pudge finishes the climb, then makes one restrained gesture.
    emphasis = beat(f, 409, 454, 495)
    turn(a, 'bicep_L', (1, 0, 0), -.075*emphasis)
    turn(a, 'bicep_R', (1, 0, 0), .045*emphasis)
    turn(a, 'head', (1, 0, 0), -.012*beat(f, 427, 457, 488))
    # A reaction settles into focus rather than holding a gaping mouth.
    turn(n, 'head', (0, 0, 1), .035*beat(f, 250, 272, 315))
    for act in (p, a, n):
        for b in act['arm'].pose.bones:
            b.rotation_mode = 'QUATERNION'
            for prop in ('location', 'rotation_quaternion', 'scale'):
                b.keyframe_insert(prop, frame=f)
        values = poses[act['root'].name]['face'].copy()
        if act is n:
            values['jawOpen'] *= .48
            values['upperLidRaiser'] *= .65
            values['eyeDown'] = .12
            values['browLowerer'] = .12*ease((f-275)/20)
        else:
            values['jawOpen'] *= .68
            values['lowerLipDepressor'] = values.get('lowerLipDepressor', 0)*.72
            values['upperLipRaiser'] = values.get('upperLipRaiser', 0)*.8
            values['eyeDown'] = 0
            values['eyeUp'] = .12 if act is a else .08
            values['squint'] = .23 if act is a else .1
        for key in act['head'].data.shape_keys.key_blocks:
            if key.name != 'Basis':
                key.value = values.get(key.name, 0)
                key.keyframe_insert('value', frame=f)
    for (obj, act, bone), offset in zip(items, offsets):
        obj.matrix_world = act['arm'].matrix_world @ act['arm'].pose.bones[bone].matrix @ offset
        obj.rotation_mode = 'QUATERNION'
        for prop in ('location', 'rotation_quaternion', 'scale'):
            obj.keyframe_insert(prop, frame=f)


def camera(name, first, last, target0, target1, lens, start, end, aperture=6.3):
    obj = bpy.data.objects[name]
    obj.animation_data_clear()
    obj.data.animation_data_clear()
    obj.data.lens = lens
    obj.data.dof.use_dof = True
    obj.data.dof.aperture_fstop = aperture
    for f, loc, target in ((start, first, target0), (end, last, target1)):
        obj.location = loc
        aim(obj, target)
        obj.data.dof.focus_distance = (Vector(target)-obj.location).length
        obj.keyframe_insert('location', frame=f)
        obj.keyframe_insert('rotation_euler', frame=f)
        obj.data.keyframe_insert('dof.focus_distance', frame=f)


camera('01_Shadow_identity', (-2.5,-6.5,2.65), (-2.2,-6.0,2.65),
       (-1.8,-.35,1.9), (-1.8,-.35,1.95), 49, 1,90)
camera('02_Time_erasure', (-.7,-11.5,4.7),(-.5,-11.2,4.65),
       (.15,-.5,2.5),(.3,-.5,2.5), 33,91,222,8)
camera('03_Diavolo_glimpse', (2.85,-4.9,2.9),(2.85,-4.9,2.9),
       (2.65,-.4,2.3),(2.65,-.4,2.3), 36,223,244)
camera('04_Polnareff_reaction', (-.1,-2.6,3.5),(.0,-2.8,3.5),
       (1,-6.7,2.55),(1,-6.7,2.6), 80,245,315,3.5)
camera('05_Column_reveal', (-1.2,-8.8,3.7),(3,-10,3.8),
       (2.45,-.4,1.8),(2.75,-3.1,2.15), 36,316,407,8)
camera('06_Diavolo_eye', (2.6,-7.8,3.4),(2.5,-7.65,3.4),
       (2.25,-3.8,2.9),(2.25,-3.8,2.9), 53,408,452,6.3)
camera('07_Diavolo_portrait', (2.85,-8.8,3.4),(2.7,-8.55,3.35),
       (2.75,-3.7,2.65),(2.75,-3.7,2.65), 41,453,504,6.3)

s.render.engine = 'BLENDER_EEVEE'
s.eevee.taa_render_samples = 96
s.render.resolution_x = 720
s.render.resolution_y = 1280
s.render.resolution_percentage = 100
s.render.filepath = str(OUT / 'frames/frame_')
s.frame_start, s.frame_end = 1, 504
s.frame_set(1)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'jojo-v4.blend'))
print('JOJO_POLISH_READY', flush=True)
