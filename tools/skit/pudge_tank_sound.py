"""Sparse, nonoverlapping action cues from native game recordings."""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from chase_audio import SR, ff, encode, loudness, decode


def build(out):
    root=Path(__file__).resolve().parents[2]
    assets=out/'audio_sources/sounds'
    mix=np.zeros((480000,2),dtype=np.float64)
    occupancy=np.zeros(len(mix),dtype=int)
    cues=[]

    def cue(path,at,duration,rms,lowpass,pitch=1.,pan=0.,fade=.04):
        filters=f'aresample={SR},asetrate={round(SR*pitch)},aresample={SR},highpass=f=35,lowpass=f={lowpass}'
        raw=ff(['-v','error','-i',path,'-ac',1,'-af',filters,'-ar',SR,'-f','f32le','pipe:1']).stdout
        a=np.frombuffer(raw,np.float32).astype(float)
        if len(a)<2 or not np.isfinite(a).all():
            raise ValueError(f'Invalid or too short cue: {path}')
        peak=float(np.max(np.abs(a)))
        if peak==0:
            raise ValueError(f'Silent cue: {path}')
        # Remove leading encoder silence while preserving the transient's attack.
        active=np.flatnonzero(np.abs(a)>max(.0005,peak*.012))
        if len(active):
            a=a[max(0,int(active[0]) - 96):]
        a=a[:round(duration*SR)].copy()
        if len(a)<2:
            raise ValueError(f'Too short cue: {path}')
        a*=rms/max(1e-6,float(np.sqrt(np.mean(a*a))))
        n=min(round(fade*SR),len(a)//2)
        a[:min(240,n)]*=np.linspace(0,1,min(240,n))
        a[-n:]*=np.linspace(1,0,n)**2
        if 'idle_loop' in str(path):
            t=np.linspace(0,1,len(a))
            a*=np.sin(np.pi*t)**.65
        start=round(at*SR)
        angle=(pan+1)*math.pi/4
        stereo=a[:,None]*np.array([math.cos(angle),math.sin(angle)])
        mix[start:start+len(a)]+=stereo
        occupancy[start:start+len(a)]+=1
        cues.append({'source':str(path.relative_to(root)).replace('\\','/'),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'at':at,'end':(start+len(a))/SR,'lowpass_hz':lowpass,'pitch':pitch,'rms':rms})

    cue(assets/'weapons/hero/rattletrap/attack01.wav',1.28,.12,.018,1400,pitch=.72,pan=.15)
    cue(root/'_game/sfx/step01',1.8,.17,.025,2200,pan=.2)
    cue(assets/'weapons/hero/rattletrap/attack01.wav',2.8,.22,.048,1300,pitch=.62)
    cue(assets/'physics/movement/hero/gyrocopter/idle_loop.wav',3.6,2.6,.043,380,pitch=.62,fade=.28)
    cue(assets/'weapons/creep/good/engine_attack01.wav',6.6,.25,.18,3200,pitch=.8,pan=-.15)
    cue(assets/'physics/damage/engines/dire_base_destruction_01.wav',6.9,1.85,.22,2800,pitch=.9,fade=.35)
    assert occupancy.max()==1,'Cue windows unexpectedly overlap'
    # Gentle peak compression keeps isolated shots from forcing the entire mix down.
    mix=np.tanh(mix*1.8)/1.8
    raw=encode(mix)
    stats=loudness(raw)
    gain_db=min(-14-stats['lufs'],-1.5-stats['true_peak_dbtp'])
    wav=encode(mix*10**(gain_db/20))
    path=out/'action_sound_v2.wav';path.write_bytes(wav)
    samples=decode(path)
    silent=[]
    for start,end in ((0,1.2),(1.43,1.77),(2.05,2.75),(3.1,3.5),(6.25,6.55),(8.8,10)):
        peak=float(np.max(np.abs(samples[round(start*SR):round(end*SR)])))
        assert peak<1e-7,(start,end,peak)
        silent.append({'start':start,'end':end,'peak':peak})
    report={'audio_heard':False,'cues':cues,'max_simultaneous_cues':int(occupancy.max()),
            'silent_intervals':silent,'master_gain_db':gain_db,'meter':loudness(wav),
            'limitations':'Filtering, timing and silence are measured; artistic suitability requires listening.'}
    (out/'sound_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return path,report

if __name__=='__main__':
    out=Path(__file__).resolve().parents[2]/'_game/skits/pudge_tank/polish_v2'
    print(build(out)[1])
