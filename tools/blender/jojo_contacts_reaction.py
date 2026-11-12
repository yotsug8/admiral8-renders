"""JoJo v6: solid architectural junctions, ward clearance and stronger reaction.

Run against the preserved v5 scene. Keeps the comic stair beat and audio timing.
"""
import bpy
import math
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

OUT = Path(__file__).resolve().parents[2] / 'out/dota-jojo/v6'
OUT.mkdir(parents=True, exist_ok=True)
s = bpy.context.scene
s.frame_set(1)

# Coplanar front faces of overlapping capitals/beam caused depth fighting.
# Union the solid structure before beveling; no duplicate visible surfaces.
beam = bpy.data.objects['Continuous architrave']
parts = [bpy.data.objects[n] for n in ('Column capital', 'Ceiling slab',
         'Outer pier capital', 'Outer pier capital.001',
         'Outer structural pier', 'Outer structural pier.001')]
for obj in [beam] + parts:
    obj.modifiers.clear()
bpy.context.view_layer.objects.active = beam
for obj in parts:
    mod = beam.modifiers.new('Solid junction', 'BOOLEAN')
    mod.operation = 'UNION'
    mod.solver = 'EXACT'
    mod.object = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(obj, do_unlink=True)
bevel = beam.modifiers.new('Continuous worn edges', 'BEVEL')
bevel.width = .025
bevel.segments = 3


def actor(name):
    root = bpy.data.objects[name]
    arm = max((o for o in root.children_recursive if o.type == 'ARMATURE'),
              key=lambda o: len(o.pose.bones))
    head = next(o for o in root.children_recursive if o.type == 'MESH'
                and o.data.shape_keys and 'jawOpen' in o.data.shape_keys.key_blocks)
    return arm, head


p, ph = actor('PUDGE_DOPPIO')
n, nh = actor('SNIPER_POLNAREFF')
items = [(bpy.data.objects['ITEM / observer'], 'wrist_R'),
         (bpy.data.objects['ITEM / sentry'], 'wrist_L')]
cache = {}
for f in range(1, 505):
    s.frame_set(f)
    cache[f] = ([{b.name: b.matrix_basis.copy() for b in arm.pose.bones} for arm in (p, n)],
                {k.name: k.value for k in nh.data.shape_keys.key_blocks},
                [(p.matrix_world @ p.pose.bones[bone].matrix).inverted() @ obj.matrix_world
                 for obj, bone in items])
for arm in (p, n):
    arm.animation_data_clear()
nh.data.shape_keys.animation_data_clear()
for obj, _ in items:
    obj.animation_data_clear()


def ease(x):
    x = max(0, min(1, x))
    return x*x*(3-2*x)


def pulse(f, start, peak, end):
    return ease((f-start)/(peak-start))*(1-ease((f-peak)/(end-peak)))


def pos(arm, name):
    return (arm.matrix_world @ arm.pose.bones[name].matrix).translation


def rotate(arm, name, quaternion):
    bone = arm.pose.bones[name]
    world = arm.matrix_world @ bone.matrix
    pivot = world.translation.copy()
    bone.matrix = (arm.matrix_world.inverted() @ Matrix.Translation(pivot)
                   @ quaternion.to_matrix().to_4x4() @ Matrix.Translation(-pivot) @ world)
    bpy.context.view_layer.update()


def turn(arm, name, axis, angle):
    rotate(arm, name, Quaternion(axis, angle))


def hand(side, target):
    upper, middle, end = ['bicep_'+side, 'elbow_'+side, 'wrist_'+side]
    shoulder, elbow, wrist = [pos(p, b) for b in (upper, middle, end)]
    u, v = elbow-shoulder, wrist-elbow
    forward = (target-shoulder).normalized()
    d = min((target-shoulder).length, (u.length+v.length)*.97)
    target = shoulder + forward*d
    pole = Vector((1 if side == 'L' else -1, .15, -.25))
    pole = (pole-forward*pole.dot(forward)).normalized()
    x = (u.length_squared-v.length_squared+d*d)/(2*d)
    desired = shoulder+forward*x+pole*math.sqrt(max(0, u.length_squared-x*x))
    rotate(p, upper, u.rotation_difference(desired-shoulder))
    rotate(p, middle, (pos(p, end)-pos(p, middle)).rotation_difference(target-pos(p, middle)))
    # Spread roll over forearm and wrist, keeping the native fist/shaft axis.
    socket = 'weapon_rt_1' if side == 'R' else 'weapon_lf_2'
    grip = -(p.matrix_world @ p.pose.bones[socket].matrix).to_3x3().col[1]
    grip.normalize()
    if grip.z < 0:
        grip = -grip
    axis = (pos(p, end)-pos(p, middle)).normalized()
    up = Vector((0, 0, 1))
    a = (grip-axis*grip.dot(axis)).normalized()
    b = (up-axis*up.dot(axis)).normalized()
    angle = math.atan2(axis.dot(a.cross(b)), a.dot(b))
    rotate(p, middle, Quaternion(axis, angle*.8))
    rotate(p, end, Quaternion(axis, angle*.2))


for f in range(1, 505):
    s.frame_set(f)
    poses, face, offsets = cache[f]
    for arm, pose in zip((p, n), poses):
        for bone in arm.pose.bones:
            bone.matrix_basis = pose[bone.name]
    bpy.context.view_layer.update()
    for side in 'LR':
        # Move the hand and its bundle together, never float a prop off the fist.
        old = pos(p, 'wrist_'+side)-pos(p, 'bicep_'+side)
        target = pos(p, 'bicep_'+side) + Vector((.39 if side == 'L' else -.39,
                                              -.76, old.z+.09))
        hand(side, target)
    surprise = pulse(f, 245, 258, 286)
    scrutiny = ease((f-278)/18) * (1-ease((f-309)/12))
    turn(n, 'Spine_0', (1, 0, 0), .12*surprise)
    turn(n, 'neck_1', (1, 0, 0), .10*surprise-.025*scrutiny)
    turn(n, 'head', (0, 0, 1), -.09*surprise+.065*scrutiny)
    turn(n, 'beard2_0', (1, 0, 0), .35+.20*surprise)
    turn(n, 'bicep_L', (1, 0, 0), -.17*surprise)
    turn(n, 'bicep_R', (1, 0, 0), -.10*surprise)
    face['jawOpen'] = max(face.get('jawOpen', 0), .50*surprise+.12*scrutiny)
    face['upperLidRaiser'] = max(face.get('upperLidRaiser', 0), .85*surprise)
    face['innerBrowRaiser'] = .65*surprise
    face['outerBrowRaiser'] = .55*surprise
    face['browLowerer'] = .38*scrutiny
    face['squint'] = .28*scrutiny
    for arm in (p, n):
        for bone in arm.pose.bones:
            bone.rotation_mode = 'QUATERNION'
            for prop in ('location', 'rotation_quaternion', 'scale'):
                bone.keyframe_insert(prop, frame=f)
    for key in nh.data.shape_keys.key_blocks:
        if key.name != 'Basis':
            key.value = face.get(key.name, 0)
            key.keyframe_insert('value', frame=f)
    for (obj, bone), offset in zip(items, offsets):
        obj.matrix_world = p.matrix_world @ p.pose.bones[bone].matrix @ offset
        obj.rotation_mode = 'QUATERNION'
        for prop in ('location', 'rotation_quaternion', 'scale'):
            obj.keyframe_insert(prop, frame=f)

# Give the left-side actor clearance from the column as well as his own chest.
root = bpy.data.objects['PUDGE_DOPPIO']
translations = {}
for f in range(1, 505):
    s.frame_set(f)
    translations[f] = [obj.location.copy() for obj in [root]+[x[0] for x in items]]
for f, locations in translations.items():
    for obj, location in zip([root]+[x[0] for x in items], locations):
        location.x -= .9
        obj.location = location
        obj.keyframe_insert('location', frame=f)

# Both ward bundles must remain visible after moving the arms away from the chest.
camera = bpy.data.objects['01_Shadow_identity']
camera.data.lens = 36
camera.animation_data_clear()
for f in range(1, 91):
    t = ease((f-1)/89)
    camera.location = (-4.70+.2*t, -6.5+.5*t, 2.65)
    target = Vector((-2.37, -.35, 1.9+.05*t))
    camera.rotation_euler = (target-camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.keyframe_insert('location', frame=f)
    camera.keyframe_insert('rotation_euler', frame=f)
    camera.data.dof.focus_distance = (target-camera.location).length
    camera.data.keyframe_insert('dof.focus_distance', frame=f)
# The establishing shot must still include the farther-left Observer bundle.
bpy.data.objects['02_Time_erasure'].data.lens = 27
wide = bpy.data.objects['02_Time_erasure']
locations = {}
for f in range(91, 223):
    s.frame_set(f)
    locations[f] = wide.location.copy()
for f, location in locations.items():
    location.x -= .3
    wide.location = location
    wide.keyframe_insert('location', frame=f)
s.render.filepath = str(OUT / 'frames/frame_')
s.frame_set(1)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'jojo-v6.blend'))
print('JOJO_V6_READY', flush=True)
