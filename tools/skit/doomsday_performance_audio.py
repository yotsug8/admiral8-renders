"""Prepare a Russian threat using the original Axe voice, plus native attack cues."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/doomsday/v6'
sys.path.insert(0,str(Path(__file__).resolve().parent))


def prepare():
    from faster_whisper import WhisperModel
    folder=OUT/'audio_sources/sounds/vo/axe'
    files=sorted(folder.glob('axe_rare_*.mp3'))[:4]+sorted(folder.glob('axe_attack_*.mp3'))[:3]
    cache=OUT/'axe_voice_audit.json'
    data=json.loads(cache.read_text()) if cache.exists() else {}
    missing=[p for p in files if p.name not in data]
    if missing:
        model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
        for path in missing:
            segments,_=model.transcribe(str(path),language='en',beam_size=3)
            data[path.name]=' '.join(s.text.strip() for s in segments)
        cache.write_text(json.dumps(data,indent=2))
    print(json.dumps(data,ensure_ascii=False),flush=True)
    reference=[p for p in files if 'rare' in p.name and len(data[p.name].split())>=4]
    if not reference:raise ValueError('No verified original voice reference')
    vo=ROOT/'_game/vo';wav=vo/'ref_axe.wav';meta=vo/'ref_axe.json'
    if not wav.exists():
        listing=OUT/'axe_reference.lst'
        listing.write_text(''.join(f"file '{p.as_posix()}'\n" for p in reference))
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-ar','44100','-ac','1',str(wav)],check=True)
        meta.write_text(json.dumps({'text':' '.join(data[p.name] for p in reference),
            'files':[p.name for p in reference],'source_language':'en',
            'scope':'Original installed-game Axe voice; no Axe entries in the installed Russian VPK.'},indent=2))
    reference_metadata=json.loads(meta.read_text())
    payload={'destination':'https://api.fish.audio/v1/tts','model':'s2.1-pro-free',
        'text':'Клянусь, ты будешь молить о пощаде!',
        'reference_audio':str(wav.relative_to(ROOT)).replace('\\','/'),
        'reference_audio_bytes':wav.stat().st_size,
        'reference_audio_sha256':hashlib.sha256(wav.read_bytes()).hexdigest(),
        'reference_text':reference_metadata['text'],'reference_files':reference_metadata['files'],
        'format':'mp3','sent':False,'scope':'Prepared locally only; external transfer requires explicit approval.'}
    (OUT/'audio_payload_review.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False),flush=True)
    return payload


def synthesize():
    import voices
    if not voices.fish_key():raise ValueError('Character voice synthesis unavailable; do not substitute a robotic voice')
    result=voices.make(str(OUT/'voice'),[{'name':'threat','who':'axe',
        'text':'Клянусь, ты будешь молить о пощаде!','voice':{'ref':'axe'}}])
    print(json.dumps({k:{x:v[x] for x in ('dur','say','voice')} for k,v in result.items()},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only',action='store_true',help='Local extraction/ASR/reference preparation only; no external request')
    mode.add_argument('--synthesize',action='store_true',help='Send reviewed payload to Fish; run only after explicit approval')
    args=parser.parse_args()
    prepare()
    if args.synthesize:synthesize()
