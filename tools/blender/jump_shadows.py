"""Keep the existing soft blob on its ground baseline during planned flight.

Uses simple expression drivers, retaining parenting/visibility and the original
look outside flight. This is a flat-support approximation, not terrain tracing.
"""
import math

from jump_motion import _root_z_curve


def _driver_target(owner, path, index):
    data = owner.id_data
    full_path = owner.path_from_id(path)
    channel = 0 if index is None else index
    ad = data.animation_data
    if ad and any(c.data_path == full_path and c.array_index == channel for c in ad.drivers):
        raise ValueError(f'jump shadow refuses to replace existing driver: {full_path}[{channel}]')
    return data, full_path, channel


def _driver(owner, path, root, expression, index=None):
    _driver_target(owner, path, index)
    curve = owner.driver_add(path) if index is None else owner.driver_add(path, index)
    driver = curve.driver
    driver.type = 'SCRIPTED'
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    variable = driver.variables.new()
    variable.name = 'root_z'
    variable.type = 'TRANSFORMS'
    variable.targets[0].id = root
    variable.targets[0].transform_type = 'LOC_Z'
    variable.targets[0].transform_space = 'WORLD_SPACE'
    driver.expression = expression
    if not driver.is_simple_expression:
        raise ValueError('jump shadow needs a simple expression driver')


def attach_jump_shadows(D, actors, scene):
    import bpy
    bpy.context.view_layer.update()
    grouped = {}
    for plan in D.get('jump_plan') or []:
        grouped.setdefault(plan['who'], []).append(plan)
    results = []
    unit = scene.unit_settings.scale_length
    if not grouped:
        return results
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError('jump shadow needs positive finite scene unit scale')
    staged, targets = [], set()
    for who, plans in grouped.items():
        root = actors[who]['root']
        blob = bpy.data.objects.get(who + '_blob')
        if blob is None:
            continue  # Blob shadows may be disabled by the look profile.
        if root.parent or any(abs(s - 1) > 1e-6 for s in root.scale):
            raise ValueError('jump shadow requires an unparented, unit-scale actor root')
        if abs(root.rotation_euler.x) > 1e-6 or abs(root.rotation_euler.y) > 1e-6:
            raise ValueError('jump shadow requires a yaw-only actor root')
        if (blob.parent != root or blob.constraints or
                any(abs(blob.matrix_parent_inverse[i][j] - (1 if i == j else 0)) > 1e-6
                    for i in range(4) for j in range(4))):
            raise ValueError('jump shadow requires direct root parenting with identity parent inverse and no constraints')
        curve = _root_z_curve(root)
        terms = []
        for plan in plans:
            baseline = float(curve.evaluate(plan['prep_start'] * D['fps']))
            left, right = plan['takeoff'] * D['fps'], plan['land'] * D['fps']
            if not all(math.isfinite(v) for v in (baseline, left, right)):
                raise ValueError('nonfinite jump shadow timeline')
            terms.append(f'((root_z - {baseline!r}) if {left!r} <= frame <= {right!r} else 0.0)')
        height = '(' + ' + '.join(terms) + ')'
        offset = float(blob.location.z)
        plane = bpy.data.objects.get('Plane') if not D.get('map') else None
        if plane is not None:
            # Flat diagnostic support is known; keep the decal 1 mm above it.
            baseline = float(curve.evaluate(plans[0]['prep_start'] * D['fps']))
            offset = float(plane.matrix_world.translation.z) + .001 / unit - baseline
        material = blob.active_material
        if material is None or material.node_tree is None:
            raise ValueError('jump shadow needs a node-based blob material')
        nodes = [n for n in material.node_tree.nodes if n.type == 'MATH' and n.operation == 'MULTIPLY']
        if len(nodes) != 1:
            raise ValueError('jump shadow expects one gain node in the blob material')
        socket = nodes[0].inputs[1]
        if socket.is_linked:
            raise ValueError('jump shadow gain input must not be linked')
        gain = float(socket.default_value)
        if not all(math.isfinite(v) for v in (offset, gain)):
            raise ValueError('jump shadow offset/gain must be finite')
        for owner, path, index, expression, value in (
                (blob, 'location', 2, f'{offset!r} - {height}', float(blob.location.z)),
                (socket, 'default_value', None,
                 f'{gain!r} / (1.0 + 3.0 * max(0.0, {height}) * {unit!r})', gain)):
            data, full_path, channel = _driver_target(owner, path, index)
            key = (data.as_pointer(), full_path, channel)
            if key in targets:
                raise ValueError('jump shadows cannot share a driven channel between actors')
            targets.add(key)
            staged.append((owner, path, index, root, expression, value, data,
                           data.animation_data is not None))
        results.append(dict(who=who, baseline_offset=offset, base_gain=gain))
    # All actors/materials/target channels are checked before creating a driver.
    attempted = []
    try:
        for operation in staged:
            attempted.append(operation)  # driver_add itself can fail after allocation.
            owner, path, index, root, expression, _, _, _ = operation
            _driver(owner, path, root, expression, index)
    except Exception:
        for owner, path, index, _, _, value, data, had_animation in reversed(attempted):
            if index is None:
                owner.driver_remove(path)
                setattr(owner, path, value)
            else:
                owner.driver_remove(path, index)
                getattr(owner, path)[index] = value
            ad = data.animation_data
            if not had_animation and ad and not ad.drivers and ad.action is None and not ad.nla_tracks:
                data.animation_data_clear()
        bpy.context.view_layer.update()
        raise
    return results
