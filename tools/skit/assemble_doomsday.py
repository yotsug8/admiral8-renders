"""Assemble the selected action beats, retaining frame and audio provenance."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from chase_audio import SR, ff, encode, loudness

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/doomsday'
DRAFT=OUT/'draft_v1'
SOURCE_FRAMES=[*range(18),*range(23,35),*range(35,60,2),*range(60,73),*range(89,101),*range(105,117)]
N=len(SOURCE_FRAMES)
FPS=15


def sound():
    mix=np.zeros((round(SR*N/FPS),2),dtype=np.float64)
    occupancy=np.zeros(len(mix),dtype=np.uint8)
    events=[('sven/storm_bolt',.40,1.0,.10),
            ('sven/attack01',2.00,.35,.09),
            ('rubick/telekinesis_cast',2.40,.35,.08),
            ('rubick/telekinesis_stun',43/15,.85,.20)]
    cues=[]
    for name,at,duration,level in events:
        path=OUT/'audio_sources/sounds/weapons/hero'/f'{name}.wav'
        raw=ff(['-v','error','-i',path,'-af','highpass=f=45,lowpass=f=4800',
                '-ar',SR,'-ac',1,'-f','f32le','pipe:1']).stdout
        a=np.frombuffer(raw,np.float32).astype(float)
        active=np.flatnonzero(abs(a)>max(.001,float(abs(a).max())*.015))
        a=a[max(0,int(active[0])-96):][:round(duration*SR)].copy()
        a*=level/max(1e-7,float(np.sqrt(np.mean(a*a))))
        fade=min(round(.09*SR),len(a)//3)
        a[:120]*=np.linspace(0,1,120)
        a[-fade:]*=np.linspace(1,0,fade)**2
        start=round(at*SR)
        mix[start:start+len(a)]+=a[:,None]*.7071
        occupancy[start:start+len(a)]+=1
        cues.append(dict(source=name,at=at,end=(start+len(a))/SR,
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    assert int(occupancy.max())==1
    mix=np.tanh(mix*1.6)/1.6
    measured=loudness(encode(mix))
    gain=min(-14-measured['lufs'],-1.5-measured['true_peak_dbtp'])
    wav=encode(mix*10**(gain/20))
    path=DRAFT/'sound.wav';path.write_bytes(wav)
    return path,dict(cues=cues,max_simultaneous_cues=1,audio_heard=False,meter=loudness(wav))


def grade(im):
    a=np.asarray(im.convert('RGB'),dtype=float)/255
    # Modest contrast, with room left in highlights for the thin energy arcs.
    a=np.clip((a-.05)*1.10,0,1)
    bright=np.maximum(a.max(axis=2)-.58,0)/.42
    chroma=np.maximum(a[:,:,2],a[:,:,1])-a[:,:,0]
    bright*=np.clip(chroma*3,0,1)
    mask=Image.fromarray(np.uint8(bright*255)).filter(ImageFilter.GaussianBlur(9))
    halo=np.asarray(mask,dtype=float)/255
    a+=halo[:,:,None]*np.array([.12,.28,.33])
    return Image.fromarray(np.uint8(np.clip(a,0,1)*255))


def main():
    DRAFT.mkdir(parents=True,exist_ok=True)
    frames=DRAFT/'frames';graded=DRAFT/'graded';graded.mkdir(exist_ok=True)
    hashes=[]
    for f,source in enumerate(SOURCE_FRAMES):
        path=frames/f'{source*2:04d}.png'
        if not path.is_file():raise ValueError(f'Missing frame {f}')
        with Image.open(path) as im:
            assert im.size==(540,960),(f,im.size)
            grade(im).save(graded/f'{f:04d}.png')
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    audio,qa=sound()
    video=DRAFT/'doomsday_draft.mp4'
    ff(['-v','error','-y','-framerate',FPS,'-start_number',0,'-i',graded/'%04d.png',
        '-i',audio,'-frames:v',N,'-c:v','libx264','-crf',17,'-pix_fmt','yuv420p',
        '-c:a','aac','-b:a','192k','-movflags','+faststart',video])
    ff(['-v','error','-i',video,'-f','null','-'])
    decoded=DRAFT/'decoded';decoded.mkdir(exist_ok=True)
    ff(['-v','error','-y','-i',video,'-vf','fps=6,scale=270:480',decoded/'final_%03d.jpg'])
    fs=sorted(decoded.glob('final_*.jpg'));sheet=Image.new('RGB',(2160,((len(fs)+7)//8)*505));draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(fs):
        x=i%8*270;y=i//8*505
        sheet.paste(Image.open(p),(x,y));draw.text((x+5,y+483),f'{i/6:.2f}s',fill='white')
    sheet.save(DRAFT/'contact.jpg')
    qa.update(frame_count=N,fps=FPS,duration=N/FPS,source_sha256=hashes,source_frames=[f*2 for f in SOURCE_FRAMES],
              scene_sha256=hashlib.sha256((OUT/'doomsday_v1.blend').read_bytes()).hexdigest(),
              video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
              decoded_all_frames=True,visual_sampling_hz=6)
    qa['aac_meter']=loudness(ff(['-v','error','-i',video,'-vn','-f','wav','pipe:1']).stdout)
    (DRAFT/'assembly_qa.json').write_text(json.dumps(qa,indent=2))
    print(video)
    print(json.dumps(qa['aac_meter']))


if __name__=='__main__':main()
