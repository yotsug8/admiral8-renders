"""Generate a Russian line locally from its hero's localized game audio."""

from functools import cache
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from .game_vo import extract
from resource_paths import RESOURCES


ROOT = Path(__file__).resolve().parents[2]
VOICE_ROOT = RESOURCES / "voice/character"
REFERENCES = {"pudge": "pud_rare_01.mp3", "invoker": "invo_rare_01.mp3"}
MODEL = "Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf"
PROJECTOR = "mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf"


def voice_reference(hero):
    name = REFERENCES.get(hero)
    if not name:
        raise ValueError(f"Для {hero} пока не подготовлен оригинальный русский голос.")
    path = next((Path(path) for path in extract(hero) if Path(path).name == name), None)
    if path is None:
        raise ValueError(f"В русских игровых файлах отсутствует реплика {name}.")
    return path


def generate(text, reference, wav):
    exe = VOICE_ROOT / "bin/llama-tts.exe"
    model, projector = VOICE_ROOT / MODEL, VOICE_ROOT / PROJECTOR
    if not all(p.is_file() for p in (exe, model, projector)):
        raise ValueError("Локальный синтез голосов героев не установлен. См. инструкцию настройки.")
    with TemporaryDirectory(prefix=".voice-", dir=wav.parent) as directory:
        prompt = Path(directory) / "line.txt"
        prompt.write_text(text, encoding="utf-8")
        subprocess.run([str(exe), "-m", str(model), "-mm", str(projector), "-f", str(prompt),
                        "--tts-lang", "ru", "--tts-speaker-file", str(reference),
                        "-ngl", "0", "-c", "2048", "-t", "6", "-s", "19",
                        "-n", str(max(130, len(text) * 2)), "-o", str(wav)], timeout=160, check=True)


@cache
def speech_recognizer():
    try:
        from faster_whisper import WhisperModel
        model = os.environ.get("A8_WHISPER_MODEL", "small")
        return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
    except (ImportError, OSError, ValueError) as error:
        raise ValueError("Для проверки реплик установите локальный faster-whisper small по инструкции.") from error


def align(text, wav):
    from difflib import SequenceMatcher

    segments, _ = speech_recognizer().transcribe(str(wav), language="ru", beam_size=3, word_timestamps=True)
    words = [(word.word.strip(), word.start, word.end) for seg in segments for word in seg.words]
    heard = " ".join(word for word, _, _ in words)
    def normalize(value):
        return re.sub("[^а-я0-9]", "", value.casefold().replace("ё", "е"))
    expected = normalize(text)
    if not expected or SequenceMatcher(None, expected, normalize(heard)).ratio() < .85:
        raise ValueError(f"Синтез и текст расходятся. Распознано «{heard}».")
    return words
