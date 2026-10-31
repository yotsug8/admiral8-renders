"""Fixed-support lateral weight-shift study, not a mass/balance simulation.

apply_weight_shifts(D, actors, scene, fps) consumes optional D.weight_shifts:
[{who, start, prepare=.4, move=.6, hold=.4, recover=.8, settle=.4,
  side_fraction=.1, depth_fraction=.05, lean_deg=5, arm_clearance={}}].
Times are seconds, zero-based frames=fps*time. End is start+all five phases.
Prepare lowers the pelvis; move adds lateral displacement/torso lean; hold
keeps both; recover removes lateral displacement/lean; settle removes depth.
Smoothstep envelopes have zero endpoint speed. Durations except hold must
be positive. Three whole baseline frames are required at each scene edge.

Positive side_fraction means actor-left (root-local -X); negative means
right. Magnitude <=.2, measured against ankle spacing projected on this
horizontal side axis. depth_fraction is [0,.1] of the shorter two-segment
leg. lean_deg is [0,10], towards the selected side; zero disables torso
requirements. arm_clearance maps optional L/R to [0,30] degrees, follows
the crouch envelope, and requires inherited shoulder-child rotations.

Only stationary sources are supported: root/pelvis and full ankle world
matrices must stay within 20 micrometres / .0001 rad / .00001 scale of
their start pose at dense samples and independent midpoints. Feet are fixed
to start-pose WORLD matrices, never to animated per-frame ankle positions.
No root keys, original actions or D values are changed. The public call
includes scene-local skin repair for weight_shifts only; on failure it
restores original mesh datablocks and flag presence/values, and removes
new orphan meshes along with the bake's actions/tracks. Same-actor
crouches/contact_reactions/jumps/looks and overlapping padded windows are
rejected. Existing correction tracks are unsupported. All sampling precedes
new NLA tracks. Bake uses 4 points/frame plus exact events, independent
midpoint witnesses, full-influence REPLACE with baseline padding and no
quaternion-channel blend. Validation is finite sampling, not a continuous
contact proof. Sole geometry, weapon collisions, skin and balance need QA.
"""
import math
import re
from copy import deepcopy

import bpy
from mathutils import Matrix, Vector

from contact_reaction import _rig, _basis, _action, _solve_leg, _uniform_world

_PREFIX = 'weight_shift_'
_DEFAULTS = dict(prepare=.4, move=.6, hold=.4, recover=.8, settle=.4,
                 side_fraction=.1, depth_fraction=.05, lean_deg=5.)


def _number(value, name, low=0., high=None, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value < low or
            (positive and value <= 0) or (high is not None and value > high)):
        raise ValueError(f'weight shift: invalid {name}: {value!r}')
    return float(value)


def _frame(scene, frame):
    scene.frame_set(math.floor(frame), subframe=frame-math.floor(frame))


def _smooth(value):
    s = min(1., max(0., value))
    return s*s*(3-2*s)


def _envelopes(event, time):
    a, b, c, d, e, f = event['times']
    depth = _smooth((time-a)/(b-a)) if time < b else 1-_smooth((time-e)/(f-e))
    side = _smooth((time-b)/(c-b)) if time < d else 1-_smooth((time-d)/(e-d))
    return depth, side


def _matrix_error(actual, expected, unit):
    _number(unit,'matrix-error metres per unit',positive=True)
    _finite_matrix(actual)
    _finite_matrix(expected)
    pos = (actual.translation-expected.translation).length*unit
    angle = actual.to_quaternion().rotation_difference(expected.to_quaternion()).angle
    scale = (actual.to_scale()-expected.to_scale()).length
    if not all(math.isfinite(value) for value in (pos,angle,scale)):
        raise ValueError('weight shift: nonfinite matrix error result')
    angle = min(abs(angle), abs(2*math.pi-angle))
    return pos, angle, scale


def _finite_matrix(matrix):
    if not all(math.isfinite(value) for row in matrix for value in row):
        raise ValueError('weight shift: nonfinite transform matrix')


def _torso(arm, pelvis, legs):
    candidates = [b for b in arm.pose.bones if b.parent and b.parent.name == pelvis
                  and re.sub('[^a-z]', '', b.name.lower()) == 'spine']
    if len(candidates) != 1:
        raise ValueError(f'{arm.name}: lean needs one spine directly below pelvis')
    torso = candidates[0]
    descendants = {b.name for b in torso.children_recursive}
    if any(name in descendants or name == torso.name for leg in legs for name in leg):
        raise ValueError('weight shift: torso lean must not contain leg chains')
    if any(not b.bone.use_inherit_rotation for b in torso.children_recursive):
        raise ValueError('weight shift: torso descendants must inherit rotation')
    return torso


def _preflight(D, actors, fps):
    events = D.get('weight_shifts')
    if not isinstance(events, list):
        raise ValueError('weight shift: weight_shifts must be a list')
    frames = D.get('frames')
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 2:
        raise ValueError('weight shift: frames must be an integer >=2')
    if D.get('fps', fps) != fps:
        raise ValueError('weight shift: FPS must match D.fps')
    staged, intervals = [], {}
    for event in events:
        if not isinstance(event, dict) or set(event)-set(_DEFAULTS)-{'who','start','arm_clearance'}:
            raise ValueError('weight shift: unknown event fields or invalid entry')
        who = event.get('who')
        if not isinstance(who, str) or who not in actors:
            raise ValueError(f'weight shift: unknown actor {who!r}')
        for kind in ('crouches', 'contact_reactions', 'jumps', 'looks'):
            other = D.get(kind) or []
            if isinstance(other, dict):
                conflict = who in other or other.get('who') == who
            elif isinstance(other, list):
                conflict = any(isinstance(item, dict) and item.get('who') == who for item in other)
            else:
                raise ValueError(f'weight shift: unsupported {kind} schema')
            if conflict:
                raise ValueError(f'{who}: weight shift cannot combine with {kind}')
        params = {k: _number(event.get(k, default), k,
                             low=-.2 if k == 'side_fraction' else 0.,
                             high={ 'side_fraction':.2, 'depth_fraction':.1, 'lean_deg':10.}.get(k),
                             positive=k in ('prepare','move','recover','settle'))
                  for k, default in _DEFAULTS.items()}
        if params['side_fraction'] == 0 and params['lean_deg']:
            raise ValueError('weight shift: nonzero lean needs a signed lateral direction')
        time = _number(event.get('start'), 'start')
        times = [time]
        for phase in ('prepare','move','hold','recover','settle'):
            time = _number(time+params[phase], 'phase end')
            times.append(time)
        left = math.floor(_number(times[0]*fps,'start frame'))-3
        right = math.ceil(_number(times[-1]*fps,'end frame'))+3
        if left < 0 or right >= frames:
            raise ValueError(f'{who}: weight shift needs 3-frame padding; scene is not extended')
        actor = actors[who]
        arm, root = actor['arm'], actor['root']
        if arm.type != 'ARMATURE':
            raise ValueError('weight shift: expected an armature')
        if root.parent or root.constraints:
            raise ValueError('weight shift: root must be unconstrained and unparented')
        ad = arm.animation_data
        if ad is None or not ad.nla_tracks:
            raise ValueError(f'{who}: fixed-support shift requires an existing frozen NLA stance')
        if ad and any(t.name.startswith((_PREFIX,'airborne_pose_','contact_reaction_','look_'))
                      for t in ad.nla_tracks):
            raise ValueError(f'{who}: existing correction track is unsupported')
        for a, b in intervals.setdefault(arm, []):
            if left <= b and right >= a:
                raise ValueError(f'{who}: overlapping padded weight-shift windows')
        intervals[arm].append((left, right))
        clearance = event.get('arm_clearance', {})
        if not isinstance(clearance, dict) or set(clearance)-{'L','R'}:
            raise ValueError('weight shift: arm_clearance must map L/R to degrees')
        clearance = {s:_number(v,'arm clearance',high=30.) for s,v in clearance.items()}
        pelvis, legs, corrected, shoulders = _rig(arm, clearance)
        torso = _torso(arm, pelvis, legs) if params['lean_deg'] else None
        if torso:
            corrected.append(torso)
        affected = {bone.name:bone for bone in corrected}
        for bone in ([torso] if torso else []) + [arm.pose.bones[name] for name in shoulders.values()]:
            affected.update((child.name,child) for child in bone.children_recursive)
        for bone in affected.values():
            if bone.rotation_mode == 'AXIS_ANGLE' or any(not c.mute and c.influence for c in bone.constraints):
                raise ValueError(f'{bone.name}: unsupported rotation/constraint')
            if ad and any(not c.mute and c.data_path.startswith(bone.path_from_id()+'.') for c in ad.drivers):
                raise ValueError(f'{bone.name}: driven correction channel unsupported')
        staged.append(dict(who=who, arm=arm, root=root, params=params, times=times,
                           left=left, right=right, pelvis=pelvis, legs=legs,
                           corrected=corrected, torso=torso, shoulders=shoulders, clearance=clearance))
    return staged


def _source(event, scene, frame, unit):
    _frame(scene, frame)
    dg = bpy.context.evaluated_depsgraph_get()
    arm = event['arm'].evaluated_get(dg)
    mw = arm.matrix_world.copy()
    _finite_matrix(mw)
    _uniform_world(mw, event['who'])
    root = event['root'].evaluated_get(dg).matrix_world.copy()
    _finite_matrix(root)
    base = {b.name: mw @ b.matrix for b in arm.pose.bones}
    for matrix in base.values():
        _finite_matrix(matrix)
    if 'reference' in event:
        ref = event['reference']
        for name, current, expected in [('actor root',root,ref['root']),
                (event['pelvis'],base[event['pelvis']],ref['base'][event['pelvis']]),
                *[(leg[2],base[leg[2]],ref['base'][leg[2]]) for leg in event['legs']]]:
            error = _matrix_error(current, expected, unit)
            if error[0] > .00002 or error[1] > .0001 or error[2] > .00001:
                raise ValueError(f'{event["who"]}: moving source {name} at frame {frame:g}; '
                                 'fixed-support shift requires frozen root/pelvis/ankles')
    return root, mw, base


def _samples(event, scene, fps, unit):
    root, mw, base = _source(event, scene, event['times'][0]*fps, unit)
    event['reference'] = dict(root=root, base=base)
    # Actor-left and forward are horizontal unit axes, independent of model scale.
    if abs(root.to_quaternion().to_euler().x) > 1e-5 or abs(root.to_quaternion().to_euler().y) > 1e-5:
        raise ValueError('weight shift: yaw-only root required')
    side = root.to_quaternion() @ Vector((-1,0,0)); side.normalize()
    forward = root.to_quaternion() @ Vector((0,-1,0)); forward.normalize()
    anchors = {leg[2]:base[leg[2]].copy() for leg in event['legs']}
    width = abs((base[event['legs'][0][2]].translation-base[event['legs'][1][2]].translation).dot(side))
    leg_length = min(sum((base[a].translation-base[b].translation).length
                         for a,b in zip(leg,leg[1:])) for leg in event['legs'])
    if width <= .05*leg_length:
        raise ValueError('weight shift: insufficient lateral ankle spacing')
    params = event['params']
    distance, depth = params['side_fraction']*width, params['depth_fraction']*leg_length
    event.update(side_m=distance*unit, depth_m=depth*unit, anchors=anchors)
    frames = sorted({event['left']+k/4 for k in range((event['right']-event['left'])*4+1)} |
                    {t*fps for t in event['times']})
    shifted = {b.name for b in event['arm'].pose.bones
               if b.name == event['pelvis'] or event['pelvis'] in {p.name for p in b.parent_recursive}}
    poles, samples = [None,None], []
    for frame in frames:
        _, mw, base = _source(event, scene, frame, unit)
        inv = mw.inverted()
        desired = {n:m.copy() for n,m in base.items()}
        drop, lateral = _envelopes(event, frame/fps)
        delta = side*(distance*lateral)+Vector((0,0,-depth*drop))
        for name in shifted:
            desired[name].translation += delta
        for i,leg in enumerate(event['legs']):
            poles[i] = _solve_leg(base,desired,leg,delta,poles[i],forward,anchors[leg[2]])
        if event['torso']:
            bone = event['torso']
            pivot = desired[bone.name].translation
            angle = math.radians(params['lean_deg'])*lateral*(1 if distance > 0 else -1)
            rotate = Matrix.Translation(pivot) @ Matrix.Rotation(angle,4,forward) @ Matrix.Translation(-pivot)
            for child in [bone,*bone.children_recursive]:
                desired[child.name] = rotate @ desired[child.name]
        for s,name in event['shoulders'].items():
            pivot = desired[name].translation
            angle = math.radians(event['clearance'][s])*drop*(1 if s == 'L' else -1)
            rotate = Matrix.Translation(pivot) @ Matrix.Rotation(angle,4,forward) @ Matrix.Translation(-pivot)
            for child in [event['arm'].pose.bones[name],*event['arm'].pose.bones[name].children_recursive]:
                desired[child.name] = rotate @ desired[child.name]
        basis = {}
        for bone in event['corrected']:
            parent = inv @ desired[bone.parent.name] if bone.parent else None
            basis[bone.name] = _basis(bone,inv @ desired[bone.name],parent)
        samples.append(dict(frame=frame,basis=basis))
    witnesses = [(a+b)/2 for a,b in zip(frames,frames[1:])]
    for f in witnesses:
        _source(event,scene,f,unit)  # Reject source motion between baked keys too.
    return samples, sorted(frames+witnesses)


def _bake_weight_shifts(events, scene, fps, unit):
    """Bake already-preflighted events; public caller owns mesh transaction."""
    saved = scene.frame_current, scene.frame_subframe
    tracks, actions, reports = [], [], []
    try:
        staged = [(event,*_samples(event,scene,fps,unit)) for event in events]
        for event,samples,checks in staged:
            arm = event['arm']
            ad = arm.animation_data_create()
            track = ad.nla_tracks.new(prev=ad.nla_tracks[-1]) if ad.nla_tracks else ad.nla_tracks.new()
            tracks.append((ad,track))
            track.name = _PREFIX+event['who']
            action = _action(arm,event['corrected'],samples,track.name,scene)
            actions.append(action)
            strip = track.strips.new(action.name,event['left'],action)
            if hasattr(strip,'action_slot') and hasattr(action,'slots'):
                strip.action_slot = action.slots[0]
            strip.action_frame_start,strip.action_frame_end = event['left'],event['right']
            strip.frame_start,strip.frame_end = event['left'],event['right']
            strip.repeat=1.; strip.scale=1.; strip.blend_type='REPLACE'; strip.extrapolation='NOTHING'
            strip.use_auto_blend=False; strip.blend_in=strip.blend_out=0.
            strip.influence=1.; strip.use_animated_influence=False
        # Validate the complete resulting stack, including independent midpoints.
        for event,samples,checks in staged:
            position=angle=scale=root_error=0.
            for frame in checks:
                _frame(scene,frame)
                dg = bpy.context.evaluated_depsgraph_get()
                arm = event['arm'].evaluated_get(dg)
                for name,anchor in event['anchors'].items():
                    err = _matrix_error(arm.matrix_world @ arm.pose.bones[name].matrix,anchor,unit)
                    position=max(position,err[0]); angle=max(angle,err[1]); scale=max(scale,err[2])
                    if err[0] > .0001 or err[1] > .001 or err[2] > .0001:
                        raise ValueError(f'{event["who"]}: fixed foot {name} drift at {frame:g}: {err}')
                err = _matrix_error(event['root'].evaluated_get(dg).matrix_world,event['reference']['root'],unit)
                root_error=max(root_error,err[0])
                if err[0] > .00002 or err[1] > .0001 or err[2] > .00001:
                    raise ValueError('weight shift: root changed during validation')
            report = dict(who=event['who'],times=event['times'],window=[event['left'],event['right']],
                          side_m=event['side_m'],depth_m=event['depth_m'],lean_deg=event['params']['lean_deg'],
                          keyed_samples=len(samples),independent_midpoints=len(checks)-len(samples),
                          max_foot_error_m=position,max_foot_error_rad=angle,max_foot_scale_error=scale,
                          max_root_error_m=root_error,anchors='fixed start-pose full world ankle matrices',
                          limitations='finite bone checks; sole/skin/weapon/support-polygon QA and visual acceptance pending')
            reports.append(report)
            print('WEIGHT_SHIFT',report,flush=True)
        return reports
    except Exception:
        for ad,track in reversed(tracks):
            ad.nla_tracks.remove(track)
        for action in actions:
            if action.users == 0:
                bpy.data.actions.remove(action)
        raise
    finally:
        scene.frame_set(saved[0],subframe=saved[1])


def apply_weight_shifts(D, actors, scene, fps):
    """Preflight, repair target skins, then bake as one transaction.

    Missing/empty weight_shifts is a no-op. Other D.crouches are never passed
    to the repair helper. Mesh pointers and stabilization flags on all target
    meshes are preserved on any repair/sampling/bake/validation error. Reports
    keep the original per-event schema and add skin_repair diagnostics.
    """
    if not D.get('weight_shifts'):
        return []
    fps = _number(fps,'fps',positive=True)
    unit = _number(scene.unit_settings.scale_length,'metres per unit',positive=True)
    events = _preflight(D,actors,fps)  # No skin mutation for unsupported configs.
    saved = scene.frame_current, scene.frame_subframe
    snapshots = {}
    for event in events:
        for obj in event['root'].children_recursive:
            if obj.type == 'MESH' and obj not in snapshots:
                present = 'crouch_skin_stabilized' in obj
                snapshots[obj] = (obj.data,present,
                                  deepcopy(obj['crouch_skin_stabilized']) if present else None)
    original_meshes = {mesh.as_pointer() for mesh in bpy.data.meshes}
    original_actions = {action.as_pointer() for action in bpy.data.actions}
    original_tracks = {event['arm']:{track.as_pointer() for track in event['arm'].animation_data.nla_tracks}
                       for event in events}
    try:
        from joint_skin import stabilize_crouch_skins
        skin = stabilize_crouch_skins({'weight_shifts':deepcopy(D['weight_shifts'])},actors,scene,fps)
        results = _bake_weight_shifts(events,scene,fps,unit)
        for result in results:
            result['skin_repair'] = [row for row in skin if row['who'] == result['who']]
        return results
    except Exception:
        for arm,existing in original_tracks.items():
            for track in list(arm.animation_data.nla_tracks):
                if track.as_pointer() not in existing:
                    arm.animation_data.nla_tracks.remove(track)
        for action in list(bpy.data.actions):
            if action.as_pointer() not in original_actions and action.users == 0:
                bpy.data.actions.remove(action)
        for obj,(mesh,present,value) in snapshots.items():
            obj.data = mesh
            if present:
                obj['crouch_skin_stabilized'] = value
            elif 'crouch_skin_stabilized' in obj:
                del obj['crouch_skin_stabilized']
        for mesh in list(bpy.data.meshes):
            if mesh.as_pointer() not in original_meshes and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        raise
    finally:
        scene.frame_set(saved[0],subframe=saved[1])
