"""Plan game sounds from explicit foot contacts; never infer gait timing.

Records: {who: actor key, at: scene seconds, foot: 'L'/'R', gain: 0..1}.
Only Pudge has local samples. Sample selection cycles over all four names,
independently of file availability, so restoring files cannot reshuffle steps.
"""
import math
from pathlib import Path


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected a finite number")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label}: expected a finite number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label}: expected a finite number")
    return value


def plan_footsteps(scene, sfx_dir, report=print):
    """Return (sample name, seconds, gain) in chronological contact order.

    Missing metadata is a no-op. Invalid explicit records raise ValueError;
    unsupported heroes and missing local files are reported and skipped.
    Equal-time contacts retain input order. Default gain is 0.5.
    """
    if 'footsteps' not in scene:
        return []
    records = scene['footsteps']
    if not isinstance(records, list):
        raise ValueError('footsteps: expected a list')
    duration = _number(scene.get('dur'), 'footsteps scene duration')
    if duration <= 0:
        raise ValueError('footsteps scene duration: must be positive')
    actors = scene.get('actors', {})
    contacts = []
    for index, record in enumerate(records):
        label = f'footsteps[{index}]'
        if not isinstance(record, dict):
            raise ValueError(f'{label}: expected a record')
        who = record.get('who')
        if not isinstance(who, str) or who not in actors:
            raise ValueError(f'{label}.who: unknown actor')
        if record.get('foot') not in ('L', 'R'):
            raise ValueError(f'{label}.foot: expected L or R')
        at = _number(record.get('at'), f'{label}.at')
        gain = _number(record.get('gain', 0.5), f'{label}.gain')
        if not 0 <= at < duration:
            raise ValueError(f'{label}.at: must be in [0, scene duration)')
        if not 0 <= gain <= 1:
            raise ValueError(f'{label}.gain: must be in [0, 1]')
        contacts.append((at, index, who, gain))
    planned = []
    counts = {}
    for at, index, who, gain in sorted(contacts):
        hero = actors[who].get('hero')
        if hero != 'pudge':
            report(f'  шаг пропущен: {who}, герой {hero!r} — нет набора звуков')
            continue
        step = counts.get(who, 0)
        counts[who] = step + 1
        name = f'step{step % 4 + 1:02d}'
        if not (Path(sfx_dir) / name).is_file():
            report(f'  шаг пропущен: нет локального звука {name} ({who}, {at:.3f} с)')
            continue
        planned.append((name, at, gain))
    return planned
