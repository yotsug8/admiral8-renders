"""Assemble the silent internal motion test and numbered all-frame review sheets.

No artistic pass is inferred from frame count or successful encoding.
"""
import hashlib
from bisect import bisect_left
import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from chase_audio import SR, ff, encode, loudness

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/doomsday/v2'
if '--v3' in sys.argv:OUT=OUT.parent/'v3'


def sound(directory,sources,fps):
    duration=len(sources)/fps
    at_frame=lambda frame: bisect_left(sources,frame)/fps
    mix=np.zeros((round(SR*duration),2),dtype=float);occupancy=np.zeros(len(mix),dtype=np.uint8)
    audio_sources=OUT.parent/'v2/audio_sources/sounds/weapons/hero/axe'
    charge,swing,hit=(at_frame(f) for f in (8,38,44))
    cues=[(OUT.parent/'audio_sources/sounds/weapons/hero/sven/storm_bolt.wav',charge,.6,.08),
          (audio_sources/'preattack01.wav',swing,hit-swing,.11),
          (audio_sources/'culling_blade_fail.wav',hit,.48,.18)]
    provenance=[]
    for path,at,length,level in cues:
        raw=ff(['-v','error','-i',path,'-af','highpass=f=45,lowpass=f=6500','-ar',SR,'-ac',1,'-f','f32le','pipe:1']).stdout
        samples=np.frombuffer(raw,np.float32).astype(float)
        active=np.flatnonzero(abs(samples)>max(.001,float(abs(samples).max())*.015))
        if not len(active):raise ValueError(f'Empty sound: {path.name}')
        samples=samples[max(0,int(active[0])-96):][:round(length*SR)].copy()
        samples*=level/max(1e-7,float(np.sqrt(np.mean(samples*samples))))
        fade=min(round(.05*SR),len(samples)//4)
        samples[:120]*=np.linspace(0,1,120);samples[-fade:]*=np.linspace(1,0,fade)**2
        start=round(at*SR);mix[start:start+len(samples)]+=samples[:,None]*.7071;occupancy[start:start+len(samples)]+=1
        provenance.append({'source':path.name,'at':at,'end':(start+len(samples))/SR,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    if occupancy.max()>1:raise ValueError('Overlapping sound events')
    mix=np.tanh(mix*1.6)/1.6
    meter=loudness(encode(mix));gain=min(-14-meter['lufs'],-1.5-meter['true_peak_dbtp'])
    wav=encode(mix*10**(gain/20));path=directory/'sound.wav';path.write_bytes(wav)
    return path,{'cues':provenance,'max_simultaneous_cues':int(occupancy.max()),'heard':False,'meter':loudness(wav)}


def grade(image):
    values=np.asarray(image.convert('RGB'),dtype=float)/255
    values=np.clip((values-.025)*1.045,0,1)
    glow=np.maximum(values-.8,0)
    halo=Image.fromarray(np.uint8(glow*255)).filter(ImageFilter.GaussianBlur(6))
    values+=np.asarray(halo,dtype=float)/255*.65
    return Image.fromarray(np.uint8(np.clip(values,0,1)*255))


def delivery():
    manifest=json.loads((OUT/'frames/manifest.json').read_text())
    sources=manifest['source_frames'];fps=manifest['fps']
    frames=[OUT/'frames'/f'{f:04d}.png' for f in sources]
    if [hashlib.sha256(p.read_bytes()).hexdigest() for p in frames]!=manifest['frame_sha256']:raise ValueError('Rendered frame provenance mismatch')
    # Shorten the floating flight; retain the preparation, impact and landing.
    selected=[i for i,f in enumerate(sources) if not (19<=f<39) or (f-19)%2==0]
    frames=[frames[i] for i in selected];sources=[sources[i] for i in selected];count=len(sources)
    destination=OUT/'delivery';destination.mkdir(exist_ok=True)
    audio,audio_report=sound(destination,sources,fps)
    video=destination/f'doomsday_{OUT.name}_draft.mp4'
    command=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
        '-f','rawvideo','-pix_fmt','rgb24','-s','540x960','-r',str(fps),'-i','pipe:0',
        '-i',str(audio),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',str(video)]
    thumbnails=[]
    with subprocess.Popen(command,stdin=subprocess.PIPE) as process:
        for index,path in enumerate(frames):
            with Image.open(path) as raw:
                if raw.size!=(540,960):raise ValueError('Unexpected delivery resolution')
                im=grade(raw)
            process.stdin.write(im.tobytes());thumbnails.append(im.resize((108,192)))
            if index==0:im.save(destination/'poster.jpg',quality=95)
        process.stdin.close()
        if process.wait()!=0:raise ValueError('Video encoding failed')
    for page,first in enumerate(range(0,count,30)):
        sheet=Image.new('RGB',(900,1032),(20,20,20));draw=ImageDraw.Draw(sheet)
        for slot,f in enumerate(range(first,min(first+30,count))):
            x,y=(slot%6)*150,(slot//6)*206;sheet.paste(thumbnails[f],(x+21,y));draw.text((x+21,y+192),str(sources[f]),fill='white')
        sheet.save(destination/f'review_{page}.jpg',quality=95)
    raw=ff(['-v','error','-i',video,'-vf','scale=90:160','-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1']).stdout
    decoded=len(raw)//(90*160*3)
    if decoded!=count:raise ValueError('Decoded frame count mismatch')
    report={'frames':count,'source_frames':sources,'fps':fps,'duration':count/fps,'decoded_frames':decoded,'audio':audio_report,
            'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'artistic_status':'Requires whole-fragment visual review; technical checks do not approve the staging.'}
    (destination/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'video':video.name,'frames':count,'duration':count/fps,'audio':audio_report['meter']},ensure_ascii=False))


def main():
    staging=json.loads((OUT/'staging.json').read_text(encoding='utf-8'))
    count=staging['frames'];fps=staging['fps']
    frames=[OUT/'motion'/f'{f:04d}.png' for f in range(count)]
    missing=[p.name for p in frames if not p.is_file()]
    if missing:raise ValueError(f'Missing frames: {missing}')
    for page,first in enumerate(range(0,count,30)):
        sheet=Image.new('RGB',(900,1032),(20,20,20));draw=ImageDraw.Draw(sheet)
        for slot,f in enumerate(range(first,min(first+30,count))):
            x,y=(slot%6)*150,(slot//6)*206
            with Image.open(frames[f]) as im:
                if im.size!=(360,640):raise ValueError(f'Unexpected size: {frames[f]}')
                sheet.paste(im.convert('RGB').resize((108,192)),(x+21,y))
            draw.text((x+21,y+192),str(f),fill='white')
        sheet.save(OUT/f'motion_review_{page}.jpg',quality=94)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
        '-framerate',str(fps),'-i',str(OUT/'motion/%04d.png'),'-frames:v',str(count),
        '-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',
        str(OUT/'internal_motion.mp4')],check=True)
    report={'frames':count,'fps':fps,'duration':count/fps,'audio':False,
            'artistic_status':'Internal test; requires visual review. Not a finished draft.',
            'frames_sha256':[hashlib.sha256(p.read_bytes()).hexdigest() for p in frames]}
    (OUT/'motion_review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'Internal motion assembled; all {count} frames included in review sheets.')


if __name__=='__main__':
    if '--draft' in sys.argv:delivery()
    else:main()
