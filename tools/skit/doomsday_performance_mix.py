"""Local 14-second Axe/Rubick event mix; no synthesis or network requests.

The default leaves the main dialogue window empty. Supply --voice only after
the desired character recording exists, or use --native-voice for an explicitly
labelled English fallback. Native sources remain external game dependencies.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from chase_audio import SR, db, decode, encode, ff, loudness

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / '_game/skits/doomsday'
OUT = BASE / 'v6/audio'
VOICE = BASE / 'v6/audio_sources/sounds/vo/axe'
DURATION = 14.


def build(args):
    mix = np.zeros((round(DURATION * SR), 2), dtype=np.float64)
    occupied = np.zeros(len(mix), dtype=np.uint8)
    events = []
    voice_wave = None

    def cue(label, path, at, end, level, voice=False, source_offset=0., fadeout=.045):
        nonlocal voice_wave
        a = decode(path, 1)[:, 0]
        active = np.flatnonzero(abs(a) > max(1e-5, float(abs(a).max()) * .003))
        if not len(active):
            raise ValueError(f'Empty source: {path.name}')
        a = a[max(0, int(active[0]) - round(.008 * SR)):
              min(len(a), int(active[-1]) + round(.025 * SR))].copy()
        a = a[round(source_offset * SR):]
        available = round((end - at) * SR)
        if voice and len(a) > available:
            raise ValueError(f'{label} needs {len(a)/SR:.3f}s; window is {end-at:.3f}s. '
                             'Do not cut words or silently change delivery speed.')
        a = a[:available]
        if not len(a):
            raise ValueError(f'Empty cue: {label}')
        rms = float(np.sqrt(np.mean(a*a)))
        gain = min(level / max(rms, 1e-8), .75 / max(float(abs(a).max()), 1e-8))
        a *= gain
        for seconds, incoming in ((.004 if voice else .014, True),
                                  (.008 if voice else fadeout, False)):
            k = min(round(seconds * SR), len(a)//2)
            envelope = np.linspace(0, 1, k)
            if incoming:
                a[:k] *= envelope
            else:
                a[-k:] *= envelope[::-1]
        start = round(at * SR)
        stereo = np.repeat((a * 2**-.5)[:, None], 2, axis=1)
        mix[start:start+len(a)] += stereo
        occupied[start:start+len(a)] += 1
        if label == 'dialogue':
            voice_wave = (start, stereo.copy())
        events.append({'event': label, 'source': path.relative_to(ROOT).as_posix(),
                       'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'at': at, 'end': (start+len(a))/SR, 'gain': gain,
                       'source_offset_s': source_offset, 'voice': voice})

    weapon = BASE / 'v2/audio_sources/sounds/weapons/hero/axe'
    magic = BASE / 'audio_sources/sounds/weapons/hero'
    # Separate charges leave the speaking window clean. No looping ambience,
    # repeated metal impact, invented landing or background music.
    cue('initial_charge', magic/'sven/storm_bolt.wav', .8, 1.55, .075, fadeout=.18)
    if args.voice or args.native_voice:
        path = args.voice.resolve() if args.voice else VOICE/'axe_attack_02.mp3'
        cue('dialogue', path, 2.48, 6.48, .16, voice=True)
    cue('charge_release', magic/'rubick/telekinesis_cast.wav', 6.8, 7.43, .095)
    cue('native_battle_cry', VOICE/'axe_attack_01.mp3', 7.5, 8.5, .145, voice=True)
    cue('axe_swing', weapon/'preattack01.wav', 8.55, 9.29, .105)
    cue('magic_arrest', magic/'rubick/telekinesis_stun.wav', 9.3, 10.55, .15, fadeout=.32)
    if occupied.max() > 1:
        raise ValueError('Unexpected overlap of event windows')
    before = loudness(encode(mix))
    master_db = min(-14-before['lufs'], -1.5-before['true_peak_dbtp'])
    master = 10**(master_db/20)
    wav = encode(mix*master)
    name = 'performance_mix' if args.voice else 'native_voice_preview' if args.native_voice else 'action_only'
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out/(name+'.wav')
    path.write_bytes(wav)
    decoded = decode(path)
    stats = loudness(wav)
    # Inspect the actual AAC delivery path too, without retaining another asset.
    aac = ff(['-v','error','-f','wav','-i','pipe:0','-c:a','aac','-b:a','192k',
              '-f','adts','pipe:1'], wav).stdout
    aac_wav = ff(['-v','error','-f','aac','-i','pipe:0','-ar',SR,'-ac',2,
                  '-c:a','pcm_s24le','-f','wav','pipe:1'], aac).stdout
    aac_stats = loudness(aac_wav)
    silence = occupied == 0
    assert len(decoded) == round(DURATION*SR)
    assert not np.count_nonzero(decoded[silence]), 'Noise outside scheduled events'
    assert stats['true_peak_dbtp'] <= -1 and aac_stats['true_peak_dbtp'] <= -1
    assert float(abs(decoded).max()) < 1
    voice_error = None
    if voice_wave:
        start, original = voice_wave
        voice_error = float(abs(decoded[start:start+len(original)]-original*master).max())
        assert voice_error < 3e-7, 'Dialogue altered beyond PCM quantization'
    report = {'output': path.relative_to(ROOT).as_posix(), 'duration_s': len(decoded)/SR,
              'sha256': hashlib.sha256(wav).hexdigest(), 'events': events,
              'speech_missing': not bool(args.voice or args.native_voice),
              'desired_russian_speech_missing': not bool(args.voice),
              'native_voice_fallback': args.native_voice,
              'fallback_text': 'Taste my blade!' if args.native_voice else None,
              'battle_cry_text': 'Attack!', 'voice_pitch_or_tempo_changed': False,
              'dialogue_pcm_max_error': voice_error, 'meter': stats,
              'aac_192k_meter': aac_stats, 'master_gain_db': master_db,
              'lufs_target': -14, 'peak_constrained': stats['lufs'] < -14.2,
              'sample_peak_dbfs': db(float(abs(decoded).max())),
              'clipped_samples': int(np.count_nonzero(abs(decoded)>=1)),
              'max_simultaneous_events': int(occupied.max()),
              'nonzero_samples_outside_cues': int(np.count_nonzero(decoded[silence])),
              'heard': False, 'visual_sync_reviewed': False,
              'limits': 'Measured locally; subjective timbre and final visual synchronization remain unverified.'}
    (args.out/(name+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    # The mouth cue follows the retained native cry, including its silent tail.
    # Regenerate it with every mix so visual timing cannot use an untrimmed MP3.
    def envelope(at, end, filename, text):
        samples = decoded[round(at*SR):round(end*SR)].mean(axis=1)
        step = SR//30
        rms = np.asarray([np.sqrt(np.mean(samples[i:i+step]**2))
                          for i in range(0,len(samples),step)])
        env = rms/max(float(rms.max()),1e-9)
        data = {'source':report['output'], 'source_sha256':report['sha256'],
                'fps':30, 'start_s':at, 'start_frame':at*30,
                'first_scene_frame':int(np.ceil(at*30)), 'duration_s':end-at,
                'samples_per_frame':step, 'frames':len(env), 'env':env.tolist(),
                'text':text, 'language':'en',
                'method':'RMS per exact 1/30 second window, normalized to maximum RMS; trimmed final-mix cue'}
        (args.out/filename).write_text(json.dumps(data,indent=2),encoding='utf-8')
    envelope(7.5,8.5,'battle_cry_envelope.json','Attack!')
    if args.native_voice:
        envelope(2.48,6.48,'native_dialogue_envelope.json','Taste my blade!')
    print(json.dumps({'output': report['output'], 'meter': stats,
                      'aac_meter': aac_stats, 'speech_missing': report['speech_missing']}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--voice', type=Path, help='Existing approved Russian character recording')
    mode.add_argument('--native-voice', action='store_true', help='Real English Axe fallback, not the requested Russian line')
    parser.add_argument('--out', type=Path, default=OUT)
    build(parser.parse_args())
