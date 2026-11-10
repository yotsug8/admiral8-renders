"""Prepare the Windows app inside its own folder and launch its normal UI."""

import argparse
from hashlib import file_digest
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from render_storage import file_lock


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / 'out/studio'
BOOTSTRAP = WORKSPACE / 'bootstrap'
RESOURCES = WORKSPACE / 'resources'
BLENDER = ('https://ftp.halifax.rwth-aachen.de/blender/release/Blender5.2/blender-5.2.3-windows-x64.zip',
           '723f08a4401502561eb763cdeacf8745b31e5f3f154d287d3830d97cf75dc2fb')
FFMPEG = ('https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/ffmpeg-8.1.2-essentials_build.zip',
          'db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec')
VC_RUNTIME = ('https://download.microsoft.com/download/4/7/c/47c6134b-d61f-4024-83bd-b9c9ea951c25/'
              'Microsoft.VCLibs.x64.14.00.Desktop.appx',
              'b56a9101f706f9d95f815f5b7fa6efbac972e86573d378b96a07cff5540c5961')
PLANNER = ('https://github.com/ggml-org/llama.cpp/releases/download/b7223/llama-b7223-bin-win-cpu-x64.zip',
           '3a2519c564559827a12d25bae683e676b8b9b9543dd68a67fa27c212bc0342fd')
MODEL = ('https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/'
         '91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf',
         '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e')
SOURCE2VIEWER = (
    'https://github.com/ValveResourceFormat/ValveResourceFormat/releases/download/20.1/cli-windows-x64.zip',
    '67aaf8a67a85ca60fd09ff343e62103a4cdf3a2d177fc656231d7d734c5b3aa3')
VOICE_RUNTIME = ('https://github.com/ggml-org/llama.cpp/releases/download/b11000/llama-b11000-bin-win-cpu-x64.zip',
                 'b6f6896d2e98c8af9ec89b2e05db05f469f295019a62446aa7472ce2b52abb29')
WRITER = ('https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/'
          'a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf',
          '3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597')
VOICE_URL = ('https://huggingface.co/ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF/resolve/'
             'ca27d74bc954b73dadab5b71ca265d87fc861a7c/')
WHISPER_URL = ('https://huggingface.co/Systran/faster-whisper-small/resolve/'
               '536b0662742c02347bc0e980a01041f333bce120/')
WHISPER_FILES = {
    'config.json': 'b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828',
    'model.bin': '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671',
    'tokenizer.json': 'fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab',
    'vocabulary.txt': '34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913',
}
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def download(asset, destination):
    url, expected = asset
    result = subprocess.run(['curl.exe', '--fail', '--location', '--silent', '--show-error',
                             '--proto', '=https', '--proto-redir', '=https', '--retry', '2',
                             '--output', str(destination), url], capture_output=True, creationflags=HIDDEN)
    if result.returncode:
        raise ValueError(f'Не удалось загрузить {url.rsplit("/", 1)[-1]}. Проверьте подключение и повторите запуск.')
    with destination.open('rb') as source:
        if file_digest(source, 'sha256').hexdigest() != expected:
            raise ValueError(f'Контрольная сумма не совпала. Файл {url.rsplit("/", 1)[-1]}.')


def install_zip(asset, directory, executable):
    ready = directory / executable
    if ready.is_file():
        return ready
    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.download-', dir=directory.parent) as temp:
        stage = Path(temp)
        archive = stage / 'tool.zip'
        download(asset, archive)
        with ZipFile(archive) as source:
            source.extractall(stage / 'files')
        package = stage / 'files'
        if not (package / executable).is_file():
            folders = [folder for folder in package.iterdir() if (folder / executable).is_file()]
            if len(folders) != 1:
                raise ValueError(f'В архиве отсутствует {executable}.')
            package = folders[0]
        package.rename(directory)
    return ready


def install_model(asset, path):
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.download-', dir=path.parent) as temp:
            stage = Path(temp) / path.name
            download(asset, stage)
            stage.rename(path)


def prepare():
    python = BOOTSTRAP / 'venv/Scripts/python.exe'
    requirements = ROOT / 'requirements.txt'
    marker = BOOTSTRAP / 'requirements.lock'
    current = requirements.read_bytes()
    unfinished = not python.is_file() or not marker.is_file()
    if unfinished:
        subprocess.run([sys.executable, '-m', 'venv', str(BOOTSTRAP / 'venv')], check=True)
    if unfinished or marker.read_bytes() != current:
        print('Устанавливаем библиотеки Python…', flush=True)
        subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install',
                        '--only-binary=:all:', '-r', str(requirements)], check=True)
        subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
        marker.write_bytes(current)

    blender = os.environ.get('BLENDER')
    if not blender:
        if not (BOOTSTRAP / 'blender-5.2.3/blender.exe').is_file():
            print('Загружаем Blender 5.2.3 (406 МБ)…', flush=True)
        blender = install_zip(BLENDER, BOOTSTRAP / 'blender-5.2.3', 'blender.exe')
    probe = os.environ.get('FFPROBE')
    if not probe:
        if not (BOOTSTRAP / 'ffmpeg-8.1.2/bin/ffprobe.exe').is_file():
            print('Загружаем инструменты для MP4 (110 МБ)…', flush=True)
        probe = install_zip(FFMPEG, BOOTSTRAP / 'ffmpeg-8.1.2', 'bin/ffprobe.exe')
    crt = BOOTSTRAP / 'vclibs-14.0.33321'
    install_zip(VC_RUNTIME, crt, 'msvcp140.dll')

    runtime = RESOURCES / 'runtime/bin'
    model = RESOURCES / 'model/qwen.gguf'
    if not (runtime / 'llama-server.exe').is_file() or not model.is_file():
        print('Загружаем локальный планировщик и модель (1,14 ГБ)…', flush=True)
        install_zip(PLANNER, runtime, 'llama-server.exe')
        install_model(MODEL, model)
    return python, dict(os.environ, BLENDER=str(blender), FFPROBE=str(probe), A8_CRT=str(crt),
                        PATH=str(crt) + os.pathsep + os.environ.get('PATH', ''))


def prepare_dialogue(python, progress, log):
    from importlib.metadata import PackageNotFoundError, version

    from paths import DOTA_ROOT, S2V, VPK
    from skit.character_voice import MODEL as voice_model, PROJECTOR, VOICE_ROOT

    if not Path(VPK).is_file():
        raise ValueError('Для ролика с героями установите Dota 2 через Steam.')
    if not (Path(DOTA_ROOT) / 'game/dota_russian/pak01_dir.vpk').is_file():
        raise ValueError('Выберите русский язык Dota 2 в Steam и дождитесь загрузки озвучки.')

    s2v = Path(S2V)
    if not s2v.is_file():
        progress('Загружаем инструмент для извлечения героев из Dota…')
        s2v = install_zip(SOURCE2VIEWER, RESOURCES / 'source2viewer', 'Source2Viewer-CLI.exe')
    writer = RESOURCES / 'model/dialogue.gguf'
    if not writer.is_file():
        progress('Загружаем модель для написания реплик (2,5 ГБ)…')
        install_model(WRITER, writer)
    if not all((VOICE_ROOT / name).is_file() for name in (voice_model, PROJECTOR, 'bin/llama-tts.exe')):
        progress('Загружаем синтез голосов героев (1,5 ГБ)…')
        install_zip(VOICE_RUNTIME, VOICE_ROOT / 'bin', 'llama-tts.exe')
        install_model((VOICE_URL + voice_model, '8d18c94acb2addd042f97da63c98be144eafa76d0d9495177eab65130cf85129'),
                      VOICE_ROOT / voice_model)
        install_model((VOICE_URL + PROJECTOR, '6fd65188839bcd6ecc91b277ad471e22a0edfada4699a0fe82f1165c18cfcce2'),
                      VOICE_ROOT / PROJECTOR)
    whisper = RESOURCES / 'voice/whisper-small'
    try:
        installed = version('faster-whisper')
    except PackageNotFoundError:
        installed = None
    if installed != '1.2.1':
        progress('Устанавливаем проверку русских реплик…')
        subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install',
                        '--only-binary=:all:', 'faster-whisper==1.2.1'],
                       stdout=log, stderr=subprocess.STDOUT, check=True, creationflags=HIDDEN)
    if not all((whisper / name).is_file() for name in WHISPER_FILES):
        progress('Загружаем модель проверки реплик (0,5 ГБ)…')
        for name, sha256 in WHISPER_FILES.items():
            install_model((WHISPER_URL + name, sha256), whisper / name)
    return dict(S2V=str(s2v), A8_WHISPER_MODEL=str(whisper))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    try:
        with file_lock(BOOTSTRAP / 'setup.lock'):
            python, env = prepare()
        if not args.prepare_only:
            with (WORKSPACE / 'launcher.log').open('ab') as log:
                subprocess.Popen([str(python.with_name('pythonw.exe')), '-X', 'utf8',
                                  str(ROOT / 'tools/studio.py')], cwd=ROOT, env=env, stdout=log,
                                 stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Подготовка не завершена. {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
