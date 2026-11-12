"""A small, intentional loss of composure on the last stair, based on v4."""
import bpy
import math
import random
import wave
from array import array
from pathlib import Path
from mathutils import Matrix, Quaternion

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'out/dota-jojo/v5'
OUT.mkdir(parents=True, exist_ok=True)
s = bpy.context.scene
root = bpy.data.objects['PUDGE_MUSCULAR']
arm = max((o for o in root.children_recursive if o.type == 'ARMATURE'), key=lambda o: len(o.pose.bones))
head = next(o for o in root.children_recursive if o.type == 'MESH' and o.data.shape_keys
            and 'jawOpen' in o.data.shape_keys.key_blocks)
items = [(bpy.data.objects['ITEM / dagon'], 'wrist_L'),
         (bpy.data.objects['ITEM / madness'], 'head')]
cache = {}
for f in range(1, 505):
    s.frame_set(f)
    cache[f] = ({b.name: b.matrix_basis.copy() for b in arm.pose.bones},
                {k.name: k.value for k in head.data.shape_keys.key_blocks},
                [(arm.matrix_world @ arm.pose.bones[bone].matrix).inverted() @ obj.matrix_world
                 for obj, bone in items])
arm.animation_data_clear()
head.data.shape_keys.animation_data_clear()
for obj, _ in items:
    obj.animation_data_clear()


def ease(x):
    x = max(0, min(1, x))
    return x*x*(3-2*x)


def pulse(f, start, peak, end):
    return ease((f-start)/(peak-start)) * (1-ease((f-peak)/(end-peak)))


def turn(name, axis, angle):
    bone = arm.pose.bones[name]
    matrix = arm.matrix_world @ bone.matrix
    point = matrix.translation.copy()
    bone.matrix = (arm.matrix_world.inverted() @ Matrix.Translation(point)
                   @ Quaternion(axis, angle).to_matrix().to_4x4()
                   @ Matrix.Translation(-point) @ matrix)
    bpy.context.view_layer.update()


for f in range(1, 505):
    s.frame_set(f)
    poses, face, offsets = cache[f]
    for bone in arm.pose.bones:
        bone.matrix_basis = poses[bone.name]
    bpy.context.view_layer.update()
    if f >= 384:
        loss = pulse(f, 392, 399, 414)
        catch = pulse(f, 402, 411, 425)
        flail = pulse(f, 394, 402, 424)
        # Legs retain the existing checked stair contacts. The comic beat is
        # a forward weight shift and an upper-body catch, not foot sliding.
        turn('spine1', (1, 0, 0), .24*loss-.055*catch)
        turn('bicep_R', (0, 1, 0), .65*flail)
        turn('bicep_R', (1, 0, 0), -.16*loss+.10*catch)
        turn('bicep_L', (1, 0, 0), -.11*loss)
        recovery = pulse(f, 418, 433, 452)
        pride = ease((f-447)/22)
        face['upperLidRaiser'] = max(face.get('upperLidRaiser', 0), .42*loss)
        face['innerBrowRaiser'] = max(face.get('innerBrowRaiser', 0), .32*loss)
        face['eyeDown'] = .38*loss
        face['eyeLeft'] = .25*recovery
        face['eyeUp'] = face.get('eyeUp', 0)*(1-loss)
        baseline = face.get('squint', 0)
        face['squint'] = baseline*(1-loss)+.1*loss+(.24-baseline)*pride
        face['lipCornerPuller'] = face.get('lipCornerPuller', 0)+.10*pride
    for bone in arm.pose.bones:
        bone.rotation_mode = 'QUATERNION'
        for prop in ('location', 'rotation_quaternion', 'scale'):
            bone.keyframe_insert(prop, frame=f)
    for key in head.data.shape_keys.key_blocks:
        if key.name != 'Basis':
            key.value = face.get(key.name, 0)
            key.keyframe_insert('value', frame=f)
    for (obj, bone), offset in zip(items, offsets):
        obj.matrix_world = arm.matrix_world @ arm.pose.bones[bone].matrix @ offset
        obj.rotation_mode = 'QUATERNION'
        for prop in ('location', 'rotation_quaternion', 'scale'):
            obj.keyframe_insert(prop, frame=f)

# Let the audience see the whole catch before cutting to the embarrassed face.
camera = bpy.data.objects['05_Column_reveal'].data
for f, lens in [(1, 36), (377, 36), (394, 29), (424, 29)]:
    camera.lens = lens
    camera.keyframe_insert('lens', frame=f)
next(m for m in s.timeline_markers if m.camera and m.camera.name == '06_Diavolo_eye').frame = 425
s.render.filepath = str(OUT / 'frames/frame_')
s.frame_set(1)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'jojo-v5.blend'))

# An original short comic spring/thud accent, rather than a new spoken line.
rate = 48000
rng = random.Random(14)
samples = array('h')
phase = 0.0
filtered_noise = 0.0
for i in range(int(.34*rate)):
    t = i/rate
    frequency = 75+190*math.exp(-t*13)
    phase += 2*math.pi*frequency/rate
    envelope = min(1, t/.004)*math.exp(-t*14)
    filtered_noise = .8*filtered_noise+.2*rng.uniform(-1, 1)
    sample = .23*envelope*(math.sin(phase)+.22*math.sin(phase*2))
    sample += .10*filtered_noise*math.exp(-t*55)
    samples.append(int(max(-1, min(1, sample))*32767))
with wave.open(str(OUT / 'comic-catch.wav'), 'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(rate)
    wav.writeframes(samples.tobytes())
print('JOJO_GAG_READY', flush=True)
