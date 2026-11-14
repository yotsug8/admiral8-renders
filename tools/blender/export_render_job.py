"""Encode a contiguous range from an existing resumable Blender render job."""
import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render_storage import file_lock
from media_color import SRGB_VIDEO_ARGS
from skit.grade import FF, video_timing

AUDIO_RATE = 48_000


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def read_wav(path):
    with wave.open(str(path), 'rb') as audio:
        rate, count, channels = audio.getframerate(), audio.getnframes(), audio.getnchannels()
        if count <= 0 or channels not in (1, 2):
            raise ValueError('Нужен непустой моно- или стереофайл PCM WAV')
        audio.setpos(count - 1)
        if len(audio.readframes(1)) != channels * audio.getsampwidth():
            raise ValueError('WAV заканчивается раньше заявленной длины')
    return Fraction(count, rate), channels


def mux_wav(picture, wav, target, samples, channels):
    # Ограничение числа кадров применяется при сборке картинки. В отдельном
    # сведении оно могло бы остановить кодировщик раньше конца аудио.
    subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-i', str(picture),
                    '-protocol_whitelist', 'file', '-f', 'wav', '-i', str(wav),
                    '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
                    '-af', f'aresample={AUDIO_RATE},apad=whole_len={samples},atrim=end_sample={samples}',
                    '-b:a', '192k', '-movie_timescale', str(AUDIO_RATE),
                    '-movflags', '+faststart', str(target)], check=True)
    probe = os.environ.get('FFPROBE') or shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('Для проверки MP4 нужен ffprobe')
    result = subprocess.run([probe, '-v', 'error', '-select_streams', 'a', '-show_entries',
                             'stream=codec_name,start_pts,duration_ts,time_base,channels,sample_rate',
                             '-of', 'json', str(target)], capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout).get('streams', [])
    if len(streams) != 1 or result.stderr.strip():
        raise ValueError('Итоговый MP4 должен содержать одну исправную звуковую дорожку')
    track = streams[0]
    if (track['codec_name'] != 'aac' or int(track['sample_rate']) != AUDIO_RATE or track['channels'] != channels
            or int(track['start_pts']) != 0
            or int(track['duration_ts']) * Fraction(track['time_base']) != Fraction(samples, AUDIO_RATE)):
        raise ValueError('Параметры звука, начало или длительность не совпали с заданием')
    subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-i', str(target),
                    '-map', '0:a:0', '-f', 'null', '-'], check=True)


def export(scene, folder, start, stop, wav=None, *, variant=None):
    if stop <= start:
        raise ValueError('Конец диапазона должен быть после начала')
    if variant is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', variant):
        raise ValueError('Вариант должен содержать от 1 до 48 латинских букв, цифр, дефисов или подчёркиваний')
    folder = folder.resolve(strict=True)
    manifest = folder / 'render_job.json'
    if not manifest.is_file():
        raise ValueError('Нет render_job.json. Подготовьте кадры через --resume')

    destination = folder / ('preview.mp4' if variant is None else f'preview-{variant}.mp4')
    with file_lock(folder / 'render.lock'):
        job = json.loads(manifest.read_text(encoding='utf-8'))
        if job.get('schema') != 1:
            raise ValueError('Версия задания рендера не поддерживается')
        if digest(scene) != job['source']:
            raise ValueError('Файл .blend отличается от версии задания рендера')
        size = tuple(job['size'])
        fps = job['fps']
        if (len(size) != 2 or any(type(side) is not int or side <= 0 or side % 2 for side in size)
                or type(fps) is not int or fps <= 0):
            raise ValueError('Для MP4 нужны чётные стороны кадра и положительный целый FPS')
        duration = Fraction(stop - start, fps)
        if wav is not None:
            wav = wav.resolve(strict=True)
            wav_hash = digest(wav)
            audio_duration, channels = read_wav(wav)
            if audio_duration > duration:
                raise ValueError('WAV длиннее выбранного диапазона кадров')

        for number in range(start, stop):
            frame = folder / f'f{number:04d}.png'
            record = frame.with_suffix('.sha256')
            if not frame.is_file() or not record.is_file():
                raise ValueError(f'Нет проверенного кадра {number}. Продолжите рендер с --resume')
            if record.read_bytes() != digest(frame).encode('ascii'):
                raise ValueError(f'Контрольная сумма кадра {number} не совпала. Продолжите рендер с --resume')

        with TemporaryDirectory(prefix='.encode-', dir=folder) as temporary:
            staged = Path(temporary) / destination.name
            picture = staged if wav is None else staged.with_name('picture.mp4')
            pattern = str(folder).replace('%', '%%') + '/f%04d.png'
            subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-framerate', str(fps),
                            '-start_number', str(start), '-start_number_range', '1', '-i', pattern,
                            '-frames:v', str(stop - start), '-an', '-c:v', 'libx264', '-crf', '18',
                            *SRGB_VIDEO_ARGS, '-pix_fmt', 'yuv420p',
                            '-movflags', '+faststart', str(picture)], check=True)
            if wav is not None:
                mux_wav(picture, wav, staged, round(duration * AUDIO_RATE), channels)
                if digest(wav) != wav_hash:
                    raise ValueError('WAV изменился во время экспорта')
            timing = video_timing(staged)
            if timing['size'] != size or timing['fps'] != fps or timing['count'] != stop - start:
                raise ValueError('Размер, FPS или число кадров итогового MP4 не совпали с заданием')
            if digest(scene) != job['source']:
                raise ValueError('Сцена изменилась во время кодирования')
            staged.replace(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', type=Path)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--range', required=True, dest='frames', metavar='FIRST:STOP')
    parser.add_argument('--wav', type=Path, help='Готовая запись с начала выбранного фрагмента')
    parser.add_argument('--variant', help='Сохранить отдельную версию preview-ВАРИАНТ.mp4')
    args = parser.parse_args()
    try:
        start, stop = map(int, args.frames.split(':'))
    except ValueError:
        parser.error('Диапазон задаётся двумя целыми числами через двоеточие')
    print(export(args.scene, args.folder, start, stop, wav=args.wav, variant=args.variant))


if __name__ == '__main__':
    main()
