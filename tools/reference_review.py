"""Create timestamped visual evidence; never claims playback or artistic approval."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageOps


def sample_times(duration, count, explicit=None):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Video duration must be positive and finite')
    if not 2 <= count <= 24:
        raise ValueError('Sample count must be between 2 and 24')
    times = explicit if explicit is not None else [
        duration * i / count for i in range(count)]
    if not times or len(times) > 24 or any(
            not math.isfinite(t) or t < 0 or t >= duration for t in times):
        raise ValueError('Use 1-24 finite timestamps within the video duration')
    return sorted(set(times))


def review(source, label, out, count=12, times=None):
    source = Path(source).resolve(strict=True)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', label):
        raise ValueError('Use a neutral ID: letters, digits, underscore or hyphen')
    info = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format',
        '-of', 'json', str(source)]))
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    if video is None:
        raise ValueError('No video stream')
    duration = float(info['format']['duration'])
    timestamps = sample_times(duration, count, times)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    width, height, header = 240, 426, 24
    columns = min(4, len(timestamps))
    sheet = Image.new('RGB', (columns * width,
                     math.ceil(len(timestamps) / columns) * (height + header)), '#171717')
    samples = []
    for index, second in enumerate(timestamps):
        raw = subprocess.check_output([
            'ffmpeg', '-nostdin', '-v', 'error', '-ss', str(second), '-i', str(source),
            '-map', '0:v:0', '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', '-'])
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            frame = image.convert('RGB')
        name = f'{label}-{index:02d}.png'
        frame.save(out / name)
        thumb = ImageOps.contain(frame, (width, height))
        x, y = index % columns * width, index // columns * (height + header)
        sheet.paste(thumb, (x + (width-thumb.width)//2, y+header+(height-thumb.height)//2))
        ImageDraw.Draw(sheet).text((x+5, y+5), f'{label}  {second:.3f}s', fill='white')
        samples.append({'requested_seconds': second, 'file': name})
    sheet.save(out / 'sheet.jpg', quality=92)
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    report = {
        'id': label, 'source_sha256': digest, 'duration': duration,
        'size': [video['width'], video['height']], 'fps': video['avg_frame_rate'],
        'has_audio': any(s['codec_type'] == 'audio' for s in info['streams']),
        'samples': samples, 'playback_review': 'not performed by this tool',
        'audio_review': 'not performed', 'artistic_review': 'pending',
        'limits': 'Discrete frames only; timestamps are requested seek positions. '
                  'Labels do not anonymize embedded watermarks or metadata.'}
    (out / 'evidence.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--id', required=True, help='Neutral reference ID, no channel name')
    parser.add_argument('--out', required=True, type=Path, help='New local evidence folder')
    parser.add_argument('--count', type=int, default=12)
    parser.add_argument('--times', type=float, nargs='+')
    args = parser.parse_args()
    try:
        report = review(args.source, args.id, args.out, args.count, args.times)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Review preparation failed: {exc}\n')
    print(f"{report['id']}: {len(report['samples'])} samples; {args.out / 'sheet.jpg'}")


if __name__ == '__main__':
    main()
