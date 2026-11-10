"""Small FK curl preset for official Rain v3.3 (rain_v3.2.blend).

capture() once AFTER setting ik_fingers_left/right=0 and evaluating the rig.
apply() accepts a scalar or a mapping of individual finger amounts.
Missing mapping entries mean zero, not the previous amount. Values are
clamped to [0, 1] and eased with smoothstep. The caller updates the view layer
once after posing all actors. No operators, keyframes or scene updates here.

Local +X bends all twelve ordinary finger controls palmwards on BOTH sides.
The default 35/60/40 degree endpoint is NOT a radius/contact fit. An optional
angles mapping supplies three local-X offsets per finger for a measured
grasp. Inspect skin and contact before use. The default thumb stays captured;
custom thumb angles are authored offsets, not an automatic opposition solver.
The positive-rest-Z normal in Performer.hand_q faces opposite to this curl.
"""

from collections.abc import Mapping
import math

from mathutils import Matrix, Quaternion

_FINGERS = ('Index', 'Middle', 'Ring', 'Pinky', 'Thumb')
_CURL_DEGREES = (35.0, 60.0, 40.0)
ROUND_WRIST_RADIAL = (.008221, -.003755)
ROUND_WRIST_ROLL = math.radians(2.996)
_ROUND_FINGER_OFFSETS = {
    'Index': (2.131, 2.251, 12.021),
    'Middle': (.691, 4.688, 11.143),
    'Ring': (2.150, 2.087, 11.522),
    'Pinky': (1.872, .522, 7.220),
    'Thumb': (-17.789, -9.156, 25.679),
}
_ROUND_THUMB_SPREAD = (2.540, 5.663, 15.302)


def fit_round_fingers(bones, side, amount):
    """Refine the posed Rain fingers on a 36 mm shaft in the fitted orientation."""
    mirror = 1 if side == 'R' else -1
    for finger, offsets in _ROUND_FINGER_OFFSETS.items():
        for joint, offset in enumerate(offsets, 1):
            bone = bones[f'FK-{finger}{joint}.{side}']
            correction = Quaternion((1, 0, 0), math.radians(offset * amount))
            if finger == 'Thumb':
                spread = _ROUND_THUMB_SPREAD[joint - 1] * amount * mirror
                correction @= Quaternion((0, 0, 1), math.radians(spread))
            bone.matrix_basis = bone.matrix_basis @ correction.to_matrix().to_4x4()


def _require_fk(rig, side):
    if getattr(rig, 'type', None) != 'ARMATURE':
        raise ValueError('Expected a Rain armature object')
    prop = 'ik_fingers_' + ('left' if side == 'L' else 'right')
    controls = rig.pose.bones.get('Properties_IKFK')
    if controls is None or controls.get(prop) != 0:
        raise ValueError(f'Set Properties_IKFK[{prop!r}]=0 and update before capture/apply')


def capture(rig, side):
    """Return an in-memory state; no rig changes or evaluation.

    names: ordered list of 15 FK bone names, including preserved thumb.
    basis: name -> copied mathutils.Matrix (the immutable reference pose).
    side/rig: side and owning Blender object; capture separately per actor.
    Targets are local rotation offsets, so capture a relaxed/open finger pose.
    State is not JSON; serialize basis matrices separately for authored caches.
    """
    if side not in ('L', 'R'):
        raise ValueError("side must be 'L' or 'R'")
    _require_fk(rig, side)
    names = [f'FK-{finger}{joint}.{side}'
             for finger in _FINGERS for joint in (1, 2, 3)]
    missing = [name for name in names if name not in rig.pose.bones]
    if missing:
        raise ValueError('Missing Rain FK controls: ' + ', '.join(missing))
    basis = {name: rig.pose.bones[name].matrix_basis.copy() for name in names}
    # Rain ships with unit FK scales. Reject shear/negative or nonuniform
    # scale: postmultiplying a rotation through it would alter the scale.
    for name, matrix in basis.items():
        loc, rot, scale = matrix.decompose()
        rebuilt = Matrix.LocRotScale(loc, rot, scale)
        error = max(abs(matrix[i][j] - rebuilt[i][j]) for i in range(4) for j in range(4))
        if min(scale) <= 0 or max(scale) - min(scale) > 1e-5 or error > 1e-5:
            raise ValueError(f'{name}: only positive uniform FK scale is supported')
    return {'rig': rig, 'side': side, 'names': names, 'basis': basis}


def _amounts(amount):
    keys = tuple(f.lower() for f in _FINGERS)
    if isinstance(amount, Mapping):
        unknown = set(amount) - set(keys)
        if unknown:
            raise ValueError(f'Unknown fingers: {sorted(unknown, key=str)}')
        raw = {key: float(amount.get(key, 0.0)) for key in keys}
    else:
        raw = dict.fromkeys(keys, float(amount))
    if not all(math.isfinite(value) for value in raw.values()):
        raise ValueError('Grip amount must be finite')
    def smooth(value):
        t = max(0.0, min(1.0, value))
        return t * t * (3.0 - 2.0 * t)
    return {key: smooth(value) for key, value in raw.items()}


def apply(rig, state, amount, *, angles=None):
    """Apply from captured bases, without accumulation; amount=0 resets.

    Only state['names'] are written, using matrix_basis. Wrist/arm, FK/IK
    switches and rotation modes are untouched. Default thumb angles are zero.
    Call after Performer.pose(), then bpy.context.view_layer.update() outside.
    """
    if state['rig'] != rig:
        raise ValueError('Grip state belongs to a different rig; capture each actor separately')
    _require_fk(rig, state['side'])
    amounts = _amounts(amount)  # Validate all inputs before writing any bone.
    targets = {f.lower(): (0.,0.,0.) if f=='Thumb' else _CURL_DEGREES for f in _FINGERS}
    if angles is not None:
        if set(angles)-set(targets): raise ValueError('Unknown finger in angles')
        for finger, values in angles.items():
            values=tuple(float(x) for x in values)
            if len(values)!=3 or not all(math.isfinite(x) for x in values):
                raise ValueError('Each finger needs three finite local-X angles')
            targets[finger]=values
    matrices = {}
    for finger in _FINGERS:
        for joint in (1, 2, 3):
            name = f'FK-{finger}{joint}.{state["side"]}'
            basis = state['basis'][name]
            t = amounts.get(finger.lower(), 0.0)
            if t == 0.0:
                matrices[name] = basis.copy()
            else:
                angle = math.radians(targets[finger.lower()][joint - 1]) * t
                matrices[name] = basis @ Quaternion((1, 0, 0), angle).to_matrix().to_4x4()
    for name, matrix in matrices.items():
        rig.pose.bones[name].matrix_basis = matrix
