"""Replace only the threat in the fast-attack mix with an existing Russian take.

Local PCM editing only. No Fish requests, voice time stretch, pitch shift or ASR.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from chase_audio import SR, db, decode, encode, ff, loudness

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / '_game/skits/doomsday/v12'


def build(args):
    source_report = json.loads(args.source.with_suffix('.json').read_text(encoding='utf-8'))
    voice_report = json.loads((args.voice.parent / 'voice_fix_report.json').read_text(encoding='utf-8'))
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    voice_hash = hashlib.sha256(args.voice.read_bytes()).hexdigest()
    if source_hash != source_report['sha256'] or voice_hash != voice_report['output_sha256']:
        raise ValueError('Source files changed after their preceding audits')
    original = decode(args.source)
    voice = decode(args.voice)
    if len(original) != 14 * SR:
        raise ValueError('Expected a complete 14-second source mix')
    old = next(e for e in source_report['events'] if e['event'] == 'dialogue')
    start, old_end = round(2.48 * SR), round(old['end'] * SR)
    end = start + len(voice)
    if old['at'] != 2.48 or end >= round(6.8 * SR):
        raise ValueError('Threat does not fit before the existing next event')
    if end > old_end and np.count_nonzero(original[old_end:end]):
        raise ValueError('New dialogue would overwrite another event')
    old_rms = float(np.sqrt(np.mean(original[start:old_end] ** 2)))
    voice_rms = float(np.sqrt(np.mean(voice ** 2)))
    if voice_rms <= 1e-8:
        raise ValueError('Silent replacement voice')
    voice_gain = old_rms / voice_rms
    mix = original.copy()
    mix[start:old_end] = 0
    mix[start:end] = voice * voice_gain
    before = loudness(encode(mix))
    master_db = min(-14 - before['lufs'], -1.7 - before['true_peak_dbtp'])
    master = 10 ** (master_db / 20)
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / 'performance_mix.wav'
    output.write_bytes(encode(mix * master))
    delivered = decode(output)
    meter = loudness(output.read_bytes())
    aac = ff(['-v', 'error', '-f', 'wav', '-i', 'pipe:0', '-c:a', 'aac', '-b:a', '192k',
              '-f', 'adts', 'pipe:1'], output.read_bytes()).stdout
    aac_wav = ff(['-v', 'error', '-f', 'aac', '-i', 'pipe:0', '-ar', SR, '-ac', 2,
                  '-c:a', 'pcm_s24le', '-f', 'wav', 'pipe:1'], aac).stdout
    aac_meter = loudness(aac_wav)
    changed = np.zeros(len(original), dtype=bool)
    changed[start:max(end, old_end)] = True
    retained_error = float(abs(delivered[~changed] - original[~changed] * master).max())
    voice_error = float(abs(delivered[start:end] - voice * voice_gain * master).max())
    events = [dict(e) for e in source_report['events']]
    speech = next(e for e in events if e['event'] == 'dialogue')
    speech.update(end=end / SR, source=args.voice.relative_to(ROOT).as_posix(),
                  source_sha256=voice_hash, source_at=0, source_end=len(voice) / SR,
                  processing='Existing Russian take; RMS matched to old dialogue; common master gain only')
    occupied = np.zeros(len(original), dtype=np.uint8)
    for event in events:
        occupied[round(event['at'] * SR):round(event['end'] * SR)] += 1
    checks = {
        'duration_14s': len(delivered) == 14 * SR,
        'loudness_minus14_lufs': abs(meter['lufs'] + 14) <= .15,
        'wav_true_peak_at_most_minus1_5': meter['true_peak_dbtp'] <= -1.5,
        'aac_true_peak_at_most_minus1_5': aac_meter['true_peak_dbtp'] <= -1.5,
        'no_clipping': not np.count_nonzero(abs(delivered) >= 1),
        'quiet_outside_cues': not np.count_nonzero(delivered[occupied == 0]),
        'other_events_unchanged_except_common_gain': retained_error < 3e-7,
        'new_voice_unchanged_except_gain': voice_error < 3e-7,
        'no_dialogue_overlap': bool(np.all(occupied[start:end] == 1)),
        'only_existing_cry_whoosh_overlap': int(np.count_nonzero(occupied > 1)) == round(.1015 * SR),
    }
    checks = {name: bool(passed) for name, passed in checks.items()}
    report = {
        'output': output.relative_to(ROOT).as_posix(),
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'source': args.source.relative_to(ROOT).as_posix(), 'source_sha256': source_hash,
        'voice_source': args.voice.relative_to(ROOT).as_posix(), 'voice_sha256': voice_hash,
        'voice_identity': voice_report['voice_identity'], 'duration_s': len(delivered) / SR,
        'sample_rate': SR, 'channels': 2, 'events': events, 'meter': meter,
        'aac_192k_meter': aac_meter, 'voice_gain_db': db(voice_gain), 'master_gain_db': master_db,
        'retained_events_pcm_max_error_after_common_gain': retained_error,
        'voice_pcm_max_error_after_gain': voice_error,
        'max_simultaneous_events': int(occupied.max()),
        'existing_cry_whoosh_overlap_s': np.count_nonzero(occupied > 1) / SR,
        'nonzero_samples_outside_cues': int(np.count_nonzero(delivered[occupied == 0])),
        'clipped_samples': int(np.count_nonzero(abs(delivered) >= 1)),
        'voice_time_or_pitch_changed': False, 'new_synthesis': False, 'asr_repeated': False,
        'checks': checks, 'passed': all(checks.values()), 'heard': False,
        'limitations': 'Technical mix checks only. The threat is a temporary low Russian library voice, not the original Axe actor. The retained native battle cry remains English. Final mux and visual timing need separate verification.',
    }
    (args.out / 'performance_mix.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    mono = voice.mean(axis=1)
    hop = SR // 30
    rms = np.array([np.sqrt(np.mean(mono[i:i + hop] ** 2)) for i in range(0, len(mono), hop)])
    env = np.clip(rms / max(1e-6, np.percentile(rms, 95)), 0, 1)
    envelope = {
        'start_s': 2.48, 'start_frame_exact': 74.4, 'first_active_integer_frame': 75,
        'fps': 30, 'sample_step_s': 1 / 30, 'duration_s': len(voice) / SR,
        'env': [round(float(value), 6) for value in env],
        'source': report['voice_source'], 'source_sha256': voice_hash,
        'timing': 'Time-based: local_index=(scene_frame/30 - 2.48)*30. Use zero before start_s, interpolate adjacent env samples; never round 74.4 down to 74.',
        'method': 'RMS windows of the exact inserted untrimmed voice, normalized to its 95th percentile.',
    }
    (args.out / 'threat_ru_envelope.json').write_text(json.dumps(envelope, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': report['output'], 'meter': meter, 'aac_meter': aac_meter,
                      'voice_gain_db': report['voice_gain_db'], 'master_gain_db': master_db,
                      'dialogue_end_s': end / SR, 'passed': report['passed'], 'checks': checks}))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=BASE / 'assembled/performance_mix.wav')
    parser.add_argument('--voice', type=Path, default=BASE / 'audio_ru_fix/threat_ru.wav')
    parser.add_argument('--out', type=Path, default=BASE / 'revision_alive')
    build(parser.parse_args())
