"""Bounded chase glance and blink overlay; call after body and face setup.

Uses the currently loaded scene; never opens, saves or renders a blend file.
Only Hoodwink neck/head NLA and a copied eyeClosed action are authored.
"""
import json
import math
from pathlib import Path

import bpy

from look_motion import apply_looks, _rig
from contact_reaction import _curves


def apply_chase_acting(actors, sc=None, report_path=None):
    sc = sc or bpy.context.scene
    saved_frame, saved_subframe = sc.frame_current, sc.frame_subframe
    fps = sc.render.fps / sc.render.fps_base
    actor = actors['hoodwink']
    arm, root = actor['arm'], actor['root']
    ad = arm.animation_data
    if any(t.name.startswith('look_motion_') for t in ad.nla_tracks):
        raise ValueError('Look already present: reload the clean scene before applying again.')
    original_action, original_slot = ad.action, ad.action_slot
    # Source has only visibility in its active action. Never hide pose channels.
    if original_action and any(c.data_path != 'hide_render' for c in _curves(original_action)):
        raise ValueError('Unsupported active rig action: expected visibility only.')
    mesh = actors['hoodwink']['head']
    keys = mesh.data.shape_keys
    blink = keys.key_blocks.get('eyeClosed') if keys else None
    face_ad = keys.animation_data if keys else None
    face_action = face_ad.action if face_ad else None
    face_slot = face_ad.action_slot if face_ad else None
    blink_path = blink.path_from_id('value') if blink else None
    if blink and (not face_action or any(c.data_path == blink_path for c in face_ad.drivers)):
        raise ValueError('Blink requires an existing undriven facial action.')
    new_face_action = None
    old_tracks = set(ad.nla_tracks)
    try:
        ad.action = None
        _, _, corrected = _rig(actor)
        ad.action = original_action
        if original_action:
            ad.action_slot = original_slot
        moving = {b.name for b in [corrected[0], *corrected[0].children_recursive]}

        def witness(f):
            sc.frame_set(f)
            dg = bpy.context.evaluated_depsgraph_get()
            values = []
            for who, a in actors.items():
                ev = a['arm'].evaluated_get(dg)
                for obj in (a['root'], a['arm']):
                    values.extend(v for row in obj.evaluated_get(dg).matrix_world for v in row)
                for b in ev.pose.bones:
                    if who == 'hoodwink' and b.name in moving and 5.5 * fps <= f <= 6.8 * fps:
                        continue
                    values.extend(v for row in b.matrix for v in row)
            if keys:
                values.extend(k.value for k in keys.key_blocks if k != blink)
            return values

        baseline = {f: witness(f) for f in range(sc.frame_start, sc.frame_end + 1)}
        sc.frame_set(round(6.15 * fps))
        delta = actors['kunkka']['root'].matrix_world.translation - root.matrix_world.translation
        local_delta = root.matrix_world.to_3x3().inverted() @ delta
        # Actor forward is local -Y. Positive world yaw turns toward local +X.
        yaw = 22.0 if local_delta.x >= 0 else -22.0
        event = dict(who='hoodwink', start=5.5, end=6.8, yaw_deg=yaw,
                     pitch_deg=5.0, attack=.45, release=.45, eye_lead=0.)
        ad.action = None
        try:
            looks = apply_looks(dict(frames=sc.frame_end + 1, fps=fps, looks=[event]),
                                {'hoodwink': actor}, sc, fps)
        finally:
            ad.action = original_action
            if original_action:
                ad.action_slot = original_slot

        blink_windows = [(5.56, 5.80), (6.54, 6.80)] if blink else []
        samples = []
        for start, end in blink_windows:
            for f in range(math.floor(start * fps) - 2, math.ceil(end * fps) + 3):
                sc.frame_set(f)
                u = min(1., max(0., (f / fps - start) / (end - start)))
                envelope = math.sin(math.pi * u) ** 2 if 0 < u < 1 else 0.
                samples.append((f, max(blink.value, envelope)))
        if blink:
            # Copy-on-write: every other facial curve/key stays intact.
            new_face_action = face_action.copy()
            new_face_action.name = 'lively_fix_hoodwink_face'
            face_ad.action = new_face_action
            face_ad.action_slot = next(s for s in new_face_action.slots if s.identifier == face_slot.identifier)
            for f, value in samples:
                blink.value = value
                blink.keyframe_insert('value', frame=f)
            # Only the blink window gets linear segments; guards retain baseline.
            for c in _curves(new_face_action):
                if c.data_path == blink_path:
                    for k in c.keyframe_points:
                        if any(math.floor(a * fps) - 1 <= k.co.x <= math.ceil(b * fps) + 1 for a, b in blink_windows):
                            k.interpolation = 'LINEAR'

        worst = 0.
        for f, before in baseline.items():
            after = witness(f)
            err = max(abs(a - b) for a, b in zip(before, after))
            worst = max(worst, err)
            if len(before) != len(after) or err > 2e-5:
                raise ValueError(f'Protected channels changed at frame {f}: {err}')
        report = dict(event=event, look_diagnostics=looks, blink_windows=blink_windows,
                      blink_channel=blink_path, protected_frames=len(baseline),
                      max_protected_matrix_or_shape_error=worst,
                      local_pursuer_direction=list(local_delta),
                      limitations=['Integer-frame numeric QA only; no render or geometry collision QA.',
                                   'A 22-degree glance indicates the pursuer side, not a full backward target lock.',
                                   'Eye direction and corrective facial channels are preserved, not re-authored.',
                                   'Neck/head descendants inherit movement; clothing intersections require visual review.',
                                   'Apply once to the clean source; no scene save is performed.'])
        if report_path:
            Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('ACTING_OK', json.dumps(report, ensure_ascii=False), flush=True)
        return report
    except Exception:
        for track in list(ad.nla_tracks):
            if track not in old_tracks:
                actions = [s.action for s in track.strips]
                ad.nla_tracks.remove(track)
                for action in actions:
                    if action.users == 0:
                        bpy.data.actions.remove(action)
        if new_face_action:
            face_ad.action = face_action
            face_ad.action_slot = face_slot
            if new_face_action.users == 0:
                bpy.data.actions.remove(new_face_action)
        raise
    finally:
        ad.action = original_action
        if original_action:
            ad.action_slot = original_slot
        sc.frame_set(saved_frame, subframe=saved_subframe)

