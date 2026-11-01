"""CPU-only chase candidate from existing assets and replaceable contact events.

Port of the local chase_finish/audio/build_audio.py recipe. Unlike that recipe,
the contact window limits onsets, not sample tails. No TTS, EQ or voice dynamics.
Events are mandatory and never generated from an assumed gait rate.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np

SR = 48000
REPO = Path(__file__).resolve().parents[2]
FF = imageio_ffmpeg.get_ffmpeg_exe()


def ff(args, data=None):
    return subprocess.run([FF, '-hide_banner', '-nostdin', *map(str, args)],
                          input=data, capture_output=True, check=True)


def decode(path, channels=2, pitch=1.):
    args = ['-v', 'error', '-i', path, '-vn', '-ac', channels, '-ar', SR]
    if pitch != 1:
        args += ['-af', f'aresample={SR},asetrate={round(SR*pitch)},aresample={SR}']
    raw = ff([*args, '-f', 'f32le', 'pipe:1']).stdout
    a = np.frombuffer(raw, np.float32).reshape(-1, channels).astype(np.float64)
    if not len(a) or not np.isfinite(a).all():
        raise ValueError(f'Invalid source: {path}')
    return a


def encode(a):
    return ff(['-v', 'error', '-f', 'f32le', '-ar', SR, '-ac', 2, '-i', 'pipe:0',
               '-c:a', 'pcm_s24le', '-f', 'wav', 'pipe:1'],
              a.astype(np.float32).tobytes()).stdout


def loudness(wav):
    log = ff(['-i', 'pipe:0', '-af',
              'loudnorm=I=-14:TP=-1:LRA=11:print_format=json', '-f', 'null', '-'],
             wav).stderr.decode(errors='replace')
    d = json.loads(log[log.rindex('{'):log.rindex('}')+1])
    return {'lufs': float(d['input_i']), 'true_peak_dbtp': float(d['input_tp'])}


def db(value):
    return 20 * math.log10(value) if value > 0 else None


def metrics(a, black_start=9.3, duration=9.6):
    tail = a[round(black_start*SR):round(duration*SR)]
    return dict(duration_s=len(a)/SR, sample_peak_dbfs=db(float(abs(a).max())),
                clipped_samples=int(np.count_nonzero(abs(a) >= 1)),
                max_channel_difference=float(abs(a[:, 0]-a[:, 1]).max()),
                black_tail_peak_dbfs=db(float(abs(tail).max())) if len(tail) else None,
                black_tail_nonzero_samples=int(np.count_nonzero(tail)))


def build(args):
    # Preserve defaults for existing callers as well as the command line.
    timeline = dict(duration=9.6, black_start=9.3, chase_start=4.8,
                    chase_end=8., voice_at=2.2, rustle_end=2.2)
    for key, default in timeline.items():
        timeline[key] = getattr(args, key, default)
        setattr(args, key, timeline[key])
    if not all(math.isfinite(t) for t in timeline.values()) or not (
            0 <= args.voice_at < args.chase_start < args.chase_end <= args.black_start
            < args.duration and 0 < args.rustle_end <= args.voice_at):
        raise ValueError('Invalid timeline: voice < chase start < chase end <= black < duration')
    event_bytes = args.events.read_bytes()
    document = json.loads(event_bytes.decode('utf-8-sig'))
    events = document if isinstance(document, list) else document.get('footsteps', document.get('events'))
    if not isinstance(events, list) or not events:
        raise ValueError('Supply explicit contacts; no inferred cadence')
    n = round(args.duration*SR)
    mix = np.zeros((n, 2), np.float64)
    cues, hashes = [], {}
    voice_ref = None

    def cue(file, at, gain, pan, pitch=1., end=None, fadein=.005, fadeout=.025):
        end = args.black_start if end is None else end
        path = args.assets / file
        hashes[file] = hashlib.sha256(path.read_bytes()).hexdigest()
        a = decode(path, 1, pitch)[:, 0]
        source_length = len(a)
        start = round(at*SR)
        count = min(len(a), round(end*SR)-start)
        if count <= 0:
            raise ValueError('Empty cue')
        a = a[:count].copy()
        for seconds, incoming in ((fadein, True), (fadeout, False)):
            k = min(len(a), round(seconds*SR))
            if k:
                if incoming:
                    a[:k] *= np.linspace(0, 1, k)
                else:
                    a[-k:] *= np.linspace(1, 0, k)
        angle = (pan+1)*math.pi/4
        stereo = a[:, None]*gain*np.array([math.cos(angle), math.sin(angle)])
        mix[start:start+count] += stereo
        cues.append(dict(file=file, at=at, end=(start+count)/SR, pan=pan, gain=gain,
                         pitch=pitch, source_samples=source_length, retained_samples=count))
        return stereo

    cue('search_leaves_rustle.wav', 0, .045, 0, end=args.rustle_end, fadein=.12, fadeout=.15)
    voice_ref = cue('kunkka_search_ru.mp3', args.voice_at, .8, -.3, fadein=0, fadeout=0)
    for i, event in enumerate(sorted(events, key=lambda e: e['at'])):
        hero = event.get('hero', event.get('who', event.get('actor')))
        if hero != 'hoodwink':
            raise ValueError('This T-pose chase accepts Hoodwink contacts only')
        at, gain, pan = (float(event[k]) for k in ('at', 'gain', 'pan'))
        if not all(math.isfinite(v) for v in (at, gain, pan)):
            raise ValueError('Nonfinite contact')
        if not (args.chase_start <= at < args.chase_end and 0 <= gain <= 1 and -1 <= pan <= 1):
            raise ValueError('Contact outside chase window or gain/pan bounds')
        cue(f'originals/sounds/physics/footsteps/hero/shared/general{i%6+1:02d}.wav',
            at, .2*gain, pan, pitch=1.3)

    # A single scalar preserves voice waveform and channel ratio. Do not drive a
    # limiter harder just to meet LUFS; report peak-constrained cases explicitly.
    raw_stats = loudness(encode(mix))
    gain_db = min(-14-raw_stats['lufs'], -1.3-raw_stats['true_peak_dbtp'])
    master = 10**(gain_db/20)
    wav = encode(mix*master)
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out/'chase_candidate.wav'
    output.write_bytes(wav)
    a = decode(output)
    stats = loudness(wav)
    start = round(args.voice_at*SR)
    null_error = float(abs(a[start:start+len(voice_ref)]-voice_ref*master).max())
    assert len(a) == n and not np.any(a[round(args.black_start*SR):])
    assert stats['true_peak_dbtp'] <= -1 and abs(a).max() < 1
    assert null_error < 3e-7, 'Voice waveform changed beyond PCM quantization'
    assert args.events.read_bytes() == event_bytes, 'Events changed; rebuild'
    assert all(hashlib.sha256((args.assets/f).read_bytes()).hexdigest() == h
               for f, h in hashes.items()), 'Sources changed; rebuild'
    comparisons = {}
    for path in (args.assets/'chase_mix.wav', args.assets.parent/'kunkka_hoodwink_chase.mp4'):
        if path.exists():
            old = decode(path)
            comparisons[path.name] = {**metrics(old), **loudness(encode(old)),
                                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    report = dict(audio_heard=False, status='candidate_contacts_not_final',
                  timeline=timeline,
                  candidate={**metrics(a, args.black_start, args.duration), **stats}, master_gain_db=gain_db,
                  target_lufs_met=abs(stats['lufs']+14) <= .1,
                  voice_null_max_abs=null_error, voice_processing='constant gain and pan only',
                  cues=cues, comparisons=comparisons, source_sha256=hashes,
                  events_sha256=hashlib.sha256(event_bytes).hexdigest(),
                  candidate_sha256=hashlib.sha256(wav).hexdigest(),
                  limitations=['Contacts supplied externally; visible contact is not validated here.',
                               'No listening, ASR or current camera verification.',
                               'Zero pan in supplied contacts is preserved, not widened artificially.',
                               'WAV only; existing MP4 was not updated.'])
    (args.out/'events_used.json').write_bytes(event_bytes)
    (args.out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('candidate', 'master_gain_db', 'voice_null_max_abs')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--assets', type=Path, default=REPO/'_game/skits/chase_finish/audio')
    parser.add_argument('--out', type=Path, default=REPO/'_game/skits/chase_audio_review')
    for name, default in [('duration', 9.6), ('black-start', 9.3), ('chase-start', 4.8),
                          ('chase-end', 8.), ('voice-at', 2.2), ('rustle-end', 2.2)]:
        parser.add_argument('--'+name, type=float, default=default)
    build(parser.parse_args())
