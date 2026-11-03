"""Combine verified shot patches without copying or overwriting the base cache."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/skits/doomsday/v12/assembled'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = OUT / 'delivery_frames'
    target.mkdir(exist_ok=True)
    rows = []
    for frame in range(420):
        folder = 'finished_frames'
        if 45 <= frame < 120:
            folder = 'weapon_patch'
        if 120 <= frame < 195 or 295 <= frame < 330 or 360 <= frame < 420:
            folder = 'acting_camera_patch'
        source = OUT / folder / f'{frame:04d}.png'
        if not source.is_file():
            raise ValueError(f'Missing delivery frame: {folder}/{source.name}')
        expected = digest(source)
        destination = target / source.name
        if destination.exists():
            if digest(destination) != expected:
                raise ValueError(f'Different existing frame: {destination.name}; preserve this delivery cache')
        else:
            os.link(source, destination)
        rows.append({'frame': frame, 'source': f'{folder}/{source.name}', 'sha256': expected})
    report = {'frames': 420, 'fps': 30, 'size': [1280, 720],
              'base_settings': json.loads((OUT / 'finished_frames/settings.json').read_text(encoding='utf8')),
              'final_scene_sha256': digest(OUT / 'material_framed.blend'),
              'patches': {'weapon_patch': [[45, 119]],
                          'acting_camera_patch': [[120, 194], [295, 329], [360, 419]]},
              'frame_sources': rows}
    (target / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps({'frames': len(rows), 'base_frames_retained': 175,
                      'patched_frames': 245, 'additional_image_copies': 0}))


if __name__ == '__main__':
    main()
