"""Assemble the approved chase frames and local sound; produce visual review sheets.

Usage: python tools/blender/finish_chase.py --folder _game/skits/chase_finish
Requires 279 finished 1080x1920 PNGs and audio/chase_mix.wav (9.6 seconds).
"""
import argparse
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    args=parser.parse_args();folder=args.folder.resolve()
    frames=folder/'frames_full';audio=folder/'audio/chase_mix.wav'
    if not audio.is_file():raise ValueError('Missing final local audio')
    stats=[]
    for i in range(279):
        with Image.open(frames/f'f{i:04d}.png') as image:
            if image.size!=(1080,1920):raise ValueError(f'Wrong resolution at {i}')
            values=np.asarray(image.convert('RGB').resize((90,160)),dtype=float)
            mean=float(values.mean())
            if mean<8:raise ValueError(f'Unexpected dark/empty frame {i}: {mean}')
            stats.append(dict(frame=i,mean_rgb=mean))
    ff=imageio_ffmpeg.get_ffmpeg_exe()
    output=folder/'kunkka_hoodwink_chase.mp4'
    subprocess.run([ff,'-hide_banner','-loglevel','error','-y','-framerate','30',
                    '-start_number','0','-i',str(frames/'f%04d.png'),'-i',str(audio),
                    '-vf','tpad=stop_mode=add:stop_duration=0.3:color=black',
                    '-frames:v','288','-c:v','libx264','-preset','medium','-crf','17',
                    '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
                    '-movflags','+faststart',str(output)],check=True)
    samples=sorted(set([*range(0,279,30),65,66,98,99,125,126,143,144,191,192,239,240,278]))
    for page,start in enumerate(range(0,len(samples),8)):
        selected=samples[start:start+8];sheet=Image.new('RGB',(270*len(selected),505))
        draw=ImageDraw.Draw(sheet)
        for col,index in enumerate(selected):
            with Image.open(frames/f'f{index:04d}.png') as image:
                sheet.paste(image.convert('RGB').resize((270,480)),(col*270,25))
            draw.text((col*270+6,6),f'{index/30:.2f}s / {index}',fill='white')
        sheet.save(folder/f'review_{page}.jpg',quality=92)
    subprocess.run([ff,'-hide_banner','-loglevel','error','-y','-i',str(output),
                    '-vf','fps=8,scale=270:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse',
                    '-an',str(folder/'preview.gif')],check=True)
    (folder/'frame_review.json').write_text(json.dumps(dict(frames=stats,
        limitation='Brightness and dimensions only; review sheets require visual inspection.'),indent=2))
    print(output)


if __name__=='__main__':main()
