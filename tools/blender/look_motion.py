"""Small FK look overlays and pure eye-lead planning (not universal head aim).

Caller hooks, deliberately not installed by this module:
  D = plan_looks(D)                 # before face.animate / actor face imports
  apply_looks(D, ACTORS, sc, FPS)   # after ALL body NLA/pose/root baking

Positive yaw is world RZ+, toward actor-left (matching the turn DSL).
Positive pitch looks up about negative actor-local X. The total rotation
is shared 30% neck / 70% head.
If no named neck exists (Lina), 100% goes to head; spine is never substituted.
Angles are bounded to yaw +/-35 and pitch +/-20 degrees. Eye FACS coordinates
use -yaw/35 and pitch/20: Lina's eyeRight moves toward negative root-local X.
This sign mapping is not an optical target solve or counter-rotation.
Overlaps blend in input order, with the last active look taking priority.

Only neck/head local channels are baked in new REPLACE NLA windows. Source
actions, object/root keys, phase, scene duration and input dictionaries are not
changed. Active main-rig constraints, driven corrected bones, active actions
above NLA, solo/tweak NLA, nonuniform/reflected scales and missing head
are rejected. Integer-frame validation is not a subframe or geometry test.
Eye geometry still needs visual QA: gaze is added after face.unfold.
"""

import copy
import math
import re

from gaze import _number, _smoothstep, prepare_gazes


_PREFIX = 'look_motion_'


def _events(D, known_actors=None):
    events = D.get('looks')
    if events is None:
        return []
    if not isinstance(events, (list, tuple)):
        raise ValueError('looks must be a list of objects')
    if not events:
        return []
    actors = D.get('actors') if known_actors is None else known_actors
    if actors is None:
        raise ValueError('looks require an actor mapping for validation')
    limit = None
    if 'dur' in D:
        limit = _number(D['dur'], 'scene duration')
        if limit <= 0:
            raise ValueError('look scene duration must be positive')
    if 'frames' in D and 'fps' in D:
        count, rate = D['frames'], _number(D['fps'], 'scene FPS')
        if isinstance(count, bool) or not isinstance(count, int) or count < 2 or rate <= 0:
            raise ValueError('looks require >=2 scene frames and positive FPS')
        last = (count - 1) / rate
        limit = last if limit is None else min(last, limit)
    result = []
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f'look {i} must be an object')
        who = event.get('who')
        if not isinstance(who, str) or not who or who not in actors:
            raise ValueError(f'look {i}: unknown actor {who!r}')
        try:
            start, end = (_number(event[k], 'look ' + k) for k in ('start', 'end'))
            yaw, pitch = (_number(event[k], 'look ' + k) for k in ('yaw_deg', 'pitch_deg'))
        except KeyError as exc:
            raise ValueError(f'look {i}: missing {exc.args[0]}') from exc
        attack = _number(event.get('attack', .35), 'look attack')
        release = _number(event.get('release', .4), 'look release')
        lead = _number(event.get('eye_lead', .12), 'look eye_lead')
        if start < 0 or end <= start or attack <= 0 or release <= 0 or lead < 0:
            raise ValueError(f'look {i}: invalid window/attack/release/eye_lead')
        if abs(yaw) > 35 or abs(pitch) > 20:
            raise ValueError(f'look {i}: yaw limited to +/-35, pitch to +/-20 degrees')
        if limit is not None and end > limit + 1e-9:
            raise ValueError(f'look {i}: window exceeds existing scene duration')
        result.append(dict(who=who, start=start, end=end, yaw_deg=yaw, pitch_deg=pitch,
                           attack=attack, release=release, eye_lead=lead))
    return result


def plan_looks(D):
    """Pure/idempotent: copy only when the planned gaze list actually changes.

    Existing explicit gazes retain order; derived look gazes are appended and
    thus have priority. Eye ramps use the existing gaze defaults .12/.18 s.
    Only records marked _generated_by='look_motion' belong to this planner.
    Replanning replaces those records, including removing them without looks.
    """
    events = _events(D)
    existing = D.get('gazes') or []
    if not isinstance(existing, (list, tuple)):
        if events:
            prepare_gazes(existing, events[0]['who'], D['actors'])
        return D  # do not change validation/behavior of a no-look legacy scene
    gazes = [g for g in existing
             if not (isinstance(g, dict) and g.get('_generated_by') == 'look_motion')]
    if not events and len(gazes) == len(existing):
        return D
    for event in events:
        gazes.append(dict(who=event['who'], start=max(0., event['start'] - event['eye_lead']),
                          end=event['end'], x=max(-1., min(1., -event['yaw_deg'] / 35.)),
                          y=max(-1., min(1., event['pitch_deg'] / 20.)), attack=.12, release=.18,
                          _generated_by='look_motion'))
    # Validate the complete gaze list even if the first actor has no head mesh.
    if events:
        prepare_gazes(gazes, events[0]['who'], D['actors'])
    if gazes == existing:
        return D
    result = copy.deepcopy(D)
    result['gazes'] = copy.deepcopy(gazes)
    return result


def _angles(events, time):
    yaw = pitch = 0.
    for event in events:
        if not event['start'] < time < event['end']:
            continue
        weight = (_smoothstep((time - event['start']) / event['attack']) *
                  _smoothstep((event['end'] - time) / event['release']))
        yaw += (event['yaw_deg'] - yaw) * weight
        pitch += (event['pitch_deg'] - pitch) * weight
    return yaw, pitch


def _rig(actor):
    arm, root = actor['arm'], actor['root']
    if arm.type != 'ARMATURE':
        raise ValueError('look actor must have an armature')
    hint = actor.get('info', {}).get('head_bone')
    head = arm.pose.bones.get(hint) if hint else None
    if head is None:
        candidates = [b for b in arm.pose.bones if re.fullmatch(r'head(?:_?\d+)?', b.name, re.I)]
        if len(candidates) != 1:
            raise ValueError(f'{arm.name}: ambiguous/missing head bone')
        head = candidates[0]
    neck = next((b for b in head.parent_recursive
                 if re.fullmatch(r'neck(?:_?\d+)?', b.name, re.I)), None)
    corrected = [neck, head] if neck is not None else [head]
    for obj in (root, arm):
        if any(not c.mute and c.influence != 0 for c in obj.constraints):
            raise ValueError(f'{arm.name}: constrained actor objects unsupported')
    if any(not c.mute and c.influence != 0 for b in arm.pose.bones for c in b.constraints):
        raise ValueError(f'{arm.name}: constrained main rig unsupported')
    ad = arm.animation_data
    if ad:
        if ad.action or ad.use_tweak_mode or not ad.use_nla or any(t.is_solo for t in ad.nla_tracks):
            raise ValueError(f'{arm.name}: need ordinary NLA without active action/solo/tweak')
        if any(t.name.startswith(_PREFIX) for t in ad.nla_tracks):
            raise ValueError(f'{arm.name}: look overlay already applied')
        paths = tuple(b.path_from_id() + '.' for b in corrected)
        if any(not fc.mute and fc.data_path.startswith(paths) for fc in ad.drivers):
            raise ValueError(f'{arm.name}: driven neck/head unsupported')
    if any(b.rotation_mode == 'AXIS_ANGLE' for b in corrected):
        raise ValueError(f'{arm.name}: axis-angle corrected bones unsupported')
    return arm, root, corrected


def apply_looks(D, ACTORS, sc, FPS):
    """Bake/validate only new neck/head tracks; return diagnostics or roll back."""
    events = _events(D, ACTORS)
    if not events:
        return []
    # Lazy imports keep plan_looks and scalar tests usable in ordinary Python.
    import bpy
    from mathutils import Matrix, Quaternion, Vector
    from contact_reaction import _action, _basis, _uniform_world, _windows

    fps = _number(FPS, 'look FPS')
    count = D.get('frames')
    if fps <= 0 or isinstance(count, bool) or not isinstance(count, int) or count < 2:
        raise ValueError('look bake requires positive FPS and >=2 frames')
    if 'fps' in D and abs(_number(D['fps'], 'scene FPS') - fps) > 1e-9:
        raise ValueError('look bake FPS differs from scene FPS')
    if any(e['end'] * fps > count - 1 + 1e-8 for e in events):
        raise ValueError('look bake would exceed scene bounds')
    grouped = {}
    for event in events:
        grouped.setdefault(event['who'], []).append(event)
    frame, subframe = sc.frame_current, sc.frame_subframe
    tracks, actions, results = [], [], []

    def matrix_error(a, b):
        return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))

    try:
        staged, seen = [], set()
        for who, look_events in grouped.items():
            arm, root, bones = _rig(ACTORS[who])
            if arm in seen:
                raise ValueError('look actors must have distinct armatures')
            seen.add(arm)
            head = bones[-1]
            neck = bones[0] if len(bones) == 2 else None
            descendants = {b.name: [b, *b.children_recursive] for b in bones}
            moving = {b.name for b in descendants[bones[0].name]}
            windows = _windows([(e['start'], e['end'] - e['start'], 0.)
                                for e in look_events], fps, count - 1)
            samples = []
            for left, right in windows:
                frames = []
                for f in range(left, right + 1):
                    sc.frame_set(f)
                    graph = bpy.context.evaluated_depsgraph_get()
                    evaluated = arm.evaluated_get(graph)
                    rw = root.evaluated_get(graph).matrix_world.copy()
                    mw = evaluated.matrix_world.copy()
                    _uniform_world(mw, arm.name)
                    _uniform_world(rw, root.name)
                    inverse = mw.inverted()
                    base = {b.name: mw @ b.matrix for b in evaluated.pose.bones}
                    desired = {n: m.copy() for n, m in base.items()}
                    yaw, pitch = _angles(look_events, f / fps)
                    actor_x = (rw.to_3x3() @ Vector((1, 0, 0))).normalized()
                    total = (Quaternion(Vector((0, 0, 1)), math.radians(yaw)) @
                             Quaternion(actor_x, -math.radians(pitch)))
                    shares = ((neck, .3), (head, .7)) if neck is not None else ((head, 1.),)
                    for bone, share in shares:
                        pivot = desired[bone.name].translation.copy()
                        rotation = Quaternion().slerp(total, share).to_matrix().to_4x4()
                        transform = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
                        for child in descendants[bone.name]:
                            desired[child.name] = transform @ desired[child.name]
                    basis = {}
                    for bone in bones:
                        parent = inverse @ desired[bone.parent.name] if bone.parent else None
                        basis[bone.name] = _basis(bone, inverse @ desired[bone.name], parent)
                    frames.append(dict(frame=f, basis=basis, root_world=rw, arm_world=mw,
                                       expected={n: m for n, m in desired.items()
                                                 if n not in moving or n in {b.name for b in bones}}))
                samples.append((left, right, frames))
            staged.append((who, arm, root, bones, samples))
        for who, arm, root, bones, samples in staged:
            ad = arm.animation_data_create()
            track = (ad.nla_tracks.new(prev=ad.nla_tracks[-1]) if len(ad.nla_tracks)
                     else ad.nla_tracks.new())
            track.name = _PREFIX + who
            tracks.append((ad, track))
            for left, right, frames in samples:
                action = _action(arm, bones, frames, f'{_PREFIX}{who}_{left}_{right}', sc)
                actions.append(action)
                strip = track.strips.new(action.name, left, action)
                if hasattr(strip, 'action_slot') and len(action.slots):
                    strip.action_slot = action.slots[0]
                strip.action_frame_start, strip.action_frame_end = left, right
                strip.frame_start, strip.frame_end = left, right
                strip.scale, strip.repeat = 1., 1.
                strip.blend_type, strip.extrapolation = 'REPLACE', 'NOTHING'
                strip.use_auto_blend = False
                # The action already has smooth envelopes and baseline padding.
                strip.blend_in = strip.blend_out = 0.
                strip.influence, strip.use_animated_influence = 1., False
            max_pose = max_world = 0.
            for _, _, frames in samples:
                for sample in frames:
                    sc.frame_set(sample['frame'])
                    graph = bpy.context.evaluated_depsgraph_get()
                    evaluated = arm.evaluated_get(graph)
                    rw = root.evaluated_get(graph).matrix_world
                    max_world = max(max_world, matrix_error(rw, sample['root_world']),
                                    matrix_error(evaluated.matrix_world, sample['arm_world']))
                    for name, expected in sample['expected'].items():
                        actual = evaluated.matrix_world @ evaluated.pose.bones[name].matrix
                        max_pose = max(max_pose, matrix_error(actual, expected))
                    if max_world > 1e-5 or max_pose > 2e-4:
                        raise ValueError(f'{who}: look validation failed at {sample["frame"]}: '
                                         f'world={max_world:.6g}, pose={max_pose:.6g}')
            has_neck = len(bones) == 2
            result = dict(who=who, bones=[b.name for b in bones],
                          neck_share=.3 if has_neck else 0., head_share=.7 if has_neck else 1.,
                          head_only_fallback=not has_neck,
                          windows=[(a, b) for a, b, _ in samples],
                          max_world_matrix_error=max_world, max_pose_matrix_error=max_pose)
            results.append(result)
            print('LOOK_MOTION', result, flush=True)
        return results
    except Exception:
        for ad, track in reversed(tracks):
            ad.nla_tracks.remove(track)
        for action in actions:
            if action.users == 0:
                bpy.data.actions.remove(action)
        raise
    finally:
        sc.frame_set(frame, subframe=subframe)
