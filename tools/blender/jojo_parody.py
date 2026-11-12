"""Author the local Pudge/Sniper JoJo reference study; run with Blender -b -P."""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector, Quaternion, Matrix

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'out/dota-jojo'
TMP = Path('D:/Admiral8-temp/dota-jojo')
OUT.mkdir(exist_ok=True, parents=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
s = bpy.context.scene
s.render.fps = 30
s.frame_start = 1
s.frame_end = 504


def imp(path):
    before = set(bpy.data.objects)
    actions = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(path), bone_heuristic='BLENDER')
    obs = list(set(bpy.data.objects) - before)
    for o in obs[:]:
        if o.name.startswith('Icosphere') or 'hitbox' in o.name:
            obs.remove(o)
            bpy.data.objects.remove(o, do_unlink=True)
    return obs, list(set(bpy.data.actions) - actions)


def materials(obs):
    for o in obs:
        for slot in getattr(o, 'material_slots', []):
            m = slot.material
            if not m or not m.use_nodes:
                continue
            for n in m.node_tree.nodes:
                if n.type != 'BSDF_PRINCIPLED':
                    continue
                for name, val in [('Alpha', 1), ('Metallic', 0), ('Roughness', .58), ('Emission Strength', 0)]:
                    for link in list(n.inputs[name].links):
                        m.node_tree.links.remove(link)
                    n.inputs[name].default_value = val


def actor(name, file, parts, idle, height, pos):
    obs, acts = imp(file)
    body_meshes = [o for o in obs if o.type == 'MESH']
    arm = next(o for o in obs if o.type == 'ARMATURE')
    arm.animation_data_clear()
    action = next(a for a in acts if a.name == idle or a.name.startswith(idle + '.'))
    arm.animation_data_create()
    arm.animation_data.action = action
    arm.animation_data.action_slot = action.slots[0]
    s.frame_set(0)
    bpy.context.view_layer.update()
    base = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
    arm.animation_data_clear()
    for b in arm.pose.bones:
        b.matrix_basis = base[b.name]
    root = bpy.data.objects.new(name, None)
    s.collection.objects.link(root)
    arm.parent = root
    for path in parts:
        po, _ = imp(path)
        for pa in [o for o in po if o.type == 'ARMATURE']:
            pa.animation_data_clear()
            for b in pa.pose.bones:
                match = next((n for n in arm.pose.bones.keys() if n.lower() == b.name.lower()), None)
                if match:
                    c = b.constraints.new('COPY_TRANSFORMS')
                    c.target = arm
                    c.subtarget = match
            pa.parent = root
        obs.extend(po)
    for o in obs:
        if not o.parent:
            o.parent = root
        if o.type == 'MESH' and o.data.shape_keys:
            o.data.shape_keys.animation_data_clear()
            for k in o.data.shape_keys.key_blocks:
                k.value = 0
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.use_deform_preserve_volume = True
    materials(obs)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    points = [o.matrix_world @ Vector(v) for o in body_meshes
              for v in o.evaluated_get(dg).bound_box]
    bottom = min(p.z for p in points)
    size = max(p.z for p in points) - bottom
    root.scale = (height / size,) * 3
    root.location = (pos[0], pos[1], -bottom * height / size)
    bpy.context.view_layer.update()
    return dict(root=root, arm=arm, obs=obs, base=base, origin=root.location.copy())


GAME = ROOT / '_game/models/render'
p = actor('PUDGE_DOPPIO', ROOT / 'out/kunkka-last-stand/pudge-clean-idle.glb',
          [GAME / ('models_heroes_pudge_' + x + '.glb') for x in ['leftarm', 'hair', 'belt', 'bracer', 'back']],
          'pudge_idle_anim', 2.8, (-1.8, 0))
a = actor('PUDGE_DIAVOLO', OUT / 'assets/pudge_arcana_base.glb',
          [OUT / 'assets/pudge_arcana_back.glb', GAME / 'models_heroes_pudge_leftarm.glb'],
          'arc_mid_pudge_idle', 2.8, (1.6, 0))
n = actor('SNIPER_POLNAREFF', OUT / 'assets/sniper.glb',
          [OUT / ('assets/' + x + '.glb') for x in ['bracer', 'cape', 'headitem', 'shoulder', 'weapon']],
          'MGC_sniper_idle', 2.05, (1, -6.5))
n['root'].rotation_euler.z = math.pi


def aim(o, target):
    o.rotation_euler = (Vector(target) - o.location).to_track_quat('-Z', 'Y').to_euler()


def area(name, pos, target, color, power, size):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = power
    data.color = color
    data.shape = 'DISK'
    data.size = size
    o = bpy.data.objects.new(name, data)
    s.collection.objects.link(o)
    o.location = pos
    aim(o, target)
    return o


def stone(name, loc, dim):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.dimensions = dim
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = o.modifiers.new('Worn edges', 'BEVEL')
    bevel.width = .045
    bevel.segments = 3
    o.data.materials.append(rock)
    return o


rock = bpy.data.materials.new('Dark weathered masonry')
rock.use_nodes = True
nt = rock.node_tree
bs = nt.nodes.get('Principled BSDF')
bs.inputs['Roughness'].default_value = .88
noise = nt.nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 5
noise.inputs['Detail'].default_value = 4
ramp = nt.nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].color = (.012, .019, .027, 1)
ramp.color_ramp.elements[1].color = (.035, .045, .055, 1)
nt.links.new(noise.outputs['Fac'], ramp.inputs[0])
nt.links.new(ramp.outputs[0], bs.inputs['Base Color'])
bump = nt.nodes.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = .32
bump.inputs['Distance'].default_value = .075
nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
nt.links.new(bump.outputs[0], bs.inputs['Normal'])
stone('Foundation', (0, 0, -.22), (25, 28, .4))
for row in range(13):
    for col in range(12):
        stone('Rear masonry', ((col-5.5)*1.8+(row%2)*.9, 4.5, .45+row*.9), (1.77, .7, .87))
pillar_path = GAME / 'models_heroes_hoodwink_debut_models_ruins_hoodwink_debut_pillar_hoodwink_debut_pillar.glb'
obs, _ = imp(pillar_path)
for o in obs:
    o.animation_data_clear()
materials(obs)
pillar_root = bpy.data.objects.new('DOTA_RUIN_COLUMN', None)
s.collection.objects.link(pillar_root)
for o in obs:
    if not o.parent:
        o.parent = pillar_root
bpy.context.view_layer.update()
points = [o.matrix_world @ Vector(v) for o in obs if o.type == 'MESH' for v in o.bound_box]
minz, maxz = min(v.z for v in points), max(v.z for v in points)
pillar_root.scale = (.42*5.8/(maxz-minz),.42*5.8/(maxz-minz),5.8/(maxz-minz))
pillar_root.location.z = -minz*pillar_root.scale.z
pillar_root.location.x = -(min(v.x for v in points)+max(v.x for v in points))*.5*pillar_root.scale.x
pillar_root.location.y = -1.65-(min(v.y for v in points)+max(v.y for v in points))*.5*pillar_root.scale.y
for x, y in [(-6, 2), (6, 2), (-8, -4), (8, -4)]:
    for o in obs:
        if o.type != 'MESH':
            continue
        dup = o.copy()
        dup.data = o.data
        s.collection.objects.link(dup)
        dup.parent = None
        bpy.context.view_layer.update()
        dup.matrix_world = o.matrix_world.copy()
        dup.location += Vector((x, y+.8, 0))

area('Moon key', (1,-5,7), (0,0,1.6), (.42,.55,1), 700, 5)
area('Violet rim', (3,2,4.5), (1,0,1.7), (.8,.12,1), 600, 3)
area('Face fill', (-3,-4,3.2), (0,0,1.8), (.5,.6,1), 220, 4)
area('Sniper key', (2,-3.5,4), (1,-6.5,1.4), (.5,.62,1), 300, 3)
s.world = bpy.data.worlds.new('Night')
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.015,.02,.04,1)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .1


def camera(name, loc, target, lens, start, end, finish=None):
    data = bpy.data.cameras.new(name)
    o = bpy.data.objects.new(name, data)
    s.collection.objects.link(o)
    data.lens = lens
    data.clip_end = 150
    o.location = loc
    aim(o, target)
    o.keyframe_insert('location', frame=start)
    o.keyframe_insert('rotation_euler', frame=start)
    if finish:
        o.location = finish
        aim(o, target)
    o.keyframe_insert('location', frame=end)
    o.keyframe_insert('rotation_euler', frame=end)
    marker = s.timeline_markers.new(name, frame=start)
    marker.camera = o
    return o


camera('01_Shadow_identity', (-3,-6,2.6), (-1.65,-.4,2.25), 62, 1, 90, (-2.7,-5.6,2.6))
camera('02_Time_erasure', (0,-11.6,3.7), (0,0,2.15), 32, 91, 222, (0,-11.2,3.5))
camera('03_Diavolo_glimpse', (2,-3.3,2.45), (1.85,-.45,2.2), 95, 223, 244)
camera('04_Polnareff_reaction', (.3,-3.7,1.95), (1,-6.7,1.73), 72, 245, 315, (.4,-4.0,1.94))
camera('05_Column_reveal', (-1.3,-7.8,2.4), (1.35,0,1.9), 55, 316, 407, (2,-7.5,2.4))
camera('06_Diavolo_eye', (1.95,-2.8,2.45), (1.85,-.5,2.37), 100, 408, 452)
camera('07_Diavolo_portrait', (2.3,-4.3,2.6), (1.85,-.4,2.15), 65, 453, 504, (2.1,-3.9,2.5))


def ease(t):
    t = max(0, min(1, t))
    return t*t*(3-2*t)


def turn(act, bone, axis, angle):
    b = act['arm'].pose.bones.get(bone)
    if b:
        b.rotation_mode = 'QUATERNION'
        b.rotation_quaternion = b.rotation_quaternion @ Quaternion(axis, angle)


def position(act, name):
    return (act['arm'].matrix_world @ act['arm'].pose.bones[name].matrix).translation.copy()


def world_turn(act, name, q):
    arm = act['arm']
    b = arm.pose.bones[name]
    m = arm.matrix_world @ b.matrix
    p = m.translation
    b.matrix = arm.matrix_world.inverted() @ Matrix.Translation(p) @ q.to_matrix().to_4x4() @ Matrix.Translation(-p) @ m
    bpy.context.view_layer.update()


def leg(act, side, target):
    shoulder, elbow, wrist = ['thigh_'+side, 'knee_'+side, 'ankle_'+side]
    p0, e, w = [position(act, name) for name in (shoulder, elbow, wrist)]
    u, v = e-p0, w-e
    ray = target-p0
    d = min(ray.length, (u.length+v.length)*.985)
    forward = ray.normalized()
    sidevec = Vector((0,-1,0))
    sidevec = (sidevec-forward*sidevec.dot(forward)).normalized()
    x = (u.length_squared-v.length_squared+d*d)/(2*d)
    new_e = p0+forward*x+sidevec*math.sqrt(max(0,u.length_squared-x*x))
    world_turn(act, shoulder, u.rotation_difference(new_e-p0))
    world_turn(act, elbow, (position(act,wrist)-position(act,elbow)).rotation_difference(target-position(act,elbow)))


bpy.context.view_layer.update()
feet = {side:(a['arm'].matrix_world @ a['arm'].pose.bones['ankle_'+side].matrix).copy() for side in 'LR'}


for f in range(1, 505):
    s.frame_set(f)
    for act in [p, a, n]:
        for b in act['arm'].pose.bones:
            b.matrix_basis = act['base'][b.name]
        act['root'].location = act['origin']
    # Foot-planted expressive changes, no arbitrary translation or recycled walk.
    breathe = math.sin(f/23)*.008
    turn(p, 'spine2', (1,0,0), -.11+breathe)
    turn(p, 'head', (0,1,0), -.18+.12*ease((f-30)/45))
    bpy.context.view_layer.update()
    world_turn(p, 'head', Quaternion((1,0,0), .22*(1-ease((f-28)/55))))
    turn(a, 'spine2', (1,0,0), .05+breathe)
    turn(a, 'head', (0,1,0), -.1+.19*ease((f-340)/80))
    turn(a, 'clavicle_R', (0,0,1), .05*ease((f-340)/70))
    reaction = ease((f-246)/12)-.45*ease((f-274)/37)
    turn(n, 'Spine_1', (1,0,0), -.12*reaction)
    turn(n, 'head', (1,0,0), -.13*reaction)
    turn(n, 'head', (0,1,0), -.07+.08*ease((f-260)/30))
    if f >= 316:
        advance = ease((f-326)/58)
        a['root'].location.x -= 1.15*(1-advance)
        bpy.context.view_layer.update()
        for side, begin, end in [('R',322,353),('L',350,386)]:
            t = ease((f-begin)/(end-begin))
            target = feet[side].translation + Vector((-1.15*(1-t),0,.15*math.sin(math.pi*t)))
            leg(a,side,target)
            m = feet[side].copy()
            m.translation = position(a,'ankle_'+side)
            a['arm'].pose.bones['ankle_'+side].matrix = a['arm'].matrix_world.inverted() @ m
    for act in [p, a, n]:
        act['root'].keyframe_insert('location',frame=f)
        for b in act['arm'].pose.bones:
            for attr in ['location', 'rotation_quaternion', 'scale']:
                b.keyframe_insert(attr, frame=f)
        visible = (f < 155 if act is p else f >= 155 if act is a else f < 316)
        for o in act['obs']:
            o.hide_render = not visible
            o.keyframe_insert('hide_render', frame=f)
            if o.type == 'MESH' and o.data.shape_keys:
                keys = o.data.shape_keys.key_blocks
                expressions = {'jawOpen': .15*reaction if act is n else .08,
                               'upperLidRaiser': .65*reaction if act is n else .18,
                               'browLowerer': .12 if act is n else .5}
                for name, value in expressions.items():
                    if name in keys:
                        keys[name].value = value
                        keys[name].keyframe_insert('value', frame=f)

s.render.engine = 'CYCLES'
s.cycles.samples = 24
s.cycles.use_denoising = True
s.cycles.max_bounces = 5
s.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'
prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
s.render.resolution_x = 360
s.render.resolution_y = 640
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'PNG'
s.render.film_transparent = False
s.render.use_persistent_data = True
s.view_settings.view_transform = 'AgX'
s.view_settings.look = 'AgX - Medium High Contrast'
s.render.filepath = str(OUT/'frames/frame_')
# Resolve relocated original Pudge textures before packing the scene.
for img in bpy.data.images:
    if img.source == 'FILE' and not Path(bpy.path.abspath(img.filepath)).is_file():
        candidate = GAME / Path(bpy.path.abspath(img.filepath)).name
        if candidate.is_file():
            img.filepath = str(candidate)
            img.reload()
s.frame_set(1)
s.camera = s.timeline_markers[0].camera
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'jojo-draft.blend'))
report = {}
for act in [p,a,n]:
    report[act['root'].name] = {'location':list(act['root'].location),'scale':list(act['root'].scale),
        'head':list((act['arm'].matrix_world@act['arm'].pose.bones['head'].matrix).translation)}
(TMP/'staging.json').write_text(json.dumps(report,indent=2))
print('JOJO_SCENE_READY', flush=True)
