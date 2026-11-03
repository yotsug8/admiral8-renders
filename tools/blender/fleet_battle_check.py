"""CPU continuity checks for the fleet. Not an artistic or collision certificate."""
import hashlib
import json
import math
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/skits/fleet_battle'


def main():
    scene_path = OUT / 'scene.blend'
    bpy.ops.wm.open_mainfile(filepath=str(scene_path), use_scripts=False)
    sc = bpy.context.scene
    meta = json.loads((OUT / 'staging.json').read_text())
    roots = [bpy.data.objects[a['root']] for a in meta['actors']]
    previous = {}
    jumps = []
    failures = []
    for frame in range(meta['count']):
        sc.frame_set(frame)
        for root in roots:
            position = root.matrix_world.translation.copy()
            rotation = root.matrix_world.to_quaternion()
            if not all(math.isfinite(x) for x in (*position, *rotation)):
                failures.append(dict(frame=frame, actor=root.name, issue='nonfinite transform'))
            if root.name in previous:
                p, q = previous[root.name]
                angle = math.degrees(q.rotation_difference(rotation).angle)
                angle = min(angle, 360-angle)
                distance = (position-p).length
                jumps.append(dict(frame=frame, actor=root.name, angle_deg=angle, distance=distance))
                if angle > 30 or distance > 1.2:
                    failures.append(jumps[-1])
            previous[root.name] = (position, rotation)
    report = dict(
        scene_sha256=hashlib.sha256(scene_path.read_bytes()).hexdigest(),
        checked_frames=meta['count'], actors=len(roots),
        max_angular_step=max(jumps,key=lambda x:x['angle_deg']),
        max_position_step=max(jumps,key=lambda x:x['distance']),
        failures=failures, passed=not failures,
        scope='Placement continuity only. Does not cover skin, contacts, framing, sound or acting.',
    )
    (OUT/'continuity.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    if failures:
        raise RuntimeError('Placement continuity failed')


if __name__ == '__main__':
    main()
