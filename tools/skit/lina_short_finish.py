"""Encode the rendered Lina short and verify every exported frame and audio tail."""
import hashlib
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw
from chase_audio import decode, encode, loudness, metrics

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/study/lina_threat/final'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest=json.loads((OUT/'manifest.json').read_text())
    if sha(OUT/'scene.blend')!=manifest['scene_sha256']:
        raise ValueError('Scene no longer matches rendered frames')
    frames=[OUT/'frames'/f'frame_{i:04}.png' for i in range(270)]
    if len(manifest['frames'])!=270 or any(sha(p)!=manifest['frames'][p.name] for p in frames):
        raise ValueError('Incomplete or changed render')
    wav=OUT/'audio/lina_short_stereo48k.wav'
    audio_report=json.loads((OUT/'audio/report.json').read_text(encoding='utf-8'))
    if sha(wav)!=audio_report['sha256']:
        raise ValueError('Audio changed since its check')
    movie=OUT/'lina_forest_short.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
        '-framerate','30','-start_number','0','-i',str(OUT/'frames/frame_%04d.png'),
        '-i',str(wav),'-map','0:v','-map','1:a','-t','9','-c:v','libx264',
        '-preset','medium','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
        '-af','loudnorm=I=-14:TP=-1.5:LRA=11','-ar','48000',
        '-movflags','+faststart',str(movie)],check=True)
    review=OUT/'review';review.mkdir(exist_ok=True)
    reader=imageio_ffmpeg.read_frames(str(movie),pix_fmt='rgb24');meta=next(reader)
    if meta['size']!=(1080,1920) or abs(meta['fps']-30)>.001:
        raise ValueError('Wrong video format')
    worst=0.;minimum=255.;count=0
    overview=Image.new('RGB',(180*9,340),'#151920')
    try:
        for i,data in enumerate(reader):
            if i>=270:raise ValueError('Extra frame')
            im=Image.frombytes('RGB',meta['size'],data)
            small=np.asarray(im.resize((90,160)),dtype=float)
            with Image.open(frames[i]) as source:
                worst=max(worst,float(np.abs(small-np.asarray(source.resize((90,160)),dtype=float)).mean()))
            minimum=min(minimum,float(small.mean()))
            if i%15==0:sheet=Image.new('RGB',(180*5,340*3),'#151920')
            x=i%5*180;y=i%15//5*340
            sheet.paste(im.resize((180,320)),(x,y+20))
            ImageDraw.Draw(sheet).text((x+3,y+3),str(i),fill='white')
            if i%15==14:sheet.save(review/f'qa_{i//15:02}.jpg',quality=90)
            if i%30==0:
                x=i//30*180;overview.paste(im.resize((180,320)),(x,20))
                ImageDraw.Draw(overview).text((x+3,3),f'{i/30:.0f}s',fill='white')
            count+=1
    finally:reader.close()
    overview.save(review/'overview.jpg',quality=93)
    pcm=decode(movie);audio={**metrics(pcm,8.1,9),**loudness(encode(pcm))}
    report=dict(frames=count,fps=meta['fps'],resolution=meta['size'],duration_s=meta['duration'],
        video_sha256=sha(movie),scene_sha256=manifest['scene_sha256'],
        max_mean_frame_error_255=worst,min_mean_frame_255=minimum,
        audio=audio,audio_heard=False,audio_normalization='FFmpeg loudnorm I=-14 TP=-1.5 LRA=11',
        passed=count==270 and worst<3 and minimum>8 and audio['clipped_samples']==0
            and abs(audio['duration_s']-9)<.03 and audio['black_tail_nonzero_samples']==0
            and abs(audio['lufs']+14)<1 and audio['true_peak_dbtp']<=-1,
        scope='Export correspondence, format, levels and quiet ending; visual sheets reviewed separately. No auditory acceptance.')
    (OUT/'delivery_check.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if not report['passed']:raise ValueError(report)
    print(json.dumps(report))


if __name__=='__main__':main()
