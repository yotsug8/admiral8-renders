"""Воспроизводимый CPU-микс флота, 30 fps; без музыки, TTS и субтитров.

Примеры (из корня проекта):
  python -B tools/skit/fleet_battle_mix.py --write-events _game/skits/fleet_battle/audio/events.json
  python -B tools/skit/fleet_battle_mix.py --output _game/skits/fleet_battle/audio/preview.wav
  python -B tools/skit/fleet_battle_mix.py --source silent.mp4 --output mixed.mp4 --events events.json

JSON полностью заменяет список событий, а не дополняет его. Формат:
  {"fps":30,"duration":18,"events":[
    {"id":"hit","sound":"sword","frame":240,"gain_db":-3,"pan":0.2}]}
frame отсчитывается от нуля (сцена флота также начинается с кадра 0); вместо frame можно
указать at в секундах. Ровно одно из этих полей обязательно. gain_db: -60..12,
pan: -1..1 (баланс исходного стерео). Только waves допускает duration:
это управляемый фон с кроссфейдом петли и плавными краями. Остальные ресурсы
воспроизводятся полностью, без подрезки, смены высоты или скорости.

--tail-policy extend (по умолчанию) сохраняет все хвосты и при необходимости
добавляет удержание последнего видеокадра, CPU H.264. Без продления видео
копируется без перекодирования. --tail-policy error требует вместить хвосты
в исходную длину. Исходная аудиодорожка не входит в новый микс.
Штатный JSON — гипотеза тайминга, не проверенная синхронизация с постановкой.
Извлечение: только точные VPK-пути через существующий Source2Viewer CLI.
Ресурсы принадлежат игре, остаются локальными; никаких загрузок/синтеза.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np

# Не создавать __pycache__ в чужих каталогах при отдельном поручении.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import DOTA_ROOT, S2V, VPK
from chase_audio import SR, FF, decode, encode, ff, loudness

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / '_game/skits/fleet_battle/audio'
SOUNDS = {
    'waves': 'ambient/soundscapes/waves_close_lp_1',
    'hook_throw': 'weapons/hero/pudge/hook_throw',
    'hook_stop': 'weapons/hero/pudge/hook_retract_stop',
    'hook_impact': 'weapons/hero/pudge/hook_impact',
    'swoosh': 'weapons/hero/dragon_knight/sword_swing1',
    'sword': 'weapons/hero/kunkka/attack01',
    'heavy_sword': 'weapons/hero/shared/impacts/heavy_sword_impact1',
    'body_impact': 'physics/deaths/common/body_impact_heavy_01',
    'waterstep1': 'physics/footsteps/common/waterstep_01',
    'waterstep2': 'physics/footsteps/common/waterstep_02',
    'step1': 'physics/footsteps/hero/pudge/step01',
    'step2': 'physics/footsteps/hero/pudge/step02',
    'chain': 'physics/movement/hero/pudge/chain_movement1',
    'giant_swing': 'weapons/hero/pudge/dismember_swing1',
    'bell': 'weapons/hero/kunkka/ability_ghost_ship_bell',
    'ghost_ship': 'weapons/hero/kunkka/ability_ghost_ship',
    'ship_crash': 'weapons/hero/kunkka/ghostship_crash',
    'splash': 'physics/body/water_splash_large',
    'battlecry': 'vo/kunkka/kunk_attack_01',
}


def sound_file(name):
    return AUDIO / (name + ('.mp3' if name == 'battlecry' else '.wav'))


def default_events():
    events = []

    def cue(name, sound, frame=None, gain_db=0, pan=0, **kw):
        event = dict(id=name, sound=sound, gain_db=gain_db, pan=pan, **kw)
        if frame is not None:
            event['frame'] = frame
        events.append(event)

    cue('ocean', 'waves', 0, -22, duration=18)
    cue('threat_chain', 'chain', 119, -5)
    cue('threat_chain_stop', 'hook_stop', 134, -7)
    for i, frame in enumerate((182, 191)):
        cue(f'landing_step_{i + 1}', f'waterstep{i % 2 + 1}', frame, -9,
            -.25 if i % 2 == 0 else .25)
    for i, frame in enumerate((191, 203, 215, 230)):
        cue(f'shore_step_{i + 1}', f'step{i % 2 + 1}', frame, -12,
            -.25 if i % 2 == 0 else .25)
    for i, frame in enumerate((259, 274)):
        cue(f'swing_{i + 1}', 'swoosh', frame - 4, -8)
        cue(f'sword_{i + 1}', 'sword', frame, -5)
        cue(f'contact_{i + 1}', 'heavy_sword', frame, -4)
    cue('giant_swing', 'giant_swing', 315, -5)
    cue('giant_ground_contact', 'body_impact', 320, -2)
    cue('native_battlecry', 'battlecry', 345, 1)
    cue('summon_bell', 'bell', 384, -7)
    cue('ghost_fleet_pass', 'ghost_ship', 390, -6)
    cue('ram_left', 'ship_crash', 429, -3, -.25)
    cue('ram_right', 'ship_crash', 443, -6, .25)
    cue('ram_center', 'ship_crash', 457, -8, 0)
    cue('dropped_cleaver', 'heavy_sword', 465, -14, .35)
    cue('dropped_hook', 'chain', 467, -15, -.35)
    cue('giant_shore_fall', 'body_impact', 483, 1)
    return dict(fps=30, duration=18, status='staged_events_pending_final_picture_review',
                frame_origin='zero_based; Blender frame 0 is video frame 0',
                timeline=[{'start': a, 'end': b, 'action': action} for a, b, action in (
                    (0, 2, 'leading_ship_tracking'), (2, 3.5, 'fleet_and_shore'),
                    (3.5, 5.5, 'giant_threat'), (5.5, 8, 'landing_and_run'),
                    (8, 11.5, 'sword_battle'), (11.5, 13, 'summon_order'),
                    (13, 15.5, 'ghost_ship_ram'), (15.5, 17, 'giant_falls_on_shore'),
                    (17, 18, 'aftermath'))], events=events)


def number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label}: expected number')
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}: expected {low}..{high}')
    return float(value)


def validate(config):
    if not isinstance(config, dict) or config.get('fps', 30) != 30:
        raise ValueError('Expected an object with fps=30')
    duration = number(config.get('duration', 18), 'duration', 1, 120)
    if abs(duration * 30 - round(duration * 30)) > 1e-7:
        raise ValueError('duration must contain a whole number of 30 fps frames')
    events = config.get('events')
    if not isinstance(events, list) or not 1 <= len(events) <= 500:
        raise ValueError('events must contain 1..500 explicit events')
    ids, result = set(), []
    allowed = {'id', 'sound', 'frame', 'at', 'gain_db', 'pan', 'duration'}
    for event in events:
        if not isinstance(event, dict) or set(event) - allowed:
            raise ValueError(f'Unknown event fields: {event}')
        name = event.get('id')
        if not isinstance(name, str) or not name or name in ids:
            raise ValueError('Every event needs a unique nonempty id')
        ids.add(name)
        if event.get('sound') not in SOUNDS:
            raise ValueError(f'{name}: unknown sound; use --list-sounds')
        if ('frame' in event) == ('at' in event):
            raise ValueError(f'{name}: provide exactly one of frame / at')
        if 'frame' in event:
            frame = number(event['frame'], name + '.frame', 0, duration * 30)
            if not frame.is_integer():
                raise ValueError(f'{name}: frame must be integral')
            at = frame / 30
        else:
            at = number(event['at'], name + '.at', 0, duration)
        if at >= duration:
            raise ValueError(f'{name}: onset must precede timeline end')
        row = dict(id=name, sound=event['sound'], at=at,
                   gain_db=number(event.get('gain_db', 0), name + '.gain_db', -60, 12),
                   pan=number(event.get('pan', 0), name + '.pan', -1, 1))
        if 'duration' in event:
            if event['sound'] != 'waves':
                raise ValueError(f'{name}: one-shot duration overrides would cut tails')
            row['duration'] = number(event['duration'], name + '.duration', .1, duration - at)
        result.append(row)
    return duration, sorted(result, key=lambda e: e['at'])


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as src:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def display(path):
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n',
                    encoding='utf-8')


def prepare(names):
    """Одно точное извлечение на ресурс; кэш защищён SHA, не размером файла."""
    AUDIO.mkdir(parents=True, exist_ok=True)
    manifest_path = AUDIO / 'assets.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    selected = {}
    for name in sorted(names):
        path = sound_file(name)
        resource = f'sounds/{SOUNDS[name]}.vsnd_c'
        archive = (Path(DOTA_ROOT) / 'game/dota_russian/pak01_dir.vpk'
                   if name == 'battlecry' else Path(VPK))
        archive_label = ('game/dota_russian/pak01_dir.vpk' if name == 'battlecry'
                         else 'game/dota/pak01_dir.vpk')
        saved = manifest.get(name)
        if saved and path.exists():
            if (saved['resource'] != resource or saved['sha256'] != sha(path)
                    or saved.get('archive', archive_label) != archive_label):
                raise ValueError(f'Cached resource changed: {path}; review before re-extraction')
        else:
            if shutil.disk_usage(AUDIO).free < 32 * 1024**2:
                raise ValueError('Less than 32 MiB free; extraction stopped')
            if not Path(S2V).is_file() or not archive.is_file():
                raise FileNotFoundError('Missing Source2Viewer/VPK; set S2V and DOTA_ROOT')
            # Прямой путь вывода проверен изолированной пробой. Временный
            # каталог исключает использование неполного файла после сбоя.
            with tempfile.TemporaryDirectory(prefix='.extract-', dir=AUDIO) as tmp:
                staged = Path(tmp) / path.name
                subprocess.run([S2V, '-i', str(archive), '--vpk_filepath', resource,
                                '-d', '-o', str(staged)], capture_output=True, check=True)
                samples = decode(staged)
                if len(samples) > 30 * SR:
                    raise ValueError(f'{name}: unexpectedly long resource')
                staged.replace(path)
            manifest[name] = dict(resource=resource, archive=archive_label,
                                  file=path.name, sha256=sha(path),
                                  duration_s=len(samples) / SR, bytes=path.stat().st_size)
            write_json(manifest_path, manifest)
        selected[name] = manifest[name]
    return selected


def loop_bed(clip, count):
    """Петля только для фоновых волн; линейный 100 ms кроссфейд шва."""
    overlap = min(round(.1 * SR), len(clip) // 4)
    if overlap < 2:
        raise ValueError('Ambient resource too short')
    out = np.zeros((count, 2), dtype=np.float64)
    first = min(count, len(clip))
    out[:first] = clip[:first]
    end = first
    while end < count:
        start = end - overlap
        n = min(len(clip), count - start)
        ramp = np.linspace(0, 1, overlap)[:, None]
        out[start:end] = out[start:end] * (1 - ramp) + clip[:overlap] * ramp
        out[end:start + n] = clip[overlap:n]
        end = start + n
    fade = min(round(.15 * SR), count // 2)
    out[:fade] *= np.linspace(0, 1, fade)[:, None]
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return out


def mix_events(events, duration):
    cache, clips, cues = {}, [], []
    end = round(duration * SR)
    for event in events:
        name = event['sound']
        if name not in cache:
            cache[name] = decode(sound_file(name))
        clip = cache[name].copy()
        if 'duration' in event:
            clip = loop_bed(clip, round(event['duration'] * SR))
        gain = 10 ** (event['gain_db'] / 20)
        pan = event['pan']
        clip *= gain * np.array([1 - max(0, pan), 1 + min(0, pan)])
        start = round(event['at'] * SR)
        end = max(end, start + len(clip))
        clips.append((start, clip))
        cues.append({**event, 'start_sample': start, 'samples': len(clip),
                     'end_s': (start + len(clip)) / SR,
                     'tail_preserved': 'duration' not in event})
    # Кратность 30 fps позволяет удержать картинку точно до конца звука.
    count = math.ceil(end / (SR // 30)) * (SR // 30)
    mix = np.zeros((count, 2), dtype=np.float64)
    for start, clip in clips:
        mix[start:start + len(clip)] += clip
    if not np.isfinite(mix).all() or not np.any(mix):
        raise ValueError('Invalid or silent mix')
    return mix, cues


def norm_stats(data):
    log = ff(['-i', 'pipe:0', '-af',
              'loudnorm=I=-14:TP=-3.5:LRA=11:print_format=json', '-f', 'null', '-'],
             data).stderr.decode(errors='replace')
    return json.loads(log[log.rindex('{'):log.rindex('}') + 1])


def master(mix):
    """Oversampled limiter с компенсацией задержки, затем two-pass loudnorm."""
    # float WAV до лимитера: перегруз суммы не обрезается PCM-кодированием.
    raw = ff(['-v', 'error', '-f', 'f32le', '-ar', SR, '-ac', 2, '-i', 'pipe:0',
              '-c:a', 'pcm_f32le', '-f', 'wav', 'pipe:1'], mix.astype(np.float32).tobytes()).stdout
    initial = norm_stats(raw)
    gain = -14 - float(initial['input_i'])
    limited = ff(['-v', 'error', '-i', 'pipe:0', '-af',
                  f'volume={gain:.9f}dB,aresample=192000,'
                  'alimiter=limit=0.668344:attack=5:release=80:level=0:latency=1,'
                  'aresample=48000', '-c:a', 'pcm_f32le', '-f', 'wav', 'pipe:1'], raw).stdout
    measured = norm_stats(limited)
    filt = 'loudnorm=I=-14:TP=-3.5:LRA=11:linear=true:' + ':'.join([
        f'measured_I={measured["input_i"]}', f'measured_TP={measured["input_tp"]}',
        f'measured_LRA={measured["input_lra"]}', f'measured_thresh={measured["input_thresh"]}',
        f'offset={measured["target_offset"]}'])
    wav = ff(['-v', 'error', '-i', 'pipe:0', '-af', filt, '-ar', SR,
              '-c:a', 'pcm_s24le', '-f', 'wav', 'pipe:1'], limited).stdout
    # Гейт LUFS у разреженных ударов меняется после ограничителя: второй
    # проход loudnorm сам по себе не гарантирует -14 на декодированном выходе.
    # Коррекция проверяется заново; 192kHz limiter не позволяет ей перегрузить пик.
    corrections = []
    for _ in range(4):
        measured_out = loudness(wav)
        correction = -14 - measured_out['lufs']
        if abs(correction) <= .05:
            break
        corrections.append(correction)
        wav = ff(['-v', 'error', '-i', 'pipe:0', '-af',
                  f'volume={correction:.9f}dB,aresample=192000,'
                  'alimiter=limit=0.668344:attack=5:release=80:level=0:latency=1,'
                  'aresample=48000', '-c:a', 'pcm_s24le', '-f', 'wav', 'pipe:1'], wav).stdout
    return wav, dict(pre_limiter_gain_db=gain, loudnorm_filter=filt,
                     correction_gains_db=corrections,
                     limiter='192kHz, -3.5dBFS (AAC reconstruction headroom); '
                             '5ms attack, 80ms release, latency compensated')


def check_audio(path, expected_samples, lossy=False):
    decoded = decode(path)
    stats = loudness(encode(decoded))
    checks = dict(loudness=abs(stats['lufs'] + 14) <= .2,
                  true_peak=stats['true_peak_dbtp'] <= -1,
                  no_clipping=bool(np.max(np.abs(decoded)) < 1),
                  duration=(expected_samples <= len(decoded) <= expected_samples + 1024
                            if lossy else len(decoded) == expected_samples))
    return dict(**stats, decoded_samples=len(decoded), checks=checks,
                passed=all(checks.values()))


def calibrate_aac(wav):
    """Измерение AAC в памяти до дорогого mux; пики проверяются и после него."""
    gain = 0.0
    for _ in range(3):
        aac = ff(['-v', 'error', '-i', 'pipe:0', '-af', f'volume={gain:.9f}dB',
                  '-c:a', 'aac', '-b:a', '320k', '-f', 'adts', 'pipe:1'], wav).stdout
        pcm = ff(['-v', 'error', '-f', 'aac', '-i', 'pipe:0', '-ar', SR, '-ac', 2,
                  '-c:a', 'pcm_s24le', '-f', 'wav', 'pipe:1'], aac).stdout
        stats = loudness(pcm)
        if abs(stats['lufs'] + 14) <= .05 and stats['true_peak_dbtp'] <= -1.1:
            return gain, stats
        gain += min(-14 - stats['lufs'], -1.15 - stats['true_peak_dbtp'])
    raise ValueError(f'AAC calibration failed: {stats}; review event gains')


def build(args):
    config = json.loads(args.events.read_text(encoding='utf-8-sig')) if args.events else default_events()
    duration, events = validate(config)
    if args.source and (not args.source.is_file() or args.source.resolve() == args.output.resolve()):
        raise ValueError('Source must exist and differ from output')
    suffix = args.output.suffix.lower()
    if suffix not in ('.wav', '.mp4', '.mkv'):
        raise ValueError('Output must be WAV, MP4 or MKV')
    if suffix != '.wav' and not args.source:
        raise ValueError('Video output requires --source / --video')
    if args.output.resolve() in {sound_file(name).resolve() for name in SOUNDS}:
        raise ValueError('Output must not overwrite a cached game resource')
    timing = None
    if args.source:
        from grade import video_timing
        timing = video_timing(args.source)
        if timing['fps'] != 30 or abs(timing['duration'] - duration) > 1e-6:
            raise ValueError('Source must be CFR 30 fps and match JSON duration exactly')
    assets = prepare({event['sound'] for event in events})
    mix, cues = mix_events(events, duration)
    total = len(mix) / SR
    if total > duration and args.tail_policy == 'error':
        raise ValueError(f'Full tails end at {total:.6f}s, beyond {duration}s; '
                         'retime events or use --tail-policy extend')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    estimate = len(mix) * 6 + 32 * 1024**2
    if suffix != '.wav':
        estimate += args.source.stat().st_size * 2
    if shutil.disk_usage(args.output.parent).free < estimate:
        raise ValueError('Insufficient free space for staged output and 32 MiB reserve')
    wav, mastering = master(mix)
    aac_gain = 0.0
    if suffix != '.wav':
        aac_gain, aac_stats = calibrate_aac(wav)
        mastering.update(aac_bitrate='320k', aac_gain_db=aac_gain, aac_preflight=aac_stats)
    # Сначала проверка временного результата; предыдущий выход сохраняется
    # при любой ошибке декодирования, громкости или длительности.
    with tempfile.TemporaryDirectory(prefix='.mix-', dir=AUDIO) as tmp:
        wave_path = Path(tmp) / 'master.wav'
        wave_path.write_bytes(wav)
        wav_qa = check_audio(wave_path, len(mix))
        if not wav_qa['passed']:
            raise ValueError(f'WAV QA failed: {wav_qa}')
        with tempfile.TemporaryDirectory(prefix='.fleet-', dir=args.output.parent) as out_tmp:
            staged = Path(out_tmp) / args.output.name
            video_mode = None
            if suffix == '.wav':
                staged.write_bytes(wav)
                delivery_qa = wav_qa
            else:
                extension = total - duration
                video_args = ['-c:v', 'copy']
                video_mode = 'stream_copy'
                if extension > 0:
                    video_args = ['-vf', f'tpad=stop_mode=clone:stop_duration={extension:.9f}',
                                  '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                                  '-pix_fmt', 'yuv420p', '-threads', '2']
                    video_mode = 'CPU_H264_last_frame_hold'
                ff(['-v', 'error', '-i', args.source, '-i', wave_path,
                    '-map', '0:v:0', '-map', '1:a:0', '-map_metadata', '-1', '-sn', '-dn',
                    *video_args, '-af', f'volume={aac_gain:.9f}dB',
                    '-c:a', 'aac', '-b:a', '320k',
                    *(['-movflags', '+faststart'] if suffix == '.mp4' else []), str(staged)])
                delivery_qa = check_audio(staged, len(mix), lossy=True)
                output_timing = video_timing(staged)
                delivery_qa['checks']['video_frames'] = output_timing['count'] == round(total * 30)
                delivery_qa['checks']['video_fps'] = output_timing['fps'] == 30
                delivery_qa['passed'] = all(delivery_qa['checks'].values())
            if not delivery_qa['passed']:
                raise ValueError(f'Delivery QA failed: {delivery_qa}')
            staged.replace(args.output)
    report = dict(status='technical_candidate_not_picture_synced', audio_heard=False,
                  output=display(args.output), output_sha256=sha(args.output), fps=30,
                  timeline_s=duration, output_duration_s=total, tail_extension_s=total - duration,
                  sample_rate=SR, channels=2, events_config=config, events=cues,
                  assets=assets, mastering=mastering, wav_qa=wav_qa, delivery_qa=delivery_qa,
                  source=display(args.source) if args.source else None,
                  source_sha256=sha(args.source) if args.source else None, video_mode=video_mode,
                  ffmpeg_version=ff(['-version']).stdout.decode(errors='replace').splitlines()[0],
                  limitations=['No listening or visible-contact verification.',
                               'Default onsets are provisional; replace with staged event JSON.',
                               'waves is an edited ambience loop; one-shots retain full duration.',
                               'Source audio and subtitle streams are excluded.'])
    report_path = AUDIO / f'{args.output.stem}.report.json'
    write_json(report_path, report)
    print(json.dumps(dict(output=display(args.output), report=display(report_path),
                          duration_s=total, tail_extension_s=total - duration,
                          meter=delivery_qa, audio_heard=False), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', '--video', type=Path, help='Silent CFR 30 fps video; source audio ignored')
    parser.add_argument('--output', '--out', type=Path, help='WAV preview, or MP4/MKV with --source')
    parser.add_argument('--events', type=Path, help='JSON replaces the complete provisional event list')
    parser.add_argument('--tail-policy', choices=('extend', 'error'), default='extend')
    parser.add_argument('--write-events', type=Path, help='Write editable defaults and exit')
    parser.add_argument('--list-sounds', action='store_true')
    args = parser.parse_args()
    if args.list_sounds:
        print(json.dumps(SOUNDS, indent=2))
    elif args.write_events:
        write_json(args.write_events, default_events())
    elif args.output:
        build(args)
    else:
        parser.error('--output, --write-events or --list-sounds required')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'fleet_battle_mix: {exc}', file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr.decode(errors='replace') if isinstance(exc.stderr, bytes)
                  else exc.stderr, file=sys.stderr)
        raise SystemExit(1)
