"""Lighting, assets, FX and secondary motion pass over packed v13.

Run with Blender --background --python this_file -- --source scene.blend
--out output_directory [--probes | --render]. Hero performances are preserved;
zombie limb settling and helicopter motion are re-authored in the output scene.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector, Matrix, Quaternion, Euler
from mathutils.bvhtree import BVHTree


def terrain():
    vertices, faces = [], []
    root = bpy.data.objects['Actual Dota map / expanded Radiant mid']
    for o in root.children_recursive:
        if o.type != 'MESH' or not any(m and m.get('vmat') and m['vmat'].get('ShaderName') == 'multiblend.vfx' for m in o.data.materials):
            continue
        start = len(vertices)
        vertices.extend(o.matrix_world @ v.co for v in o.data.vertices)
        faces.extend([start + i for i in p.vertices] for p in o.data.polygons)
    return BVHTree.FromPolygons(vertices, faces)


def ground_height(bvh, p):
    hit = bvh.ray_cast(Vector((p.x, p.y, 40)), Vector((0, 0, -1)), 80)[0]
    return hit.z if hit is not None else 0


def settle_feet(scene, ground):
    def position(rig, bone):
        return (rig.matrix_world @ rig.pose.bones[bone].matrix).translation.copy()

    def aim(rig, bone, child, target):
        p = position(rig, bone)
        old = position(rig, child) - p
        new = target - p
        if old.length < 1e-5 or new.length < 1e-5:
            return
        q = old.rotation_difference(new)
        m = rig.matrix_world @ rig.pose.bones[bone].matrix
        rig.pose.bones[bone].matrix = rig.matrix_world.inverted() @ Matrix.Translation(p) @ q.to_matrix().to_4x4() @ Matrix.Translation(-p) @ m
        bpy.context.view_layer.update()

    # Original solver only lifted feet that were underground; it never let
    # already raised legs settle. Re-author their contact and preserve torsos.
    for i, hit in enumerate([73, 104, 269, 272, 270, 275, 273], 1):
        root = bpy.data.objects.get(f'Zombie {i:02d}')
        if root is None:
            continue
        rig = next(o for o in root.children_recursive if o.type == 'ARMATURE')
        start, end = hit + 8, hit + 32
        names = [f'{part}_{side}' for side in 'LR' for part in ['thigh', 'knee', 'ankle', 'bicep', 'elbow', 'wrist']]
        cache = {}
        for f in range(start, end + 1):
            scene.frame_set(f)
            cache[f] = {name: rig.pose.bones[name].matrix_basis.copy() for name in names}
        action = rig.animation_data.action
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        if any(f'pose.bones["{name}"]' in curve.data_path for name in names):
                            for j in range(len(curve.keyframe_points) - 1, -1, -1):
                                if curve.keyframe_points[j].co.x >= start:
                                    curve.keyframe_points.remove(curve.keyframe_points[j])
        final = None
        for f in range(start, end + 1):
            scene.frame_set(f)
            for name in names:
                rig.pose.bones[name].matrix_basis = cache[f][name]
            bpy.context.view_layer.update()
            u = (f - start) / (end - start); u = u*u*(3-2*u)
            for side, parts in [(side, parts) for side in 'LR' for parts in [('thigh', 'knee', 'ankle'), ('bicep', 'elbow', 'wrist')]]:
                upper, middle, endbone = [f'{part}_{side}' for part in parts]
                p = position(rig, upper); mid = position(rig, middle); foot = position(rig, endbone)
                target = foot.copy(); target.z = ground_height(ground, target) + (.12 if parts[0] == 'thigh' else .15)
                target = foot.lerp(target, u)
                l1, l2 = (mid-p).length, (foot-mid).length
                direction = target-p; distance = max(.01, min(direction.length, (l1+l2)*.995))
                direction.normalize()
                x = (l1*l1-l2*l2+distance*distance)/(2*distance)
                height = math.sqrt(max(0, l1*l1-x*x))
                pole = mid.copy(); pole.z = ground_height(ground, pole) + .24
                plane = pole-p; plane -= direction*plane.dot(direction)
                if plane.length < 1e-5:
                    plane = Vector((1, 0, 0))
                plane.normalize()
                aim(rig, upper, middle, p+direction*x+plane*height)
                aim(rig, middle, endbone, target)
            for name in names:
                b = rig.pose.bones[name]
                b.keyframe_insert('rotation_quaternion', frame=f)
                b.keyframe_insert('location', frame=f)
            final = {name: rig.pose.bones[name].matrix_basis.copy() for name in names}
        scene.frame_set(479)
        for name, matrix in final.items():
            b = rig.pose.bones[name]; b.matrix_basis = matrix
            b.keyframe_insert('rotation_quaternion', frame=479); b.keyframe_insert('location', frame=479)


def falling_helicopter(scene, ground, out):
    scene.frame_set(0)
    h = bpy.data.objects['HELICOPTER / falling carrier']
    rotor = bpy.data.objects['UH60 MainRotor']
    pivot = h.matrix_world.inverted() @ rotor.matrix_world.translation
    center = rotor.matrix_world.translation.copy(); scale = h.scale.copy()
    corners = [h.matrix_world.inverted() @ (o.matrix_world @ Vector(c))
               for o in h.children_recursive if o.type == 'MESH' and not o.hide_render
               for c in o.bound_box]
    h.animation_data_clear(); h.rotation_mode = 'XYZ'
    contact = None; origins = []; rows = []; impact_location = None
    for f in range(480):
        t = f / 30
        if contact is None:
            u = min(f/72, 1)
            q = Euler((.12+1.2*u, -.08-.35*u, -.55+math.tau*(.28*t+.20*t*t)), 'XYZ').to_matrix()
            target = center + Vector((7*t, 8*t, -1.2*t-3.4*t*t))
            offset = q @ Vector(tuple(pivot[j]*scale[j] for j in range(3)))
            location = target-offset
            rotated = [q @ Vector(tuple(c[j]*scale[j] for j in range(3))) for c in corners]
            clearance = min((location+c).z-ground_height(ground, location+c) for c in rotated)
            if clearance <= .05:
                location.z += .05-clearance
                contact = f
                impact_location = location.copy()
                impact_rotation = q.to_quaternion()
                impact_heading = h.rotation_euler.z
        else:
            # Let the body settle after the first rotor/gear contact instead
            # of freezing the tilted aircraft at the height of a blade tip.
            u = min(1, (f-contact)/18); ease = 1-(1-u)**2
            resting = Euler((.08, -.12, impact_heading+.35), 'XYZ').to_quaternion()
            q = impact_rotation.slerp(resting, ease).to_matrix()
            location = impact_location + Vector((.75*ease, 1.1*ease, 0))
            rotated = [q @ Vector(tuple(c[j]*scale[j] for j in range(3))) for c in corners]
            required_z = max(ground_height(ground, location+c)-c.z+.05 for c in rotated)
            location.z = required_z
            offset = q @ Vector(tuple(pivot[j]*scale[j] for j in range(3)))
        h.location = location
        h.rotation_euler = q.to_euler('XYZ', h.rotation_euler)
        key(h, f, location=h.location, rotation_euler=h.rotation_euler)
        origins.append(location+offset)
        if f <= 100:
            rows.append({'frame':f, 'center':list(location+offset), 'contact':contact})
    # Background smoke follows the actual engine until impact.
    for rotor_object in [o for o in h.children_recursive if o.type == 'EMPTY' and 'Rotor' in o.name]:
        cached = []
        for f in range(contact + 1):
            scene.frame_set(f); cached.append(rotor_object.rotation_euler.copy())
        velocity = Vector(cached[-1]) - Vector(cached[-2])
        rotor_object.animation_data_clear()
        for f, rotation in enumerate(cached):
            key(rotor_object, f, rotation_euler=rotation)
        for f in range(contact+1, 480):
            age = min(8, f-contact)
            rotation = Vector(cached[-1]) + velocity * (age-age*age/16)
            key(rotor_object, f, rotation_euler=rotation)
    for i in range(22):
        o = bpy.data.objects.get(f'Helicopter engine smoke {i}')
        if not o:
            continue
        o.animation_data_clear(); born = i*4; origin = origins[born]
        for f in range(480):
            age = max(0, (f-born)/30); radius = .10+age*.16
            key(o, f, location=origin+Vector((-.25*age, 0, .4*age)),
                scale=(radius, radius*.8, radius), hide_render=f<born or age>1.6 or born>contact)
    (out/'helicopter-motion.json').write_text(json.dumps({'contact_frame':contact, 'fps':30, 'samples':rows}, indent=2))


def key(obj, frame, **values):
    for name, value in values.items():
        setattr(obj, name, value)
        obj.keyframe_insert(name, frame=frame)


def volume_material(name):
    """Continuous density with zero density at the container boundary."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    n, link = nt.nodes.new, nt.links.new
    out = n('ShaderNodeOutputMaterial')
    vol = n('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value = (.20, .17, .13, 1)
    vol.inputs['Anisotropy'].default_value = .15
    link(vol.outputs['Volume'], out.inputs['Volume'])
    coord = n('ShaderNodeTexCoord')
    offset = n('ShaderNodeVectorMath'); offset.operation = 'SUBTRACT'
    offset.inputs[1].default_value = (.5, .5, .5)
    link(coord.outputs['Generated'], offset.inputs[0])
    length = n('ShaderNodeVectorMath'); length.operation = 'LENGTH'
    link(offset.outputs[0], length.inputs[0])
    edge = n('ShaderNodeMapRange'); edge.clamp = True
    edge.inputs['From Min'].default_value = .16
    edge.inputs['From Max'].default_value = .49
    edge.inputs['To Min'].default_value = 1
    edge.inputs['To Max'].default_value = 0
    link(length.outputs['Value'], edge.inputs[0])
    noise = n('ShaderNodeTexNoise'); noise.noise_dimensions = '4D'
    noise.inputs['Scale'].default_value = 5
    noise.inputs['Detail'].default_value = 2
    link(coord.outputs['Generated'], noise.inputs['Vector'])
    shaped = n('ShaderNodeMapRange'); shaped.clamp = True
    shaped.inputs['From Min'].default_value = .32
    shaped.inputs['From Max'].default_value = .70
    shaped.inputs['To Min'].default_value = 0
    shaped.inputs['To Max'].default_value = 5
    link(noise.outputs['Fac'], shaped.inputs[0])
    density = n('ShaderNodeMath'); density.operation = 'MULTIPLY'
    link(edge.outputs[0], density.inputs[0]); link(shaped.outputs[0], density.inputs[1])
    fade = n('ShaderNodeMath'); fade.operation = 'MULTIPLY'
    link(density.outputs[0], fade.inputs[0]); link(fade.outputs[0], vol.inputs['Density'])
    vol.inputs['Emission Color'].default_value = (1, .22, .035, 1)
    for f, amount in [(0, 0), (267, 0), (268, 1), (276, .9), (290, .55), (310, .20), (335, 0), (479, 0)]:
        key(fade.inputs[1], f, default_value=amount)
    # A grenade gives a brief hot core, then mostly earth and smoke.
    for f, energy in [(0, 0), (267, 0), (268, 7), (270, 3), (273, .4), (277, 0), (479, 0)]:
        key(vol.inputs['Emission Strength'], f, default_value=energy)
    for f, phase in [(267, 0), (335, .9)]:
        key(noise.inputs['W'], f, default_value=phase)
    return mat


def hero_source_maps(source_root, out):
    """Use Valve's original maps; preserve UVs, meshes, rigs and animation.

    Source workshop normal maps use the opposite green convention from the
    glTF maps. This was verified against the existing decoded game textures.
    """
    if source_root is None:
        return
    files = {p.name: p for p in source_root.rglob('*.tga')}
    pudge = {'pudge2_body':'__pudge_base', 'pudge2_armleft':'pudge_shoulder',
             'pudge2_apron':'pudge_back', 'pudge2_hair':'pudge_head',
             'pudge2_bracer':'pudge_arms', 'pudge2_waist':'pudge_belt'}
    report = []
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        prefix = mat.name.split('.')[0]
        original_prefix = pudge.get(prefix, prefix)
        if not (prefix.startswith('kunkka2_') or prefix in pudge):
            continue
        for node in list(mat.node_tree.nodes):
            if node.type != 'TEX_IMAGE' or not node.image:
                continue
            old = node.image
            suffix = next((kind for kind in ['color', 'normal'] if f'_{kind}_' in old.name), None)
            if suffix is None:
                continue
            path = files.get(f'{original_prefix}_{suffix}.tga')
            if path is None:
                continue
            new = bpy.data.images.load(str(path), check_existing=True)
            new.colorspace_settings.name = 'sRGB' if suffix == 'color' else 'Non-Color'
            node.image = new
            if suffix == 'normal':
                links = list(node.outputs['Color'].links)
                flip = mat.node_tree.nodes.new('ShaderNodeVectorMath')
                flip.operation = 'MULTIPLY_ADD'; flip.label = 'Source normal Y to glTF convention'
                flip.inputs[1].default_value = (1, -1, 1)
                flip.inputs[2].default_value = (0, 1, 0)
                mat.node_tree.links.new(node.outputs['Color'], flip.inputs[0])
                for link in links:
                    mat.node_tree.links.new(flip.outputs[0], link.to_socket)
            new.pack()
            report.append({'material': mat.name, 'kind': suffix, 'old_size':list(old.size),
                           'new_size':list(new.size), 'source':str(path)})
    (out/'hero-map-upgrade.json').write_text(json.dumps(report, indent=2))


def upgrade_zombies(path, out):
    if path is None:
        return
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = set(bpy.data.objects)-before
    source_rig = next(o for o in imported if o.type == 'ARMATURE')
    source_mesh = max((o for o in imported if o.type == 'MESH'), key=lambda o:len(o.data.vertices))
    local = source_rig.matrix_world.inverted() @ source_mesh.matrix_world
    roots = [o for o in before if o.type == 'EMPTY' and (o.name.startswith('Zombie ') or o.name.startswith('Reinforcement '))]
    report = []
    for root in roots:
        rig = next((o for o in root.children_recursive if o.type == 'ARMATURE'), None)
        if rig is None:
            continue
        common = set(source_rig.data.bones.keys()) & set(rig.data.bones.keys())
        error = max((source_rig.data.bones[n].head_local-rig.data.bones[n].head_local).length for n in common)
        if error > .001:
            raise ValueError(f'Incompatible zombie bind pose: {root.name}: {error}')
        old = [o for o in root.children_recursive if o.type == 'MESH' and o.data.materials and any('undying_zombie' in m.name for m in o.data.materials if m)]
        if not old:
            continue
        mesh = source_mesh.copy(); mesh.data = source_mesh.data.copy()
        bpy.context.scene.collection.objects.link(mesh)
        mesh.name = f'V14 HQ / {root.name}'
        mesh.parent = rig; mesh.matrix_parent_inverse = Matrix.Identity(4); mesh.matrix_basis = local
        for mod in mesh.modifiers:
            if mod.type == 'ARMATURE':
                mod.object = rig
        if old[0].animation_data and old[0].animation_data.action:
            mesh.animation_data_create(); mesh.animation_data.action = old[0].animation_data.action
            mesh.animation_data.action_slot = old[0].animation_data.action_slot
        # Extra cosmetic sword bones have no authored animation in the old rig.
        # Bind their vertices to the nearest existing parent in the source rig.
        for group in list(mesh.vertex_groups):
            if group.name in rig.data.bones:
                continue
            bone = source_rig.data.bones.get(group.name)
            while bone and bone.name not in rig.data.bones:
                bone = bone.parent
            if bone:
                target = mesh.vertex_groups.get(bone.name) or mesh.vertex_groups.new(name=bone.name)
                for vertex in mesh.data.vertices:
                    weight = next((g.weight for g in vertex.groups if g.group == group.index), 0)
                    if weight:
                        target.add([vertex.index], weight, 'ADD')
            mesh.vertex_groups.remove(group)
        for o in old:
            o.animation_data_clear(); o.hide_render = True; o.hide_viewport = True
        report.append({'root':root.name,'vertices':len(mesh.data.vertices),'bind_error':error})
    for o in imported:
        bpy.data.objects.remove(o, do_unlink=True)
    for image in bpy.data.images:
        if image.source == 'FILE' and not image.packed_file:
            image.pack()
    (out/'zombie-upgrade.json').write_text(json.dumps(report, indent=2))


def build(args):
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    s = bpy.context.scene
    hero_source_maps(args.hero_sources, args.out)
    upgrade_zombies(args.zombie_source, args.out)
    ground = terrain()
    settle_feet(s, ground)
    falling_helicopter(s, ground, args.out)
    # Broad frontal illumination was erasing the surface modelling.
    strengths = {'Faces': 210, 'Sky softbox': 650, 'Map moonlight': 1800,
                 'Far terrain fill': 9000, 'Distant map fill': 2200,
                 'Distant moon across full map': .38, 'Rim behind heroes': 1900,
                 'Undead rim': 2000, 'Warm ruin fire': 1100}
    for name, power in strengths.items():
        light = bpy.data.objects[name].data
        light.energy = power
    for name, size in [('Faces', 3), ('Rim behind heroes', 2.5), ('Undead rim', 3), ('Warm ruin fire', 2)]:
        bpy.data.objects[name].data.size = size
    bpy.data.objects['Warm ruin fire'].data.color = (1, .49, .20)
    bpy.data.objects['Rim behind heroes'].data.color = (.42, .65, 1)
    s.world.node_tree.nodes.get('Background').inputs['Strength'].default_value = .16
    s.view_settings.exposure = -.05

    # Raw Z reintroduced black speckles AFTER denoising. Mist was also noisy
    # inside volumes in this scene. Keep the actual lit background instead;
    # the expanded map was inspected without this destructive darkening mask.
    tree = s.compositing_node_group
    output = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT')
    glare = next(n for n in tree.nodes if n.type == 'GLARE')
    tree.links.new(glare.outputs['Image'], output.inputs['Image'])
    glare.inputs['Threshold'].default_value = 1.8
    glare.inputs['Strength'].default_value = .17

    # Rebuild faulty explosion containers/materials; preserve impact frame and location.
    for o in list(bpy.data.objects):
        if o.name.startswith('Explosion smoke lobe'):
            bpy.data.objects.remove(o, do_unlink=True)
    rng = random.Random(1401)
    center = Vector((.7, 7.3, .24))
    for i in range(8):
        angle = i * math.tau / 8
        direction = Vector((math.cos(angle), math.sin(angle), .6 + rng.random()))
        bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, location=center)
        o = bpy.context.object; o.name = f'V14 / grenade dust {i}'
        o.data.materials.append(volume_material(o.name))
        for f in range(480):
            age = max(0, (f - 268) / 30)
            expansion = 1 - math.exp(-age * 8)
            radius = .06 + .64 * expansion + .12 * age
            p = center + direction * (.65 * expansion + .10 * age)
            p.z += .45 * age
            key(o, f, location=p, scale=(radius, radius, radius * (1 + .3 * age)),
                hide_render=f < 268 or f > 335)
    light = bpy.data.objects['Blast illumination']
    light.animation_data_clear(); light.data.animation_data_clear()
    light.data.type = 'POINT'; light.data.shadow_soft_size = .7
    light.location = center + Vector((0, 0, .6)); light.data.color = (1, .48, .12)
    for f, watts in [(0, 0), (267, 0), (268, 1700), (270, 850), (274, 180), (280, 0), (479, 0)]:
        key(light.data, f, energy=watts)

    # Keep thin, irregular flashes. Remove the opaque-looking translucent surface.
    flash = bpy.data.objects['Muzzle flare core']
    mat = bpy.data.materials.new('V14 / hot gas transparent emission'); mat.use_nodes = True
    nt = mat.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    transparent = nt.nodes.new('ShaderNodeBsdfTransparent')
    emission = nt.nodes.new('ShaderNodeEmission'); emission.inputs['Color'].default_value = (1, .48, .10, 1)
    emission.inputs['Strength'].default_value = 12
    mix = nt.nodes.new('ShaderNodeMixShader'); mix.inputs[0].default_value = .22
    nt.links.new(transparent.outputs[0], mix.inputs[1]); nt.links.new(emission.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    flash.data.materials.clear(); flash.data.materials.append(mat)

    # Reduce high-frequency metal grain while retaining existing maps and wear.
    metal = bpy.data.materials.get('Parkerized steel, fine machining')
    if metal:
        for node in metal.node_tree.nodes:
            if node.type == 'BUMP':
                node.inputs['Distance'].default_value = min(node.inputs['Distance'].default_value, .0006)
                node.inputs['Strength'].default_value = min(node.inputs['Strength'].default_value, .12)
            if node.type == 'MAP_RANGE':
                node.inputs['To Min'].default_value = .24
                node.inputs['To Max'].default_value = .48
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == 'OPTIX'
    s.render.engine = 'CYCLES'; s.cycles.device = 'GPU'
    s.cycles.samples = 64; s.cycles.adaptive_threshold = .02
    # OptiX leaves visible stippling on this volume; OIDN was compared in-frame.
    s.cycles.use_denoising = True; s.cycles.denoiser = 'OPENIMAGEDENOISE'
    s.cycles.volume_bounces = 2; s.cycles.volume_step_rate = .5
    s.cycles.transparent_max_bounces = 16; s.cycles.max_bounces = 8
    s.render.use_persistent_data = True
    s.render.resolution_x = 720; s.render.resolution_y = 1280
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = 'PNG'; s.render.fps = 30
    s.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out / 'combat-v14.blend'))
    if args.probes:
        for f in [int(value) for value in args.probe_frames.split(',')]:
            s.frame_set(f); s.render.filepath = str(args.out / f'probe-{f:04d}.png')
            bpy.ops.render.render(write_still=True)
    if args.render:
        render_sequence(args)


def render_sequence(args):
    import hashlib
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render_study_frames import complete_png
    scene_path = args.out / 'combat-v14.blend'
    bpy.ops.wm.open_mainfile(filepath=str(scene_path))
    s = bpy.context.scene
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == 'OPTIX'
    s.cycles.samples = args.samples
    frames = args.out / 'frames'; frames.mkdir(exist_ok=True)
    manifest = {'scene_sha256':hashlib.sha256(scene_path.read_bytes()).hexdigest(),
                'samples':args.samples, 'size':[s.render.resolution_x,s.render.resolution_y],
                'fps':30, 'frames':480, 'status':'draft, not artistically accepted'}
    record = frames / 'source.json'
    if record.exists() and json.loads(record.read_text()) != manifest:
        raise RuntimeError('Existing frames belong to different scene/settings; use a new output directory.')
    record.write_text(json.dumps(manifest, indent=2))
    def complete(frame):
        try:
            return complete_png(frames/f'f{frame:04d}.png', manifest['size'])
        except (OSError, ValueError):
            return False
    s.frame_start = next((f for f in range(480) if not complete(f)), 480)
    s.frame_end = 479; s.frame_step = 1
    s.render.filepath = str(frames / 'f')
    if s.frame_start < 480:
        bpy.ops.render.render(animation=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--probes', action='store_true')
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--hero-sources', type=Path)
    parser.add_argument('--zombie-source', type=Path)
    parser.add_argument('--probe-frames', default='0,25,50,100,179,268,275,285,419')
    parser.add_argument('--render-only', action='store_true')
    parser.add_argument('--samples', type=int, default=64)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.out.mkdir(parents=True, exist_ok=True)
    if args.render_only:
        render_sequence(args)
    else:
        build(args)
