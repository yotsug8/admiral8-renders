"""Restore matching skin weights at an existing split-mesh junction.

No new geometry, joining, smoothing or guessed projection. Only coincident
rest vertices are eligible. Facial keys are preserved; active keys that move
the seam are rejected because this operation does not retarget facial shapes.
"""


def match_skin_seam(head, body, tolerance=1e-5):
    from mathutils.kdtree import KDTree

    def rig(obj):
        mods = [m for m in obj.modifiers if m.type == 'ARMATURE']
        if len(mods) != 1 or mods[0].object is None:
            raise ValueError('Skin seam needs one Armature modifier per mesh')
        return mods[0].object

    if rig(head) != rig(body):
        raise ValueError('Skin seam meshes must share their armature')
    matrix = head.matrix_world.inverted() @ body.matrix_world
    tree = KDTree(len(body.data.vertices))
    for v in body.data.vertices:
        tree.insert(matrix @ v.co, v.index)
    tree.balance()
    planned = []
    pairs = []
    max_shape_delta = 0.
    for vertex in head.data.vertices:
        near = tree.find_range(vertex.co, tolerance)
        if not near:
            continue
        weights = []
        for _, index, _ in near:
            weights.append({body.vertex_groups[g.group].name: g.weight
                            for g in body.data.vertices[index].groups if g.weight > 0})
        if any(w != weights[0] for w in weights[1:]):
            raise ValueError('Body has conflicting weights at the same junction point')
        pairs.append((vertex.index, near[0][1]))
        if head.data.shape_keys:
            keys = head.data.shape_keys.key_blocks
            for key in list(keys)[1:]:
                delta = (key.data[vertex.index].co-keys[0].data[vertex.index].co).length
                max_shape_delta = max(max_shape_delta, delta)
                if abs(key.value) > 1e-8 and delta > tolerance:
                    raise ValueError('Active facial shape moves the seam; coordinate its boundary first')
        old = {head.vertex_groups[g.group].name: g.weight for g in vertex.groups if g.weight > 0}
        if old != weights[0]:
            planned.append((vertex.index, weights[0]))
    if len(pairs) < 3:
        raise ValueError('No sufficient existing skin junction')
    if planned and head.data.users > 1:
        head.data = head.data.copy()
    for index, weights in planned:
        for group in list(head.data.vertices[index].groups):
            head.vertex_groups[group.group].remove([index])
        for name, weight in weights.items():
            group = head.vertex_groups.get(name) or head.vertex_groups.new(name=name)
            group.add([index], weight, 'REPLACE')
    return dict(pairs=pairs, corrected_vertices=[i for i, _ in planned],
                max_preserved_shape_delta=max_shape_delta,
                scope='Rest-position matched weights. Animation and facial seam continuity require separate validation.')
