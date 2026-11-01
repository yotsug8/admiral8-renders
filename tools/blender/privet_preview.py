"""Build the greeting with the established skit renderer and save draft probes."""
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/skits/privet'
os.environ['A8_BLEND'] = str(OUT / 'privet.blend')
os.environ['A8_SAMPLES'] = '48'
sys.argv = ['render_scene.py', '--', str(OUT / 'scene.json'),
            str(OUT / 'frames'), 'all', 'half']
try:
    runpy.run_path(str(ROOT / 'tools/blender/render_scene.py'), run_name='__main__')
except SystemExit as exc:
    if exc.code not in (None, 0):
        raise

import bpy
scene = bpy.context.scene
data = json.loads((OUT / 'scene.json').read_text(encoding='utf-8'))
ends = [shot[0] for shot in data['shots'][1:]] + [data['frames'] / data['fps']]
frames = [round((shot[0] + end) / 2 * data['fps'])
          for shot, end in zip(data['shots'], ends)]
for frame in frames:
    scene.frame_set(frame)
    scene.render.filepath = str(OUT / f'probe_{frame:05d}.png')
    bpy.ops.render.render(write_still=True)
print('GREETING_PROBES', frames, flush=True)
