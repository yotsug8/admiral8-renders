"""Bake a staged rigid prop from stationary world space into a hand's space.

The caller must position the prop and author the grasp first. This module
preserves the hand-relative transform at transfer; it does not solve fingers,
surface contact, support, collisions, release, or physics.
"""
import math

import bpy


def _error(a, b):
    return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))


def bake_pickup(prop, arm, bone_name, grab_frame, end_frame, start_frame=0):
    """Eighth-frame bake with independent sixteenth-frame playback witnesses.

Prop must be unparented and undriven, with no constraints or animation. Its
current world matrix is the staged stationary pose, including at grab_frame.
Only the prop receives animation; neither rig nor source meshes are modified.
    """
    sc = bpy.context.scene
    if (any(not math.isfinite(float(f)) for f in (start_frame, grab_frame, end_frame))
            or not start_frame < grab_frame < end_frame
            or any(float(f)*8 != round(float(f)*8) for f in (start_frame, grab_frame, end_frame))):
        raise ValueError('Require ordered finite eighth-frame boundaries')
    if prop.parent or prop.constraints or prop.animation_data:
        raise ValueError('Use an unparented, unconstrained, unanimated staged prop')
    if arm.type != 'ARMATURE' or bone_name not in arm.pose.bones:
        raise ValueError('Missing hand bone')
    saved_frame, saved_subframe = sc.frame_current, sc.frame_subframe
    original, mode = prop.matrix_world.copy(), prop.rotation_mode
    action = None

    def hand_at(frame):
        sc.frame_set(math.floor(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        ev = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
        return ev.matrix_world @ ev.pose.bones[bone_name].matrix

    try:
        hand_grab = hand_at(grab_frame)
        relative = hand_grab.inverted() @ original

        def desired(frame):
            hand = hand_at(frame)
            return original if frame <= grab_frame else hand @ relative

        # Stage all samples before adding curves; reject shear/reflection rather
        # than silently changing a rigid prop when decomposing its matrix.
        from mathutils import Matrix
        samples = []
        for i in range(round((end_frame-start_frame)*8)+1):
            frame = start_frame+i/8
            matrix = desired(frame)
            location, rotation, scale = matrix.decompose()
            rebuilt = Matrix.LocRotScale(location, rotation, scale)
            if min(scale) <= 0 or _error(rebuilt, matrix) > 1e-5:
                raise ValueError('Rigid attachment cannot bake reflected/sheared transforms')
            samples.append((frame, matrix.copy()))
        prop.rotation_mode = 'QUATERNION'
        previous = None
        for frame, matrix in samples:
            prop.matrix_world = matrix
            if previous is not None and prop.rotation_quaternion.dot(previous) < 0:
                prop.rotation_quaternion.negate()
            previous = prop.rotation_quaternion.copy()
            for channel in ('location', 'rotation_quaternion', 'scale'):
                prop.keyframe_insert(channel, frame=frame)
        action = prop.animation_data.action
        action.name = 'pickup_'+prop.name
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
        world_error = static_error = relative_error = 0.
        count = round((end_frame-start_frame)*16)+1
        for i in range(count):
            frame = start_frame+i/16
            expected = desired(frame)
            actual = prop.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
            world_error = max(world_error, _error(actual, expected))
            if frame <= grab_frame:
                static_error = max(static_error, _error(actual, original))
            else:
                relative_error = max(relative_error, _error(hand_at(frame).inverted() @ actual, relative))
        if world_error > 2e-4 or static_error > 1e-5 or relative_error > 2e-4:
            raise ValueError(f'Attachment playback error {world_error}, {static_error}, {relative_error}')
        hand_at(grab_frame)
        switch_error = _error(prop.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world, original)
        return dict(samples=count, max_world_matrix_error=world_error,
                    max_stationary_matrix_error=static_error, max_grip_matrix_error=relative_error,
                    switch_matrix_error=switch_error,
                    limits='Transform continuity only, not velocity continuity; no grasp, contact, support, or collision certification.')
    except Exception:
        created = prop.animation_data.action if prop.animation_data else action
        prop.animation_data_clear()
        prop.rotation_mode = mode
        prop.matrix_world = original
        if created is not None and created.users == 0:
            bpy.data.actions.remove(created)
        raise
    finally:
        sc.frame_set(saved_frame, subframe=saved_subframe)
