"""Small airborne leg tuck over an existing ballistic actor-root trajectory.

Applied before contact reactions so their padding samples include this pose.
World-space ankle goals are checked at all baked frames and exact events.
Does not solve balance, cloth contact, arm swing or terrain.
"""
import math

import bpy
from mathutils import Matrix, Vector

from contact_reaction import _rig, _action, _basis, _solve_leg, _uniform_world, _smoothstep


def _frame(scene, frame):
    whole = math.floor(frame)
    scene.frame_set(whole, subframe=frame - whole)


def apply_airborne_poses(D, actors, scene, fps):
    if not D.get('jump_plan'):
        return []
    frame, subframe = scene.frame_current, scene.frame_subframe
    tracks, actions = [], []
    results = []
    unit = scene.unit_settings.scale_length
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError('airborne pose needs positive scene unit scale')
    # Reject unsupported track overlap before evaluating poses or creating data.
    # Group by actual armature, so actor aliases cannot bypass this guard.
    windows, prepared = {}, []
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('airborne pose needs positive finite fps')
    for index, plan in enumerate(D['jump_plan']):
        who = plan['who']
        arm = actors[who]['arm']
        start = plan['prep_start'] * fps
        end = plan['recover'] * fps
        if not all(math.isfinite(v) for v in (start, end)) or start > end:
            raise ValueError(f'{who}: invalid airborne pose window')
        left = max(0, math.floor(start) - 3)
        right = min(D['frames'] - 1, math.ceil(end) + 3)
        if left >= right:
            raise ValueError(f'{who}: airborne pose window is outside scene bounds')
        for previous_left, previous_right in windows.setdefault(arm, []):
            if left <= previous_right and right >= previous_left:
                raise ValueError(f'{who}: overlapping expanded airborne windows '
                                 f'[{left}, {right}] and [{previous_left}, {previous_right}]; '
                                 'blending multiple jumps is not supported')
        windows[arm].append((left, right))
        prepared.append((index, plan, left, right))
    try:
        staged = []
        for index, plan, left, right in prepared:
            who = plan['who']
            arm, root = actors[who]['arm'], actors[who]['root']
            if any(t.name.startswith('airborne_pose_') for t in arm.animation_data.nla_tracks):
                raise ValueError(f'{who}: airborne poses already applied')
            clearance = any(o.type == 'MESH' and 'leftweapon' in o.name.lower() for o in root.children_recursive)
            pelvis, legs, corrected, shoulders = _rig(arm, ['L'] if clearance else [])
            start, end = plan['takeoff'] * fps, plan['land'] * fps
            events = [start, plan['apex'] * fps, end, plan['prep_start'] * fps, plan['recover'] * fps]
            frames = sorted(set([float(f) for f in range(left, right + 1)] + events))
            _frame(scene, start)
            length = min(sum((arm.matrix_world @ arm.pose.bones[a].matrix.translation
                              - arm.matrix_world @ arm.pose.bones[b].matrix.translation).length
                             for a, b in zip(leg, leg[1:])) for leg in legs) * unit
            requested = (D.get('jumps') or [])[index].get('tuck', min(.16, .18 * length))
            if isinstance(requested, bool) or not isinstance(requested, (int, float)) or not math.isfinite(requested) or not 0 <= requested <= .4:
                raise ValueError('jump tuck must be finite metres in [0, .4]')
            poles = [None, None]
            samples = []
            for f in frames:
                _frame(scene, f)
                evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
                mw = evaluated.matrix_world.copy()
                _uniform_world(mw, arm.name)
                inv = mw.inverted()
                base = {b.name: mw @ b.matrix for b in evaluated.pose.bones}
                desired = {n: m.copy() for n, m in base.items()}
                u = (f / fps - plan['takeoff']) / plan['flight']
                weight = math.sin(math.pi * u) ** 2 if 0 < u < 1 else 0.0
                forward = root.matrix_world.to_quaternion() @ Vector((0, -1, 0))
                side = root.matrix_world.to_quaternion() @ Vector((1, 0, 0))
                feet = {}
                for i, leg in enumerate(legs):
                    target = base[leg[2]].copy()
                    target.translation += (Vector((0, 0, requested)) - forward * min(.05, requested * .3)) * weight / unit
                    position = target.translation.copy()
                    target = Matrix.Translation(position) @ Matrix.Rotation(math.radians(8) * weight, 4, side) @ Matrix.Translation(-position) @ target
                    if weight > 1e-12:
                        poles[i] = _solve_leg(base, desired, leg, Vector(), poles[i], forward, target)
                    feet[leg[2]] = target
                if clearance:
                    time = f / fps
                    prep_duration = (plan['takeoff'] - plan['prep_start']) * .6
                    park = _smoothstep((time - plan['prep_start']) / max(.05, prep_duration))
                    release = max(plan['land'], plan['recover'] - .25)
                    park *= 1 - _smoothstep((time - release) / max(.05, plan['recover'] - release))
                    name = shoulders['L']
                    pivot = desired[name].translation
                    rotation = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(18) * park, 4, forward) @ Matrix.Translation(-pivot)
                    for bone in [arm.pose.bones[name], *arm.pose.bones[name].children_recursive]:
                        desired[bone.name] = rotation @ desired[bone.name]
                basis = {}
                for b in corrected:
                    parent = inv @ desired[b.parent.name] if b.parent else None
                    basis[b.name] = _basis(b, inv @ desired[b.name], parent)
                samples.append(dict(frame=f, basis=basis, feet=feet))
            staged.append((who, index, arm, corrected, left, right, samples, requested))
        for who, index, arm, corrected, left, right, samples, requested in staged:
            ad = arm.animation_data
            track = ad.nla_tracks.new(prev=ad.nla_tracks[-1]) if len(ad.nla_tracks) else ad.nla_tracks.new()
            track.name = f'airborne_pose_{who}_{index}'
            tracks.append((ad, track))
            action = _action(arm, corrected, samples, track.name, scene)
            actions.append(action)
            strip = track.strips.new(action.name, left, action)
            strip.action_slot = action.slots[0]
            strip.action_frame_start, strip.action_frame_end = left, right
            strip.frame_start, strip.frame_end = left, right
            strip.extrapolation = 'NOTHING'
            strip.blend_type = 'REPLACE'
            strip.use_auto_blend = False
            strip.blend_in = strip.blend_out = 3
            error = angle_error = 0.0
            for sample in samples:
                _frame(scene, sample['frame'])
                evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
                for name, expected in sample['feet'].items():
                    actual = evaluated.matrix_world @ evaluated.pose.bones[name].matrix
                    position_error = (actual.translation - expected.translation).length * unit
                    angle = actual.to_quaternion().rotation_difference(expected.to_quaternion()).angle
                    angle = min(abs(angle), abs(2 * math.pi - angle))
                    error, angle_error = max(error, position_error), max(angle_error, angle)
                    if position_error > .0001 or angle > .001:
                        raise ValueError(f'{who}: airborne foot goal missed at {sample["frame"]}: {position_error}m/{angle}rad')
            result = dict(who=who, frames=[left, right], tuck_m=requested, max_ankle_error_m=error, max_ankle_error_rad=angle_error)
            results.append(result)
            print('AIRBORNE_POSE', result, flush=True)
        return results
    except Exception:
        for ad, track in reversed(tracks):
            ad.nla_tracks.remove(track)
        for action in actions:
            if action.users == 0:
                bpy.data.actions.remove(action)
        raise
    finally:
        scene.frame_set(frame, subframe=subframe)
