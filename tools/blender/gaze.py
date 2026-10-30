"""Pure gaze validation/compositing; no Blender dependencies or random draws.

Coordinates follow existing FACS: +x=eyeRight, -x=eyeLeft,
+y=eyeUp, -y=eyeDown. Entries retain input order: a later entry is
composited over earlier entries, with its own smooth attack/release.
Short windows may have overlapping ramps and never reach full strength.
"""

import math
from numbers import Real


EYE_CHANNELS = ('eyeRight', 'eyeLeft', 'eyeUp', 'eyeDown')


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'gaze {label} must be a finite number')
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f'gaze {label} must be a finite number') from exc
    if not math.isfinite(value):
        raise ValueError(f'gaze {label} must be a finite number')
    return value


def prepare_gazes(entries, actor, known_actors=None):
    """Validate every entry, then return immutable tuples for one actor.

    Unknown actors are errors when the scene supplies an actor mapping/set.
    Without that mapping the caller can only filter by exact actor name.
    Tuple layout: start, end, x, y, attack, release.
    """
    if entries is None:
        return ()
    if not isinstance(entries, (list, tuple)):
        raise ValueError('gazes must be a list of objects')
    result = []
    for index, event in enumerate(entries):
        if not isinstance(event, dict):
            raise ValueError(f'gaze {index} must be an object')
        who = event.get('who')
        if not isinstance(who, str) or not who:
            raise ValueError(f'gaze {index} needs an actor name')
        if known_actors is not None and who not in known_actors:
            raise ValueError(f'gaze {index}: unknown actor {who!r}')
        try:
            start = _number(event['start'], 'start')
            end = _number(event['end'], 'end')
            x = _number(event['x'], 'x')
            y = _number(event['y'], 'y')
        except KeyError as exc:
            raise ValueError(f'gaze {index}: missing {exc.args[0]}') from exc
        attack = _number(event.get('attack', .12), 'attack')
        release = _number(event.get('release', .18), 'release')
        if start < 0 or end <= start:
            raise ValueError(f'gaze {index}: require 0 <= start < end')
        if attack <= 0 or release <= 0:
            raise ValueError(f'gaze {index}: attack/release must be positive')
        if not -1 <= x <= 1 or not -1 <= y <= 1:
            raise ValueError(f'gaze {index}: x/y must be within [-1, 1]')
        if who == actor:
            result.append((start, end, x, y, attack, release))
    return tuple(result)


def _smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def blend_gaze(random_channels, time, gazes):
    """Return FACS random-gaze channels blended toward each active target.

    The original mapping object is returned outside all active ramps. Channel
    blending also preserves rare legacy frames receiving two random segments.
    No caller-owned data is mutated; unrelated mapping entries are retained.
    """
    result = random_channels
    for start, end, target_x, target_y, attack, release in gazes:
        if not start < time < end:
            continue
        weight = _smoothstep((time - start) / attack) * _smoothstep((end - time) / release)
        if weight <= 0.0:
            continue
        if result is random_channels:
            result = dict(random_channels)
        target = gaze_channels(target_x, target_y)
        for channel in EYE_CHANNELS:
            old = result.get(channel, 0.0)
            result[channel] = (target[channel] if weight == 1.0 else
                               old + (target[channel] - old) * weight)
    return result


def gaze_channels(x, y):
    """Same signed-coordinate to FACS mapping as the legacy random gaze."""
    return dict(zip(EYE_CHANNELS, (max(0, x), max(0, -x), max(0, y), max(0, -y))))
