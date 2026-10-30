"""Bake small contact crouches over existing NLA without moving actor objects.

Call apply_contact_reactions(D, ACTORS, sc, FPS) after all actor animation and
root-object keys have been built. Times are absolute seconds, frames start at
zero, depth is in metres. No rendering, operators, saves or scene extension.

Each pat is depth*sin(pi*u)**2, 0<u<1. Crouches use smoothstep down,
constant hold and smoothstep up. All overlapping profiles add. A two-bone
position solve preserves each original animated ankle's full world matrix;
it does NOT plant a walking foot at one constant location for the whole clip.
Only the shared hip ancestor and thigh/knee/ankle channels are baked. Other
channels, original actions, strips, phases and actor-object keys are untouched.

Limits: FK/deform rigs with direct thigh->knee->ankle chains, no active
constraints/drivers on corrected bones, ordinary quaternion/Euler rotations,
uniform positive armature world scale, reachable feet. Straight knees use a
continuous pole fallback. Toe bones inherit the preserved ankle transform;
separately constrained/animated toe contacts are not a ground solver.
Validation is at integer frames, not arbitrary render subframes. Corrections
are linear between samples, with three baseline padding frames and 3-frame
NLA edge blends. No active action above NLA or solo/tweak NLA is supported.
Raises on unsupported rigs/unreachable goals instead of stretching the legs.
"""

import math
import re

import bpy
from mathutils import Matrix, Vector


_PREFIX = 'contact_reaction_'
_PADDING = 3


def _finite(value, label, minimum=None):
    value = float(value)
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError(f'contact reaction: invalid {label}: {value}')
    return value


def _bone(arm, stems, side):
    aliases = {stem + suffix for stem in stems
               for suffix in (side, 'left' if side == 'l' else 'right')}
    aliases |= {('left' if side == 'l' else 'right') + stem for stem in stems}
    hits = [b for b in arm.pose.bones
            if re.sub('[^a-z]', '', b.name.lower()) in aliases]
    if len(hits) != 1:
        raise ValueError(f'{arm.name}: ambiguous/missing {stems}/{side}: '
                         f'{[b.name for b in hits]}')
    return hits[0]


def _rig(arm):
    legs = [tuple(_bone(arm, stems, side) for stems in
                  (('thigh', 'hip'), ('knee',), ('ankle',))) for side in ('l', 'r')]
    for thigh, knee, ankle in legs:
        if knee.parent != thigh or ankle.parent != knee:
            raise ValueError(f'{arm.name}: expected direct thigh->knee->ankle chain')
    ancestors = []
    parent = legs[0][0].parent
    while parent:
        ancestors.append(parent)
        parent = parent.parent
    other = set()
    parent = legs[1][0].parent
    while parent:
        other.add(parent.name)
        parent = parent.parent
    pelvis = next((b for b in ancestors if b.name in other), None)
    if pelvis is None:
        raise ValueError(f'{arm.name}: no common pelvis/root ancestor of the thighs')
    corrected = [pelvis] + [b for leg in legs for b in leg]
    # Correction is expressed through unconstrained local transform channels.
    for bone in corrected:
        if bone.rotation_mode == 'AXIS_ANGLE':
            raise ValueError(f'{arm.name}/{bone.name}: axis-angle rotation unsupported')
        if any(not c.mute and c.influence != 0 for c in bone.constraints):
            raise ValueError(f'{arm.name}/{bone.name}: active pose constraints unsupported')
    ad = arm.animation_data
    if ad:
        if ad.action is not None:
            raise ValueError(f'{arm.name}: active action above NLA; finish NLA assembly first')
        if ad.use_tweak_mode or any(t.is_solo for t in ad.nla_tracks):
            raise ValueError(f'{arm.name}: NLA solo/tweak mode unsupported')
        if not ad.use_nla:
            raise ValueError(f'{arm.name}: NLA evaluation is disabled')
        paths = tuple(b.path_from_id() + '.' for b in corrected)
        if any(not f.mute and f.data_path.startswith(paths) for f in ad.drivers):
            raise ValueError(f'{arm.name}: drivers on corrected bones unsupported')
        if any(t.name.startswith(_PREFIX) for t in ad.nla_tracks):
            raise ValueError(f'{arm.name}: contact reactions already applied')
    return pelvis.name, [tuple(b.name for b in leg) for leg in legs], corrected


def _windows(pulses, fps, last):
    windows = []
    for pulse in sorted(pulses, key=lambda p: p[0]):
        start, duration, depth = pulse[:3]
        left = max(0, math.floor(start * fps) - _PADDING)
        right = min(last, math.ceil((start + duration) * fps) + _PADDING)
        if windows and left <= windows[-1][1] + 1:
            windows[-1] = (windows[-1][0], max(right, windows[-1][1]))
        else:
            windows.append((left, right))
    return windows


def _smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def _drop(pulses, time):
    result = 0.0
    for pulse in pulses:
        start, duration, depth = pulse[:3]
        elapsed = time - start
        if not 0 < elapsed < duration:
            continue
        if len(pulse) == 3:
            weight = math.sin(math.pi * elapsed / duration) ** 2
        else:
            _, _, _, down, hold, up = pulse
            if elapsed < down:
                weight = _smoothstep(elapsed / down)
            elif elapsed <= down + hold:
                weight = 1.0
            else:
                weight = _smoothstep((duration - elapsed) / up)
        result += depth * weight
    return _finite(result, 'summed depth', 0)


def _add_pulse(grouped, who, pulse, fps, last):
    """Validate shared scene bounds before either event kind reaches the baker."""
    start, duration, depth = pulse[:3]
    end = _finite(start + duration, 'reaction end')
    first_frame = _finite(start * fps, 'reaction start frame')
    last_frame = _finite(end * fps, 'reaction end frame')
    if start < 0 or last_frame > last + 1e-6:
        raise ValueError(f'{who}: reaction crosses scene bounds; duration is not extended')
    if first_frame < _PADDING or last_frame > last - _PADDING:
        raise ValueError(f'{who}: reaction needs 3 baseline padding frames within scene')
    grouped.setdefault(who, []).append(pulse)


def _uniform_world(matrix, label):
    axes = [matrix.to_3x3().col[i] for i in range(3)]
    lengths = [v.length for v in axes]
    scale = max(lengths)
    if (min(lengths) <= 1e-10 or matrix.to_3x3().determinant() <= 0
            or max(lengths) - min(lengths) > scale * 1e-5
            or any(abs(axes[i].dot(axes[j])) > scale * scale * 1e-5
                   for i in range(3) for j in range(i))):
        raise ValueError(f'{label}: nonuniform/reflected/sheared world scale unsupported')


def _redirect(matrix, old_direction, new_direction, position):
    rotation = old_direction.rotation_difference(new_direction).to_matrix().to_4x4()
    result = rotation @ matrix
    result.translation = position
    return result


def _solve_leg(base, desired, leg, drop, previous_pole, forward):
    thigh, knee, ankle = leg
    h0, k0, a0 = (base[n].translation for n in leg)
    hip = h0 + drop
    target = a0.copy()
    upper, lower = (k0 - h0).length, (a0 - k0).length
    axis = target - hip
    distance = axis.length
    tolerance = max(upper + lower, 1.0) * 1e-7
    if (min(upper, lower, distance) <= tolerance
            or distance > upper + lower + tolerance
            or distance < abs(upper - lower) - tolerance):
        raise ValueError(f'{thigh}: ankle target unreachable at requested crouch depth')
    direction = axis.normalized()
    original_axis = a0 - h0
    if original_axis.length <= tolerance:
        raise ValueError(f'{thigh}: degenerate original leg')
    original_axis.normalize()
    pole = k0 - h0
    pole -= original_axis * pole.dot(original_axis)
    if pole.length <= tolerance * 10:
        pole = previous_pole.copy() if previous_pole is not None else forward.copy()
    pole -= direction * pole.dot(direction)
    if pole.length <= tolerance:
        # Deterministic secondary direction for a fully straight, vertical leg.
        pole = min((Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))),
                   key=lambda v: abs(v.dot(direction)))
        pole -= direction * pole.dot(direction)
    pole.normalize()
    if previous_pole is not None and pole.dot(previous_pole) < 0:
        pole.negate()
    along = (upper * upper - lower * lower + distance * distance) / (2 * distance)
    height = math.sqrt(max(0.0, upper * upper - along * along))
    joint = hip + direction * along + pole * height
    q_upper = (k0 - h0).rotation_difference(joint - hip)
    desired[thigh] = _redirect(base[thigh], k0 - h0, joint - hip, hip)
    # Transport the knee's twist with the thigh before aiming its lower segment.
    carried = q_upper.to_matrix().to_4x4() @ base[knee]
    desired[knee] = _redirect(carried, q_upper @ (a0 - k0), target - joint, joint)
    desired[ankle] = base[ankle].copy()  # full position, orientation AND scale
    return pole


def _basis(bone, matrix, parent_matrix):
    kw = dict(invert=True)
    if bone.parent:
        kw.update(parent_matrix=parent_matrix,
                  parent_matrix_local=bone.parent.bone.matrix_local)
    return bone.bone.convert_local_to_pose(matrix, bone.bone.matrix_local, **kw)


def _sample(arm, sc, fps, pulses, windows, pelvis, legs, corrected, metres_per_unit):
    """Read evaluated source poses before attaching ANY correction action."""
    samples = []
    poles = [None, None]
    shifted = {b.name for b in arm.pose.bones
               if b.name == pelvis or pelvis in {p.name for p in b.parent_recursive}}
    for left, right in windows:
        frames = []
        for frame in range(left, right + 1):
            sc.frame_set(frame)
            evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mw = evaluated.matrix_world.copy()
            _uniform_world(mw, arm.name)
            inverse = mw.inverted()
            base = {b.name: mw @ b.matrix for b in evaluated.pose.bones}
            desired = {n: m.copy() for n, m in base.items()}
            depth = _drop(pulses, frame / fps) / metres_per_unit
            if depth > 1e-12:
                delta = Vector((0, 0, -depth))
                for name in shifted:
                    desired[name].translation += delta
                forward = mw.to_3x3() @ Vector((0, -1, 0))
                for i, leg in enumerate(legs):
                    poles[i] = _solve_leg(base, desired, leg, delta, poles[i], forward)
            local = {}
            for bone in corrected:
                parent = inverse @ desired[bone.parent.name] if bone.parent else None
                local[bone.name] = _basis(bone, inverse @ desired[bone.name], parent)
            frames.append(dict(frame=frame, basis=local,
                               feet={leg[2]: base[leg[2]].copy() for leg in legs}))
        samples.append((left, right, frames))
    return samples


def _curves(action):
    # Layered actions (Blender 4.4+) and older legacy actions.
    if hasattr(action, 'layers') and len(action.layers):
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from action.fcurves


def _action(arm, corrected, frames, name, sc):
    """Key a temporary scene-linked proxy without reassigning source animation."""
    proxy = bpy.data.objects.new(name + '_bake', arm.data)
    action = None
    try:
        sc.collection.objects.link(proxy)
        proxy.hide_render = True
        # Keep viewport evaluation enabled: an unlinked/excluded armature may
        # have no Pose in Blender 5.2 until the dependency graph is updated.
        bpy.context.view_layer.update()
        if proxy.pose is None:
            raise RuntimeError(f'{name}: temporary armature pose was not initialized')
        previous_q, previous_euler = {}, {}
        for bone in corrected:
            proxy.pose.bones[bone.name].rotation_mode = bone.rotation_mode
        for sample in frames:
            for bone in corrected:
                pb = proxy.pose.bones[bone.name]
                matrix = sample['basis'][bone.name]
                location, rotation, scale = matrix.decompose()
                if bone.name in previous_q and rotation.dot(previous_q[bone.name]) < 0:
                    rotation.negate()
                previous_q[bone.name] = rotation.copy()
                rebuilt = Matrix.LocRotScale(location, rotation, scale)
                if max(abs(matrix[i][j] - rebuilt[i][j])
                       for i in range(4) for j in range(4)) > 1e-5:
                    raise ValueError(f'{arm.name}/{bone.name}: sheared local pose cannot be baked')
                pb.location, pb.scale = location, scale
                if pb.rotation_mode == 'QUATERNION':
                    pb.rotation_quaternion = rotation
                    rotation_path = 'rotation_quaternion'
                else:
                    prior = previous_euler.get(bone.name)
                    euler = (rotation.to_euler(pb.rotation_mode, prior) if prior is not None
                             else rotation.to_euler(pb.rotation_mode))
                    previous_euler[bone.name] = euler.copy()
                    pb.rotation_euler = euler
                    rotation_path = 'rotation_euler'
                for path in ('location', rotation_path, 'scale'):
                    pb.keyframe_insert(path, frame=sample['frame'], group=bone.name)
        action = proxy.animation_data.action
        action.name = name
        for curve in _curves(action):
            for key in curve.keyframe_points:
                key.interpolation = 'LINEAR'
        return action
    except Exception:
        # keyframe_insert may have created the action before an exception.
        action = proxy.animation_data.action if proxy.animation_data else action
        if proxy.animation_data:
            proxy.animation_data_clear()
        if action and action.users == 0:
            bpy.data.actions.remove(action)
        raise
    finally:
        bpy.data.objects.remove(proxy, do_unlink=True)


def _validate(arm, sc, samples, metres_per_unit):
    max_position = max_angle = 0.0
    for left, right, frames in samples:
        for sample in frames:
            sc.frame_set(sample['frame'])
            evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            for name, expected in sample['feet'].items():
                actual = evaluated.matrix_world @ evaluated.pose.bones[name].matrix
                position = (actual.translation - expected.translation).length * metres_per_unit
                angle = actual.to_quaternion().rotation_difference(expected.to_quaternion()).angle
                angle = min(abs(angle), abs(2 * math.pi - angle))
                scale_error = (actual.to_scale() - expected.to_scale()).length
                max_position, max_angle = max(max_position, position), max(max_angle, angle)
                if position > .0001 or angle > .001 or scale_error > .0001:
                    raise ValueError(f'{arm.name}: frame {sample["frame"]} {name}: '
                                     f'foot drift {position:.6g}m/{angle:.6g}rad '
                                     f'(scale error {scale_error:.6g})')
    return max_position, max_angle


def apply_contact_reactions(D, ACTORS, sc, FPS):
    """Return per-actor diagnostics; on failure roll back only this call's data.

    D['contact_reactions']: [{who, at, pats, pat_dur, depth}], where pat offsets
    are relative to at. D['crouches']: [{who, at, depth, down, hold, up}], with
    positive depth/down/up and nonnegative hold. Both lists share one additive
    bake per actor. D['frames'] bounds the bake, not scene.frame_end (which may
    still be Blender's default when this helper is called).
    """
    events = D.get('contact_reactions') or []
    crouches = D.get('crouches') or []
    if not events and not crouches:
        return []
    fps = _finite(FPS, 'FPS', 1e-9)
    last = int(D['frames']) - 1
    if last < 1:
        raise ValueError('contact reaction: scene needs at least two frames')
    unit = _finite(sc.unit_settings.scale_length, 'metres per unit', 1e-12)
    grouped = {}
    for event in events:
        who = event['who']
        if who not in ACTORS:
            raise ValueError(f'contact reaction: unknown actor {who!r}')
        at = _finite(event['at'], 'at')
        duration = _finite(event.get('pat_dur', .6), 'pat_dur', 1e-9)
        depth = _finite(event['depth'], 'depth', 0)
        for pat in event.get('pats', (.15, .8)):
            start = _finite(at + _finite(pat, 'pat offset'), 'pat start')
            if depth == 0:
                continue
            _add_pulse(grouped, who, (start, duration, depth), fps, last)
    for event in crouches:
        who = event['who']
        if who not in ACTORS:
            raise ValueError(f'contact reaction: unknown actor {who!r}')
        start = _finite(event['at'], 'crouch at')
        depth = _finite(event['depth'], 'crouch depth', 0)
        down = _finite(event['down'], 'crouch down', 0)
        hold = _finite(event['hold'], 'crouch hold', 0)
        up = _finite(event['up'], 'crouch up', 0)
        if depth <= 0 or down <= 0 or up <= 0:
            raise ValueError('crouch depth, down and up must be positive')
        duration = _finite(down + hold + up, 'crouch duration')
        _add_pulse(grouped, who, (start, duration, depth, down, hold, up), fps, last)
    original_frame, original_subframe = sc.frame_current, sc.frame_subframe
    created_tracks, created_actions = [], []
    results = []
    try:
        # Stage all actors' evaluated source/corrected poses before adding tracks.
        staged = []
        seen = set()
        for who, pulses in grouped.items():
            arm = ACTORS[who]['arm']
            if arm.type != 'ARMATURE' or arm in seen:
                raise ValueError(f'{who}: expected a distinct armature per actor')
            seen.add(arm)
            pelvis, legs, corrected = _rig(arm)
            windows = _windows(pulses, fps, last)
            samples = _sample(arm, sc, fps, pulses, windows, pelvis, legs, corrected, unit)
            staged.append((who, arm, pelvis, corrected, samples))
        for who, arm, pelvis, corrected, samples in staged:
            ad = arm.animation_data_create()
            track = (ad.nla_tracks.new(prev=ad.nla_tracks[-1]) if len(ad.nla_tracks)
                     else ad.nla_tracks.new())
            track.name = _PREFIX + who
            created_tracks.append((ad, track))
            for left, right, frames in samples:
                action = _action(arm, corrected, frames, f'{_PREFIX}{who}_{left}_{right}', sc)
                created_actions.append(action)
                strip = track.strips.new(action.name, left, action)
                if hasattr(strip, 'action_slot') and hasattr(action, 'slots') and len(action.slots):
                    strip.action_slot = action.slots[0]
                strip.action_frame_start, strip.action_frame_end = left, right
                strip.frame_start, strip.frame_end = left, right
                strip.repeat = 1.0
                strip.scale = 1.0
                strip.blend_type = 'REPLACE'
                strip.extrapolation = 'NOTHING'
                strip.use_auto_blend = False
                strip.blend_in = strip.blend_out = _PADDING
                strip.influence = 1.0
                strip.use_animated_influence = False
            position, angle = _validate(arm, sc, samples, unit)
            result = dict(who=who, pelvis=pelvis,
                          windows=[(a, b) for a, b, _ in samples],
                          keyed_bones=[b.name for b in corrected],
                          max_foot_error_m=position, max_foot_error_rad=angle)
            results.append(result)
            print(f'CONTACT_REACTION {who}: {result["windows"]}, pelvis={pelvis}, '
                  f'foot error={position:.6g}m/{angle:.6g}rad', flush=True)
        return results
    except Exception:
        for ad, track in reversed(created_tracks):
            ad.nla_tracks.remove(track)
        for action in created_actions:
            if action.users == 0:
                bpy.data.actions.remove(action)
        raise
    finally:
        sc.frame_set(original_frame, subframe=original_subframe)
