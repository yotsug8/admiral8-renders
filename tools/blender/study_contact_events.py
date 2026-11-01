"""Convert explicit gait surface-band entries into paired footstep events.

Run with Blender: -b scene.blend --python-exit-code 1 -P this_script.py --
    --gait side.json --gait front.json --actor-root hoodwink_root --out events.json
No rendering, scene saving, bone-height inference, or audio synthesis.
"""
import argparse
import json
import math
from pathlib import Path
import sys


METHOD = ('Evaluated paired paw surface-band entries, separately per continuous '
          'shot; camera-projected pan.')
PAIR_WINDOW_S = 0.05


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label}: expected a finite number')
    if not math.isfinite(value):
        raise ValueError(f'{label}: expected a finite number')
    return value


def load_gait(path):
    """Validate the subset consumed from gait_metrics reports; ignore diagnostics."""
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path.name}: expected an object')
    actor = data.get('actor')
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError(f'{path.name}: missing actor')
    fps = number(data.get('fps'), 'fps')
    if fps <= 0:
        raise ValueError('fps must be positive')
    frames = data.get('frames')
    if not isinstance(frames, list) or len(frames) != 2:
        raise ValueError('frames must contain [start, end]')
    start, end = [number(v, 'frames') for v in frames]
    if start < 0 or end <= start:
        raise ValueError('frames must be nonnegative and increasing')
    paws = data.get('paws')
    if not isinstance(paws, dict):
        raise ValueError('missing paws object')
    contacts = {}
    for prefix in ('hand', 'ankle'):
        for side in ('L', 'R'):
            key = f'{prefix}_{side}'
            paw = paws.get(key)
            times = paw.get('contact_entry_times_s') if isinstance(paw, dict) else None
            if not isinstance(times, list):
                raise ValueError(f'{key}: missing contact_entry_times_s array')
            previous = -math.inf
            for t in times:
                number(t, key)
                if t < 0 or t <= previous:
                    raise ValueError(f'{key}: times must be nonnegative and strictly increasing')
                if not start / fps - 1e-9 <= t <= end / fps + 1e-9:
                    raise ValueError(f'{key}: time outside report frame range')
                previous = t
            contacts[key] = times
    return actor, fps, (start, end), contacts


def paired_entries(contacts):
    """Legacy greedy left-order pairing; ties use the earliest unused right index."""
    for prefix in ('hand', 'ankle'):
        used = set()
        for t in contacts[f'{prefix}_L']:
            matches = [(abs(t-r), i, r)
                       for i, r in enumerate(contacts[f'{prefix}_R'])
                       if i not in used and abs(t-r) <= PAIR_WINDOW_S]
            if not matches:
                continue
            _, i, r = min(matches)
            used.add(i)
            yield prefix + '_pair', (t+r)/2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gait', type=Path, action='append', required=True,
                        help='One gait_metrics JSON per continuous shot; repeat in shot order')
    parser.add_argument('--actor-root', required=True)
    parser.add_argument('--out', type=Path, required=True, help='Output JSON file')
    args = parser.parse_args(argv)

    import bpy
    from bpy_extras.object_utils import world_to_camera_view

    if not bpy.data.filepath:
        raise ValueError('Load the scene first with blender -b scene.blend')
    inputs = [p.resolve() for p in args.gait]
    if len(set(inputs)) != len(inputs):
        raise ValueError('Duplicate gait input')
    if args.out.resolve() in {*inputs, Path(bpy.data.filepath).resolve(), Path(__file__).resolve()}:
        raise ValueError('Output must not overwrite an input or the script')
    reports = [load_gait(p) for p in args.gait]
    sc = bpy.context.scene
    root = sc.objects.get(args.actor_root)
    if root is None:
        raise ValueError(f'Actor root not found in active scene: {args.actor_root}')
    fps = sc.render.fps / sc.render.fps_base
    previous_end = -math.inf
    for actor, report_fps, (start, end), _ in reports:
        if actor != reports[0][0]:
            raise ValueError('Gait reports must describe the same actor')
        if not math.isclose(report_fps, fps, rel_tol=0, abs_tol=1e-9):
            raise ValueError('Gait fps does not match scene fps / fps_base')
        if start <= previous_end:
            raise ValueError('Shot ranges must be ordered and nonoverlapping')
        previous_end = end

    events = []
    saved_frame, saved_subframe, saved_camera = sc.frame_current, sc.frame_subframe, sc.camera
    try:
        for actor, _, _, contacts in reports:
            for foot, at in paired_entries(contacts):
                # Absolute timeline seconds, with no frame_start offset.
                f = at * fps
                sc.frame_set(math.floor(f), subframe=f % 1)
                bpy.context.view_layer.update()
                camera = sc.camera  # frame_set also applies shot camera markers.
                if camera is None or camera.type != 'CAMERA':
                    raise ValueError(f'No active camera at {at:g}s')
                point = root.matrix_world.translation
                uv = world_to_camera_view(sc, camera, point)
                distance = (camera.matrix_world.translation-point).length
                if not all(math.isfinite(v) for v in (*point, *uv, distance)) or distance <= 0:
                    raise ValueError(f'Invalid camera projection or zero distance at {at:g}s')
                events.append(dict(who=actor, at=at, foot=foot,
                                   gain=.55*max(.4, min(1., 8/distance)),
                                   pan=max(-.8, min(.8, 2*uv.x-1))))
    finally:
        sc.frame_set(saved_frame, subframe=saved_subframe)
        sc.camera = saved_camera
        bpy.context.view_layer.update()
    report = dict(footsteps=sorted(events, key=lambda e: e['at']), method=METHOD,
                  sources=[p.name for p in args.gait])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('FOOT_EVENTS', len(events), flush=True)


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
