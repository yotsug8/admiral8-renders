"""Composite the tank draft, add synchronized action sound, and inspect decoding."""
import json
from pathlib import Path
import subprocess
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/pudge_tank/motion'
FF=imageio_ffmpeg.get_ffmpeg_exe()
data=json.loads((OUT/'build.json').read_text(encoding='utf-8'))
count,fps=data['frames'],data['fps']
plates=[Image.open(OUT/f'plate_{i}.png').convert('RGBA') for i in range(len(data['cuts'])-1)]
(OUT/'frames').mkdir(exist_ok=True)
changes=[]
previous=None
for index in range(count):
    shot=max(i for i,cut in enumerate(data['cuts'][:-1]) if cut<=index)
    with Image.open(OUT/'layers'/f'f{index:05d}.png') as actor:
        frame=Image.alpha_composite(plates[shot],actor.convert('RGBA')).convert('RGB')
    assert frame.size==(540,960)
    sample=np.asarray(frame.resize((54,96)),dtype=float)
    assert sample.mean()>3, index
    if previous is not None:
        changes.append((index,float(np.abs(sample-previous).mean())))
    previous=sample
    frame.save(OUT/'frames'/f'f{index:05d}.png')

# Effects follow visible actions; no music or continuous background beat.
sr=48000
sound=np.zeros(round(count/fps*sr))
rng=np.random.default_rng(718)
def noise(n,cutoff):
    x=rng.normal(0,1,n)
    f=np.fft.rfftfreq(n,1/sr)
    x=np.fft.irfft(np.fft.rfft(x)/(1+(f/cutoff)**4),n)
    return x/max(.001,np.std(x))
def add(start,x,gain=1):
    a=round(start*sr)
    n=min(len(x),len(sound)-a)
    sound[a:a+n]+=gain*x[:n]
def metal(start,duration,gain):
    t=np.arange(round(duration*sr))/sr
    x=sum(np.sin(2*np.pi*f*t)*np.exp(-t*d) for f,d in ((311,12),(521,18),(893,25),(1469,35)))
    x+=noise(len(t),4500)*np.exp(-t*70)*.5
    add(start,x,gain)
metal(1.22,.5,.07)
metal(2.8,.65,.15)
t=np.arange(round(3.15*sr))/sr
frequency=38+19*np.sin(np.pi*np.clip(t/3.15,0,1))
phase=np.cumsum(frequency)/sr*2*np.pi
engine=sum(np.sin(phase*k)/k for k in range(1,7))
engine+=noise(len(t),550)*.22
env=np.minimum(1,t/.3)*np.minimum(1,(3.15-t)/.4)
add(3.35,engine*env,.095)
for t0 in np.arange(3.6,6.15,.19):
    metal(float(t0),.1,.009)
t=np.arange(round(.65*sr))/sr
shot=(noise(len(t),2700)*np.exp(-t*17)+2*np.sin(2*np.pi*(85*t-30*t*t))*np.exp(-t*12))
add(6.6,shot,.3)
t=np.arange(round(2.8*sr))/sr
blast=noise(len(t),250)*np.exp(-t*1.8)+noise(len(t),3200)*np.exp(-t*14)*.45
blast*=np.minimum(1,t/.008)
add(6.9,blast,.35)
for t0 in (7.17,7.38,7.66,8.04,8.31,8.59):
    metal(t0,.22,.025)
sound*=.92/max(.92,float(np.max(np.abs(sound))))
with wave.open(str(OUT/'action_sound.wav'),'wb') as wav:
    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(sr)
    wav.writeframes((sound*32767).astype('<i2').tobytes())
meter=subprocess.run([FF,'-hide_banner','-i',str(OUT/'action_sound.wav'),'-af',
    'loudnorm=I=-14:TP=-1:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
stats=json.JSONDecoder().raw_decode(meter.stderr[meter.stderr.rfind('{'):])[0]
normalizer=('loudnorm=I=-14:TP=-1:LRA=11:linear=true:'
    f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
    f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}")
final=OUT/'pudge_tank_draft.mp4'
subprocess.run([FF,'-y','-v','error','-framerate',str(fps),'-start_number','0',
    '-i',str(OUT/'frames/f%05d.png'),'-i',str(OUT/'action_sound.wav'),
    '-frames:v',str(count),'-c:v','libx264','-crf','15','-pix_fmt','yuv420p',
    '-af',normalizer,'-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',str(final)],check=True)
reader=imageio_ffmpeg.read_frames(str(final),pix_fmt='rgb24')
meta=next(reader)
selected=[]
decoded=0
for index,raw in enumerate(reader):
    if index%fps==0 or index in (53,65,78,81,91,198,206,218,255,299):
        selected.append((index,Image.frombytes('RGB',meta['size'],raw).resize((216,384))))
    decoded+=1
assert decoded==count,(decoded,count)
sheet=Image.new('RGB',(216*6,410*((len(selected)+5)//6)),(20,22,25))
draw=ImageDraw.Draw(sheet)
for n,(index,im) in enumerate(selected):
    x,y=n%6*216,n//6*410
    sheet.paste(im,(x,y+24));draw.text((x+5,y+5),f'{index/fps:.2f}s / {index}',fill='white')
sheet.save(OUT/'review.jpg',quality=94)
meter=subprocess.run([FF,'-hide_banner','-i',str(final),'-af',
    'loudnorm=I=-14:TP=-1:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
(OUT/'audio_meter.txt').write_text(meter.stderr,encoding='utf-8')
report={'frames':decoded,'seconds':decoded/fps,'size':meta['size'],
    'largest_changes':sorted(changes,key=lambda r:-r[1])[:15],
    'audio':json.JSONDecoder().raw_decode(meter.stderr[meter.stderr.rfind('{'):])[0],
    'limitations':['Audio measured but not listened to.',
                  'Whole-video decode and sampled visual review do not certify continuous collision clearance.']}
(OUT/'delivery_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report),flush=True)
print(final,flush=True)
