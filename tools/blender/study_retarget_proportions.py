"""One unequal-proportion Retarget probe, reusing the isolated smoke harness.

Blender --factory-startup; --root points to the verified retarget_smoke folder.
Same profile/package, new output under root/proportions; no rendering.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys
import traceback

import bpy
from bpy_extras import anim_utils
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_retarget_smoke as base


def rest(ob, prefix=''):
    return {name: dict(matrix=[list(r) for r in ob.data.bones[prefix+name].matrix_local],
                       head=list(ob.data.bones[prefix+name].head_local),
                       tail=list(ob.data.bones[prefix+name].tail_local),
                       length=ob.data.bones[prefix+name].length,
                       parent=ob.data.bones[prefix+name].parent.name if ob.data.bones[prefix+name].parent else None,
                       connected=ob.data.bones[prefix+name].use_connect)
            for name in base.BONES}


def action_digest(ob):
    data = ob.animation_data
    bag = anim_utils.action_get_channelbag_for_slot(data.action, data.action_slot)
    curves = [(c.data_path, c.array_index, [(list(k.co), k.interpolation) for k in c.keyframe_points])
              for c in bag.fcurves]
    return hashlib.sha256(json.dumps(curves, sort_keys=True).encode()).hexdigest()


def change_proportions(ob):
    base.select_only(ob)
    bpy.ops.object.mode_set(mode='EDIT')
    for bone in ob.data.edit_bones:
        bone.use_connect = False
    height = 0.
    for name in base.BONES:
        bone = ob.data.edit_bones[name]
        length = .24 if name in ('spine2', 'head') else .2
        bone.head = (0, 0, height)
        height += length
        bone.tail = (0, 0, height)
        bone.roll = 0.
    for bone in ob.data.edit_bones:
        bone.use_connect = bone.parent is not None
    bpy.ops.object.mode_set(mode='OBJECT')


def length_metrics(ob, own_rest):
    result = dict(samples=len(base.FRAMES), max_length_error_m=0., max_joint_gap_m=0., ranges={})
    for name in base.BONES:
        result['ranges'][name] = [float('inf'), 0.]
    for frame in base.FRAMES:
        bpy.context.scene.frame_set(int(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for name in base.BONES:
            bone = evaluated.pose.bones[name]
            head, tail = (evaluated.matrix_world @ p for p in (bone.head, bone.tail))
            length = (tail-head).length
            result['ranges'][name][0] = min(result['ranges'][name][0], length)
            result['ranges'][name][1] = max(result['ranges'][name][1], length)
            result['max_length_error_m'] = max(result['max_length_error_m'], abs(length-own_rest[name]['length']))
            if bone.parent:
                result['max_joint_gap_m'] = max(result['max_joint_gap_m'],
                    (head-evaluated.matrix_world @ bone.parent.tail).length)
    result['passed'] = result['max_length_error_m'] <= .0001 and result['max_joint_gap_m'] <= .0001
    assert result['passed'], result
    return result


def orientation_metrics(donor, receiver):
    result = dict(samples=len(base.FRAMES), bone_matrices=len(base.FRAMES)*6,
                  max_rotation_deg=0., max_position_difference_m=0.)
    for a, b in zip(donor, receiver):
        for name in base.BONES:
            ma, mb = Matrix(a[name]), Matrix(b[name])
            q = ma.to_quaternion().rotation_difference(mb.to_quaternion())
            angle = math.degrees(2*math.atan2(math.sqrt(q.x*q.x+q.y*q.y+q.z*q.z), abs(q.w)))
            result['max_rotation_deg'] = max(result['max_rotation_deg'], angle)
            result['max_position_difference_m'] = max(result['max_position_difference_m'],
                                                      (ma.translation-mb.translation).length)
    result['orientation_passed'] = result['max_rotation_deg'] <= .05
    assert result['orientation_passed'], result
    assert result['max_position_difference_m'] > .039, 'Position unexpectedly copied from shorter donor'
    return result


def run(folder, root, report):
    module = importlib.import_module('retarget')
    entry = bpy.context.preferences.addons.new()
    entry.module = 'retarget'
    module.register()
    try:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        bpy.context.preferences.filepaths.file_preview_type = 'NONE'
        bpy.context.preferences.filepaths.save_version = 0
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end, scene.render.fps = 1, 60, 30
        donor = base.make_rig('Donor', 'donor_')
        receiver = base.make_rig('Receiver', '')
        original_receiver = rest(receiver)
        change_proportions(receiver)
        own_rest, donor_rest = rest(receiver), rest(donor, 'donor_')
        report['length_ratios'] = {n: own_rest[n]['length']/original_receiver[n]['length'] for n in base.BONES}
        assert all(abs(report['length_ratios'][n]-(1.2 if n in ('spine2', 'head') else 1.)) < 1e-5 for n in base.BONES)
        report['receiver_rest_before_binding'] = own_rest
        for frame in range(1, 61):
            for name, axis, amplitude in [('spine2', 0, 4), ('neck1', 2, 3)]:
                bone = donor.pose.bones['donor_'+name]
                bone.rotation_euler[axis] = math.radians(amplitude)*math.sin(2*math.pi*(frame-1)/60)
                bone.keyframe_insert('rotation_euler', frame=frame, group=bone.name)
        action = donor.animation_data.action
        assert len(action.slots) == 1 and action.slots[0].target_id_type == 'OBJECT'
        for curve in anim_utils.action_get_channelbag_for_slot(action, donor.animation_data.action_slot).fcurves:
            for key in curve.keyframe_points:
                key.interpolation = 'LINEAR'
        digest = action_digest(donor)
        donor_before = base.snapshot(donor, 'donor_')
        # Earlier equal-rig live matrices are an independent recorded witness
        # of this donor trajectory, not a target for the longer receiver.
        report['donor_matches_previous_smoke'] = base.compare(
            json.loads((root/'live_matrices.json').read_text()), donor_before)
        scene.frame_set(1)
        base.select_only(donor)
        receiver.select_set(True)
        options = json.loads((root/'smoke.json').read_text())['binding_options']
        report['binding_options'] = options
        report['binding_result'] = sorted(base.invoke_binding(module, options, report))
        report['rest_unchanged_by_binding'] = own_rest == rest(receiver)
        report['donor_original_rest_unchanged'] = donor_rest == rest(donor, 'donor_')
        report['donor_action_unchanged'] = digest == action_digest(donor)
        assert report['rest_unchanged_by_binding'] and report['donor_original_rest_unchanged'] and report['donor_action_unchanged']
        constraints = [c for b in receiver.pose.bones for c in b.constraints]
        assert len(constraints) == 6 and all(c.type == 'COPY_ROTATION' for c in constraints)
        live = base.snapshot(receiver)
        report['donor_to_live_orientation'] = orientation_metrics(donor_before, live)
        report['live_lengths'] = length_metrics(receiver, own_rest)
        base.write_json(folder/'live_matrices.json', live)
        base.write_json(folder/'receiver_rest.json', own_rest)
        base.select_only(receiver)
        module.bone_utils.bake_anim(frame_start=1, frame_end=60, only_selected=False,
            bake_bones=True, bake_object=False, use_current_action=False,
            suffix=module.bone_utils.cp_suffix, step=1, interpolation='LINEAR', inverse=False)
        assert len(receiver.animation_data.action.slots) == 1
        assert receiver.animation_data.action.slots[0].target_id_type == 'OBJECT'
        for c in constraints:
            c.mute = True
        receiver.update_tag()
        report['live_to_baked'] = base.compare(live, base.snapshot(receiver))
        report['baked_lengths'] = length_metrics(receiver, own_rest)
        report['rest_unchanged_by_bake'] = own_rest == rest(receiver)
        assert report['rest_unchanged_by_bake']
        assert digest == action_digest(donor) and donor_rest == rest(donor, 'donor_')
        base.select_only(receiver)
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'baked.blend'))
    finally:
        module.unregister()
        bpy.context.preferences.addons.remove(entry)


def reopen(folder, report):
    assert not any(n == 'retarget' or n.startswith('retarget.') for n in sys.modules)
    assert 'retarget' not in bpy.context.preferences.addons
    bpy.ops.wm.open_mainfile(filepath=str(folder/'baked.blend'))
    receiver = bpy.data.objects['Receiver']
    constraints = [c for b in receiver.pose.bones for c in b.constraints]
    assert len(constraints) == 6 and all(c.mute for c in constraints)
    own_rest = json.loads((folder/'receiver_rest.json').read_text())
    report['rest_unchanged_after_reopen'] = own_rest == rest(receiver)
    assert report['rest_unchanged_after_reopen']
    report['live_to_reopened'] = base.compare(json.loads((folder/'live_matrices.json').read_text()), base.snapshot(receiver))
    report['reopened_lengths'] = length_metrics(receiver, own_rest)
    report['addon_imported'] = any(n == 'retarget' or n.startswith('retarget.') for n in sys.modules)
    assert not report['addon_imported']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--mode', choices=('build', 'reopen'), required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root, folder = args.root.resolve(), args.root.resolve()/'proportions'
    folder.mkdir(exist_ok=True)
    report = dict(task_id='retarget_proportions', mode=args.mode,
                  package_sha256=base.PACKAGE_HASH, blender_version=list(bpy.app.version),
                  build_hash=bpy.app.build_hash.decode(), errors=[])
    journal = dict(task_id='retarget_proportions', stage=args.mode, active=True,
                   pid=os.getpid(), exitcode=None, next_step='Inspect one proportions probe',
                   utc=datetime.now(timezone.utc).isoformat())
    base.write_json(args.journal, journal)
    try:
        package = base.check_package(root)
        base.guard(root, args.journal.resolve())
        if args.mode == 'build':
            sys.path.insert(0, str(package))
            run(folder, root, report)
        else:
            reopen(folder, report)
        base.check_package(root)
        report['package_unchanged'] = True
        journal.update(stage=args.mode+'_complete', exitcode=0)
    except Exception:
        report['errors'].append(traceback.format_exc())
        journal.update(stage='failed', exitcode=2)
        raise
    finally:
        base.write_json(folder/(args.mode+'.json'), report)
        journal.update(active=False, utc=datetime.now(timezone.utc).isoformat())
        base.write_json(args.journal, journal)
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
