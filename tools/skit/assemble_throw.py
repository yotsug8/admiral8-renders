"""Encode a silent four-second comparison and check every decoded frame.

Top: mechanical control. Bottom: anticipation, arc and follow-through.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mechanical',required=True,type=Path)
    p.add_argument('--staged',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    args=p.parse_args();folders=[args.mechanical.resolve(),args.staged.resolve()]
    for folder in folders:
        if not json.loads((folder/'audit.json').read_text())['passed']:
            raise ValueError('Passing scene audit required')
        expected=[folder/'frames'/f'frame_{i:04d}.png' for i in range(120)]
        if any(not x.is_file() or not x.stat().st_size for x in expected):
            raise ValueError('Missing frame')
        if len(list((folder/'frames').glob('frame_*.png')))!=120:
            raise ValueError('Unexpected frame count')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    movie=out/'throw_comparison.mp4';ff=imageio_ffmpeg.get_ffmpeg_exe()
    command=[ff,'-v','error']
    for folder in folders:command+=['-framerate','30','-start_number','0','-i',str(folder/'frames/frame_%04d.png')]
    command+=['-filter_complex','[0:v][1:v]vstack=inputs=2[v]','-map','[v]','-frames:v','120',
              '-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)]
    subprocess.run(command,check=True)
    reader=imageio_ffmpeg.read_frames(str(movie),pix_fmt='rgb24');meta=next(reader)
    if meta['size']!=(960,1080) or abs(meta['fps']-30)>.001:raise ValueError('Wrong video format')
    count=0;worst=0.;sheet=None
    try:
        for i,data in enumerate(reader):
            if i>=120:raise ValueError('Extra encoded frame')
            im=Image.frombytes('RGB',meta['size'],data)
            for j,folder in enumerate(folders):
                actual=np.array(im.crop((0,540*j,960,540*(j+1))).resize((160,90),Image.Resampling.LANCZOS),dtype=float)
                with Image.open(folder/'frames'/f'frame_{i:04d}.png') as source:
                    expected=np.array(source.convert('RGB').resize((160,90),Image.Resampling.LANCZOS),dtype=float)
                worst=max(worst,float(abs(actual-expected).mean()))
            if i%20==0:sheet=Image.new('RGB',(1200,1160),'#202833')
            x=(i%5)*240;y=((i%20)//5)*290
            sheet.paste(im.resize((240,270),Image.Resampling.LANCZOS),(x,y+20))
            ImageDraw.Draw(sheet).text((x+5,y+3),str(i),fill='white')
            if i%20==19:sheet.save(out/f'qa_{i//20:02d}.jpg',quality=90)
            count+=1
    finally:reader.close()
    report={'decoded_frames':count,'fps':meta['fps'],'max_frame_mean_error_255':worst,
            'sha256':hashlib.sha256(movie.read_bytes()).hexdigest(),
            'passed':count==120 and worst<3.,'audio':False}
    (out/'qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not report['passed']:raise ValueError(report)
    print(json.dumps(report))


if __name__=='__main__':main()
