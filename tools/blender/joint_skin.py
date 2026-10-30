"""Stabilize abrupt leg skin weights on scene-local meshes before crouch baking.

Only short edges with large weight discontinuities trigger the repair. The
reference posed surface is preserved by inverting the new linear skin matrix.
This is not cloth simulation or a guarantee for other poses/rigs.
"""
import math

import bpy
from mathutils import Matrix


def _sample(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(dg)
    mesh = evaluated.to_mesh()
    try:
        return [v.co.copy() for v in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def _plan(obj, arm, unit):
    if obj.data.shape_keys:
        return None
    groups = {g.index: g.name for g in obj.vertex_groups}
    weights = [{g.group: g.weight for g in v.groups} for v in obj.data.vertices]
    mask = []
    for w in weights:
        ankle = sum(x for g, x in w.items() if 'ankle' in groups[g].lower() or 'toe' in groups[g].lower())
        leg = sum(x for g, x in w.items() if any(s in groups[g].lower() for s in ('thigh', 'hip', 'knee')))
        mask.append(ankle < .3 and leg > .5)
    if not any(mask):
        return None
    reference = _sample(obj)
    if len(reference) != len(weights):
        raise ValueError(f'{obj.name}: skin repair needs matching evaluated topology')
    adjacency = [set() for _ in weights]
    risky = []
    for edge in obj.data.edges:
        a, b = edge.vertices
        adjacency[a].add(b)
        adjacency[b].add(a)
        length = (obj.matrix_world.to_3x3() @ (reference[a] - reference[b])).length * unit
        difference = sum(abs(weights[a].get(g, 0) - weights[b].get(g, 0))
                         for g in weights[a].keys() | weights[b].keys())
        if mask[a] and mask[b] and 1e-6 < length < .03 and difference > .5:
            risky.append((a, b))
    if not risky:
        return None
    modifiers = [m for m in obj.modifiers if m.show_viewport]
    if len(modifiers) != 1 or modifiers[0].type != 'ARMATURE' or modifiers[0].use_deform_preserve_volume:
        raise ValueError(f'{obj.name}: weight repair requires one linear Armature modifier')
    if any(groups[g] not in arm.pose.bones for w in weights for g in w):
        raise ValueError(f'{obj.name}: non-bone weights cannot be inverted safely')
    smoothed = [dict(w) for w in weights]
    for _ in range(8):
        following = []
        for i, w in enumerate(smoothed):
            if not mask[i] or not adjacency[i]:
                following.append(dict(w))
                continue
            factors = {j: 1 / max(.005, (obj.matrix_world.to_3x3() @ (reference[i] - reference[j])).length * unit)
                       for j in adjacency[i]}
            denominator = sum(factors.values())
            average = {}
            for j, factor in factors.items():
                for g, value in smoothed[j].items():
                    average[g] = average.get(g, 0) + value * factor / denominator
            values = {g: .5 * w.get(g, 0) + .5 * average.get(g, 0) for g in w.keys() | average.keys()}
            total = sum(values.values())
            following.append({g: value / total for g, value in values.items() if value > 1e-8})
        smoothed = following
    into_arm = arm.matrix_world.inverted() @ obj.matrix_world
    out_of_arm = obj.matrix_world.inverted() @ arm.matrix_world
    transforms = {g: out_of_arm @ arm.pose.bones[name].matrix @ arm.data.bones[name].matrix_local.inverted() @ into_arm
                  for g, name in groups.items() if name in arm.pose.bones}
    coordinates = [v.co.copy() for v in obj.data.vertices]
    for i, w in enumerate(smoothed):
        if not mask[i]:
            continue
        matrix = Matrix(((0, 0, 0, 0),) * 4)
        for g, value in w.items():
            matrix += transforms[g] * value
        if abs(matrix.determinant()) < 1e-10:
            raise ValueError(f'{obj.name}: singular skin matrix at vertex {i}')
        coordinates[i] = matrix.inverted() @ reference[i]
        if not all(math.isfinite(x) for x in coordinates[i]):
            raise ValueError(f'{obj.name}: nonfinite repaired vertex {i}')
    return reference, coordinates, smoothed, sum(mask), len(risky)


def stabilize_crouch_skins(D, actors, scene, fps):
    """Return reports; restore meshes and frame if any repair fails."""
    frame, subframe = scene.frame_current, scene.frame_subframe
    originals = []
    reports = []
    try:
        first = {}
        for event in D.get('crouches') or []:
            first[event['who']] = min(first.get(event['who'], float('inf')), event['at'])
        for who, at in first.items():
            scene.frame_set(round(at * fps))
            arm, root = actors[who]['arm'], actors[who]['root']
            for obj in root.children_recursive:
                if obj.type != 'MESH' or obj.get('crouch_skin_stabilized'):
                    continue
                if not any(m.type == 'ARMATURE' and m.object == arm for m in obj.modifiers):
                    continue
                plan = _plan(obj, arm, scene.unit_settings.scale_length)
                if plan is None:
                    continue
                reference, coordinates, weights, count, risky = plan
                old = obj.data
                obj.data = old.copy()
                originals.append((obj, old, obj.data))
                for group in obj.vertex_groups:
                    group.remove(list(range(len(weights))))
                for i, values in enumerate(weights):
                    for group, value in values.items():
                        obj.vertex_groups[group].add([i], value, 'REPLACE')
                    obj.data.vertices[i].co = coordinates[i]
                obj.data.update()
                bpy.context.view_layer.update()
                actual = _sample(obj)
                error = max((obj.matrix_world.to_3x3() @ (a - b)).length for a, b in zip(actual, reference)) * scene.unit_settings.scale_length
                if error > .0001:
                    raise ValueError(f'{obj.name}: reference skin changed by {error:.6g}m')
                obj['crouch_skin_stabilized'] = True
                report = dict(who=who, mesh=obj.name, vertices=count, risky_edges=risky, reference_error_m=error)
                reports.append(report)
                print(f'JOINT_SKIN {who}: {obj.name}, vertices={count}, reference error={error:.6g}m', flush=True)
        return reports
    except Exception:
        for obj, old, new in reversed(originals):
            obj.data = old
            if 'crouch_skin_stabilized' in obj:
                del obj['crouch_skin_stabilized']
            if new.users == 0:
                bpy.data.meshes.remove(new)
        raise
    finally:
        scene.frame_set(frame, subframe=subframe)
