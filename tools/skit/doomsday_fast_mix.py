"""Retime the existing Axe cry and shorten its swing for the fast attack cut.

No network, synthesis, voice stretching or pitch shifting. The verified source
mix has disjoint event windows, so its event stems can be recovered exactly.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from chase_audio import SR, db, decode, encode, ff, loudness

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / '_game/skits/doomsday'


def build(args):
    source_report = json.loads(args.source.with_suffix('.json').read_text(encoding='utf-8'))
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    if source_hash != source_report['sha256']:
        raise ValueError('Source WAV differs from its event report')
    source = decode(args.source)
    if source.shape != (14 * SR, 2):
        raise ValueError('The source must contain exactly 14 seconds of stereo audio')
    event_map = {event['event']: event for event in source_report['events']}
    source_occupancy = np.zeros(len(source), dtype=np.uint8)
    for event in event_map.values():
        source_occupancy[round(event['at'] * SR):round(event['end'] * SR)] += 1
    if source_occupancy.max() != 1 or np.count_nonzero(source[source_occupancy == 0]):
        raise ValueError('Cannot isolate stems from overlapping events or an ambient bed')

    mix = np.zeros_like(source)
    occupancy = np.zeros(len(source), dtype=np.uint8)
    events = []

    def stem(name):
        event = event_map[name]
        return source[round(event['at'] * SR):round(event['end'] * SR)].copy()

    def place(name, clip, at, processing='Unchanged source-mix segment'):
        start = round(at * SR)
        mix[start:start + len(clip)] += clip
        occupancy[start:start + len(clip)] += 1
        events.append({'event': name, 'at': at, 'end': (start + len(clip)) / SR,
                       'source_at': event_map[name]['at'],
                       'source_end': event_map[name]['end'], 'processing': processing})

    for name in ('initial_charge', 'dialogue', 'charge_release', 'magic_arrest'):
        place(name, stem(name), event_map[name]['at'])

    cry = stem('native_battle_cry')
    cry_at = 8.2
    cry_end = cry_at + len(cry) / SR
    if cry_end >= 9.2:
        raise ValueError('Native cry no longer fits before the arrest')
    place('native_battle_cry', cry, cry_at, 'Moved without time stretch, pitch change or trimming')

    swing_at, swing_end = 9.0, 9.29
    swing = stem('axe_swing')[:round((swing_end - swing_at) * SR)]
    if len(swing) != round((swing_end - swing_at) * SR):
        raise ValueError('Swing source is too short')
    # Keep the source attack transient and taper its cut tail. During the last
    # syllable, only the whoosh is reduced; the cry is never compressed or cut.
    fade = min(round(.035 * SR), len(swing))
    swing[-fade:] *= np.linspace(1, 0, fade)[:, None]
    times = swing_at + np.arange(len(swing)) / SR
    duck = .18 + .82 * np.clip((times - cry_end) / .018, 0, 1)
    swing *= duck[:, None]
    place('axe_swing', swing, swing_at,
          'First 0.29 s retained; 35 ms tail fade; ducked to 18% under cry, 18 ms recovery')

    before = loudness(encode(mix))
    master_db = min(-14 - before['lufs'], -1.5 - before['true_peak_dbtp'])
    master = 10 ** (master_db / 20)
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / 'performance_mix.wav'
    output.write_bytes(encode(mix * master))
    delivered = decode(output)
    stats = loudness(output.read_bytes())
    aac = ff(['-v', 'error', '-f', 'wav', '-i', 'pipe:0', '-c:a', 'aac', '-b:a', '192k',
              '-f', 'adts', 'pipe:1'], output.read_bytes()).stdout
    aac_wav = ff(['-v', 'error', '-f', 'aac', '-i', 'pipe:0', '-ar', SR, '-ac', 2,
                  '-c:a', 'pcm_s24le', '-f', 'wav', 'pipe:1'], aac).stdout
    aac_stats = loudness(aac_wav)
    quiet = occupancy == 0
    dialogue = event_map['dialogue']
    speech_slice = slice(round(dialogue['at'] * SR), round(dialogue['end'] * SR))
    speech_error = float(abs(delivered[speech_slice] - source[speech_slice] * master).max())
    checks = {
        'duration_14s': len(delivered) == 14 * SR,
        'loudness_target': abs(stats['lufs'] + 14) <= .15,
        'wav_peak_safe': stats['true_peak_dbtp'] <= -1,
        'aac_peak_safe': aac_stats['true_peak_dbtp'] <= -1,
        'no_clipping': not np.count_nonzero(abs(delivered) >= 1),
        'quiet_outside_cues': not np.count_nonzero(delivered[quiet]),
        'dialogue_unchanged_except_common_gain_and_pcm_quantization': speech_error < 3e-7,
        'cry_finishes_before_9_2': cry_end < 9.2,
        'contact_at_frame_279': event_map['magic_arrest']['at'] * 30 == 279,
        'only_intentional_cry_swing_overlap': occupancy.max() == 2
            and np.count_nonzero(occupancy > 1) == round((cry_end - swing_at) * SR),
    }
    checks = {name: bool(passed) for name, passed in checks.items()}
    report = {
        'output': output.relative_to(ROOT).as_posix(),
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'source': args.source.relative_to(ROOT).as_posix(), 'source_sha256': source_hash,
        'duration_s': len(delivered) / SR, 'sample_rate': SR, 'channels': 2,
        'events': sorted(events, key=lambda event: event['at']),
        'meter': stats, 'aac_192k_meter': aac_stats, 'master_gain_db': master_db,
        'sample_peak_dbfs': db(float(abs(delivered).max())),
        'clipped_samples': int(np.count_nonzero(abs(delivered) >= 1)),
        'nonzero_samples_outside_cues': int(np.count_nonzero(delivered[quiet])),
        'max_simultaneous_events': int(occupancy.max()),
        'intentional_overlap_s': np.count_nonzero(occupancy > 1) / SR,
        'dialogue_pcm_max_error_after_common_gain': speech_error,
        'voice_tempo_or_pitch_changed': False, 'new_synthesis': False,
        'battle_cry_language': 'en', 'main_dialogue_language': 'ru',
        'checks': checks, 'passed': all(checks.values()), 'heard': False,
        'limitations': 'Technical audio analysis only; no subjective listening. The short source cry remains English. Final video mux and visible synchronization require their own check.',
    }
    (args.out / 'performance_mix.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    # Derive mouth movement from the isolated cry, never from its overlap with
    # the whoosh. Its new start must be used by the visual face animation.
    step = SR // 30
    mono = cry.mean(axis=1)
    rms = np.array([np.sqrt(np.mean(mono[i:i + step] ** 2)) for i in range(0, len(mono), step)])
    envelope = {'source': report['source'], 'source_sha256': source_hash,
                'cue': 'native_battle_cry', 'fps': 30, 'start_s': cry_at,
                'start_frame': round(cry_at * 30), 'duration_s': len(cry) / SR,
                'frames': len(rms), 'env': (rms / max(float(rms.max()), 1e-9)).tolist(),
                'text': 'Attack!', 'language': 'en',
                'method': 'RMS of isolated existing cry per 1/30 s; excludes overlapping swing.'}
    (args.out / 'battle_cry_envelope.json').write_text(json.dumps(envelope, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': report['output'], 'meter': stats, 'aac_meter': aac_stats,
                      'master_gain_db': master_db, 'passed': report['passed'], 'checks': checks}))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=BASE / 'v6/audio/performance_mix.wav')
    parser.add_argument('--out', type=Path, default=BASE / 'v12/assembled')
    build(parser.parse_args())
