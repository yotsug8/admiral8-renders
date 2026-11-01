"""Assemble a silent learning report from verified clips, without retiming.

Report headings are separate from production-scene subtitle settings.
Use --assets for the renders branch checkout and --font for a Cyrillic TTF.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--font', type=Path, required=True)
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    assets, out = args.assets.resolve(), args.out.resolve()
    clips = recipe['clips']
    if not clips or recipe['fps'] != 30:
        raise ValueError('Nonempty 30 fps report required')
    # Validate all inputs before creating any output. Paths remain under assets.
    sources = []
    for item in clips:
        source = (assets/item['file']).resolve()
        source.relative_to(assets)
        if not source.is_file() or item['frames'] <= 0:
            raise ValueError('Missing clip or invalid frame count')
        reader = imageio_ffmpeg.read_frames(str(source), pix_fmt='rgb24')
        try:
            meta = next(reader)
            if abs(meta['fps']-30) > .001:
                raise ValueError('Retiming is not allowed')
            count = sum(1 for _ in reader)
        finally:
            reader.close()
        if count != item['frames']:
            raise ValueError(f'Frame count differs: {item["file"]}: {count}')
        sources.append(source)
    title_font = ImageFont.truetype(str(args.font), 27)
    detail_font = ImageFont.truetype(str(args.font), 19)
    out.mkdir(parents=True, exist_ok=False)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    records, parts, cuts, total = [], [], [], 0
    for index, (item, source) in enumerate(zip(clips, sources)):
        banner = Image.new('RGB', (960, 80), '#141b23')
        draw = ImageDraw.Draw(banner)
        for text, y, font in [(item['title'], 7, title_font), (item['limit'], 44, detail_font)]:
            if draw.textbbox((0, 0), text, font=font)[2] > 924:
                raise ValueError('Report heading does not fit: '+text)
            draw.text((18, y), text, font=font, fill='#f0f1f2')
        heading = out/f'heading_{index:02d}.png'
        banner.save(heading)
        part = out/f'part_{index:02d}.mp4'
        graph = ('[0:v]scale=960:540:force_original_aspect_ratio=decrease,'
                 'pad=960:540:(ow-iw)/2:(oh-ih)/2:color=0x141b23,setsar=1[clip];'
                 '[1:v][clip]vstack=inputs=2[v]')
        subprocess.run([ff, '-v', 'error', '-i', str(source), '-loop', '1', '-framerate', '30',
                        '-i', str(heading), '-filter_complex', graph, '-map', '[v]', '-an',
                        '-frames:v', str(item['frames']), '-c:v', 'libx264', '-crf', '18',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(part)], check=True)
        cuts.append(total)
        total += item['frames']
        parts.append(part)
        records.append(dict(file=item['file'], frames=item['frames'],
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    # Generated basenames contain no user-provided shell/concat syntax.
    (out/'parts.txt').write_text(''.join(f"file '{p.name}'\n" for p in parts), encoding='utf-8')
    movie = out/'learning_progress.mp4'
    subprocess.run([ff, '-v', 'error', '-f', 'concat', '-safe', '1', '-i', str(out/'parts.txt'),
                    '-map', '0:v:0', '-an', '-c', 'copy', '-movflags', '+faststart', str(movie)], check=True)
    selected = set(range(0, total, 30)) | {total-1} | set(cuts)
    selected.update(f-1 for f in cuts if f)
    thumbnails = []
    reader = imageio_ffmpeg.read_frames(str(movie), pix_fmt='rgb24')
    count = 0
    try:
        meta = next(reader)
        if tuple(meta['size']) != (960, 620) or abs(meta['fps']-30) > .001:
            raise ValueError('Unexpected report format')
        for count, frame in enumerate(reader, 1):
            if count-1 in selected:
                img = Image.frombytes('RGB', (960, 620), frame)
                img.thumbnail((320, 207))
                thumbnails.append((count-1, img))
    finally:
        reader.close()
    if count != total:
        raise ValueError('Concatenation lost frames')
    sheet = Image.new('RGB', (1280, 228*((len(thumbnails)+3)//4)), '#141b23')
    draw = ImageDraw.Draw(sheet)
    for i, (frame, img) in enumerate(thumbnails):
        x, y = i%4*320, i//4*228
        draw.text((x+3, y+2), f'{frame} / {frame/30:.2f}s', fill='white')
        sheet.paste(img, (x, y+20))
    sheet.save(out/'review.jpg', quality=92)
    report = dict(frames=total, fps=30, duration=total/30, cuts=cuts, sources=records,
                  sha256=hashlib.sha256(movie.read_bytes()).hexdigest(),
                  scope='Silent report, source motion unchanged; frame counts verified. Not new animation acceptance.')
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
