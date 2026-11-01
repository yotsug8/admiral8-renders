"""Isolated compatibility probe for the exact Retarget 5.2.0 release.

Run only in a factory-startup Blender process with four BLENDER_USER_* paths
under OUT/profile. No package installation, presets execution or rendering.
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
import types
import zipfile

import bpy
from mathutils import Matrix
from bpy_extras import anim_utils

PACKAGE_HASH = '521ec8ff5c2373893ea8022b3f71d27ed191fb73f3a5634cac31585e0dcb7af3'
ENV_KEYS = ('BLENDER_USER_CONFIG', 'BLENDER_USER_SCRIPTS',
            'BLENDER_USER_EXTENSIONS', 'BLENDER_USER_DATAFILES')


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def check_package(folder):
    archive = folder/'retarget.zip'
    raw = archive.read_bytes()
    if len(raw) != 225631 or hashlib.sha256(raw).hexdigest() != PACKAGE_HASH:
        raise ValueError('Unexpected package: do not execute')
    package = folder/'package'
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            path = (package/info.filename).resolve()
            if not path.is_relative_to(package.resolve()) or path.read_bytes() != z.read(info):
                raise ValueError('Extracted package differs from verified archive')
    return package


def guard(folder, journal_path):
    profile = (folder/'profile').resolve()
    for key in ENV_KEYS:
        value = Path(os.environ.get(key, '')).resolve()
        if not value.is_relative_to(profile):
            raise ValueError('Isolated profile required: '+key)
    for kind in ('CONFIG', 'SCRIPTS', 'DATAFILES'):
        if not Path(bpy.utils.user_resource(kind)).resolve().is_relative_to(profile):
            raise ValueError('Blender user resource escaped isolated profile: '+kind)
    sys.dont_write_bytecode = True

    def audit(event, args):
        if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system'):
            raise RuntimeError('Network/subprocess disabled for this probe')
        if event == 'exec':
            name = str(args[0].co_filename).replace('\\', '/')
            if '/presets/' in name and name.endswith('.py'):
                raise RuntimeError('Python presets must not execute')
        if event == 'open' and not isinstance(args[0], int):
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            path = Path(args[0]).resolve()
            if writing and not path.is_relative_to(folder) and path != journal_path:
                raise RuntimeError('Python write outside probe directory')
    sys.addaudithook(audit)


def registration(report):
    module = importlib.import_module('retarget')
    report['import'] = 'passed'
    # Standard addon preference entry, in memory only; never save preferences.
    entry = bpy.context.preferences.addons.new()
    entry.module = 'retarget'
    module.register()
    report['register'] = 'passed'
    module.unregister()
    bpy.context.preferences.addons.remove(entry)
    report['unregister'] = 'passed'
    report['residual_surface_rna'] = hasattr(bpy.types.WindowManager, 'psr_retarget_align_on_x')
    report['retarget_handlers'] = [f.__module__+'.'+f.__name__
        for name in ('load_post', 'depsgraph_update_post') for f in getattr(bpy.app.handlers, name)
        if f.__module__.startswith('retarget')]


BONES = ('root', 'spine1', 'spine2', 'spine3', 'neck1', 'head')
FIELDS = ('root', 'spine', 'spine1', 'spine2', 'neck', 'head')
FRAMES = [1+i/4 for i in range(237)]


def select_only(ob):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def make_rig(name, prefix):
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(ob)
    select_only(ob)
    bpy.ops.object.mode_set(mode='EDIT')
    parent = None
    for i, name in enumerate(BONES):
        bone = data.edit_bones.new(prefix+name)
        bone.head, bone.tail = (0, 0, i*.2), (0, 0, (i+1)*.2)
        bone.parent = parent
        bone.use_connect = parent is not None
        parent = bone
    bpy.ops.object.mode_set(mode='OBJECT')
    for bone in ob.pose.bones:
        bone.rotation_mode = 'XYZ'
    settings = data.retarget_retarget
    settings.root = prefix+'root'
    for field, name in zip(FIELDS[1:], BONES[1:]):
        setattr(settings.spine, field, prefix+name)
    settings.deform_preset = '--'
    return ob


def snapshot(ob, prefix=''):
    result = []
    for frame in FRAMES:
        bpy.context.scene.frame_set(int(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        result.append({name: [list(row) for row in evaluated.matrix_world @
                              evaluated.pose.bones[prefix+name].matrix] for name in BONES})
    return result


def compare(reference, actual):
    if len(reference) != len(FRAMES) or len(actual) != len(FRAMES):
        raise ValueError('Incomplete matrix samples')
    result = dict(samples=len(FRAMES), bone_matrices=len(FRAMES)*6,
                  max_translation_m=0., max_rotation_deg=0., max_matrix_element=0.)
    for before, after in zip(reference, actual):
        for name in BONES:
            a, b = Matrix(before[name]), Matrix(after[name])
            result['max_translation_m'] = max(result['max_translation_m'], (a.translation-b.translation).length)
            q = a.to_quaternion().rotation_difference(b.to_quaternion())
            angle = math.degrees(2*math.atan2(math.sqrt(q.x*q.x+q.y*q.y+q.z*q.z), abs(q.w)))
            result['max_rotation_deg'] = max(result['max_rotation_deg'], angle)
            result['max_matrix_element'] = max(result['max_matrix_element'],
                max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4)))
    result['passed'] = result['max_translation_m'] <= .0001 and result['max_rotation_deg'] <= .05
    if not result['passed']:
        raise ValueError('World matrix mismatch: '+json.dumps(result))
    return result


def invoke_binding(module, options, report):
    cls = module.operators.ConstrainToArmature
    # Background bpy.ops bypasses invoke(), even with INVOKE_DEFAULT. Delegate
    # the unmodified Python implementation through RNA defaults and methods.
    # This adapter changes neither the class nor the package source.
    class ContextAdapter:
        def __getattr__(self, name):
            value = getattr(cls, name)
            if isinstance(value, property):
                return value.fget(self)
            if isinstance(value, types.FunctionType):
                return types.MethodType(value, self)
            return value

        def report(self, level, message):
            report.setdefault('operator_messages', []).append(dict(level=sorted(level), message=message))

    adapter = ContextAdapter()
    rna = bpy.ops.armature.retarget_constrain_to_armature.get_rna_type()
    for prop in rna.properties:
        if prop.identifier == 'rna_type':
            continue
        if prop.identifier in options:
            setattr(adapter, prop.identifier, options[prop.identifier])
            continue
        if getattr(prop, 'is_array', False):
            setattr(adapter, prop.identifier, tuple(prop.default_array))
        else:
            setattr(adapter, prop.identifier, prop.default)
    for name, value in options.items():
        setattr(adapter, name, value)
    return cls.invoke(adapter, bpy.context, None)


def binding_options():
    return dict(src_preset='--Current--', trg_preset='--Current--',
        same_bone_names=False, bind_by_name=False, loc_constraints=False,
        rot_constraints=True, scal_constraints=False, bind_floating=False,
        fit_target_scale='--', match_transform='None', match_object_transform=False,
        center=False, apply_rotation=False, adjust_location=False,
        advance_setting=False, hand_fk_ik=False, foot_fk_ik=False,
        hand_ik_fk=False, foot_ik_fk=False, align_rest_pose=False, align_leg=False,
        math_look_at=False, copy_IK_roll_hands=False, copy_IK_roll_feet=False,
        fix_foot=False, constrain_root='Default', constraint_policy='nothing',
        play=False, action_range=False, transfer_pose=False, force_dialog=False)


def smoke(folder, report):
    module = importlib.import_module('retarget')
    entry = bpy.context.preferences.addons.new()
    entry.module = 'retarget'
    module.register()
    try:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        bpy.context.preferences.filepaths.file_preview_type = 'NONE'
        bpy.context.preferences.filepaths.save_version = 0
        sc = bpy.context.scene
        sc.frame_start, sc.frame_end, sc.render.fps = 1, 60, 30
        donor = make_rig('Donor', 'donor_')
        receiver = make_rig('Receiver', '')
        report['test'] = dict(frames=60, fps=30, bones=list(BONES), donor_prefix='donor_',
                              spine2_degrees=4, neck1_degrees=3,
                              translation_tolerance_m=.0001, rotation_tolerance_deg=.05)
        for frame in range(1, 61):
            for name, axis, amplitude in [('spine2', 0, 4), ('neck1', 2, 3)]:
                bone = donor.pose.bones['donor_'+name]
                bone.rotation_euler[axis] = math.radians(amplitude)*math.sin(2*math.pi*(frame-1)/60)
                bone.keyframe_insert('rotation_euler', frame=frame, group=bone.name)
        action = donor.animation_data.action
        assert len(action.slots) == 1 and action.slots[0].target_id_type == 'OBJECT'
        channelbag = anim_utils.action_get_channelbag_for_slot(action, donor.animation_data.action_slot)
        for curve in channelbag.fcurves:
            for key in curve.keyframe_points:
                key.interpolation = 'LINEAR'
        sc.frame_set(1)
        select_only(donor)
        receiver.select_set(True)
        binding = binding_options()
        report['binding_options'] = binding
        report['bind_result'] = sorted(invoke_binding(module, binding, report))
        constraints = [(bone.name, c) for bone in receiver.pose.bones for c in bone.constraints]
        assert len(constraints) == 6 and all(c.type == 'COPY_ROTATION' for _, c in constraints)
        report['constraints'] = [dict(bone=name, type=c.type, target=c.target.name,
                                      subtarget=c.subtarget) for name, c in constraints]
        live = snapshot(receiver)
        try:
            compare(live, [live[0]]*len(live))
        except ValueError:
            report['static_negative_control'] = 'caught'
        else:
            raise AssertionError('Static animation unexpectedly passed')
        report['donor_to_live'] = compare(snapshot(donor, 'donor_'), live)
        write_json(folder/'live_matrices.json', live)
        select_only(receiver)
        # The addon's bake operator delegates to this function. Calling it
        # directly avoids the operator's unconditional UI animation_play().
        module.bone_utils.bake_anim(frame_start=1, frame_end=60, only_selected=False,
            bake_bones=True, bake_object=False, use_current_action=False,
            suffix=module.bone_utils.cp_suffix, step=1, interpolation='LINEAR', inverse=False)
        assert receiver.animation_data and receiver.animation_data.action
        baked_action = receiver.animation_data.action
        assert len(baked_action.slots) == 1 and baked_action.slots[0].target_id_type == 'OBJECT'
        report['baked_slots'] = [s.target_id_type for s in baked_action.slots]
        for _, constraint in constraints:
            constraint.mute = True
        receiver.update_tag()
        report['live_to_baked'] = compare(live, snapshot(receiver))
        # Motion is nontrivial; a static/no-op transfer must not pass.
        report['head_excursion_m'] = (Matrix(live[60]['head']).translation-Matrix(live[180]['head']).translation).length
        assert report['head_excursion_m'] > .02
        select_only(receiver)
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'baked.blend'))
        report['save'] = 'passed'
    finally:
        module.unregister()
        bpy.context.preferences.addons.remove(entry)


def reopen(folder, report):
    assert not any(n == 'retarget' or n.startswith('retarget.') for n in sys.modules)
    assert 'retarget' not in bpy.context.preferences.addons
    bpy.ops.wm.open_mainfile(filepath=str(folder/'baked.blend'))
    receiver = bpy.data.objects['Receiver']
    assert all(c.mute for b in receiver.pose.bones for c in b.constraints)
    report['live_to_reopened_without_addon'] = compare(
        json.loads((folder/'live_matrices.json').read_text()), snapshot(receiver))
    report['addon_imported'] = any(n == 'retarget' or n.startswith('retarget.') for n in sys.modules)
    assert not report['addon_imported']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--mode', choices=('registration', 'smoke', 'reopen'), default='registration')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    folder = args.out.resolve()
    report = dict(package_sha256=PACKAGE_HASH, blender_version=list(bpy.app.version),
                  build_hash=bpy.app.build_hash.decode(), errors=[])
    journal = dict(task_id='retarget_smoke', stage=args.mode, active=True,
                   pid=os.getpid(), exitcode=None, utc=datetime.now(timezone.utc).isoformat(),
                   next_step='Inspect '+args.mode+' result')
    write_json(args.journal, journal)
    try:
        package = check_package(folder)
        guard(folder, args.journal.resolve())
        if args.mode == 'reopen':
            reopen(folder, report)
        else:
            sys.path.insert(0, str(package))
            if args.mode == 'registration':
                registration(report)
            else:
                smoke(folder, report)
        journal.update(stage=args.mode+'_complete', exitcode=0)
    except Exception:
        report['errors'].append(traceback.format_exc())
        journal.update(stage='failed', exitcode=2)
        raise
    finally:
        write_json(folder/(args.mode+'.json'), report)
        journal.update(active=False, utc=datetime.now(timezone.utc).isoformat())
        write_json(args.journal, journal)
        print(json.dumps(dict(report=report, journal=journal)), flush=True)


if __name__ == '__main__':
    main()
