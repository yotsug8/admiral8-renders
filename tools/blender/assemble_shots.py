"""Join silent Blender shot exports and optionally add a shared WAV track."""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render_storage import file_lock
from skit.grade import FF, video_timing
from blender.export_render_job import AUDIO_RATE, digest, mux_wav, read_wav


def silent_video_timebase(probe, source, name):
    info = subprocess.check_output([probe, '-v', 'error', '-show_entries',
                                    'stream=codec_type,time_base', '-of', 'json', str(source)])
    streams = json.loads(info).get('streams', [])
    if len(streams) != 1 or streams[0].get('codec_type') != 'video':
        raise ValueError(f'Ожидается один видеопоток без звука: {name}')
    return Fraction(streams[0]['time_base'])


def picture_hashes(source):
    result = subprocess.check_output([FF, '-nostdin', '-v', 'error', '-xerror', '-i', str(source),
                                      '-map', '0:v:0', '-fps_mode', 'passthrough',
                                      '-f', 'framemd5', '-'], text=True, encoding='utf-8')
    return [line.rsplit(',', 1)[-1].strip() for line in result.splitlines() if not line.startswith('#')]


def cut_mp4_timing(source):
    if source.suffix.lower() != '.mp4':
        raise ValueError('Для удаления отрезка нужен MP4')
    probe = os.environ.get('FFPROBE') or shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('Для монтажа нужен ffprobe')
    info = subprocess.check_output([probe, '-v', 'error', '-show_entries',
                                    'stream=codec_type,codec_name,start_pts,time_base,duration_ts,channels,sample_rate',
                                    '-of', 'json', str(source)])
    streams = json.loads(info).get('streams', [])
    kinds = sorted(stream['codec_type'] for stream in streams)
    if kinds not in (['video'], ['audio', 'video']):
        raise ValueError('Нужен MP4 с одним видеопотоком и не более чем одной звуковой дорожкой')
    timing = video_timing(source)
    if kinds == ['video']:
        return timing
    audio = next(stream for stream in streams if stream['codec_type'] == 'audio')
    samples = round(timing['count'] * AUDIO_RATE / timing['fps'])
    if (audio['codec_name'] != 'aac' or audio.get('sample_rate') != str(AUDIO_RATE)
            or audio.get('channels') not in (1, 2) or audio.get('start_pts') != 0
            or int(audio.get('duration_ts', -1)) * Fraction(audio['time_base']) != Fraction(samples, AUDIO_RATE)):
        raise ValueError('Для вырезания нужен синхронный моно- или стереозвук AAC 48 кГц на всю длину видео')
    info = subprocess.check_output([probe, '-v', 'error', '-select_streams', 'a:0',
                                    '-show_packets', '-show_entries', 'packet=pts,duration',
                                    '-of', 'json', str(source)])
    packets = json.loads(info).get('packets', [])
    if (not packets or any(packet.get('duration', 0) <= 0 for packet in packets)
            or any(a['pts'] + a['duration'] != b['pts'] for a, b in zip(packets, packets[1:]))):
        raise ValueError('Звуковая дорожка содержит разрывы или перекрытия')
    return dict(timing, audio_channels=audio['channels'])


def cut_audio(source, wav, first, stop, timing):
    fps = timing['fps']
    start, end, total = (round(frame * AUDIO_RATE / fps) for frame in (first, stop, timing['count']))
    spans = [(a, b) for a, b in ((0, start), (end, total)) if a < b]
    filters, labels = [], []
    for index, (a, b) in enumerate(spans):
        label = f'[a{index}]'
        chain = f'[0:a:0]atrim=start_sample={a}:end_sample={b},asetpts=N/SR/TB'
        # Use a short fade on the edited edge to avoid a click at the splice.
        fade = min(240, b - a)
        if a:
            chain += f',afade=t=in:ss=0:ns={fade}'
        if b != total:
            chain += f',afade=t=out:ss={b-a-fade}:ns={fade}'
        filters.append(chain + label)
        labels.append(label)
    filters.append(''.join(labels) + f'concat=n={len(spans)}:v=0:a=1[a]')
    subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(source),
                    '-filter_complex', ';'.join(filters), '-map', '[a]', '-c:a', 'pcm_s16le',
                    str(wav)], check=True)
    if read_wav(wav) != (Fraction(total - end + start, AUDIO_RATE), timing['audio_channels']):
        raise ValueError('Число отсчётов или число каналов после монтажа звука изменилось')


def cut_frames(source, output, first, stop, timing):
    """Write and verify a cut inside the caller's staging directory."""
    count, fps = timing['count'], timing['fps']
    if not 0 <= first < stop <= count or stop - first == count:
        raise ValueError('Выберите непустой отрезок, оставляющий кадры в ролике')
    filters = f"select='not(between(n,{first},{stop-1}))',settb={fps.denominator}/{fps.numerator},setpts=N"
    channels = timing.get('audio_channels')
    picture = output if channels is None else source.parent / 'cut-picture.mp4'
    subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(source),
                    '-map', '0:v:0', '-vf', filters, '-c:v', 'libx264', '-qp', '0',
                    '-pix_fmt', 'yuv420p', '-r', str(fps), '-movflags', '+faststart',
                    str(picture)], check=True)
    retained = count - stop + first
    if channels is not None:
        wav = source.parent / 'cut-audio.wav'
        cut_audio(source, wav, first, stop, timing)
        mux_wav(picture, wav, output, round(retained * AUDIO_RATE / fps), channels)
    before = picture_hashes(source)
    expected = before[:first] + before[stop:]
    final = video_timing(output)
    if ((final['size'], final['fps'], final['count']) != (timing['size'], fps, retained)
            or picture_hashes(output) != expected):
        raise ValueError('Монтаж изменил кадры за пределами указанного отрезка')


def decode_pcm(source, channels):
    return subprocess.check_output([FF, '-nostdin', '-v', 'error', '-xerror', '-i', str(source),
                                    '-map', '0:a:0', '-ac', str(channels), '-ar', str(AUDIO_RATE),
                                    '-f', 's16le', '-'])


def write_pcm(destination, data, channels):
    with wave.open(str(destination), 'wb') as output:
        output.setparams((channels, 2, AUDIO_RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(data)
    return destination


def replace_scene_audio(source, replacement, destination, first, stop, new_count):
    """Keep neighboring PCM on frame boundaries, inserting the new scene's sound."""
    timing = cut_mp4_timing(source)
    channels = timing.get('audio_channels')
    if channels is None and replacement is None:
        return None
    fps = timing['fps']
    start, end, total, inserted = (round(frame * AUDIO_RATE / fps)
                                   for frame in (first, stop, timing['count'], new_count))
    output_channels = channels or 2
    sample_width = 2 * output_channels

    original = decode_pcm(source, output_channels) if channels else bytes(total * sample_width)
    changed = decode_pcm(replacement, output_channels) if replacement else bytes(inserted * sample_width)
    if len(original) < total * sample_width or len(changed) != inserted * sample_width:
        raise ValueError('Звуковая дорожка не совпадает с длительностью сцены')
    data = original[:start * sample_width] + changed + original[end * sample_width:total * sample_width]
    return write_pcm(destination, data, output_channels)


def reorder_scene_audio(source, destination, spans):
    timing = cut_mp4_timing(source)
    channels = timing.get('audio_channels')
    if channels is None:
        return None
    fps = timing['fps']
    pcm = decode_pcm(source, channels)
    length = round(timing['count'] * AUDIO_RATE / fps) * 2 * channels
    if len(pcm) < length:
        raise ValueError('Звуковая дорожка короче монтажа')
    data = b''.join(pcm[round(first * AUDIO_RATE / fps) * 2 * channels:
                        round(stop * AUDIO_RATE / fps) * 2 * channels] for first, stop in spans)
    if len(data) != length:
        raise ValueError('Перестановка сцен изменила длительность дорожки')
    return write_pcm(destination, data, channels)


def assemble(sources, output, *, wav=None, lossless=False):
    if len(sources) < 2:
        raise ValueError('Нужны как минимум два плана')
    output = output.resolve()
    sources = [source.resolve(strict=True) for source in sources]
    if wav is not None:
        wav = wav.resolve(strict=True)
    if output.suffix.lower() != '.mp4' or any(source.suffix.lower() != '.mp4' for source in sources):
        raise ValueError('Планы и итоговый файл должны быть MP4')
    inputs = sources if wav is None else [*sources, wav]
    if any(output == source or (output.exists() and output.samefile(source)) for source in inputs):
        raise ValueError('Итоговый файл не должен заменять исходный план или звук')
    probe = os.environ.get('FFPROBE') or shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('Для сборки нужен ffprobe')

    with file_lock(output.with_suffix('.mp4.lock')):
        with TemporaryDirectory(prefix='.shots-', dir=output.parent) as directory:
            folder = Path(directory)
            listing = folder / 'shots.txt'
            shots = []
            timebases = []
            hashes = []
            profile = None
            for index, source in enumerate(sources):
                snapshot = folder / f'shot_{index:04d}.mp4'
                shutil.copyfile(source, snapshot)
                timebases.append(silent_video_timebase(probe, snapshot, source.name))
                timing = video_timing(snapshot)
                current_profile = timing['size'], timing['fps']
                if profile is not None and current_profile != profile:
                    raise ValueError(f'Размер или частота кадров плана отличаются: {source.name}')
                profile = current_profile
                hashes.extend(picture_hashes(snapshot))
                shots.append(snapshot)
            if not lossless and len(set(timebases)) > 1:
                # The concat demuxer needs identical stream time bases.
                # Choose a scale that represents the common frame period exactly.
                fps_numerator = profile[1].numerator
                scale = fps_numerator * max(1, 90_000 // fps_numerator)
                for index, (shot, timebase) in enumerate(zip(shots, timebases)):
                    if timebase == Fraction(1, scale):
                        continue
                    remuxed = folder / f'normalized_{index:04d}.mp4'
                    subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-i', str(shot),
                                    '-map', '0:v:0', '-c:v', 'copy', '-video_track_timescale',
                                    str(scale), str(remuxed)], check=True)
                    shots[index] = remuxed
            picture = staged = folder / 'assembled.mp4'
            if wav is not None:
                wav_hash = digest(wav)
                duration = Fraction(len(hashes), profile[1])
                audio_duration, channels = read_wav(wav)
                if audio_duration > duration:
                    raise ValueError('WAV длиннее монтажа')
                staged = folder / 'voiced.mp4'
            command = [FF, '-nostdin', '-v', 'error', '-xerror']
            if lossless:
                # Rebuild PTS/DTS across cuts with different H.264 frame reordering.
                for shot in shots:
                    command.extend(['-i', str(shot)])
                labels = ''.join(f'[{index}:v:0]' for index in range(len(shots)))
                command.extend(['-filter_complex', f'{labels}concat=n={len(shots)}:v=1:a=0[v]',
                                '-map', '[v]', '-c:v', 'libx264', '-qp', '0',
                                '-pix_fmt', 'yuv420p', '-r', str(profile[1])])
            else:
                listing.write_text(''.join(f"file '{shot.name}'\n" for shot in shots), encoding='ascii')
                command.extend(['-f', 'concat', '-safe', '1', '-i', str(listing),
                                '-map', '0:v:0', '-c:v', 'copy'])
            subprocess.run([*command, '-movflags', '+faststart', str(picture)], check=True)
            if wav is not None:
                mux_wav(picture, wav, staged, round(duration * AUDIO_RATE), channels)
                if digest(wav) != wav_hash:
                    raise ValueError('WAV изменился во время монтажа')
            final = video_timing(staged)
            if ((final['size'], final['fps']) != profile or final['count'] != len(hashes)
                    or picture_hashes(staged) != hashes):
                raise ValueError('Монтаж изменил кадры или их временные метки')
            staged.replace(output)
    return output


def audio_packets(probe, source):
    return subprocess.check_output([
        probe, '-v', 'error', '-select_streams', 'a', '-show_packets',
        '-show_data_hash', 'sha256', '-show_entries', 'packet=stream_index,pts_time,duration_time,data_hash',
        '-of', 'compact=p=0', str(source),
    ])


def same_audio(probe, base, edited):
    before = audio_packets(probe, base).splitlines()
    after = audio_packets(probe, edited).splitlines()
    if before == after:
        return True
    if not before or before[:-1] != after[:-1]:
        return False

    # Some MP4 muxers shorten the declared duration of the final AAC
    # packet to the edit-list boundary without changing the playback.
    def packet_without_duration(packet):
        return [field for field in packet.split(b'|') if not field.startswith(b'duration_time=')]

    if not after or packet_without_duration(before[-1]) != packet_without_duration(after[-1]):
        return False

    def playback(path):
        timing = subprocess.check_output([
            probe, '-v', 'error', '-select_streams', 'a', '-show_entries',
            'stream=time_base,start_pts,duration_ts', '-of', 'compact', str(path),
        ])
        samples = subprocess.check_output([
            FF, '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
            '-map', '0:a', '-c:a', 'pcm_s32le', '-f', 'streamhash', '-hash', 'sha256', '-',
        ])
        return timing, samples

    return playback(base) == playback(edited)


def keep_project_audio(picture, base, output):
    """Copy the original audio onto an equal-length silent picture in staging."""
    probe = os.environ.get('FFPROBE') or shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('Для сборки нужен ffprobe')
    timing, original = video_timing(picture), video_timing(base)
    if (timing['fps'], timing['count']) != (original['fps'], original['count']):
        raise ValueError('Новый кадр изменил длительность монтажа')
    subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(picture), '-i', str(base),
                    '-map', '0:v:0', '-map', '1:a?', '-c', 'copy', '-movflags', '+faststart',
                    str(output)], check=True)
    if (video_timing(output) != timing or picture_hashes(output) != picture_hashes(picture)
            or not same_audio(probe, base, output)):
        raise ValueError('Сборка изменила кадры, звук или синхронизацию')
    return output


def replace_frames(base, insert, start, output):
    """Replace a fixed-length interval and retain decoded frames and original audio."""
    base, insert = (path.resolve(strict=True) for path in (base, insert))
    output = output.resolve()
    if any(path.suffix.lower() != '.mp4' for path in (base, insert, output)):
        raise ValueError('Для замены кадров нужны MP4')
    if any(output == path or (output.exists() and output.samefile(path)) for path in (base, insert)):
        raise ValueError('Итоговый файл не должен заменять исходники')
    probe = os.environ.get('FFPROBE') or shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('Для сборки нужен ffprobe')

    with file_lock(output.with_suffix('.mp4.lock')):
        with TemporaryDirectory(prefix='.replace-', dir=output.parent) as directory:
            folder = Path(directory)
            original, replacement, staged = (folder / name for name in ('base.mp4', 'insert.mp4', 'edited.mp4'))
            shutil.copyfile(base, original)
            shutil.copyfile(insert, replacement)
            silent_video_timebase(probe, replacement, insert.name)
            timing, edit = video_timing(original), video_timing(replacement)
            if (timing['size'], timing['fps']) != (edit['size'], edit['fps']):
                raise ValueError('Размер или частота кадров вставки отличается')
            stop = start + edit['count']
            if not 0 <= start < stop <= timing['count']:
                raise ValueError('Вставка выходит за диапазон кадров')

            spans = [(index, first, end) for index, first, end in
                     ((0, 0, start), (1, 0, edit['count']), (0, stop, timing['count'])) if first < end]
            labels = [f'[p{i}]' for i in range(len(spans))]
            filters = [f'[{index}:v:0]trim=start_frame={first}:end_frame={end},'
                       f'setpts=PTS-STARTPTS,format=yuv420p{label}'
                       for (index, first, end), label in zip(spans, labels)]
            filters.append(''.join(labels) + f'concat=n={len(spans)}:v=1:a=0[v]')
            subprocess.run([FF, '-nostdin', '-v', 'error', '-xerror', '-i', str(original),
                            '-i', str(replacement), '-filter_complex', ';'.join(filters),
                            '-map', '[v]', '-map', '0:a?', '-c:a', 'copy',
                            '-c:v', 'libx264', '-qp', '0', '-pix_fmt', 'yuv420p',
                            '-r', str(timing['fps']), '-movflags', '+faststart', str(staged)], check=True)
            before = picture_hashes(original)
            expected = before[:start] + picture_hashes(replacement) + before[stop:]
            if (video_timing(staged) != timing or picture_hashes(staged) != expected
                    or not same_audio(probe, original, staged)):
                raise ValueError('Замена изменила кадры, звук или длительность вне заданного интервала')
            staged.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('shots', type=Path, nargs='+', help='Планы в порядке монтажа')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--wav', type=Path, help='Общая дорожка PCM WAV от начала монтажа')
    parser.add_argument('--lossless', action='store_true', help='Склеить с перекодированием без потерь')
    parser.add_argument('--replace-at', type=int, metavar='FRAME',
                        help='Заменить кадры первого MP4 немой вставкой из второго. Отсчёт с нуля.')
    args = parser.parse_args()
    if args.replace_at is not None and (len(args.shots) != 2 or args.wav is not None or args.lossless):
        parser.error('--replace-at требует исходный MP4 и немую вставку, звук берётся из исходника')
    try:
        if args.replace_at is None:
            print(assemble(args.shots, args.out, wav=args.wav, lossless=args.lossless))
        else:
            print(replace_frames(*args.shots, args.replace_at, args.out))
    except (ValueError, OSError, RuntimeError, EOFError, wave.Error, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Сборка не завершена. {exc}') from None


if __name__ == '__main__':
    main()
