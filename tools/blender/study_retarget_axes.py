"""Single Retarget roll-axis probe; no solver, render or package changes.

Reuse the isolated smoke profile/package and source helpers. Outputs root/axes.
Expected rotations are world pose relative to each rig's own world rest basis.
"""
import argparse
from datetime import datetime, timezone
import importlib
import json
import math
import os
from pathlib import Path
import sys
import traceback

import bpy
from bpy_extras import anim_utils
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_retarget_smoke as base
import study_retarget_proportions as proportions


def angle_degrees(a, b):
    q = a.to_quaternion().rotation_difference(b.to_quaternion())
    return math.degrees(2*math.atan2(math.sqrt(q.x*q.x+q.y*q.y+q.z*q.z), abs(q.w)))


def world_rotation_metrics(donor, receiver, donor_rest, receiver_rest):
    if len(donor) != len(base.FRAMES) or len(receiver) != len(base.FRAMES):
        raise ValueError('Incomplete samples')
    result = dict(samples=len(base.FRAMES), bone_matrices=len(base.FRAMES)*6,
                  max_expected_world_rotation_error_deg=0.,
                  max_absolute_pose_rotation_difference_deg=0.,
                  static_negative_control_error_deg=0., worst=None)
    # Both object matrices are identity and asserted at construction. Rest
    # matrices are therefore already world-space rotation bases.
    for frame, d, r in zip(base.FRAMES, donor, receiver):
        for name in base.BONES:
            rd = Matrix(donor_rest[name]['matrix']).to_3x3()
            rr = Matrix(receiver_rest[name]['matrix']).to_3x3()
            md, mr = Matrix(d[name]).to_3x3(), Matrix(r[name]).to_3x3()
            expected = md @ rd.inverted() @ rr
            error = angle_degrees(expected, mr)
            if error > result['max_expected_world_rotation_error_deg']:
                result['max_expected_world_rotation_error_deg'] = error
                result['worst'] = dict(frame=frame, bone=name)
            result['max_absolute_pose_rotation_difference_deg'] = max(
                result['max_absolute_pose_rotation_difference_deg'], angle_degrees(md, mr))
            result['static_negative_control_error_deg'] = max(
                result['static_negative_control_error_deg'], angle_degrees(expected, rr))
    result['passed'] = result['max_expected_world_rotation_error_deg'] <= .05
    assert result['static_negative_control_error_deg'] > 3., 'Motion must be nontrivial'
    return result


def build(root, folder, report):
    addon = importlib.import_module('retarget')
    entry = bpy.context.preferences.addons.new()
    entry.module = 'retarget'
    addon.register()
    try:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        bpy.context.preferences.filepaths.file_preview_type = 'NONE'
        bpy.context.preferences.filepaths.save_version = 0
        sc = bpy.context.scene
        sc.frame_start, sc.frame_end, sc.render.fps = 1, 60, 30
        donor = base.make_rig('Donor', 'donor_')
        receiver = base.make_rig('Receiver', '')
        assert donor.matrix_world == Matrix.Identity(4) and receiver.matrix_world == Matrix.Identity(4)
        before = proportions.rest(receiver)
        base.select_only(receiver)
        bpy.ops.object.mode_set(mode='EDIT')
        for name in ('spine2', 'neck1'):
            receiver.data.edit_bones[name].roll = math.pi/2
        bpy.ops.object.mode_set(mode='OBJECT')
        own_rest, donor_rest = proportions.rest(receiver), proportions.rest(donor, 'donor_')
        geometry = ('head', 'tail', 'parent', 'connected')
        report['head_tail_lengths_hierarchy_unchanged'] = all(
            before[n][field] == own_rest[n][field] for n in base.BONES for field in geometry)
        report['roll_edit_length_property_roundoff_m'] = max(
            abs(before[n]['length']-own_rest[n]['length']) for n in base.BONES)
        report['roll_edit_geometric_length_change_m'] = max(abs(
            (Vector(before[n]['tail'])-Vector(before[n]['head'])).length -
            (Vector(own_rest[n]['tail'])-Vector(own_rest[n]['head'])).length) for n in base.BONES)
        assert report['head_tail_lengths_hierarchy_unchanged']
        assert report['roll_edit_geometric_length_change_m'] == 0.
        report['rest_basis_change_deg'] = {n: angle_degrees(Matrix(before[n]['matrix']),
                                                          Matrix(own_rest[n]['matrix'])) for n in base.BONES}
        assert all(abs(report['rest_basis_change_deg'][n]-(90 if n in ('spine2', 'neck1') else 0)) < .001
                   for n in base.BONES)
        base.write_json(folder/'receiver_rest.json', own_rest)
        base.write_json(folder/'donor_rest.json', donor_rest)
        for frame in range(1, 61):
            for name, axis, amplitude in [('spine2', 0, 4), ('neck1', 2, 3)]:
                bone = donor.pose.bones['donor_'+name]
                bone.rotation_euler[axis] = math.radians(amplitude)*math.sin(2*math.pi*(frame-1)/60)
                bone.keyframe_insert('rotation_euler', frame=frame, group=bone.name)
        data = donor.animation_data
        assert len(data.action.slots) == 1 and data.action.slots[0].target_id_type == 'OBJECT'
        for curve in anim_utils.action_get_channelbag_for_slot(data.action, data.action_slot).fcurves:
            for key in curve.keyframe_points:
                key.interpolation = 'LINEAR'
        digest = proportions.action_digest(donor)
        donor_motion = base.snapshot(donor, 'donor_')
        report['donor_matches_previous_smoke'] = base.compare(
            json.loads((root/'live_matrices.json').read_text()), donor_motion)
        base.write_json(folder/'donor_matrices.json', donor_motion)
        sc.frame_set(1)
        base.select_only(donor)
        receiver.select_set(True)
        options = json.loads((root/'smoke.json').read_text())['binding_options']
        report['binding_options'] = options
        report['binding_result'] = sorted(base.invoke_binding(addon, options, report))
        report['rest_unchanged_by_binding'] = own_rest == proportions.rest(receiver)
        report['donor_rest_action_unchanged'] = donor_rest == proportions.rest(donor, 'donor_') and digest == proportions.action_digest(donor)
        assert report['rest_unchanged_by_binding'] and report['donor_rest_action_unchanged']
        constraints = [c for b in receiver.pose.bones for c in b.constraints]
        assert len(constraints) == 6 and all(c.type == 'COPY_ROTATION' for c in constraints)
        live = base.snapshot(receiver)
        base.write_json(folder/'live_matrices.json', live)
        report['world_rotation'] = world_rotation_metrics(donor_motion, live, donor_rest, own_rest)
        if not report['world_rotation']['passed']:
            raise ValueError('Live world relative-rotation tolerance exceeded')
        report['live_lengths'] = proportions.length_metrics(receiver, own_rest)
        base.select_only(receiver)
        addon.bone_utils.bake_anim(frame_start=1, frame_end=60, only_selected=False,
            bake_bones=True, bake_object=False, use_current_action=False,
            suffix=addon.bone_utils.cp_suffix, step=1, interpolation='LINEAR', inverse=False)
        data = receiver.animation_data
        assert len(data.action.slots) == 1 and data.action.slots[0].target_id_type == 'OBJECT'
        for c in constraints:
            c.mute = True
        receiver.update_tag()
        report['live_to_baked'] = base.compare(live, base.snapshot(receiver))
        report['baked_lengths'] = proportions.length_metrics(receiver, own_rest)
        report['rest_unchanged_by_bake'] = own_rest == proportions.rest(receiver)
        assert report['rest_unchanged_by_bake']
        assert donor_rest == proportions.rest(donor, 'donor_') and digest == proportions.action_digest(donor)
        base.select_only(receiver)
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'baked.blend'))
    except Exception:
        # Preserve the actual failing state rather than trying another solver.
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'failure.blend'))
        raise
    finally:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--mode', choices=('build', 'reopen'), required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root, folder = args.root.resolve(), args.root.resolve()/'axes'
    folder.mkdir(exist_ok=True)
    report = dict(task_id='retarget_axes', mode=args.mode, package_sha256=base.PACKAGE_HASH,
                  blender_version=list(bpy.app.version), build_hash=bpy.app.build_hash.decode(), errors=[])
    journal = dict(task_id='retarget_axes', stage=args.mode, active=True, pid=os.getpid(),
                   exitcode=None, next_step='Inspect one local-axis probe', utc=datetime.now(timezone.utc).isoformat())
    base.write_json(args.journal, journal)
    try:
        package = base.check_package(root)
        base.guard(root, args.journal.resolve())
        if args.mode == 'build':
            sys.path.insert(0, str(package))
            build(root, folder, report)
        else:
            proportions.reopen(folder, report)
            own_rest = json.loads((folder/'receiver_rest.json').read_text())
            donor_rest = json.loads((folder/'donor_rest.json').read_text())
            report['reopened_world_rotation'] = world_rotation_metrics(
                json.loads((folder/'donor_matrices.json').read_text()),
                base.snapshot(bpy.data.objects['Receiver']), donor_rest, own_rest)
            assert report['reopened_world_rotation']['passed']
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
