"""Локальное воспроизводимое сведение 9-секундной сцены Лины, без Blender.

Запуск: py -3.11 -B tools/skit/lina_short_audio.py
Недостающие оригиналы извлекаются штатным Source2Viewer только в audio/sources.
Игровые ресурсы и WAV остаются локальными; публикуется видео, не набор звуков.
"""
import sys
sys.dont_write_bytecode = True
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import wave

import numpy as np
from chase_audio import SR, decode, encode, ff, loudness, metrics

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/study/lina_threat/final/audio'
SOURCES = (
    'sounds/weapons/hero/lina/preattack',
    'sounds/physics/movement/hero/lina/idle_loop',
    'sounds/ambient/soundscapes/snowy_wind_lp',
    'sounds/weapons/hero/lina/dragonslave01',
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encode_pcm24(a):
    """Seekable classic PCM WAV with exact RIFF/data lengths for video editors."""
    assert np.max(np.abs(a)) < 1
    ints = np.rint(a * 8388608).astype(np.int32).reshape(-1)
    packed = np.column_stack((ints & 255, (ints >> 8) & 255,
                              (ints >> 16) & 255)).astype(np.uint8)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(packed.tobytes())
    return buf.getvalue()


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [OUT / 'sources' / (s + '.wav') for s in SOURCES]
    missing = [s + '.vsnd_c' for s, p in zip(SOURCES, paths) if not p.exists()]
    if missing:
        sys.path.insert(0, str(ROOT / 'tools'))
        from paths import S2V, VPK
        result = subprocess.run([S2V, '-i', VPK, '-o', str(OUT / 'sources'),
                                 '-d', '-f', ','.join(missing)],
                                capture_output=True, check=True)
        # Не сохранять личные абсолютные пути из журнала CLI.
        assert result.returncode == 0
    if not all(p.is_file() for p in paths):
        raise FileNotFoundError('Source2Viewer did not produce all required WAVs')
    return paths


def build():
    paths = prepare()
    hashes = [sha(p) for p in paths]
    mix = np.zeros((9 * SR, 2), dtype=np.float64)
    occupancy = np.zeros(len(mix), dtype=np.uint8)
    cues = []

    def cue(name, source, at, duration, level, pan, envelope,
            offset=0., pitch=1., lowpass=8500):
        p = paths[source]
        raw = ff(['-v', 'error', '-i', p, '-ac', 1, '-af',
                  f'aresample={SR},asetrate={round(SR*pitch)},aresample={SR},'
                  f'highpass=f=45,lowpass=f={lowpass}',
                  '-ar', SR, '-f', 'f32le', 'pipe:1']).stdout
        a = np.frombuffer(raw, np.float32).astype(np.float64)
        a = a[round(offset*SR):round((offset+duration)*SR)].copy()
        if len(a) < round(duration*SR)-2:
            raise ValueError(f'Source too short for {name}')
        a = a[:round(duration*SR)]
        rms = float(np.sqrt(np.mean(a*a)))
        if not np.isfinite(a).all() or rms <= 1e-7:
            raise ValueError(f'Invalid source for {name}')
        a *= 10**(level/20) / rms
        t = np.arange(len(a))/SR
        a *= np.interp(t, *zip(*envelope))
        # Both sample endpoints are zero, also for cropped continuous sources.
        edge = min(240, len(a)//2)
        a[:edge] *= np.linspace(0, 1, edge)
        a[-edge:] *= np.linspace(1, 0, edge)
        pan_values = np.interp(t, *zip(*pan))
        angles = (pan_values+1)*math.pi/4
        stereo = a[:, None]*np.column_stack((np.cos(angles), np.sin(angles)))
        start = round(at*SR)
        assert start+len(a) <= len(mix)
        mix[start:start+len(a)] += stereo
        occupancy[start:start+len(a)] += (np.abs(a) > 1e-7)
        cues.append(dict(name=name, source=SOURCES[source]+'.vsnd_c', at_s=at,
                         end_s=(start+len(a))/SR, source_offset_s=offset,
                         duration_s=duration, pitch=pitch, lowpass_hz=lowpass,
                         rms_before_envelope_dbfs=level, pan=pan, envelope=envelope))

    cue('Возникновение огня', 0, 0., .72, -24, [(0,.18)],
        [(0,0),(.025,1),(.48,.75),(.72,0)])
    cue('Рост, удержание и угасание огня', 1, .18, 2.12, -29,
        [(0,.18)], [(0,0),(.3,.55),(1.05,1),(1.32,.42),(1.92,.35),(2.12,0)],
        lowpass=6500)
    cue('Наплыв тени справа — воздушное давление', 2, 1.5, .9, -26,
        [(0,.65),(.9,.25)], [(0,0),(.35,1),(.58,.8),(.9,0)],
        offset=2., lowpass=650)
    cue('Воздух при развороте', 2, 4.12, .68, -35,
        [(0,.05),(.68,-.15)], [(0,0),(.3,1),(.68,0)],
        offset=4., lowpass=3200)
    cue('Огненный уход влево и остаточный хвост', 3, 5., 2.83, -22,
        [(0,0),(.4,-.2),(1.4,-.72),(2.3,-.92),(2.83,-.92)],
        [(0,0),(.04,1),(.8,.85),(1.6,.55),(2.3,.15),(2.65,.04),(2.83,0)],
        pitch=.85, lowpass=7500)

    # Only static gain: preserve pauses and event hierarchy, no pumping/beat.
    stats = loudness(encode(mix))
    gain_db = min(-14-stats['lufs'], -2-stats['true_peak_dbtp'])
    mix *= 10**(gain_db/20)
    target = OUT / 'lina_short_stereo48k.wav'
    target.write_bytes(encode_pcm24(mix))
    with wave.open(str(target)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (2,3,SR,432000)
    decoded = decode(target)
    met = {**metrics(decoded, 7.83, 9), **loudness(target.read_bytes())}
    assert decoded.shape == (432000, 2)
    assert met['clipped_samples'] == 0 and met['true_peak_dbtp'] <= -1.8
    assert met['black_tail_nonzero_samples'] == 0
    assert np.count_nonzero(decoded[round(2.4*SR):round(4.12*SR)]) == 0
    assert hashes == [sha(p) for p in paths]
    # Deterministic re-encoding with the same source PCM must match exactly.
    assert encode_pcm24(mix) == target.read_bytes()
    blocks = []
    for start in np.arange(0, 9, .25):
        a = decoded[round(start*SR):round((start+.25)*SR)]
        blocks.append(dict(start_s=float(start), rms=float(np.sqrt(np.mean(a*a))),
                           peak=float(np.max(np.abs(a)))))
    report = dict(status='Технически проверено; слуховая приёмка не выполнена',
        audio_heard=False, sample_rate=SR, channels=2, pcm_bits=24,
        output=target.relative_to(ROOT).as_posix(), sha256=sha(target),
        sources=[dict(vpk_path=s+'.vsnd_c', local=p.relative_to(ROOT).as_posix(),
                      sha256=h, owner='Valve, Dota 2')
                 for s,p,h in zip(SOURCES,paths,hashes)],
        license_url='https://store.steampowered.com/video_policy',
        source_policy='Проприетарные игровые ресурсы Valve; не CC0. '
                      'Локальное сведение для видео. Не распространять WAV/исходники отдельно.',
        cues=cues, master_gain_db=gain_db, metrics=met,
        max_simultaneous_cues=int(occupancy.max()), quarter_second_metrics=blocks,
        exact_repeat_encoding=True, input_hashes_unchanged=True,
        synthetic_sources=False,
        limitations=[
            'Нет прослушивания: отсутствие нежелательных тембров и художественный баланс слухом не подтверждены.',
            'Тень озвучена обработанным ветром как постановочный акцент, не шагом невидимого персонажа.',
            'Dragon Slave использован как огненный воздушный уход; это монтажная интерпретация ресурса.',
            'Панорама задана по экранному направлению и раннему листу постановки; финальное видео ещё не сверено.',
            '7.5–7.83 с — затухающий остаток игрового эффекта; 7.83–9 с — точная цифровая тишина.',
            'LUFS ограничен запасом по истинному пику: автоматического подъёма до -14 любой ценой нет.',
        ])
    (OUT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (OUT/'report.md').write_text(
        '# Звук короткой сцены Лины\n\n'
        'Сборка: `py -3.11 -B tools/skit/lina_short_audio.py`. '
        'Выход: `lina_short_stereo48k.wav`, PCM24, stereo, 48000 Гц, ровно 9 с.\n\n'
        'Реальные источники: Dota 2 pak01_dir.vpk; точные пути и SHA256 — в report.json. '
        'Синтез, речь, музыка и случайная генерация не используются. '
        'Огонь затихает в 2.1–2.3 с; тень входит справа; уход панорамируется влево.\n\n'
        'Правообладатель — Valve. Ресурсы проприетарные. '
        '[Valve Video Policy](https://store.steampowered.com/video_policy) '
        'разрешает использование контента в видео в указанных политикой условиях, '
        'но запрещает отдельное распространение игровых ассетов. WAV — локальный материал монтажа.\n\n'
        f'Измерено: {met["lufs"]} LUFS, {met["true_peak_dbtp"]} dBTP; '
        'клиппированных отсчётов 0. Проверены длительность, цифровая тишина, '
        'повторное кодирование и неизменность источников.\n\n'
        'Ограничения:\n\n'+''.join('- '+v+'\n' for v in report['limitations']), encoding='utf-8')
    print(json.dumps(dict(output=report['output'], metrics=met, sha256=sha(target)), indent=2))


if __name__ == '__main__':
    build()
