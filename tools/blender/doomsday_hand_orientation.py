"""Match a grip orientation through explicit native PALM controls.

Only computes three control angles for an already staged arm target/pole.
It does not certify joint comfort, skin, contact, or the resulting scene.
The order is forearm roll, palm flex, palm deviation (matrix product);
the deviation acts first, then flex, about axes of the pronated rest hand.
"""
import math

import bpy
import numpy as np
from mathutils import Quaternion

from doomsday_arm_controls import _space, palm_axes


def required_hand_angles(control, target_rotation, initial=None):
    if control.get('wrist_axis_mode') != 'PALM':
        raise ValueError('Explicit PALM control calibration is required.')
    main = bpy.data.objects[control['main_armature']]
    side = control['side']
    control.matrix_world = _space(main, side)
    bpy.context.view_layer.update()
    evaluated = control.evaluated_get(bpy.context.evaluated_depsgraph_get())
    hand = (evaluated.matrix_world @ evaluated.pose.bones['hand'].matrix
            @ control.data.bones['hand'].matrix_local.inverted()
            @ main.data.bones['wrist_' + side].matrix_local)
    elbow = evaluated.matrix_world @ evaluated.pose.bones['lower'].head
    axis = (hand.translation - elbow).normalized()
    base = hand.to_quaternion().normalized()
    across, normal = (base @ vector for vector in palm_axes(main, side))
    desired = target_rotation.normalized()

    def residual(values):
        actual = (Quaternion(axis, float(values[0]))
                  @ Quaternion(across, float(values[1]))
                  @ Quaternion(normal, float(values[2])) @ base)
        difference = desired @ actual.inverted()
        if difference.w < 0:
            difference.negate()
        vector = np.array((difference.x, difference.y, difference.z))
        length = np.linalg.norm(vector)
        return vector * (2 * math.atan2(length, difference.w) / length) if length > 1e-12 else vector * 2

    properties = ('forearm_roll', 'hand_flex', 'hand_deviation')
    values = np.array(initial if initial is not None else
                      [float(control.get(name, 0)) for name in properties], dtype=float)
    for _ in range(12):
        error = residual(values)
        if np.linalg.norm(error) < 2e-6:
            break
        delta = .0005
        jacobian = np.column_stack([(residual(values + np.eye(3)[i] * delta) - error) / delta
                                    for i in range(3)])
        step = np.linalg.lstsq(jacobian, -error, rcond=None)[0]
        # Bound each numerical step, not the anatomical range of the final pose.
        values += step * min(1., .5 / max(float(np.linalg.norm(step)), 1e-12))
    error_degrees = math.degrees(float(np.linalg.norm(residual(values))))
    if error_degrees > .05:
        raise ValueError(f'Hand orientation did not converge: {error_degrees:.4f} degrees')
    values = (values + math.pi) % (2 * math.pi) - math.pi
    return dict(zip(properties, (float(value) for value in values))), error_degrees
