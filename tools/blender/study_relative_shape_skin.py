"""Small synthetic LBS/relative-key experiment, not a production weight fixer."""
import argparse
import itertools
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

VALUES = list(itertools.product((0., .5, 1.), repeat=2))
TOL = 3e-6  # meters, synthetic scene unit scale 1


def sample(obj, values):
    keys = obj.data.shape_keys.key_blocks
    keys['A'].value, keys['B'].value = values
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ v.co for v in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def distance(a, b):
    assert len(a) == len(b)
    return max((Vector(x)-Vector(y)).length for x, y in zip(a, b))


def weights(obj):
    return [{obj.vertex_groups[g.group].name: g.weight for g in v.groups}
            for v in obj.data.vertices]


def set_weights(obj, data):
    for g in obj.vertex_groups:
        g.remove(list(range(len(obj.data.vertices))))
    for i, row in enumerate(data):
        for name, value in row.items():
            obj.vertex_groups[name].add([i], value, 'REPLACE')


def weighted(transforms, row):
    result = Matrix(((0.,)*4,)*4)
    for name, value in row.items():
        result += transforms[name] * value
    return result


def inverse(matrix):
    if abs(matrix.to_3x3().determinant()) < 1e-8:
        raise ValueError('singular')
    result = matrix.inverted()
    condition = max(sum(abs(x) for x in row[:3]) for row in matrix[:3]) * max(
        sum(abs(x) for x in row[:3]) for row in result[:3])
    if not math.isfinite(condition) or condition > 1e6:
        raise ValueError('ill-conditioned')
    return result


def plan(obj, arm, new_weights, ignore_object_transforms=False):
    # Deliberately narrow domain; preflight completes before any write.
    mods = list(obj.modifiers)
    if len(mods) != 1 or mods[0].type != 'ARMATURE' or mods[0].object != arm:
        raise ValueError('unsupported stack')
    mod = mods[0]
    if not mod.show_viewport or not mod.show_render:
        raise ValueError('viewport/render mismatch')
    if mod.use_deform_preserve_volume:
        raise ValueError('DQ unsupported')
    if mod.use_bone_envelopes or not mod.use_vertex_groups or mod.vertex_group or mod.use_multi_modifier:
        raise ValueError('unsupported Armature mode')
    keys = obj.data.shape_keys
    if not keys or not keys.use_relative or keys.animation_data or obj.show_only_shape_key:
        raise ValueError('unsupported shape-key mode')
    if any(k.vertex_group or k.mute for k in keys.key_blocks):
        raise ValueError('key masks/mutes unsupported')
    old = weights(obj)
    if len(old) != len(new_weights):
        raise ValueError('weight count')
    for row in old + new_weights:
        if not row or any(n not in arm.pose.bones or not arm.data.bones[n].use_deform
                          or not math.isfinite(w) or w < 0 for n, w in row.items()):
            raise ValueError('unsupported weights')
        if abs(sum(row.values())-1) > 1e-6:
            raise ValueError('weights must sum to one')
    into = inverse(arm.matrix_world) @ obj.matrix_world
    out = inverse(obj.matrix_world) @ arm.matrix_world
    if ignore_object_transforms:
        into = out = Matrix.Identity(4)  # negative control only
    transforms = {n: out @ arm.pose.bones[n].matrix @ arm.data.bones[n].matrix_local.inverted() @ into
                  for row in old+new_weights for n in row}
    old_matrices = [weighted(transforms, row) for row in old]
    changes = [inverse(weighted(transforms, new)) @ prior for new, prior in zip(new_weights, old_matrices)]
    coordinates = {k.name: [change @ p.co for change, p in zip(changes, k.data)] for k in keys.key_blocks}
    if not all(math.isfinite(v) for points in coordinates.values() for point in points for v in point):
        raise ValueError('nonfinite coordinates')
    return coordinates, old_matrices


def apply(obj, coordinates, new_weights, only_basis=False):
    for key in obj.data.shape_keys.key_blocks:
        if not only_basis or key.name == 'Basis':
            for point, co in zip(key.data, coordinates[key.name]):
                point.co = co
    for v, co in zip(obj.data.vertices, coordinates['Basis']):
        v.co = co
    set_weights(obj, new_weights)
    obj.data.update()


def snapshot(obj):
    return (weights(obj), [[list(p.co) for p in k.data] for k in obj.data.shape_keys.key_blocks])


def clone(obj, name):
    other = obj.copy()
    other.data = obj.data.copy()
    other.name = name
    bpy.context.collection.objects.link(other)
    return other


def reference_pose(arm):
    arm.pose.bones['BoneA'].rotation_euler = (.2, -.15, .25)
    arm.pose.bones['BoneA'].location = (.03, -.02, .01)
    arm.pose.bones['BoneB'].rotation_euler = (.35, .1, -.3)
    arm.pose.bones['BoneB'].location = (.01, .02, -.01)
    bpy.context.view_layer.update()


def fixture():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    data = bpy.data.armatures.new('SyntheticArmature')
    arm = bpy.data.objects.new('SyntheticRig', data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    a = data.edit_bones.new('BoneA'); a.head = (0,0,0); a.tail = (0,0,1); a.roll = .2
    b = data.edit_bones.new('BoneB'); b.head = (0,0,1); b.tail = (0,0,2); b.roll = -.3; b.parent = a
    bpy.ops.object.mode_set(mode='OBJECT')
    arm.location = (-.2,.15,.25); arm.rotation_euler = (-.2,.1,.15); arm.scale = (.9,1.15,1.05)
    for b in arm.pose.bones:
        b.rotation_mode = 'XYZ'
    reference_pose(arm)
    mesh = bpy.data.meshes.new('Patch')
    vertices = [(x*.25, .07*math.sin(x+j), j*.45) for j in range(4) for x in (-1,0,1)]
    faces = [(j*3+i,j*3+i+1,(j+1)*3+i+1,(j+1)*3+i) for j in range(3) for i in range(2)]
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new('OriginalBasisRelative', mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = (.4,-.3,.2); obj.rotation_euler = (.1,.2,-.25); obj.scale = (1.1,.85,1.2)
    basis = obj.shape_key_add(name='Basis')
    ka = obj.shape_key_add(name='A'); kb = obj.shape_key_add(name='B')
    for i, p in enumerate(basis.data):
        ka.data[i].co = p.co + Vector((.04*(i%3-1), .08*(1+i/12), .03*math.sin(i)))
        kb.data[i].co = p.co + Vector((-.03*math.cos(i), -.05*(1+i/12), .06*(i%2)))
    ka.relative_key = basis; kb.relative_key = basis
    for n in ('BoneA','BoneB'):
        obj.vertex_groups.new(name=n)
    old = [{'BoneA': .2 if i%2 else .85, 'BoneB': .8 if i%2 else .15} for i in range(12)]
    set_weights(obj, old)
    mod = obj.modifiers.new('LinearArmature','ARMATURE'); mod.object = arm
    mod.use_vertex_groups = True; mod.use_bone_envelopes = False; mod.use_deform_preserve_volume = False
    bpy.context.view_layer.update()
    return arm, obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--reopen', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.reopen:
        prior = json.loads((args.out/'result.json').read_text())
        bpy.ops.wm.open_mainfile(filepath=str((args.out/'synthetic.blend').resolve()), load_ui=False, use_scripts=False)
        errors = []
        for name, cases in prior['reference_world'].items():
            corrected = bpy.data.objects['Corrected'+name]
            errors.extend(distance(sample(corrected, values), points) for values, points in zip(VALUES, cases))
        assert max(errors) < TOL
        result = {'cases': len(errors), 'max_world_error_m': max(errors)}
        (args.out/'reopen.json').write_text(json.dumps(result,indent=2)); print('REOPEN',result); return
    args.out.mkdir(parents=True, exist_ok=False)
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    bpy.context.preferences.filepaths.save_version = 0
    arm, base = fixture()
    chained = clone(base, 'OriginalChainedRelative')
    chained.data.shape_keys.key_blocks['B'].relative_key = chained.data.shape_keys.key_blocks['A']
    new = [{'BoneA': .75-i*.04, 'BoneB': .25+i*.04} for i in range(12)]
    report = {'blender': bpy.app.version_string, 'build': bpy.app.build_hash.decode(),
              'vertices': 12, 'values': VALUES, 'tolerance_m': TOL, 'cases': {}, 'reference_world': {}, 'refusals': {}}
    pairs = []
    for name, original in [('BasisRelative',base),('ChainedRelative',chained)]:
        coordinates, old_matrices = plan(original, arm, new)
        corrected = clone(original, 'Corrected'+name); apply(corrected, coordinates, new)
        weight_only = clone(original, 'WeightsOnly'+name); set_weights(weight_only, new)
        basis_only = clone(original, 'BasisOnly'+name); apply(basis_only, coordinates, new, only_basis=True)
        wrong = clone(original, 'WrongSpace'+name); wrong_co, _ = plan(wrong, arm, new, True); apply(wrong, wrong_co, new)
        errors = {n: [] for n in ('corrected','weights_only','basis_only','wrong_space','formula_vs_blender')}
        refs = []
        for values in VALUES:
            before = sample(original, values); refs.append([list(p) for p in before])
            for label, candidate in [('corrected',corrected),('weights_only',weight_only),('basis_only',basis_only),('wrong_space',wrong)]:
                errors[label].append(distance(sample(candidate, values), before))
            ks = original.data.shape_keys.key_blocks
            mixed = [ks['Basis'].data[i].co + sum((value*(ks[n].data[i].co-ks[n].relative_key.data[i].co)
                     for n,value in zip(('A','B'),values)), Vector()) for i in range(12)]
            predicted = [original.matrix_world @ (m @ co) for m,co in zip(old_matrices,mixed)]
            errors['formula_vs_blender'].append(distance(predicted,before))
        assert max(errors['corrected']) < TOL and max(errors['formula_vs_blender']) < TOL
        assert all(max(errors[n]) > .001 for n in ('weights_only','basis_only','wrong_space'))
        report['cases'][name] = {n: {'max_m':max(v),'per_value_case_m':v} for n,v in errors.items()}
        report['reference_world'][name] = refs
        pairs.append((original,corrected))
    def refusal(label, arrange, expected):
        obj = clone(base, 'Refusal'+label); candidate = [dict(w) for w in new]
        arrange(obj, candidate); before = snapshot(obj)
        try:
            plan(obj,arm,candidate)
        except ValueError as error:
            assert expected in str(error), str(error)
            assert snapshot(obj) == before
            report['refusals'][label] = {'reason':str(error),'no_data_mutation':True}
        else:
            raise AssertionError('Expected refusal: '+label)
    refusal('DQ',lambda o,w:setattr(o.modifiers[0],'use_deform_preserve_volume',True),'DQ')
    refusal('extra_modifier',lambda o,w:o.modifiers.new('Unsupported','SUBSURF'),'unsupported stack')
    refusal('stack_visibility',lambda o,w:setattr(o.modifiers[0],'show_render',False),'mismatch')
    refusal('key_mask',lambda o,w:setattr(o.data.shape_keys.key_blocks['A'],'vertex_group','BoneA'),'masks')
    refusal('absolute_keys',lambda o,w:setattr(o.data.shape_keys,'use_relative',False),'shape-key mode')
    refusal('unnormalized',lambda o,w:w[0].update(BoneA=.9),'sum to one')
    arm.pose.bones['BoneA'].rotation_euler=(0,0,0); arm.pose.bones['BoneA'].location=(0,0,0)
    arm.pose.bones['BoneB'].rotation_euler=(0,0,math.pi); arm.pose.bones['BoneB'].location=(0,0,0)
    bpy.context.view_layer.update()
    refusal('singular',lambda o,w:[row.update(BoneA=.5,BoneB=.5) for row in w],'singular')
    reference_pose(arm)
    arm.pose.bones['BoneB'].rotation_euler.x += .25
    report['outside_reference_pose_max_error_m'] = max(distance(sample(a,v),sample(b,v)) for a,b in pairs for v in VALUES)
    assert report['outside_reference_pose_max_error_m'] > .001
    reference_pose(arm)
    for a,b in pairs:
        sample(a,(0,0)); sample(b,(0,0))
    bpy.ops.wm.save_as_mainfile(filepath=str((args.out/'synthetic.blend').resolve()),compress=True)
    (args.out/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='reference_world'},indent=2))


if __name__ == '__main__':
    main()
