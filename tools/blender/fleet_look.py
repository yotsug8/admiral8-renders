"""Reproducible fleet look development; apply to an untouched v2 scene.

Changes are deliberately separate from the unresolved fall choreography.
The scene property prevents accidental double offsets during live iteration.
"""
import math
from collections import Counter

import bpy
from mathutils import Vector


def character_light():
    receivers = bpy.data.collections.new('Fleet character light receivers')
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj.name.startswith(('Captain', 'Giant_')):
            receivers.objects.link(obj)
    for name, position, energy, size, color in (
        ('Fleet soft character key', (-10, -8, 18), 22000, 18, (1, .92, .82)),
        ('Fleet soft character fill', (16, -6, 12), 12000, 14, (.85, .93, 1)),
    ):
        data = bpy.data.lights.new(name, 'AREA')
        data.energy, data.shape, data.size, data.color = energy, 'DISK', size, color
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = position
        obj.rotation_euler = (Vector((0, 10, 5)) - obj.location).to_track_quat('-Z', 'Y').to_euler()
        obj.light_linking.receiver_collection = receivers


def immerse_fleet(draft=1.15):
    """Move vessels and passengers together; keep shore landing positions unchanged."""
    scene = bpy.context.scene
    departures = {4:161, 5:170, 2:174, 3:181, 6:168, 7:177}
    # Read all original coordinates before inserting any keys.
    samples = []
    boats = [bpy.data.objects[f'FleetShip{i:02d}'] for i in range(7)]
    actors = [bpy.data.objects[f'Captain{i:02d}_kunkka_placement'] for i in range(14)]
    for frame in range(540):
        scene.frame_set(frame)
        samples.append(([o.location.z for o in boats], [o.location.z for o in actors]))
    for frame, (boat_z, actor_z) in enumerate(samples):
        for obj, z in zip(boats, boat_z):
            obj.location.z = z - draft
            obj.keyframe_insert('location', index=2, frame=frame)
        for i, (obj, z) in enumerate(zip(actors, actor_z)):
            departure = departures.get(i)
            weight = 1 if departure is None else 1 - max(0, min(1, (frame - departure) / 21))
            obj.location.z = z - draft * weight
            obj.keyframe_insert('location', index=2, frame=frame)


def waterline_foam():
    """Thin broken foam at actual hull/water intersection, independently of ship roll.

    Derive the shape at the mean sailing pose. The small ship roll is intentionally
    not inherited by this water surface. All positions are baked, no live handlers.
    """
    scene = bpy.context.scene
    scene.frame_set(24)
    deps = bpy.context.evaluated_depsgraph_get()
    boats = [bpy.data.objects[f'FleetShip{i:02d}'] for i in range(7)]
    shapes = []
    for i, boat in enumerate(boats):
        source = next(o for o in scene.objects if o.type == 'MESH'
                      and o.name.startswith(f'Ship{i:02d}_') and o.name.endswith('.ghostship'))
        evaluated = source.evaluated_get(deps)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        points = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        vertices, faces, feather = [], [], []
        for tri in mesh.loop_triangles:
            cut = []
            p = [points[v] for v in tri.vertices]
            for a, b in zip(p, p[1:] + p[:1]):
                if (a.z + .7) * (b.z + .7) < 0:
                    cut.append(a.lerp(b, (-.7 - a.z) / (b.z - a.z)))
            if len(cut) != 2 or (cut[1] - cut[0]).length < .015:
                continue
            direction = cut[1] - cut[0]
            side = Vector((-direction.y, direction.x, 0)).normalized() * .23
            base = len(vertices)
            for point in cut:
                for edge in (-1, 0, 1):
                    v = point + side * edge
                    vertices.append((v.x - boat.location.x, v.y - boat.location.y, -.635))
                    feather.append(.85 if edge == 0 else 0)
            faces += [(base, base+1, base+4, base+3), (base+1, base+2, base+5, base+4)]
        evaluated.to_mesh_clear()
        result = bpy.data.meshes.new(f'Hull waterline {i}')
        result.from_pydata(vertices, [], faces)
        result.attributes.new('wake_feather', 'FLOAT', 'POINT').data.foreach_set('value', feather)
        result.materials.append(bpy.data.materials['Broken sea foam'])
        obj = bpy.data.objects.new(result.name, result)
        scene.collection.objects.link(obj)
        shapes.append(obj)
    for frame in range(540):
        scene.frame_set(frame)
        for obj, boat in zip(shapes, boats):
            obj.location = (boat.location.x, boat.location.y, 0)
            obj.keyframe_insert('location', frame=frame)


def ghost_surface():
    """Preserve dissolve timing; make the surface occlude internal rigging."""
    materials = {slot.material for obj in bpy.context.scene.objects
                 if obj.type == 'MESH' and obj.name.startswith('Ghost')
                 for slot in obj.material_slots if slot.material}
    for material in materials:
        tree = material.node_tree
        bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
        for node in tree.nodes:
            if node.type != 'MATH' or node.operation != 'MULTIPLY_ADD':
                continue
            if abs(node.inputs[2].default_value - .58) < .001:
                node.inputs[1].default_value = .025
                node.inputs[2].default_value = .965
            elif abs(node.inputs[2].default_value - .25) < .001:
                node.inputs[1].default_value = 1.3
                node.inputs[2].default_value = .09
        bsdf.inputs['Emission Color'].default_value = (.035, .44, .72, 1)
        material.use_backface_culling = False


def water_light():
    """Keep a weak ship shadow on the stylized opaque sea, not a floor silhouette.

    Split the same environment-light energy into shadowed and unshadowed contributions
    for the water only. Character/shore lighting and actual hull immersion stay
    unchanged. This is art direction for EEVEE water, not underwater transport.
    """
    scene = bpy.context.scene
    if scene.get('fleet_water_light_v3'):
        raise RuntimeError('Sea lighting already applied')
    sea = bpy.data.objects['FleetCoast Ocean']
    sources = [o for o in scene.objects if o.type == 'LIGHT'
               and o.name.startswith('FleetCoast ')]
    land = bpy.data.collections.new('Fleet sun receivers except sea')
    water = bpy.data.collections.new('Fleet sea sun receivers')
    water.objects.link(sea)
    for obj in scene.objects:
        if obj.type == 'MESH' and obj != sea:
            land.objects.link(obj)
    for source in sources:
        source.light_linking.receiver_collection = land
        for label, fraction, shadows in (('shadow', .3, True), ('fill', .7, False)):
            light = source.copy()
            light.data = source.data.copy()
            light.name = 'Fleet sea light '+source.name+' '+label
            light.data.energy *= fraction
            light.data.use_shadow = shadows
            scene.collection.objects.link(light)
            light.light_linking.receiver_collection = water
    scene['fleet_water_light_v3'] = True


def closeup_surface():
    from deformation_normals import weld_compatible_uv_duplicates
    reports = []
    for suffix in ('.upper_body', '.leftarm_model'):
        obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH'
                   and o.name.startswith('Giant_') and o.name.endswith(suffix))
        reports.append(weld_compatible_uv_duplicates(obj))
        # Smooth the sparse deformed surface while pinning the existing openings.
        # The neck boundary must stay on the original head seam, not shrink away.
        mesh = obj.data
        counts = Counter()
        for poly in mesh.polygons:
            vs = list(poly.vertices)
            for a, b in zip(vs, vs[1:]+vs[:1]):
                counts[tuple(sorted((a,b)))] += 1
        crease = mesh.attributes.get('crease_edge') or mesh.attributes.new('crease_edge','FLOAT','EDGE')
        for edge in mesh.edges:
            if counts[tuple(sorted(edge.vertices))] == 1 or edge.use_edge_sharp:
                crease.data[edge.index].value = 1
        if suffix == '.upper_body':
            # The matched head ring is not entirely a topological boundary.
            # Protect that explicit junction as well as open mesh edges.
            from mathutils.kdtree import KDTree
            head = next(o for o in bpy.context.scene.objects if o.type == 'MESH'
                        and o.name.startswith('Giant_') and o.name.endswith('.head'))
            tree = KDTree(len(head.data.vertices))
            transform = obj.matrix_world.inverted()@head.matrix_world
            for vertex in head.data.vertices:
                tree.insert(transform@vertex.co,vertex.index)
            tree.balance()
            junction = {v.index for v in mesh.vertices if tree.find(v.co)[2] < 1e-5}
            vertex_crease = mesh.attributes.get('crease_vert') or mesh.attributes.new('crease_vert','FLOAT','POINT')
            for index in junction:
                vertex_crease.data[index].value = 1
            for edge in mesh.edges:
                if all(i in junction for i in edge.vertices):
                    crease.data[edge.index].value = 1
        modifier = obj.modifiers.new('Close-up surface continuity','SUBSURF')
        modifier.levels = modifier.render_levels = 1
    return reports


def solid_ship_material():
    # The original is an effect atlas with painted near-black shadows. Preserve
    # its pattern, but keep it in a readable wood/ivory range for solid vessels.
    tree = bpy.data.materials['ghostship_base'].node_tree
    bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    source = bsdf.inputs['Base Color'].links[0].from_socket
    multiply = tree.nodes.new('ShaderNodeMixRGB')
    multiply.blend_type = 'MULTIPLY'
    multiply.inputs[0].default_value = 1
    multiply.inputs[2].default_value = (.75,.75,.70,1)
    tree.links.new(source,multiply.inputs[1])
    add = tree.nodes.new('ShaderNodeMixRGB')
    add.blend_type = 'ADD'
    add.inputs[0].default_value = 1
    add.inputs[2].default_value = (.055,.025,.008,1)
    tree.links.new(multiply.outputs[0],add.inputs[1])
    tree.links.new(add.outputs[0],bsdf.inputs['Base Color'])


def landscape_depth():
    import random
    from fleet_coast import _height, _noise, _ramp, _mix
    scene = bpy.context.scene
    shore = bpy.data.objects['FleetCoast Shore']
    def extra(x,y):
        # The complete action area, including the new backward fall, stays flat.
        outside = max(abs(x)-14,y-27,0)
        weight = min(1,outside/14)**2
        return weight*(2.8*math.exp(-((y-50)/27)**2)*(1+.55*math.sin(x*.09))
                       + 14*math.exp(-((y-110)/40)**2)*(1+.35*math.sin(x*.045)))
    for vertex in shore.data.vertices:
        x,y,z = vertex.co
        vertex.co.z += extra(x,y)
    rng = random.Random(882)
    clusters = ((-47,36),(-24,48),(22,42),(48,66),(0,88))
    trees = sorted((o for o in scene.objects if o.type == 'EMPTY' and o.name.startswith('FleetCoast Tree ')),key=lambda o:o.name)
    for i,obj in enumerate(trees):
        x,y = clusters[i%len(clusters)]
        x += rng.uniform(-9,9); y += rng.uniform(-8,8)
        obj.location = (x,y,_height(x,y)+extra(x,y)-.1)
    for i in range(12):
        source = trees[i%len(trees)]
        obj = source.copy()
        obj.name = f'Fleet distant tree {i:02d}'
        scene.collection.objects.link(obj)
        x,y = -88+i*16+rng.uniform(-4,4), rng.uniform(90,118)
        obj.location = (x,y,_height(x,y)+extra(x,y)-.1)
        obj.scale *= 1.35
        for child in source.children:
            copy = child.copy()
            copy.name = obj.name+' mesh'
            scene.collection.objects.link(copy)
            copy.parent = obj
    # Broad changes break the uniform sand; fine grain remains subordinate.
    tree = shore.data.materials[0].node_tree
    bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    original = bsdf.inputs['Base Color'].links[0].from_socket
    coord = tree.nodes.new('ShaderNodeTexCoord').outputs['Object']
    broad = _noise(tree,coord,.095,2)
    patch = _ramp(tree,broad,[(.28,(0,0,0)),(.72,(.5,.5,.5))])
    tree.links.new(_mix(tree,patch,original,(.10,.072,.035)),bsdf.inputs['Base Color'])
    for node in tree.nodes:
        if node.type == 'BUMP':
            node.inputs['Strength'].default_value *= .65
    bpy.data.objects['FleetCoast warm side sun'].data.angle = .28
    # The generic hero material repair had disconnected the imported alpha-test
    # output. Foliage needs its original cutout instead of opaque polygon cards.
    for name in ('tree_oak_leaves_00','tree_pine_frond_00'):
        material = bpy.data.materials[name]
        tree = material.node_tree
        bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
        cutoff = next(n for n in tree.nodes if n.type == 'MATH' and n.operation == 'SUBTRACT'
                      and n.inputs[1].is_linked and n.inputs[1].links[0].from_node.operation == 'LESS_THAN')
        tree.links.new(cutoff.outputs[0],bsdf.inputs['Alpha'])
        bsdf.inputs['Roughness'].default_value = .85
        bsdf.inputs['Specular IOR Level'].default_value = .2
    camera = bpy.data.objects['02_Fleet_and_giant']
    camera.location = (16,-49,19)
    camera.rotation_euler = (Vector((0,-10,3.5))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.lens = 26
    camera.data.dof.focus_distance = (Vector((0,-10,3.5))-camera.location).length


def apply():
    scene = bpy.context.scene
    if scene.get('fleet_look_v3'):
        raise RuntimeError('Look already applied; reopen the untouched baseline first.')
    character_light()
    immerse_fleet()
    waterline_foam()
    ghost_surface()
    solid_ship_material()
    landscape_depth()
    closeup_surface()
    water_light()
    scene['fleet_look_v3'] = True


if __name__ == '__main__':
    apply()
