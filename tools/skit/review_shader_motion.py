"""Assemble short, aligned shader comparisons against existing graded frames.

Each --segment is FOLDER START STOP (half-open); cuts between segments are
intentional. FOLDER '-' explicitly keeps baseline frames on both sides.
Raw candidates receive daylight once; the baseline must already be graded.
"""
import argparse
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw
from chase_look import ChaseLook


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--segment', nargs=3, action='append', required=True)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--prefix', default='candidate_', help='Raw candidate filename prefix')
    p.add_argument('--label', default='shader candidate')
    args = p.parse_args()
    if args.fps <= 0:
        raise ValueError('Positive FPS required')
    pairs = []
    for folder, start, stop in args.segment:
        start, stop = int(start), int(stop)
        if start < 0 or stop <= start:
            raise ValueError('Invalid half-open segment')
        pairs.extend((f, None if folder == '-' else Path(folder)/f'{args.prefix}{f:04d}.png',
                      args.baseline/f'f{f:04d}.png') for f in range(start, stop))
    for _, new, old in pairs:
        if (new is not None and not new.is_file()) or not old.is_file():
            raise ValueError('Missing comparison frame')
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=False)
    frames = out/'frames';frames.mkdir()
    look = ChaseLook(None, 'daylight')
    rows = []
    for i, (f, new, old) in enumerate(pairs):
        with Image.open(old) as im:
            baseline = im.convert('RGB')
        if new is None:
            rgb = np.asarray(baseline)
        else:
            with Image.open(new) as im:
                rgb = look(np.asarray(im.convert('RGB')))
        if rgb.shape != (640,360,3) or baseline.size != (360,640):
            raise ValueError('Expected matching 360x640 study frames')
        sheet = Image.new('RGB', (720,660), '#202020')
        sheet.paste(baseline,(0,20));sheet.paste(Image.fromarray(rgb),(360,20))
        d = ImageDraw.Draw(sheet)
        d.text((8,3),'baseline',fill='white');d.text((368,3),args.label,fill='white')
        sheet.save(frames/f'f{i:04d}.png')
        rows.append(dict(frame=f,baseline_context=new is None,mean=float(rgb.mean()),
                         channel_limit_fraction=float((rgb>=254).any(axis=2).mean())))
    ff = imageio_ffmpeg.get_ffmpeg_exe();video=out/'comparison.mp4'
    subprocess.run([ff,'-v','error','-framerate',str(args.fps),'-i',str(frames/'f%04d.png'),
                    '-frames:v',str(len(pairs)),'-an','-c:v','libx264','-crf','18',
                    '-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True)
    raw = subprocess.check_output([ff,'-v','error','-i',str(video),'-vf','scale=360:330',
                                   '-pix_fmt','rgb24','-f','rawvideo','-'])
    decoded = np.frombuffer(raw,np.uint8).reshape(-1,330,360,3)
    if len(decoded) != len(pairs):
        raise ValueError('Decoded frame count mismatch')
    for first in range(0,len(decoded),15):
        sheet=Image.new('RGB',(1800,990),'#202020')
        for j,frame in enumerate(decoded[first:first+15]):
            sheet.paste(Image.fromarray(frame),((j%5)*360,(j//5)*330))
        sheet.save(out/f'review_{first:04d}.jpg',quality=92)
    (out/'report.json').write_text(json.dumps(dict(frames=rows,fps=args.fps,
        decoded_count=len(decoded),limits='Short excerpts only; deliberate segment cuts. '
        'No audio. Camera/pose alignment and artistic quality require separate review.'),indent=2),encoding='utf-8')
    print(f'Decoded {len(decoded)} comparison frames; review sheets saved.')


if __name__ == '__main__':
    main()
