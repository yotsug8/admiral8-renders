"""Create sampled visual evidence or a full technical decode report; no artistic approval."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageOps


def technical_review(source, label, out):
    """Decode first video/audio streams fully; report clues, not artistic approval."""
    source = Path(source).resolve(strict=True)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', label):
        raise ValueError('Use a neutral ID: letters, digits, underscore or hyphen')
    info = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format',
        '-of', 'json', str(source)]))
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    if video is None:
        raise ValueError('No video stream')
    has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    command = ['ffmpeg', '-nostdin', '-hide_banner', '-v', 'info', '-xerror',
               '-i', str(source), '-map', '0:v:0', '-vf',
               'blackdetect=d=0.1:pix_th=0.10:pic_th=0.98,freezedetect=n=-50dB:d=0.2',
               '-fps_mode', 'passthrough']
    if has_audio:
        command += ['-map', '0:a:0', '-af', 'loudnorm=print_format=json']
    command += ['-progress', 'pipe:1', '-nostats', '-f', 'null', '-']
    run = subprocess.run(command, capture_output=True, text=True,
                         encoding='utf-8', errors='replace')
    (out / 'decode.log').write_text(run.stderr, encoding='utf-8')
    (out / 'progress.log').write_text(run.stdout, encoding='utf-8')
    black = [dict(zip(('start_s', 'end_s', 'duration_s'), map(float, row)))
             for row in re.findall(r'black_start:([\d.]+) black_end:([\d.]+) '
                                   r'black_duration:([\d.]+)', run.stderr)]
    freezes = []
    for kind, value in re.findall(r'lavfi\.freezedetect\.freeze_(start|end): ([\d.]+)', run.stderr):
        if kind == 'start':
            freezes.append({'start_s': float(value), 'end_s': None})
        elif freezes and freezes[-1]['end_s'] is None:
            freezes[-1]['end_s'] = float(value)
    audio = {'status': 'absent'}
    if has_audio:
        blocks = re.findall(r'\{\s*"input_i".*?\}', run.stderr, re.S)
        audio = {'status': 'not_measured'}
        if blocks:
            metrics = json.loads(blocks[-1])
            # Preserve '-inf' as a string (valid JSON and meaningful for silence).
            audio = {'status': 'measured', 'integrated_lufs': metrics['input_i'],
                     'true_peak_dbtp': metrics['input_tp'], 'range_lu': metrics['input_lra']}
    counts = re.findall(r'^frame=(\d+)$', run.stdout, re.M)
    decoded_frames = int(counts[-1]) if counts else None
    # Demuxers can report a truncated file as a warning and still exit 0.
    # progress=end means the process ended, not that all declared media survived.
    integrity_messages = [line for line in run.stderr.splitlines() if re.search(
        r'File ended prematurely|partial file|Packet corrupt|corrupt decoded frame|'
        r'Error while decoding|Error submitting packet|Invalid data found when processing input',
        line, re.I)]
    declared_frames = video.get('nb_frames', '')
    declared_frames = int(declared_frames) if str(declared_frames).isdigit() else None
    count_mismatch = (declared_frames is not None and declared_frames > 0
                      and decoded_frames != declared_frames)
    complete = (run.returncode == 0 and 'progress=end' in run.stdout
                and decoded_frames is not None and decoded_frames > 0
                and not integrity_messages and not count_mismatch)
    # Output progress covers the mapped streams together. Different stream tails,
    # timestamps and container metadata can explain a mismatch; do not diagnose
    # a render defect or fail solely from this approximate duration comparison.
    ends = re.findall(r'^out_time_us=(-?\d+)$', run.stdout, re.M)
    output_end = int(ends[-1]) / 1_000_000 if ends else None
    try:
        container_duration = float(info['format']['duration'])
        if not math.isfinite(container_duration) or container_duration <= 0:
            container_duration = None
    except (KeyError, ValueError, TypeError):
        container_duration = None
    duration_delta = (output_end - container_duration
                      if output_end is not None and container_duration is not None else None)
    report = {
        'id': label, 'source_sha256': digest, 'streams': info['streams'],
        'ffmpeg_version': subprocess.check_output(['ffmpeg', '-version'], text=True).splitlines()[0],
        'command': command, 'decode': 'completed' if complete else 'failed',
        'exit_code': run.returncode, 'decoded_video_frames': decoded_frames,
        'integrity_messages': integrity_messages,
        'declared_video_frames': declared_frames, 'frame_count_mismatch': count_mismatch,
        'duration_observation': {
            'declared_container_s': container_duration, 'decoded_output_end_s': output_end,
            'delta_s': duration_delta,
            'review_candidate': duration_delta is not None and abs(duration_delta) > .1,
            'interpretation': 'Diagnostic only; combined output progress is not per-stream duration '
                              'and metadata disagreement alone does not establish a render defect.'},
        'black_intervals': black, 'freeze_intervals': freezes, 'audio_metrics': audio,
        'playback_review': 'not performed', 'audio_review': 'not performed',
        'artistic_review': 'pending',
        'limits': 'First video and first audio stream only. Black/freeze detections are '
                  'review candidates, not defects: intentional pauses and fades also trigger. '
                  'An open freeze interval continues to the decoded end. No pose/contact, '
                  'sound identity, audio synchronization or artistic quality assessment. '
                  'Loudnorm output is discarded; input media is never changed.'}
    with source.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != digest:
            report['decode'] = 'invalidated_source_changed'
    (out / 'evidence.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def sample_times(duration, count, explicit=None):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Video duration must be positive and finite')
    if not 2 <= count <= 24:
        raise ValueError('Sample count must be between 2 and 24')
    # Include the closing beat without seeking into an audio-only container tail.
    last = duration - min(.1, duration / 2)
    times = explicit if explicit is not None else [
        last * i / (count - 1) for i in range(count)]
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
    duration = float(video.get('duration') or info['format']['duration'])
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
    parser.add_argument('--technical-only', action='store_true',
                        help='Full decode and technical clues; no screenshots or artistic approval')
    args = parser.parse_args()
    try:
        report = (technical_review(args.source, args.id, args.out) if args.technical_only
                  else review(args.source, args.id, args.out, args.count, args.times))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Review preparation failed: {exc}\n')
    if args.technical_only:
        print(f"{report['id']}: decode {report['decode']}; {args.out / 'evidence.json'}")
        if report['decode'] != 'completed':
            parser.exit(1)
    else:
        print(f"{report['id']}: {len(report['samples'])} samples; {args.out / 'sheet.jpg'}")


if __name__ == '__main__':
    main()
