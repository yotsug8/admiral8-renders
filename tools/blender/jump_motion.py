"""Pure Stage jump planning; no Blender imports or scene-duration changes.

Times are seconds on Stage's zero-based timeline: keys[f] is at f / fps,
and the last usable time is (frames - 1) / fps. ``at`` means takeoff,
not preparation start. Height/depth are metres, gravity is m/s**2; keys
remain in native game units (39.37 units per metre).

``launch`` is a maximum recovery duration, not an exact duration:
launch_actual=min(launch, 2.5*depth/impact_speed). Preparation starts at
at-down-hold-launch_actual, reaches depth after down, holds, then recovers
during launch_actual, ending exactly at takeoff with up_speed=impact_speed.
The Hermite recovery starts with zero speed and ends with the ballistic
launch speed; its normalized final slope is at most 2.5. Flight
lasts T=sqrt(8*height/gravity), with offset g*t*(T-t)/2. Landing starts
at at+T; ``landing`` is the total compression-and-recovery time, with
compression min(0.15, landing/3, 2.5*depth/impact_speed) and no hold,
where impact_speed=gravity*T/2. Landing requests down_speed in metres per
second for Hermite compression: initial downward speed matches impact,
final speed is zero. Its normalized initial slope is at most 2.5 (<3,
the monotonicity limit). The consumer must support up_speed/down_speed;
smoothstep alone does not preserve launch/impact velocity. Both
crouches reserve three scene-boundary padding frames.

Continuous event times are never rounded; native keys sample the parabola
at f/fps. A subframe apex/landing need not coincide with a native key.
The metadata reports the exact endpoints; every key at/after landing is
exactly the original baseline. Existing XY and rotations are untouched.
Animated source Z within a jump is rejected rather than flattening it.
This plans root motion and crouch requests, not verified skeletal flight.

After native root keys have been inserted, refine_jump_roots may refine
only their Z FCurve, before skin stabilization and contact correction.
It needs Blender-like objects but imports no bpy, even when called.
"""

from copy import deepcopy
import math


def _number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'jump: {label} must be a finite number')
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (value <= 0 if positive else value < 0):
        raise ValueError(f'jump: {label} must be finite and '
                         f'{"positive" if positive else "nonnegative"}')
    return float(value)


def _finite_tree(value):
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite_tree(item)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError('jump: scene contains nonfinite numeric data')


def plan_jumps(D):
    """Return a deep independent scene, adding keys, crouches, jump_plan.

    Missing/empty jumps return an equal deep copy without added metadata.
    Same-actor action intervals include preparation, flight and recovery;
    overlapping intervals are rejected. Different actors may jump together.
    Existing crouches/contact reactions are retained unchanged; their
    artistic interaction with jumps must be checked during integration.
    """
    result = deepcopy(D)
    jumps = D.get('jumps')
    if not jumps:
        return result
    if not isinstance(jumps, list):
        raise ValueError('jump: jumps must be a list')
    _finite_tree(D)
    fps = _number(D.get('fps'), 'fps', True)
    frames = D.get('frames')
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 2:
        raise ValueError('jump: frames must be an integer >= 2')
    actors = D.get('actors')
    if not isinstance(actors, dict):
        raise ValueError('jump: actors must be a mapping')
    crouches = result.get('crouches')
    if crouches is None:
        crouches = result['crouches'] = []
    if not isinstance(crouches, list):
        raise ValueError('jump: crouches must be a list')
    reports, intervals = [], {}
    for index, event in enumerate(jumps):
        if not isinstance(event, dict):
            raise ValueError(f'jump {index}: expected an object')
        who = event.get('who')
        if not isinstance(who, str) or who not in actors:
            raise ValueError(f'jump {index}: unknown actor {who!r}')
        at = _number(event.get('at'), 'at')
        height = _number(event.get('height'), 'height', True)
        params = {name: _number(event.get(name, default), name, name != 'hold')
                  for name, default in (('depth', .15), ('down', .35),
                                        ('hold', .1), ('launch', .15),
                                        ('gravity', 9.81), ('landing', .45))}
        depth, down, hold, launch, gravity, landing = (
            params[k] for k in ('depth', 'down', 'hold', 'launch', 'gravity', 'landing'))
        # Ratio first avoids overflowing 8*height unnecessarily.
        ratio = height / gravity
        flight = (math.sqrt(8 * ratio) if math.isfinite(8 * ratio)
                  else math.sqrt(ratio) * math.sqrt(8))
        impact_speed = _number(gravity * (flight / 2), 'impact speed', True)
        speed_limit = 2.5 * (depth / impact_speed)
        launch_actual = _number(min(launch, speed_limit), 'launch duration', True)
        start = at - down - hold - launch_actual
        land, end = at + flight, at + flight + landing
        _finite_tree([flight, start, land, end, height * 39.37])
        if start * fps < 3 or end * fps > frames - 4:
            raise ValueError(f'{who}: insufficient scene duration for jump '
                             f'[{start:.6g}, {end:.6g}] plus 3-frame crouch padding; '
                             'duration is not extended')
        if flight * fps < 1:
            raise ValueError(f'{who}: flight shorter than one frame; increase height or fps')
        for left, right in intervals.setdefault(who, []):
            if start < right and end > left:
                raise ValueError(f'{who}: overlapping jump preparation/flight/landing')
        intervals[who].append((start, end))
        keys = actors[who].get('keys')
        if not isinstance(keys, (list, tuple)) or len(keys) != frames:
            raise ValueError(f'{who}: expected exactly frames root keys')
        for key in keys:
            if not isinstance(key, (list, tuple)) or len(key) != 6:
                raise ValueError(f'{who}: root key must contain x,y,z,pitch,yaw,roll')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in key):
                raise ValueError(f'{who}: root key values must be finite numbers')
        left = max(0, math.floor(start * fps))
        right = min(frames - 1, math.ceil(end * fps))
        baseline = keys[left][2]
        if any(key[2] != baseline for key in keys[left:right + 1]):
            raise ValueError(f'{who}: animated source root Z within jump; expected a fixed baseline')
        target = list(result['actors'][who]['keys'])
        for f in range(max(0, math.floor(at * fps)), min(frames, math.ceil(land * fps) + 1)):
            elapsed = f / fps - at
            if 0 < elapsed < flight:
                key = list(target[f])
                key[2] = baseline + (gravity * elapsed * (flight - elapsed) / 2) * 39.37
                _finite_tree(key)
                target[f] = key
        result['actors'][who]['keys'] = target
        compress = _number(min(.15, landing / 3, speed_limit),
                           'landing compression duration', True)
        crouches.extend([
            dict(who=who, at=start, depth=depth, down=down, hold=hold,
                 up=launch_actual, up_speed=impact_speed),
            dict(who=who, at=land, depth=depth, down=compress, hold=0.,
                 up=landing-compress, down_speed=impact_speed),
        ])
        reports.append(dict(who=who, prep_start=start, takeoff=at, apex=at+flight/2,
                            land=land, recover=end, flight=flight, height=height,
                            gravity=gravity, baseline_z=baseline, impact_speed=impact_speed,
                            launch_requested=launch, launch_actual=launch_actual,
                            contact_states=[dict(at=start, state='grounded'),
                                            dict(at=at, state='airborne'),
                                            dict(at=land, state='grounded')]))
    result['jump_plan'] = reports
    _finite_tree(result)
    return result


def _root_z_curve(root):
    """Find only the root's assigned action slot, never another slot's curves."""
    ad = getattr(root, 'animation_data', None)
    action = getattr(ad, 'action', None)
    if action is None:
        raise ValueError('jump refinement: root needs an active keyed action')
    curves = []
    if getattr(action, 'is_action_layered', False):
        slot = getattr(ad, 'action_slot', None)
        if slot is None:
            raise ValueError('jump refinement: layered root action has no assigned slot')
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', ()):
                    if bag.slot_handle == slot.handle:
                        curves.extend(bag.fcurves)
    else:
        curves = list(action.fcurves)
    matches = [curve for curve in curves
               if curve.data_path == 'location' and curve.array_index == 2]
    if len(matches) != 1:
        raise ValueError('jump refinement: expected one root location Z curve in assigned slot')
    curve = matches[0]
    if curve.modifiers or curve.mute or getattr(curve, 'lock', False):
        raise ValueError('jump refinement: root Z curve must be editable, unmuted and modifier-free')
    return curve


def refine_jump_roots(D, ACTORS, sc, FPS):
    """Refine planned root Z into exact ballistic cubic Hermite segments.

    Call after root key insertion, before joint_skin/contact_reaction. Returns
    diagnostics; no jumps is a no-op. D and frame/subframe are not changed.
    Root location must already be in scene units with world-aligned Z (the
    renderer creates unparented roots). Baseline comes from the existing Z
    curve at preparation start, preserving map/BASE offsets; never from
    native game Z or takeoff interpolation, which can already be airborne
    when takeoff falls between native keys.

    Insert fractional takeoff/apex/landing keys, retaining all native keys.
    Each flight segment has FREE handles at +/- delta_frames/3 and analytic
    slopes g*(T/2-elapsed)/(FPS*metres_per_scene_unit). This represents the
    quadratic exactly apart from Blender's float precision. Ground segments
    within preparation/recovery are flat. At takeoff the left tangent is
    zero and right tangent is launch velocity; at landing the left tangent
    is impact velocity and right tangent is zero. No smoothing across impact.
    XY, rotations, unrelated slots and animation outside these windows are
    untouched. Does not articulate legs or validate surface contact.
    """
    if not D.get('jumps'):
        return []
    plans = D.get('jump_plan')
    if not plans:
        raise ValueError('jump refinement: call plan_jumps before refining roots')
    fps = _number(FPS, 'refinement fps', True)
    if fps != D.get('fps'):
        raise ValueError('jump refinement: FPS must match planned scene fps')
    unit = _number(sc.unit_settings.scale_length, 'metres per scene unit', True)
    staged = []
    for plan in plans:
        who = plan['who']
        if who not in ACTORS:
            raise ValueError(f'jump refinement: unknown actor {who!r}')
        root = ACTORS[who]['root']
        if root.parent is not None or any(root.constraints):
            raise ValueError(f'{who}: jump refinement needs an unconstrained, unparented root')
        curve = _root_z_curve(root)
        start, apex, end = (plan[k] * fps for k in ('takeoff', 'apex', 'land'))
        baseline = float(curve.evaluate(plan['prep_start'] * fps))
        _finite_tree([start, apex, end, baseline])
        staged.append((plan, curve, start, apex, end, baseline))
    reports = []
    for plan, curve, start, apex, end, baseline in staged:
        points = curve.keyframe_points
        # Float-key coordinates in Blender are single precision. Snap event
        # keys already within float tolerance to avoid near-duplicate handles.
        tolerance = max(1e-6, abs(end) * 2e-7)
        for frame, value in ((start, baseline),
                             (apex, baseline + plan['height'] / unit),
                             (end, baseline)):
            existing = next((p for p in points if abs(p.co[0]-frame) <= tolerance), None)
            if existing is None:
                points.insert(frame, value, options={'FAST'})
            else:
                existing.co = (frame, value)
        curve.update()
        left = math.floor(plan['prep_start'] * fps)
        right = math.ceil(plan['recover'] * fps)
        selected = [p for p in points if left <= p.co[0] <= right]
        for p in selected:
            p.handle_left_type = p.handle_right_type = 'FREE'
        for p, following in zip(selected, selected[1:]):
            f0, z0 = map(float, p.co)
            f1, z1 = map(float, following.co)
            delta = (f1-f0)/3
            flight = f0 >= start-tolerance and f1 <= end+tolerance
            def slope(frame):
                elapsed = (frame-start)/fps
                return plan['gravity']*(plan['flight']/2-elapsed)/fps/unit
            m0, m1 = (slope(f0), slope(f1)) if flight else (0., 0.)
            p.interpolation = 'BEZIER'
            p.handle_right = (f0+delta, z0+m0*delta)
            following.handle_left = (f1-delta, z1-m1*delta)
        curve.update()
        reports.append(dict(who=plan['who'], baseline_scene_z=baseline,
                            takeoff_frame=start, apex_frame=apex, land_frame=end,
                            metres_per_scene_unit=unit))
    return reports
