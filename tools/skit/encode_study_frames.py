"""Encode a checked silent PNG study; compare every decoded frame to its source."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--count',type=int,required=True)
    args=ap.parse_args();source=args.source.resolve();out=args.out.resolve()
    if args.count<1 or not json.loads((source/'audit.json').read_text())['passed']:
        raise ValueError('Passing audit and positive frame count required')
    files=[source/'frames'/f'frame_{i:04d}.png' for i in range(args.count)]
    if any(not p.is_file() for p in files) or len(list((source/'frames').glob('frame_*.png')))!=args.count:
        raise ValueError('Incomplete frame sequence')
    with Image.open(files[0]) as im:size=im.size
    if any(n%2 for n in size):raise ValueError('Even dimensions required')
    out.mkdir(parents=True,exist_ok=False);movie=out/'study.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-framerate','30','-start_number','0',
        '-i',str(source/'frames/frame_%04d.png'),'-frames:v',str(args.count),'-an','-c:v','libx264',
        '-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)],check=True)
    reader=imageio_ffmpeg.read_frames(str(movie),pix_fmt='rgb24');meta=next(reader)
    if meta['size']!=size or abs(meta['fps']-30)>.001:raise ValueError('Wrong output format')
    thumb=(320,round(320*size[1]/size[0]));cell_h=thumb[1]+20
    worst=0.;count=0;minimum=255.
    try:
        for i,data in enumerate(reader):
            if i>=args.count:raise ValueError('Extra frame')
            im=Image.frombytes('RGB',size,data)
            small=np.asarray(im.resize((160,90)),dtype=float)
            minimum=min(minimum,float(small.mean()))
            with Image.open(files[i]) as original:
                if original.size!=size:raise ValueError('Source dimensions changed')
                worst=max(worst,float(np.abs(small-np.asarray(original.convert('RGB').resize((160,90)),dtype=float)).mean()))
            if i%15==0:sheet=Image.new('RGB',(thumb[0]*5,cell_h*3),'#202833')
            x=(i%5)*thumb[0];y=(i%15//5)*cell_h
            sheet.paste(im.resize(thumb),(x,y+20));ImageDraw.Draw(sheet).text((x+4,y+3),str(i),fill='white')
            if i%15==14 or i==args.count-1:sheet.save(out/f'qa_{i//15:02d}.jpg',quality=93)
            count+=1
    finally:reader.close()
    report=dict(frames=count,fps=meta['fps'],size=size,max_mean_error_255=worst,min_mean_255=minimum,
        sha256=hashlib.sha256(movie.read_bytes()).hexdigest(),passed=count==args.count and worst<3 and minimum>8,
        scope='Encoding and frame correspondence only; sheets require separate visual review. No audio.')
    (out/'qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not report['passed']:raise ValueError(report)
    print(json.dumps(report))


if __name__=='__main__':main()
