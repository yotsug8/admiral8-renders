"""Assemble the greeting draft and inspect every frame plus one image per second."""
import json
import os
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/skits/privet'
FF = imageio_ffmpeg.get_ffmpeg_exe()
data = json.loads((OUT / 'scene.json').read_text(encoding='utf-8'))
count, fps = data['frames'], data['fps']
if '--qa-only' not in sys.argv and (OUT / 'layers.json').exists():
    layers = json.loads((OUT / 'layers.json').read_text(encoding='utf-8'))
    plates = [Image.open(OUT / f'plate_{index}.png').convert('RGBA')
              for index in range(len(layers['cuts']) - 1)]
    (OUT / 'frames').mkdir(exist_ok=True)
    for index in range(count):
        shot = max(i for i, cut in enumerate(layers['cuts'][:-1]) if cut <= index)
        with Image.open(OUT / 'layers' / f'f{index:05d}.png') as actor:
            Image.alpha_composite(plates[shot], actor.convert('RGBA')).convert('RGB').save(
                OUT / 'frames' / f'f{index:05d}.png')
sizes, dark, changes, previous = set(), [], [], None
for index in range(count):
    with Image.open(OUT / 'frames' / f'f{index:05d}.png') as im:
        im.load()
        sizes.add(im.size)
        sample = np.asarray(im.convert('RGB').resize((36, 64)), dtype=float)
        if sample.mean() < 3:
            dark.append(index)
        if previous is not None:
            changes.append((index, round(float(np.abs(sample - previous).mean()), 3)))
        previous = sample
assert len(sizes) == 1 and not dark, (sizes, dark)
raw = OUT / 'privet_raw.mp4'
final = OUT / 'privet_draft.mp4'
if '--qa-only' not in sys.argv:
    subprocess.run([FF, '-y', '-v', 'error', '-framerate', str(fps), '-start_number', '0',
                '-i', str(OUT / 'frames/f%05d.png'), '-frames:v', str(count),
                '-c:v', 'libx264', '-crf', '14', '-pix_fmt', 'yuv420p', str(raw)], check=True)
    subprocess.run([sys.executable, str(ROOT / 'tools/skit/mix.py'), str(raw), str(final),
                str(OUT / 'scene.json')], env=dict(os.environ, GRADE='match'), check=True)

reader = imageio_ffmpeg.read_frames(str(final), pix_fmt='rgb24')
meta = next(reader)
size = meta['size']
selected = []
decoded = 0
for index, raw_frame in enumerate(reader):
    if index % fps == 0 or index == count - 1:
        selected.append((index, Image.frombytes('RGB', size, raw_frame).resize((216, 384))))
    decoded += 1
# The existing mixer trims to the audio timeline, whose endpoint can fall
# between two frames. Only that single trailing frame may be omitted.
assert decoded in (count, count - 1), (decoded, count)
sheet = Image.new('RGB', (216 * 6, 410 * ((len(selected) + 5) // 6)), (22, 23, 26))
draw = ImageDraw.Draw(sheet)
for n, (index, im) in enumerate(selected):
    x, y = (n % 6) * 216, (n // 6) * 410
    sheet.paste(im, (x, y + 24))
    draw.text((x + 8, y + 5), f'{index / fps:.2f}s / {index}', fill='white')
sheet.save(OUT / 'review.jpg', quality=92)
meter = subprocess.run([FF, '-hide_banner', '-i', str(final), '-af',
                        'loudnorm=I=-14:TP=-1:LRA=11:print_format=json',
                        '-f', 'null', '-'], capture_output=True, text=True)
(OUT / 'audio_meter.txt').write_text(meter.stderr, encoding='utf-8')
report = {'source_frames': count, 'decoded': decoded, 'fps': fps, 'size': list(size),
          'seconds': decoded / fps, 'mux_tail_frames_trimmed': count - decoded, 'dark_frames': dark,
          'largest_frame_changes': sorted(changes, key=lambda x: -x[1])[:12],
          'limitations': 'Frame decoding and sampling do not certify all anatomy or collisions.'}
(OUT / 'delivery_qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False), flush=True)
print(final, flush=True)
