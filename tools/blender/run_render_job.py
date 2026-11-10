"""Render and export a local job described by a versioned JSON file."""
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
from export_render_job import AUDIO_RATE, digest, export, read_wav
from paths import BLENDER
from render_storage import file_lock
from skit.grade import FF, video_timing

REQUIRED = {'schema_version', 'scene', 'out', 'frames', 'size', 'fps'}
OPTIONAL = {'wav', 'camera'}


def relative_path(base, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Путь в задании должен быть непустой строкой')
    path = Path(value)
    if path.anchor:
        raise ValueError('Используйте пути относительно файла задания')
    return (base / path).resolve()


def int_pair(value):
    return isinstance(value, list) and len(value) == 2 and all(type(x) is int for x in value)


def check_tools():
    if not shutil.which(BLENDER):
        raise ValueError('Blender не найден. Проверьте переменную BLENDER')
    if not shutil.which(os.environ.get('FFPROBE') or 'ffprobe'):
        raise ValueError('ffprobe не найден. Проверьте PATH или переменную FFPROBE')


def build_job(config, builder, builder_args=()):
    """Run an explicitly selected local scene script in a new job folder."""
    config = config.resolve()
    builder = builder.resolve(strict=True)
    if config.name != 'job.json' or not builder.is_file() or builder.suffix.lower() != '.py':
        raise ValueError('Для --build нужны локальный скрипт .py и выходной путь …/job.json')
    if any(arg in ('--', '--out') or arg.startswith('--out=') for arg in builder_args):
        raise ValueError('Папка сборки определяется путём к job.json')
    check_tools()
    folder = config.parent
    with file_lock(folder.with_name(folder.name + '.build.lock')):
        if folder.exists():
            raise ValueError('Для --build выберите новую папку. Для продолжения запустите существующий job.json')
        environment = os.environ.copy()
        environment.setdefault('FFMPEG', FF)
        subprocess.run([BLENDER, '-b', '--factory-startup', '--disable-autoexec',
                        '--python-exit-code', '2', '-P', str(builder), '--',
                        *builder_args, '--out', str(folder)],
                       env=environment, check=True)
        if not config.is_file():
            raise ValueError('Скрипт сцены не создал job.json')


def read_job(config):
    config = config.resolve(strict=True)
    job = json.loads(config.read_text(encoding='utf-8-sig'))
    if not isinstance(job, dict) or type(job.get('schema_version')) is not int or job['schema_version'] != 1:
        raise ValueError('Поддерживается объект задания schema_version=1')
    missing, unknown = REQUIRED - job.keys(), job.keys() - REQUIRED - OPTIONAL
    if missing or unknown:
        raise ValueError(f'Отсутствующие поля: {sorted(missing)}. Неизвестные поля: {sorted(unknown)}')
    if not int_pair(job['frames']) or job['frames'][0] >= job['frames'][1]:
        raise ValueError('frames — [первый кадр, конец без включения]')
    if not int_pair(job['size']) or any(side <= 0 or side % 2 for side in job['size']):
        raise ValueError('size — две положительные чётные стороны')
    fps = job['fps']
    if type(fps) is not int or fps <= 0:
        raise ValueError('fps должен быть положительным целым числом')
    camera = job.get('camera')
    if camera is not None and (not isinstance(camera, str) or not camera.strip()):
        raise ValueError('camera должна содержать имя камеры')

    start, stop = job['frames']
    scene = relative_path(config.parent, job['scene'])
    folder = relative_path(config.parent, job['out'])
    if not scene.is_file() or scene.suffix.lower() != '.blend':
        raise ValueError(f'Не найдена сохранённая сцена .blend: {scene}')
    if not folder.is_relative_to(config.parent) or folder == config.parent:
        raise ValueError('out должен указывать на подпапку рядом с файлом задания')
    wav = relative_path(config.parent, job['wav']) if job.get('wav') is not None else None
    if wav is not None and read_wav(wav)[0] > Fraction(stop - start, fps):
        raise ValueError('WAV длиннее выбранного диапазона кадров')
    return job, scene, folder, wav


def render_job(job, scene, folder, wav, *, snapshot=None, variant=None):
    start, stop = job['frames']
    renderer = Path(__file__).with_name('render_study_frames.py').resolve()
    command = [BLENDER, '-b', '--factory-startup', '--disable-autoexec', '--python-exit-code', '2',
               str(scene), '-P', str(renderer), '--', '--out', str(folder), '--range', f'{start}:{stop}',
               '--size', *map(str, job['size']), '--fps', str(job['fps']), '--resume']
    if job.get('camera') is not None:
        command.extend(['--camera', job['camera']])
    # Блокировка задания охватывает оба этапа. Внутренний render.lock
    # по-прежнему защищает от параллельного ручного рендера или экспорта.
    with file_lock(folder.with_name(folder.name + '.job.lock')):
        print('Проверка и рендер кадров', flush=True)
        subprocess.run(command, check=True)
        print('Проверка и экспорт MP4', flush=True)
        preview = export(scene, folder, start, stop, wav=wav, variant=variant)
        if snapshot is not None:
            shutil.copyfile(preview, snapshot)
            return snapshot
        return preview


def run_job(config):
    job = read_job(config)
    check_tools()
    return render_job(*job)


def join_project_audio(jobs, destination):
    """Build a stereo PCM timeline with sample boundaries derived from frame counts."""
    fps = jobs[0][0]['fps']
    total_frames = sum(job['frames'][1] - job['frames'][0] for job, _, _, _ in jobs)
    sample_count = total_frames * AUDIO_RATE // fps
    silence = bytes(65536)
    frame_end = sample_end = 0
    with wave.open(str(destination), 'wb') as mix:
        mix.setparams((2, 2, AUDIO_RATE, sample_count, 'NONE', 'not compressed'))
        for job, _, _, wav in jobs:
            frame_end += job['frames'][1] - job['frames'][0]
            boundary = frame_end * AUDIO_RATE // fps
            samples = boundary - sample_end
            sample_end = boundary
            remaining = 4 * samples
            if wav is None:
                while remaining:
                    size = min(remaining, len(silence))
                    mix.writeframesraw(silence[:size])
                    remaining -= size
                continue
            if not samples:
                raise ValueError('Звуковой план короче одного отсчёта в общей дорожке')
            original = digest(wav)
            filters = f'aresample={AUDIO_RATE},apad=whole_len={samples},atrim=end_sample={samples}'
            command = [FF, '-nostdin', '-v', 'error', '-xerror', '-protocol_whitelist', 'file',
                       '-f', 'wav', '-i', str(wav), '-map', '0:a:0', '-af', filters,
                       '-ac', '2', '-f', 's16le', '-']
            with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
                while block := process.stdout.read(len(silence)):
                    remaining -= len(block)
                    mix.writeframesraw(block)
                if process.wait() or remaining or digest(wav) != original:
                    raise ValueError(f'Не удалось сохранить точную длину звука плана {wav.name}')
    return destination


def run_project(config):
    from assemble_shots import assemble

    config = config.resolve(strict=True)
    data = json.loads(config.read_text(encoding='utf-8-sig'))
    required = {'schema_version', 'shots', 'out'}
    if (not isinstance(data, dict) or type(data.get('schema_version')) is not int
            or data['schema_version'] != 1 or not required <= data.keys()
            or data.keys() - required - {'wav', 'audio'}):
        raise ValueError('Проект версии 1 требует поля schema_version, shots и out')
    if not isinstance(data['shots'], list) or len(data['shots']) < 2:
        raise ValueError('В проекте нужны хотя бы два задания')
    jobs = [read_job(relative_path(config.parent, path)) for path in data['shots']]
    output = relative_path(config.parent, data['out'])
    if output.suffix.lower() != '.mp4' or not output.is_relative_to(config.parent):
        raise ValueError('out должен указывать на MP4 внутри папки проекта')
    shot_audio = 'audio' in data
    if shot_audio and (data['audio'] != 'shots' or data.get('wav') is not None):
        raise ValueError('Выберите audio="shots" или отдельный общий WAV')
    wav = relative_path(config.parent, data['wav']) if data.get('wav') is not None else None
    previews = [folder / 'preview.mp4' for _, _, folder, _ in jobs]
    previews += [folder / 'preview-project-picture.mp4' for _, _, folder, wav in jobs if wav is not None]
    recordings = [wav for _, _, _, wav in jobs if wav is not None]
    audio_sources = list(dict.fromkeys(recordings + ([wav] if wav is not None else [])))
    scene_sources = list(dict.fromkeys(scene for _, scene, _, _ in jobs))
    if any(output == p or (output.exists() and p.exists() and output.samefile(p))
           for p in previews + audio_sources):
        raise ValueError('Итог проекта не должен заменять промежуточный план или его WAV')
    fps, size = jobs[0][0]['fps'], jobs[0][0]['size']
    if any((job['fps'], job['size']) != (fps, size) for job, _, _, _ in jobs):
        raise ValueError('Задания проекта должны совпадать по размеру и FPS')
    if bool(recordings) != shot_audio:
        raise ValueError('Для WAV из заданий укажите audio="shots" и добавьте звук хотя бы к одному плану')
    duration = sum(Fraction(job['frames'][1] - job['frames'][0], fps) for job, _, _, _ in jobs)
    check_tools()
    with file_lock(output.with_suffix('.project.lock')), file_lock(output.with_suffix('.mp4.lock')):
        with TemporaryDirectory(prefix='.project-', dir=output.parent) as directory:
            staging = Path(directory)
            fingerprints = {path: digest(path) for path in [*scene_sources, *audio_sources]}
            snapshots = {}
            for index, (source, fingerprint) in enumerate(fingerprints.items()):
                extension = '.blend' if source in scene_sources else '.wav'
                snapshot = staging / f'input-{index:04d}{extension}'
                shutil.copyfile(source, snapshot)
                if digest(snapshot) != fingerprint:
                    raise ValueError(f'Исходник изменился во время подготовки проекта: {source.name}')
                snapshots[source] = snapshot
            if wav is not None:
                wav = snapshots[wav]
                if read_wav(wav)[0] > duration:
                    raise ValueError('WAV длиннее проекта')
            if shot_audio:
                mix_jobs = [(job, scene, folder, snapshots.get(recording))
                            for job, scene, folder, recording in jobs]
                for job, _, _, recording in mix_jobs:
                    first, stop = job['frames']
                    if recording is not None and read_wav(recording)[0] > Fraction(stop - first, fps):
                        raise ValueError('WAV длиннее своего плана')
                wav = join_project_audio(mix_jobs, staging / 'mix.wav')
            shots = [render_job(job, snapshots[scene], folder, None, snapshot=staging / f'shot-{i:04d}.mp4',
                                variant='project-picture' if wav is not None else None)
                     for i, (job, scene, folder, _) in enumerate(jobs)]
            assembled = assemble(shots, staging / 'project.mp4', wav=wav)
            for source, fingerprint in fingerprints.items():
                if digest(source) != fingerprint:
                    kind = 'Файл .blend' if source in scene_sources else 'Исходный WAV'
                    raise ValueError(f'{kind} изменился во время сборки проекта: {source.name}. Повторите запуск')
            assembled.replace(output)
    return output


def run_revision(config):
    from assemble_shots import replace_frames

    config = config.resolve(strict=True)
    data = json.loads(config.read_text(encoding='utf-8-sig'))
    required = {'schema_version', 'request', 'base', 'base_sha256', 'insert', 'replace_at', 'out'}
    if (not isinstance(data, dict) or data.keys() != required
            or type(data['schema_version']) is not int or data['schema_version'] != 1
            or not isinstance(data['request'], str) or not data['request'].strip()):
        raise ValueError('Ревизия версии 1 требует запрос, источник с SHA-256, вставку, позицию и выход')
    base = relative_path(config.parent, data['base'])
    output = relative_path(config.parent, data['out'])
    source = relative_path(config.parent, data['insert'])
    ready_clip = source.suffix.lower() == '.mp4'
    start = data['replace_at']
    if (base.suffix.lower() != '.mp4' or output.suffix.lower() != '.mp4'
            or not output.is_relative_to(config.parent) or output in (base, source)):
        raise ValueError('Для ревизии нужен отдельный выходной MP4 внутри её папки')
    if type(start) is not int or start < 0:
        raise ValueError('Позиция вставки должна быть неотрицательным номером кадра')
    if not ready_clip:
        job, scene, folder, wav = read_job(source)
        if (not folder.is_relative_to(config.parent) or base.is_relative_to(folder)
                or output.is_relative_to(folder)):
            raise ValueError('Кэш вставки должен быть в папке ревизии отдельно от её видео')
        if wav is not None:
            raise ValueError('Вставка должна быть без звука')
        check_tools()
    with file_lock(output.with_suffix('.revision.lock')):
        if output.exists():
            raise ValueError('Ревизия уже собрана. Для следующей версии выберите новый выход')
        with TemporaryDirectory(prefix='.revision-', dir=output.parent) as directory:
            work = Path(directory)
            original = work / 'base.mp4'
            shutil.copyfile(base, original)
            if digest(original) != data['base_sha256']:
                raise ValueError('Исходное видео изменилось. Сверьте хеш версии перед правкой')
            insert = source
            if not ready_clip:
                timing = video_timing(original)
                count = job['frames'][1] - job['frames'][0]
                if (start + count > timing['count'] or tuple(job['size']) != tuple(timing['size'])
                        or job['fps'] != timing['fps']):
                    raise ValueError('Вставка должна помещаться в исходный ролик и совпадать по размеру и FPS')
                insert = render_job(job, scene, folder, wav, snapshot=work / 'insert.mp4')
            edited = replace_frames(original, insert, start, work / 'edited.mp4')
            edited.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--project', action='store_true', help='Собрать упорядоченный список заданий и общий звук')
    modes.add_argument('--revision', action='store_true', help='Собрать новую версию с точечной заменой кадров')
    parser.add_argument('--build', type=Path, help='Локальный скрипт Blender для новой папки задания')
    parser.add_argument('--build-arg', action='append', default=[],
                        help='Аргумент скрипта сборки. Для флага используйте --build-arg=--portrait')
    args = parser.parse_args()
    if args.build_arg and args.build is None:
        parser.error('--build-arg требует --build')
    if (args.project or args.revision) and args.build is not None:
        parser.error('--project и --revision принимают существующие задания')
    try:
        if args.build is not None:
            build_job(args.job, args.build, args.build_arg)
        run = run_revision if args.revision else run_project if args.project else run_job
        print(run(args.job))
    except (ValueError, OSError, RuntimeError, EOFError, wave.Error, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Задание не завершено. {exc}') from None


if __name__ == '__main__':
    main()
