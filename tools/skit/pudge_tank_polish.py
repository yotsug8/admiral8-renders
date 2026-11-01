"""Assemble and verify the separately rendered tank finishing revision."""
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
import imageio_ffmpeg
from PIL import Image,ImageDraw
from pudge_tank_post import background,finish
from pudge_tank_sound import build
from chase_audio import decode,loudness

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'_game/skits/pudge_tank/motion'
OUT=ROOT/'_game/skits/pudge_tank/polish_v2'
FF=imageio_ffmpeg.get_ffmpeg_exe()
data=json.loads((SRC/'build.json').read_text(encoding='utf-8'))
count,fps=data['frames'],data['fps']
plates=[background(Image.open(SRC/f'plate_{i}.png'),i) for i in range(len(data['cuts'])-1)]
(OUT/'frames').mkdir(exist_ok=True)
changes=[];previous=None;clipped=[];source_hashes={}
for frame in range(count):
    shot=max(i for i,cut in enumerate(data['cuts'][:-1]) if cut<=frame)
    path=OUT/'layers'/f'f{frame:05d}.png'
    source_hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as actor:
        final=finish(Image.alpha_composite(plates[shot],actor.convert('RGBA')))
    assert final.size==(540,960)
    pixels=np.asarray(final)
    clipped.append({'frame':frame,'black':float((pixels.max(2)<3).mean()),
                    'white':float((pixels.min(2)>252).mean())})
    sample=np.asarray(final.resize((54,96)),dtype=float)
    assert sample.mean()>3,frame
    if previous is not None:
        changes.append((frame,float(np.abs(previous-sample).mean())))
    previous=sample
    final.save(OUT/'frames'/f'f{frame:05d}.png')
sound,sound_report=build(OUT)
video=OUT/'pudge_tank_v2.mp4'
subprocess.run([FF,'-y','-v','error','-framerate',str(fps),'-start_number','0',
    '-i',str(OUT/'frames/f%05d.png'),'-i',str(sound),'-frames:v',str(count),
    '-c:v','libx264','-crf','14','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
    '-ar','48000','-movflags','+faststart',str(video)],check=True)
reader=imageio_ffmpeg.read_frames(str(video),pix_fmt='rgb24')
metadata=next(reader);selected=[];decoded=0
for frame,raw in enumerate(reader):
    if frame%fps==0 or frame in (53,57,61,65,70,78,81,91,198,206,218,255,299):
        selected.append((frame,Image.frombytes('RGB',metadata['size'],raw).resize((216,384))))
    decoded+=1
assert decoded==count,(decoded,count)
sheet=Image.new('RGB',(1296,410*((len(selected)+5)//6)),(20,22,25))
draw=ImageDraw.Draw(sheet)
for i,(frame,im) in enumerate(selected):
    x,y=i%6*216,i//6*410
    sheet.paste(im,(x,y+24));draw.text((x+5,y+5),f'{frame/fps:.2f}s / {frame}',fill='white')
sheet.save(OUT/'review.jpg',quality=95)
audio=decode(video)
silent=[]
for interval in sound_report['silent_intervals']:
    start,end=interval['start'],interval['end']
    peak=float(np.abs(audio[round(start*48000):round(end*48000)]).max())
    assert peak<.0001,(start,end,peak)
    silent.append({'start':start,'end':end,'decoded_peak':peak})
meter=subprocess.run([FF,'-hide_banner','-i',str(video),'-af',
    'loudnorm=I=-14:TP=-1:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
stats=json.JSONDecoder().raw_decode(meter.stderr[meter.stderr.rfind('{'):])[0]
report={'frames':decoded,'fps':fps,'seconds':decoded/fps,'size':metadata['size'],
    'largest_frame_changes':sorted(changes,key=lambda r:-r[1])[:12],
    'peak_black_fraction':max(r['black'] for r in clipped),
    'peak_white_fraction':max(r['white'] for r in clipped),
    'silent_intervals':silent,'audio':stats,'audio_heard':False,
    'source_layers_sha256':source_hashes,'output_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
    'limitations':['Technical checks and sampled visual review are not artistic approval.',
                  'Original geometry and staging limitations remain.']}
(OUT/'delivery_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='source_layers_sha256'}),flush=True)
print(video,flush=True)
