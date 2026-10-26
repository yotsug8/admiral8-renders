"""
Ролик «несколько фактов о Доте»: озвучка, субтитры по словам, графика на HTML/CSS.

Кадры рисует браузер (Playwright + Chromium) по шаблону video.html.
Python готовит данные: озвучку (Fish Audio, запасной — edge-tts), героев и иконки, звук.

Запуск:
    python video.py episodes/002.json out/002.mp4    # рендер выпуска
    python video.py --takes episodes/002.json out           # дубли озвучки на выбор
Локальная проверка вёрстки без сети: FV_SILENT=1 FV_QA_ONLY=1 FV_QA_DIR=папка
Черновик за минуту (половина размера, 15 кадров/с): FV_DRAFT=1
"""
import asyncio
import json
import math
import re
import time
import os
import shutil
import subprocess
import sys
import urllib.request
import wave
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

VOICE = os.environ.get("FV_VOICE", "ru-RU-DmitryNeural")
PITCH = os.environ.get("FV_PITCH", "-10Hz")
RATE = os.environ.get("FV_RATE", "+12%")
# Fish Audio: живой голос (если задан ключ). Голос «Мем ии озвучка» из библиотеки fish.audio
FISH_KEY = os.environ.get("FISH_API_KEY", "")
FISH_VOICE = os.environ.get("FISH_VOICE", "0036c4fdc4c7442e9a47af59287b7737")
FISH_MODEL = os.environ.get("FISH_MODEL", "s2.1-pro-free")
FISH_SPEED = float(os.environ.get("FISH_SPEED", "1.15"))
FISH_TEMP = float(os.environ.get("FISH_TEMP", "0.85"))     # разброс интонаций (по умолчанию у Fish 0.7)
WATERMARK = "@admiral8dota"
SR, FPS = 44100, 30
PAD = 0.7                     # пауза после факта, сек
HERE = Path(__file__).resolve().parent
WORK = HERE / "_fv_work"


# ---------- вспомогательное ----------

CDN = "https://cdn.cloudflare.steamstatic.com"
CONSTS_URL = "https://raw.githubusercontent.com/odota/dotaconstants/master/build/"


def ffmpeg_exe():
    """ffmpeg из системы, иначе — встроенный из пакета imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def load_consts(name, consts_dir):
    """Справочник dotaconstants: из локальной папки или с GitHub (с кэшем)."""
    local = os.path.join(consts_dir, name)
    if os.path.exists(local):
        return json.load(open(local, encoding="utf-8"))
    os.makedirs(HERE / "cache", exist_ok=True)
    cached = os.path.join(HERE, "cache", name)
    if not os.path.exists(cached):
        with urllib.request.urlopen(CONSTS_URL + name, timeout=30) as r:
            data = r.read()
        with open(cached, "wb") as f:
            f.write(data)
    return json.load(open(cached, encoding="utf-8"))


def fetch_image(path, cache_dir=None):
    """Картинка с CDN Steam (с кэшем и повтором). None, если не вышло."""
    cache_dir = cache_dir or HERE / "cache"
    os.makedirs(cache_dir, exist_ok=True)
    local = os.path.join(cache_dir, path.split("?")[0].strip("/").replace("/", "_"))
    if os.path.exists(local):
        return Image.open(local).convert("RGBA")
    for _ in range(2):
        try:
            req = urllib.request.Request(CDN + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
            with open(local, "wb") as f:
                f.write(data)
            return Image.open(BytesIO(data)).convert("RGBA")
        except Exception:
            continue
    print("  ⚠ нет картинки на CDN:", path.split("?")[0])
    return None


def placeholder(w, h):
    """Запасная серая картинка, если CDN недоступен."""
    return Image.new("RGBA", (w, h), (70, 84, 104, 255))


# ---------- озвучка ----------

def tts(text, path_mp3, voice=None, pitch=None, rate=None):
    """Синтез речи + тайминги слов [(слово, старт, конец)] в секундах."""
    if os.environ.get("FV_FAKE_TTS"):           # локальная проверка вёрстки без интернета
        ws = text.replace(",", "").replace(".", "").replace("?", "").split()
        dur = 0.34 * len(ws)
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"anullsrc=r={SR}:cl=mono", "-t", f"{dur:.2f}", str(path_mp3)], check=True)
        return [(w, k * 0.34, k * 0.34 + 0.3) for k, w in enumerate(ws)]
    import edge_tts

    async def run():
        words = []
        com = edge_tts.Communicate(text, voice or VOICE, rate=rate or RATE, pitch=pitch or PITCH,
                                   boundary="WordBoundary")
        with open(path_mp3, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    s = ch["offset"] / 1e7
                    words.append((ch["text"], s, s + ch["duration"] / 1e7))
        return words

    last = None
    for attempt in range(3):
        try:
            return asyncio.run(run())
        except Exception as e:
            last = e
            print(f"  tts повтор {attempt + 1}: {e}")
    raise RuntimeError(f"озвучка не получилась: {last}")


def say_text(text):
    """Текст для голоса: {7.33|семь тридцать три} → «семь тридцать три»."""
    import re
    return re.sub(r"\{([^{}|]*)\|([^{}]*)\}", r"\2", text)


def show_text(text):
    """Текст для субтитров: {7.33|семь тридцать три} → «7.33»."""
    import re
    return re.sub(r"\{([^{}|]*)\|([^{}]*)\}", r"\1", text)


def tts_fish(text, path_mp3, voice=None, align=True):
    """Озвучка через Fish Audio + тайминги слов распознаванием (faster-whisper).
    «||» в тексте — граница смысловых кусков: каждый озвучивается отдельно и склеивается с паузой 0,3 с,
    чтобы интонация обнулялась между изменениями и речь не была сплошной."""
    import urllib.request
    text = say_text(text)
    if "||" in text:
        tags = " ".join(re.findall(r"\[[^\]]*\]", text.split("||")[0])[:1])      # первая эмоция — на все куски без своей
        chunks = [c.strip() for c in text.split("||") if c.strip()]
        pcm = []
        for k, c in enumerate(chunks):
            tmp = Path(str(path_mp3) + f".part{k}.mp3")
            tts_fish(c if c.startswith("[") or not tags else f"{tags} {c}", tmp, voice, align=False)
            pcm.append(mp3_to_pcm(tmp)); tmp.unlink()
            if k + 1 < len(chunks):
                pcm.append(np.zeros(int(0.3 * SR), np.float32))
        wav = Path(str(path_mp3) + ".wav")
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.clip(np.concatenate(pcm), -1, 1) * 32767).astype(np.int16).tobytes())
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k", str(path_mp3)], check=True)
        wav.unlink()
        return align_words(path_mp3) if align else None
    body = json.dumps({"text": text, "reference_id": voice or FISH_VOICE, "format": "mp3",
                       "mp3_bitrate": 192, "prosody": {"speed": FISH_SPEED}, "language": "ru",
                       "normalize": True, "temperature": FISH_TEMP}).encode()
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request("https://api.fish.audio/v1/tts", data=body, method="POST", headers={
                "Authorization": f"Bearer {FISH_KEY}", "Content-Type": "application/json", "model": FISH_MODEL})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < 1000:
                raise RuntimeError(f"слишком короткий ответ: {data[:200]!r}")
            Path(path_mp3).write_bytes(data)
            break
        except Exception as e:
            body_err = ""
            if hasattr(e, "read"):
                try:
                    body_err = e.read()[:300].decode("utf-8", "replace")
                except Exception:
                    pass
            last = f"{e} {body_err}".strip()
            print(f"  fish повтор {attempt + 1}: {last}")
            if getattr(e, "code", 0) in (401, 402, 403):   # ключ/оплата — повторять бессмысленно
                break
    else:
        raise RuntimeError(f"Fish Audio не ответил: {last}")
    if not Path(path_mp3).exists() or Path(path_mp3).stat().st_size < 1000:
        raise RuntimeError(f"Fish Audio не ответил: {last}")
    return align_words(path_mp3) if align else None


_WHISPER = None


def align_words(path):
    """Слова с таймингами из готовой озвучки (субтитры совпадают с тем, что звучит).
    Результат кэшируется по содержимому файла: перерендер не распознаёт дубль заново."""
    import hashlib
    key = hashlib.md5(Path(path).read_bytes()).hexdigest()
    cached = HERE / "cache" / "align" / f"{key}.json"
    if cached.exists():
        d = json.loads(cached.read_text(encoding="utf-8"))
        _PROBS[:] = d["probs"]
        return [tuple(w) for w in d["words"]]
    words = _align_words(path)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"words": words, "probs": _PROBS}, ensure_ascii=False), encoding="utf-8")
    return words


def _align_words(path):
    global _WHISPER
    from faster_whisper import WhisperModel
    if _WHISPER is None:
        _WHISPER = WhisperModel("small", device="cpu", compute_type="int8")
    # Декодируем сами через ffmpeg: встроенный декодер faster-whisper (PyAV) ломается на новых версиях
    raw = subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.float32)
    segs, _ = _WHISPER.transcribe(audio, language="ru", word_timestamps=True, vad_filter=False)
    _PROBS.clear()
    words = []
    for sg in segs:
        for w in sg.words or []:
            t = w.word.strip()
            if t:
                words.append((t, float(w.start), float(w.end)))
                _PROBS.append(float(w.probability))
    return words


_PROBS = []      # уверенность распознавания по словам последнего вызова align_words


def _norm(w):
    return "".join(ch for ch in w.lower().replace("ё", "е") if ch.isalnum())


def align_to_script(text, asr):
    """Слова для субтитров берём из исходного текста, а тайминги — из распознавания.
    Сопоставляем последовательности (difflib); несовпавшим словам времена интерполируем."""
    import difflib
    import re
    text = re.sub(r"\[[^\]]*\]", " ", show_text(text).replace("||", " "))   # теги эмоций/пауз не показываем; {показ|озвучка} → показ
    script = [w.strip(",.;:") for w in text.split() if _norm(w)]
    if not asr:
        return [(w, i * 0.35, i * 0.35 + 0.3) for i, w in enumerate(script)]
    a = [_norm(w) for w in script]
    b = [_norm(w[0]) for w in asr]
    times = [None] * len(script)
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        tag, i1, i2, j1, j2 = blk
        if tag == "equal":
            for k in range(i2 - i1):
                times[i1 + k] = (asr[j1 + k][1], asr[j1 + k][2])
        elif tag == "replace" and i2 > i1 and j2 > j1:
            # Блок разной длины («Бали Мейджор» ↔ «Балли -мейджер»): делим его время поровну
            t0, t1 = asr[j1][1], asr[j2 - 1][2]
            n = i2 - i1
            for k in range(n):
                times[i1 + k] = (t0 + (t1 - t0) * k / n, t0 + (t1 - t0) * (k + 1) / n)
    # Дыры (слова без пары) — между соседями
    for i in range(len(times)):
        if times[i] is None:
            prev = next((times[j][1] for j in range(i - 1, -1, -1) if times[j]), 0.0)
            nxt = next((times[j][0] for j in range(i + 1, len(times)) if times[j]), prev + 0.4)
            times[i] = (prev, max(prev + 0.05, min(nxt, prev + 0.4)))
    return [(w, t[0], t[1]) for w, t in zip(script, times)]


def silent(text, path_mp3):
    """Без озвучки (FV_SILENT): слова идут в темпе живой речи (~2,6 слова/с), звук — тишина той же длины."""
    words = align_to_script(text, None)
    k = 0.38 / 0.35
    words = [(w, a * k, b * k) for w, a, b in words]
    dur = (words[-1][2] if words else 1) + 0.3
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", f"{dur:.2f}", "-c:a", "libmp3lame", "-b:a", "64k", str(path_mp3)], check=True)
    return words


def speak(text, path_mp3, voice_file=None, voice=None):
    """Озвучка фрагмента: выбранный дубль, иначе Fish Audio (если есть ключ), иначе edge-tts."""
    if os.environ.get("FV_SILENT"):
        return silent(text.replace("\u0301", ""), path_mp3)
    if voice_file and (HERE / voice_file).exists() and not os.environ.get("FV_FAKE_TTS"):
        shutil.copy(HERE / voice_file, path_mp3)
        return align_to_script(text.replace("\u0301", ""), align_words(path_mp3))
    if FISH_KEY and not os.environ.get("FV_FAKE_TTS"):
        try:
            # озвучка кэшируется по тексту и настройкам голоса: перерендер не платит за неё заново
            import hashlib
            key = hashlib.md5(f"{text}|{voice or FISH_VOICE}|{FISH_MODEL}|{FISH_SPEED}|{FISH_TEMP}".encode()).hexdigest()
            cached = HERE / "cache" / "tts" / f"{key}.mp3"
            if not cached.exists():
                cached.parent.mkdir(parents=True, exist_ok=True)
                tts_fish(text, cached, voice, align=False)
            shutil.copy(cached, path_mp3)
            return align_to_script(text.replace("\u0301", ""), align_words(path_mp3))
        except Exception as e:                 # ролик всё равно соберётся, но с запасным голосом
            print(f"  ВНИМАНИЕ: Fish Audio не сработал ({e}), озвучка запасным голосом edge-tts")
    elif not FISH_KEY:
        print("  ВНИМАНИЕ: нет FISH_API_KEY, озвучка запасным голосом edge-tts")
    import re
    return tts(re.sub(r"\s*\[[^\]]*\]\s*", " ", say_text(text).replace("||", " ")).replace("\u0301", "").strip(), path_mp3)


def mp3_to_pcm(path):
    raw = subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-i", str(path), "-f", "s16le",
                          "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


# ---------- картинки ----------

def hero_cutout(key, heroes):
    """Герой в полный рост без фона (PNG с прозрачностью) → путь к файлу."""
    out = WORK / f"hero_{key}.png"
    if out.exists():
        return out
    img = fetch_image(f"/apps/dota2/videos/dota_react/heroes/renders/{key}.png")
    if img is None:
        h = heroes[key]
        img = fetch_image(h["img"]) or placeholder(256, 144)
    if img.getextrema()[3][0] >= 250:              # фон непрозрачный — вырезаем нейросетью
        try:
            from rembg import remove
            img = remove(img).convert("RGBA")
        except Exception as e:
            print("  ⚠ не удалось вырезать фон:", key, e)
    bbox = img.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    img.save(out)
    return out


def item_icon(key, items):
    out = WORK / f"item_{key}.png"
    if not out.exists():
        img = fetch_image(items[key]["img"]) or placeholder(88, 64)
        img.save(out)
    return out


# ---------- подготовка ----------

def cue_time(words, cue):
    """Время слова-метки в озвучке: «рошана» — начало слова, «минут:end» — конец, «квест#2» — второе вхождение."""
    end = cue.endswith(":end")
    cue = cue[:-4] if end else cue
    nth = 1
    if "#" in cue:
        cue, nth = cue.split("#")[0], int(cue.split("#")[1])
    key = _norm(cue)
    for w, a, b in words:
        if _norm(w).startswith(key):
            nth -= 1
            if nth == 0:
                return b if end else a
    return None

def image_ref(ref, heroes, items):
    """Картинка по ссылке: "hero:ключ" — герой без фона, "item:ключ" — иконка предмета,
    "ability:ключ" — иконка способности из assets/abilities, "file:путь" — из репозитория."""
    kind, key = ref.split(":", 1)
    path = {"hero": lambda: hero_cutout(key, heroes), "item": lambda: item_icon(key, items),
            "ability": lambda: HERE / "assets" / "abilities" / f"{key}.png",
            "file": lambda: HERE / key,
            "game": lambda: Path(os.environ.get("FV_GAME_DIR", HERE / "_game")) / "img" / key}[kind]()   # картинки из файлов игры
    if not Path(path).exists():                    # пустое место в кадре вместо картинки — заметить до рендера
        print(f"    ⚠ нет картинки: {ref} ({path})")
    return path.as_uri()


def anim_frames(key):
    """Кадры анимированного рендера героя (assets/anim/<ключ>/*.webp, родная частота из meta.json, без потерь) → {fps, frames}.
    Свечение и тень запекаются в кадры один раз: CSS-фильтр на каждом кадре был самым дорогим местом рендера."""
    from PIL import ImageFilter
    fs = sorted((HERE / "assets" / "anim" / key).glob("*.webp"))
    if not fs:
        print("  ⚠ нет анимации:", key)
    out_dir = WORK / f"anim_{key}"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for f in fs:
        out = out_dir / (f.stem + ".png")
        if not out.exists():
            im = Image.open(f).convert("RGBA")
            pad = 70
            W, H = im.width + 2 * pad, im.height + 2 * pad
            a = Image.new("L", (W, H), 0)
            a.paste(im.getchannel("A"), (pad, pad))
            canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            shadow = Image.new("RGBA", (W, H), (1, 8, 9, 0))
            shadow.putalpha(a.point(lambda v: v * 0.7))
            canvas.alpha_composite(shadow, (22, 30))                       # жёсткая тень со сдвигом
            glow = Image.new("RGBA", (W, H), (62, 240, 192, 0))
            glow.putalpha(a.filter(ImageFilter.GaussianBlur(40)).point(lambda v: min(255, v * 1.0)))
            canvas.alpha_composite(glow)                                    # мятное свечение по контуру
            canvas.alpha_composite(im, (pad, pad))
            # Хранить исходник полного размера, а в браузер отдавать не больше, чем нужно на экране (до 900 px по высоте):
            # масштабирование 1400 px на каждом кадре съедало время, а качество на экране то же
            if canvas.height > 900:
                canvas = canvas.resize((round(canvas.width * 900 / canvas.height), 900), Image.LANCZOS)
            canvas.save(out, compress_level=1)
        res.append(out.as_uri())
    meta = HERE / "assets" / "anim" / key / "meta.json"
    fps = json.load(open(meta))["fps"] if meta.exists() else 15
    return dict(fps=fps, frames=res)


# Справочник сцен (должен совпадать с scene.js / scene.css) — для проверки описания
SC_TYPES = {"text", "chip", "stamp", "number", "img", "hero", "card", "anim", "shape", "row", "col", "panel", "video", "lottie", "model", "stage"}
SC_IN = {"fade", "rise", "drop", "pop", "slam", "left", "right", "wipe", "iris", "stamp", "draw", "lines", "chars", "type", "none"}
SC_FX = SC_IN | {"pulse", "shake", "jump", "gray", "color", "dim", "show", "hide", "out", "move", "mark", "stamps", "count", "swap"}
SC_TEX = {"noise", "grid", "scan", "halftone", "paper", "parchment", "wood", "oldwood", "doors", "planks", "metal", "plate", "rust",
          "stone", "blocks", "rock", "cliff", "cobble", "leather", "burlap", "concrete", "plaster", "forest"}
SC_FRAMES = {"plate", "corners", "rivets", "tape", "ticket", "cap"}
SC_SOUNDS = {"stamp", "bubble", "tick", "pop", "whoosh"}


def check_scene(sc, label):
    """Опечатки в сцене молча ломают эффект — проверяем заранее и пишем, что не так."""
    warn, ids, cues = [], set(), set((sc.get("cues") or {}).keys()) | set((sc.get("at") or {}).keys())
    def at_ok(at, where):
        if isinstance(at, str):
            key = re.split(r"[+\-]", at)[0]
            if key not in cues:
                warn.append(f"{where}: метка «{key}» не объявлена в cues")
    def walk(items, prefix=None):
        for k, it in enumerate(items or []):
            iid = it.get("id") or (f"{prefix}.{k}" if prefix else f"i{k}")
            ids.add(iid)
            t = it.get("type", "text")
            if t not in SC_TYPES:
                warn.append(f"{iid}: неизвестный type «{t}»")
            if it.get("tex") and it["tex"] not in SC_TEX:
                warn.append(f"{iid}: неизвестная текстура «{it['tex']}»")
            for f in ([it["frame"]] if isinstance(it.get("frame"), str) else it.get("frame") or []):
                if f not in SC_FRAMES:
                    warn.append(f"{iid}: неизвестная рамка «{f}»")
            i = it.get("in")
            if i:
                fx = i if isinstance(i, str) else i.get("fx")
                if fx not in SC_IN:
                    warn.append(f"{iid}: неизвестное появление «{fx}»")
                at_ok(it.get("at") if isinstance(i, str) else i.get("at", it.get("at")), iid)
            if t in ("row", "col", "panel"):
                walk([dict(it.get("child") or {}, **c) for c in it.get("items", [])], iid)
    walk(sc.get("items"))
    for e in sc.get("fx", []):
        if e.get("fx") not in SC_FX:
            warn.append(f"fx: неизвестный эффект «{e.get('fx')}»")
        tg = (e.get("target") or "@all").split(" ")[0]
        if tg != "@all" and tg.rstrip("*").rstrip(".") not in ids:
            warn.append(f"fx «{e.get('fx')}»: нет элемента «{tg}»")
        at_ok(e.get("at"), f"fx «{e.get('fx')}»")
    for e in sc.get("sounds", []):
        if e.get("kind", "pop") not in SC_SOUNDS:
            warn.append(f"звук: неизвестный «{e.get('kind')}»")
        at_ok(e.get("at"), "звук")
    for k, v in (sc.get("at") or {}).items():
        if v is None:
            warn.append(f"метка «{k}»: слово не найдено в озвучке")
    for w in warn:
        print(f"    ⚠ {label}: {w}")
    return warn


def video_frames(node):
    """Клип из файла → кадры JPG под размер элемента (обрезка по центру), по желанию — звук клипа.
    Поля: src "file:…", from (с), dur (с), w, h, audio (громкость звука клипа, 0 — без звука)."""
    import hashlib
    path = HERE / node["src"].split(":", 1)[1]
    w, h = int(node.get("w", 880)), int(node.get("h", 495))
    a, d = float(node.get("from", 0)), float(node.get("dur", 6))
    st = path.stat()   # размер и время файла в ключе: новый клип с тем же именем не возьмёт старые кадры из кэша
    key = hashlib.md5(f"{path}|{st.st_size}|{st.st_mtime_ns}|{w}|{h}|{a}|{d}|bars".encode()).hexdigest()[:10]
    out = WORK / f"vid_{key}"
    if not out.exists():
        out.mkdir(parents=True)
        # чёрные поля вокруг картинки (мемы из TikTok, кино в вертикали) — срезать: поле ищет cropdetect
        det = subprocess.run([ffmpeg_exe(), "-hide_banner", "-ss", str(a), "-t", str(d), "-i", str(path),
                              "-vf", "cropdetect=24:2:0", "-f", "null", "-"], capture_output=True, text=True, errors="replace").stderr
        crops = re.findall(r"crop=(\d+:\d+:\d+:\d+)", det)
        bars = f"crop={max(set(crops), key=crops.count)}," if crops else ""
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(a), "-t", str(d), "-i", str(path),
                        "-vf", f"{bars}fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
                        "-q:v", "3", str(out / "%04d.jpg")], check=True)
    res = dict(fps=FPS, frames=[f.as_uri() for f in sorted(out.glob("*.jpg"))])
    if float(node.get("audio", 0)) > 0:
        wav = out / "a.wav"
        if not wav.exists():
            subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(a), "-t", str(d), "-i", str(path),
                            "-vn", "-ac", "1", "-ar", str(SR), str(wav)], check=True)
        res["wav"] = str(wav)
    return res


def meme(node):
    """Мем по имени из каталога _game/memes/catalog.json (tools/memes.py) → элемент video: кусок вокруг лучшего момента
    (пик движения и громкости), со звуком. Поля: name, dur (1,6 с), lead (сколько до пика, 0,6 с), from — свой старт."""
    cat_path = HERE / "_game" / "memes" / "catalog.json"
    if not cat_path.exists():
        raise SystemExit("нет каталога мемов: python tools/memes.py")
    cat = json.load(open(cat_path, encoding="utf-8"))
    m = cat.get(node["name"])
    if m is None:
        raise SystemExit(f"мем «{node['name']}» не найден; есть: {', '.join(cat)}")
    dur = float(node.get("dur", 1.6))
    start = float(node["from"]) if "from" in node else max(0.0, min(m["peak"] - float(node.get("lead", 0.6)), m["dur"] - dur))
    out = {k: v for k, v in node.items() if k not in ("name", "lead")}
    return dict(out, type="video", src=f"file:_game/memes/{m['file']}", **{"from": round(start, 2)}, dur=dur,
                audio=float(node.get("audio", 1 if m["audio"] else 0)))


def resolve_scene(node, heroes, items):
    """Обход описания сцены: "src": "hero:…/item:…/ability:…/file:…" → file:// URI, "anim": "ключ" → кадры анимации,
    видео → кадры, lottie → JSON анимации внутрь описания."""
    if isinstance(node, list):
        return [resolve_scene(x, heroes, items) for x in node]
    if not isinstance(node, dict):
        return node
    if node.get("type") == "meme":
        node = meme(node)
    if node.get("type") == "video" and isinstance(node.get("src"), str):
        node = dict(node, clip=video_frames(node))
        node.pop("src")
    if node.get("type") == "stage" and node.get("actors"):
        import base64
        gd = Path(os.environ.get("FV_GAME_DIR", HERE / "_game")) / "models"
        heroes_glb = {}
        for h in {a["hero"] for a in node["actors"]}:
            base = gd / h / f"{h}.glb"
            if not base.exists():
                raise SystemExit(f"нет 3D-модели {base}: сначала tools/dota_export.py model …")
            parts = sorted(p for p in (gd / h).glob("*.glb") if p != base and "ward" not in p.stem)
            heroes_glb[h] = [base64.b64encode(f.read_bytes()).decode() for f in [base, *parts]]
        node = dict(node, heroes=heroes_glb)
    if node.get("type") == "model" and node.get("hero"):
        # 3D-герой из файлов игры: _game/models/<герой>/ (tools/dota_export.py); части — список или "all"
        import base64
        d = Path(os.environ.get("FV_GAME_DIR", HERE / "_game")) / "models" / node["hero"]
        base = d / f"{node['hero']}.glb"
        if not base.exists():
            raise SystemExit(f"нет 3D-модели {base}: сначала tools/dota_export.py model …")
        parts = sorted(p for p in d.glob("*.glb") if p != base and "ward" not in p.stem) if node.get("parts", "all") == "all" \
            else [d / f"{p}.glb" for p in node["parts"]]
        node = dict(node, glb=[base64.b64encode(f.read_bytes()).decode() for f in [base, *parts]])
    if node.get("type") == "lottie" and isinstance(node.get("src"), str):
        node = dict(node, data=json.load(open(HERE / node["src"].split(":", 1)[1], encoding="utf-8")))
        node.pop("src")
    out = {}
    for k, v in node.items():
        if k == "src" and isinstance(v, str) and v.split(":", 1)[0] in ("hero", "item", "ability", "file", "game"):
            out[k] = image_ref(v, heroes, items)
        elif k == "anim" and isinstance(v, str) and node.get("type") != "model":   # у 3D-модели anim — имя анимации
            out[k] = anim_frames(v)
        else:
            out[k] = resolve_scene(v, heroes, items)
    return out


def prepare(ep, heroes, items):
    segs, t = [], 0.0
    parts = ep["parts"] + ([dict(ep["outro"], outro=True)] if ep.get("outro") else [])   # финал по желанию
    if ep.get("hook"):                       # короткий хук перед фактами
        parts = [dict(ep["hook"], hook=True)] + parts
    for i, f in enumerate(parts):
        text = f["voice"]
        mp3 = WORK / f"v{i}.mp3"
        words = speak(text, mp3, f.get("voice_file"), ep.get("voice_id"))   # голос — свой у каждого выпуска
        pcm = mp3_to_pcm(mp3)
        pad = float(ep.get("pad", PAD))      # пауза после фрагмента: можно задать в выпуске, чтобы уложиться в 45 с
        dur = len(pcm) / SR + pad + (0.6 if i == len(parts) - 1 else 0) + float(f.get("hold", 0))   # в конце чуть дольше пауза; hold — задержать кадр
        seg = dict(start=t, dur=dur, words=[[w, round(a, 3), round(b, 3)] for w, a, b in words], _pcm=pcm)
        if f.get("scene"):
            # Универсальная сцена (SCENES.md): картинки по ссылкам, анимации героев, метки из озвучки
            sc = resolve_scene(f["scene"], heroes, items)
            if sc.get("cues"):
                sc["at"] = {k: cue_time(seg["words"], c) for k, c in sc.pop("cues").items()}
                print("    метки сцены:", {k: (round(t, 2) if t is not None else "НЕ НАЙДЕНО") for k, t in sc["at"].items()})
            check_scene(sc, "hook" if f.get("hook") else "outro" if f.get("outro") else f"факт {i}")
            seg.update(scene=sc, hook=bool(f.get("hook")), outro=bool(f.get("outro")), headline="", sfx=f.get("sfx", []),
                       at=[], watermark=WATERMARK)
        elif f.get("outro"):
            thumbs = []
            for fact in ep["parts"]:
                v = fact.get("visual", {})
                # Для сетки и таймера — иконка предмета, иначе герой; thumb в выпуске — явная картинка
                if v.get("thumb"):
                    thumbs.append(image_ref(v["thumb"], heroes, items))
                elif v.get("team_logos"):          # матч команд — логотип победителя
                    thumbs.append((HERE / v["team_logos"][v.get("winner", 0)]).as_uri())
                elif v.get("icons") and (fact["layout"] in ("grid", "timer") or not v.get("heroes")):
                    thumbs.append(item_icon(v["icons"], items).as_uri())
                elif v.get("heroes"):
                    thumbs.append(hero_cutout(v["heroes"][0], heroes).as_uri())
                else:
                    thumbs.append(None)
            seg.update(outro=True, question=f["question"], cta=f["cta"], thumbs=thumbs, stats=f.get("stats", []),
                       anim=anim_frames(f["anim"]) if f.get("anim") else None,
                       floats=[image_ref(r, heroes, items) for r in f.get("floats", [])],   # иконки над водой в финале «big»
                       style=f.get("style", "cards"), watermark=WATERMARK)   # cards — карточки фактов, follow — кнопка подписки
        elif f.get("hook"):
            imgs = [image_ref(r, heroes, items) for r in f.get("images", [])]     # картинки хука
            at = [cue_time(seg["words"], c) for c in f.get("cues", [])]
            print("    метки хука:", [round(x, 2) if x is not None else "НЕ НАЙДЕНО" for x in at])
            seg.update(hook=True, headline=f["headline"], images=imgs, at=at, labels=f.get("labels", []), sfx=f.get("sfx", []),
                       style=f.get("style", "stickers"),      # stickers — наклейки, list — список вопросов, hero — анимированный герой и значки
                       anim=anim_frames(f["anim"]) if f.get("anim") else None)
        else:
            v = dict(f.get("visual", {}))
            if v.get("heroes"):
                v["heroes"] = [hero_cutout(k, heroes).as_uri() for k in v["heroes"]]
            if v.get("icons"):
                v["icons"] = dict(src=item_icon(v["icons"], items).as_uri(),
                                  count=int(v["count"]))
            if v.get("items"):                       # список иконок предметов (xray)
                v["items"] = [item_icon(k, items).as_uri() for k in v["items"]]
            if v.get("icon"):                        # одна иконка предмета (range, notes)
                v["icon"] = item_icon(v["icon"], items).as_uri()
            if v.get("logo"):
                v["logo"] = (HERE / v["logo"]).as_uri()
            if v.get("anim"):                        # анимированный герой
                v["anim"] = anim_frames(v["anim"])
            if v.get("refs"):                        # произвольные картинки по ссылкам hero:/item:/ability:/file:
                v["refs"] = {k: image_ref(r, heroes, items) for k, r in v["refs"].items()}
            if v.get("player"):                      # карточка игрока: логотипы команды и турнира
                v["player"] = dict(v["player"], logos=[(HERE / x).as_uri() for x in v["player"].get("logos", [])])
            for key in ("team_logos", "ability_icons"):     # картинки, лежащие в репозитории
                if v.get(key):
                    v[key] = [(HERE / x).as_uri() if x else None for x in v[key]]
            if v.get("event_logo"):
                v["event_logo"] = (HERE / v["event_logo"]).as_uri()
            for key in ("number", "label", "caption"):
                if v.get(key):
                    v[key] = str(v[key])
            # Метки: элемент появляется, когда диктор говорит слово про него
            if v.get("cues"):
                v["at"] = {k: cue_time(seg["words"], c) for k, c in v.pop("cues").items()}
                print("    метки:", {k: (round(t, 2) if t is not None else "НЕ НАЙДЕНО") for k, t in v["at"].items()})
            seg.update(headline=f["headline"], layout=f["layout"], visual=v)
        segs.append(seg)
        print(f"  [{i + 1}] {dur:.1f}с: {text}")
        t += dur
    return segs, t


# ---------- рендер кадров в браузере ----------

def _render_chunk(args):
    """Рендер куска кадров [a, b) в отдельном браузере → свой mp4. Возвращает проблемы аудита и QA-кадры."""
    from playwright.sync_api import sync_playwright
    import base64
    from io import BytesIO
    data, frames, checks, out_mp4, gl = args
    draft = bool(os.environ.get("FV_DRAFT"))          # черновик: половина размера и 15 кадров/с — для «то / не то»
    ff = subprocess.Popen([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "png",
                           "-framerate", str(FPS // 2 if draft else FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-crf", "16", "-preset", "veryfast", str(out_mp4)], stdin=subprocess.PIPE)
    problems, qa = [], []
    with sync_playwright() as p:
        # WebGL (swiftshader) — только для 3D (model, stage): с ним каждый снимок кадра в 3 раза дольше
        gl_args = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] if gl else ["--disable-gpu"]
        br = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security"] + gl_args)
        page = br.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.on("pageerror", lambda e: problems.append(f"JS-ошибка: {e}"))
        page.goto((HERE / "video.html").as_uri())
        page.evaluate("d => init(d)", data)
        cdp = page.context.new_cdp_session(page)
        for fi in frames:
            t = fi / FPS
            page.evaluate("t => seek(t)", t)
            # PNG без потерь, быстрый режим кодирования (в ~1,7 раза быстрее обычного скриншота)
            shot = {"format": "png", "optimizeForSpeed": True}
            if draft:
                shot["clip"] = {"x": 0, "y": 0, "width": 1080, "height": 1920, "scale": 0.5}
            png = base64.b64decode(cdp.send("Page.captureScreenshot", shot)["data"])
            ff.stdin.write(png)
            if fi == 0:
                (WORK / "cover.png").write_bytes(png)         # первый кадр собран — он же обложка
            if fi in checks:
                problems += [f"{t:.1f}с: {b}" for b in page.evaluate("() => audit()")]
                full = Image.open(BytesIO(png)).convert("RGB")
                if os.environ.get("FV_QA_DIR"):
                    full.save(os.path.join(os.environ["FV_QA_DIR"], f"frame_{t:05.1f}.jpg"), quality=90)
                qa.append((fi, full.resize((270, 480))))
        br.close()
    ff.stdin.close()
    ff.wait()
    return problems, qa


def render_frames(segs, total, video_path, qa_path, theme="", opts=None):
    """Кадры рендерятся параллельно в нескольких браузерах (FV_WORKERS, по умолчанию — по числу ядер),
    куски склеиваются без перекодирования."""
    from concurrent.futures import ProcessPoolExecutor
    import http.server, socketserver, threading, functools
    # Локальный HTTP-сервер по папке репозитория: three.js грузит куски карты (_game/maps) через fetch, а с file:// он не работает
    class _Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=str(HERE), **k)
        def log_message(self, *a): pass
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Q)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    data = dict(watermark=WATERMARK, theme=theme,       # theme — вариант оформления выпуска
                http=f"http://127.0.0.1:{srv.server_address[1]}/",
                transition=(opts or {}).get("transition"), subs_style=(opts or {}).get("subs"),   # переход и стиль субтитров (SCENES.md)
                badge=os.environ.get("FV_BADGE", ""),   # плашка сверху (для прослушки голосов на видео)
                segs=[{k: v for k, v in s.items() if not k.startswith("_")} for s in segs])
    # Ключевые моменты для проверки и контрольного листа
    checks = set()
    for s in segs:
        checks |= {int((s["start"] + x) * FPS) + 1 for x in (1.2, s["dur"] * 0.55, s["dur"] - 0.5)}
    n = int(total * FPS)
    frames = sorted(checks) if os.environ.get("FV_QA_ONLY") else list(range(0, n, 2 if os.environ.get("FV_DRAFT") else 1))   # быстрая проверка: только ключевые кадры
    workers = max(1, int(os.environ.get("FV_WORKERS", os.cpu_count() or 2)))
    size = math.ceil(len(frames) / workers)
    gl = bool(re.search(r'"type": "(model|stage)"', json.dumps(data["segs"])))
    jobs = [(data, frames[k:k + size], checks, WORK / f"chunk_{j}.mp4", gl) for j, k in enumerate(range(0, len(frames), size))]
    t0 = time.time()
    with ProcessPoolExecutor(len(jobs)) as ex:
        results = list(ex.map(_render_chunk, jobs))
    print(f"  кадров: {len(frames)}, потоков: {len(jobs)}, {time.time() - t0:.0f} с")
    lst = WORK / "chunks.txt"
    lst.write_text("".join(f"file '{j[3]}'\n" for j in jobs))
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video_path)], check=True)
    problems = [p for r in results for p in r[0]]
    qa_frames = [im for _, im in sorted((x for r in results for x in r[1]), key=lambda x: x[0])]
    # Контрольный лист: ключевые кадры сеткой
    cols = 4
    rows = max(1, math.ceil(len(qa_frames) / cols))
    sheet = Image.new("RGB", (cols * 270, rows * 480), (0, 0, 0))
    for k, im in enumerate(qa_frames):
        sheet.paste(im, ((k % cols) * 270, (k // cols) * 480))
    sheet.save(qa_path, quality=85)
    return problems


_SFX = {}


def sfx(name, max_dur):
    """Звук из assets/snd (звуки Dota 2 с вики): первые max_dur секунд с плавным затуханием. None, если файла нет."""
    key = (name, max_dur)
    if key not in _SFX:
        f = HERE / "assets" / "snd" / f"{name}.mp3"
        if not f.exists():
            _SFX[key] = None
        else:
            p = mp3_to_pcm(f)[:int(max_dur * SR)]
            fade = min(len(p), int(0.35 * SR))
            p = p.copy(); p[-fade:] *= np.linspace(1, 0, fade)
            _SFX[key] = p / (np.abs(p).max() + 1e-9) * 0.9           # громкость выравниваем
    return _SFX[key]


def mix_audio(segs, total, wav_path):
    """Голос + фоновый бит + «вжух» на переходах."""
    n = int((total + 0.5) * SR)
    mix = np.zeros(n, np.float32)
    beat = 60 / 100
    for k in range(int(total / beat) + 1 if os.environ.get("FV_BEAT") else 0):   # фоновый бит выключен: стук слышно
        i = int(k * beat * SR)
        L = min(int(0.12 * SR), n - i)
        if L <= 0:
            break
        tt = np.arange(L) / SR
        mix[i:i + L] += np.sin(2 * np.pi * 60 * tt) * np.exp(-tt * 30) * 0.10   # мягкая бочка, без шипящего хэта
    for s in segs:
        i = int(s["start"] * SR)
        p = s["_pcm"] * 1.15
        L = min(len(p), n - i)
        mix[i:i + L] += p[:L]
        if s["start"] > 0:
            # Переход — светлый воздушный «вжух»: из шума убран низ (без глухого гула), фильтр плавно
            # открывается от мягкого к звонкому и обратно; быстрый вход, плавный хвост
            L = int(0.65 * SR)
            j = max(0, i - int(0.4 * L)); L = min(L, n - j)
            x = np.random.default_rng(i).normal(0, 1, L)
            x = x - np.convolve(x, np.ones(40) / 40, "same")            # убираем низ
            pos = np.linspace(0, 1, L)
            bright = np.sin(np.pi * pos)                                   # 0 → 1 → 0: насколько открыт фильтр
            soft = np.convolve(x, np.ones(9) / 9, "same")
            w = soft * (1 - bright) + x * bright * 0.7
            env = np.where(pos < 0.35, (pos / 0.35) ** 1.5, ((1 - pos) / 0.65) ** 2)
            w *= env
            mix[j:j + L] += w / (np.abs(w).max() + 1e-9) * 0.13
    # Звуки способностей из игры под события на экране: карточки хронологии (поле sfx) и значки хука (hook.sfx)
    def add(t, snd, gain):
        i = int(t * SR)
        if snd is not None and 0 <= i < n:
            L = min(len(snd), n - i)
            mix[i:i + L] += snd[:L] * gain
    # Хронология: мягкий звон при переходе к новому патчу, удар штампа на «удалён» (звуки синтезированы)
    tt = lambda d: np.arange(int(d * SR)) / SR
    # «Бульк» — пузырь воды: тон быстро скользит вверх 260→520 Гц, мягкая атака, короткое затухание (без звона)
    bt = tt(0.16)
    freq = 260 + 260 * (bt / 0.16) ** 0.6
    chime = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-bt * 22) * np.minimum(1, bt / 0.012)
    chime /= np.abs(chime).max()
    thump = np.sin(2 * np.pi * 62 * tt(0.4)) * np.exp(-tt(0.4) * 11)
    click = np.random.default_rng(3).normal(0, 1, len(thump)) * np.exp(-tt(0.4) * 70)
    stamp = thump + 0.45 * click
    stamp /= np.abs(stamp).max()
    for s in segs:
        v = s.get("visual") or {}
        if s.get("layout") != "chronicle":
            continue
        prev = None
        for k, e in enumerate(v.get("entries", [])):
            t0 = (v.get("at") or {}).get(f"e{k}")
            if t0 is None:
                continue
            if e.get("ver") != prev:
                add(s["start"] + t0, chime, 0.16)
            if e.get("kind") == "remove":
                add(s["start"] + t0 + 0.5, stamp, 0.42)
            prev = e.get("ver")
    for s in segs:
        v = s.get("visual") or {}
        for k, e in enumerate(v.get("entries", []) if s.get("layout") == "patchline" else []):
            t0 = (v.get("at") or {}).get(f"e{k}")
            if t0 is not None and e.get("sfx"):
                add(s["start"] + t0, sfx(e["sfx"], 1.8), 0.3)
        if s.get("hook"):
            for t0, name in zip(s.get("at") or [], s.get("sfx") or []):
                if t0 is not None and name:
                    add(s["start"] + t0, sfx(name, 1.4), 0.25)
    # Звуки сцен (SCENES.md, поле sounds): синтезированные, под событие на экране
    rng = np.random.default_rng(7)
    def tick():
        x = np.sin(2 * np.pi * 1800 * tt(0.05)) * np.exp(-tt(0.05) * 90)
        return x / np.abs(x).max()
    def pop():
        b = tt(0.12); f = 420 + 500 * (b / 0.12) ** 0.5
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-b * 30) * np.minimum(1, b / 0.004)
        return x / np.abs(x).max()
    def whoosh(d=0.45):
        L = int(d * SR); x = rng.normal(0, 1, L); x = x - np.convolve(x, np.ones(30) / 30, "same")
        pos = np.linspace(0, 1, L); x *= np.where(pos < .4, (pos / .4) ** 1.5, ((1 - pos) / .6) ** 2)
        return x / np.abs(x).max()
    SND = {"stamp": (stamp, 0.42), "bubble": (chime, 0.16), "tick": (tick(), 0.12), "pop": (pop(), 0.18), "whoosh": (whoosh(), 0.12)}
    def scene_at(sc, at):
        if isinstance(at, str):
            key, _, off = at.partition("+")
            base = (sc.get("at") or {}).get(key)
            return None if base is None else base + (float(off) if off else 0)
        return float(at or 0)
    def clips(items):
        for it in items or []:
            if it.get("type") == "video" and it.get("clip", {}).get("wav"):
                yield it
            yield from clips(it.get("items"))
    # Фон сцены «река»: мягкий шум воды (низ, медленные волны громкости) и редкие всплески
    def river(d, seed):
        g = np.random.default_rng(seed); L = int(d * SR)
        x = np.cumsum(g.normal(0, 1, L)); x -= np.convolve(x, np.ones(800) / 800, "same")   # бурый шум без постоянной составляющей
        x /= np.abs(x).max() + 1e-9
        tt_ = np.arange(L) / SR
        x *= 0.55 + 0.25 * np.sin(2 * np.pi * 0.23 * tt_) + 0.2 * np.sin(2 * np.pi * 0.11 * tt_ + 1)
        for _ in range(int(d * 1.3)):                                    # всплески: короткий шум с быстрым затуханием
            i = int(g.random() * (L - SR * 0.3)); n = int(SR * (0.08 + g.random() * 0.15))
            sp = g.normal(0, 1, n); sp -= np.convolve(sp, np.ones(6) / 6, "same")
            x[i:i + n] += sp * np.exp(-np.arange(n) / SR * 25) * (0.3 + 0.4 * g.random())
        return x / (np.abs(x).max() + 1e-9)
    for s in segs:
        sc = s.get("scene") or {}
        if sc.get("ambience") == "river":
            add(s["start"], river(s["dur"], int(s["start"] * 10) + 1), float(sc.get("ambience_gain", 0.18)))
    for s in segs:
        sc = s.get("scene") or {}
        for it in clips(sc.get("items")):                 # звук клипа с момента его старта
            i_ = it.get("in")
            t0 = scene_at(sc, it.get("start", (i_.get("at") if isinstance(i_, dict) else None) or it.get("at") or 0))
            if t0 is not None:
                with wave.open(it["clip"]["wav"]) as w_:
                    snd = np.frombuffer(w_.readframes(w_.getnframes()), np.int16).astype(np.float32) / 32768
                add(s["start"] + t0, snd, float(it.get("audio", 0)))
        for e in sc.get("sounds", []):
            at = e.get("at", 0)
            if isinstance(at, str):
                key, _, off = at.partition("+")
                base = (sc.get("at") or {}).get(key)
                if base is None:
                    continue
                at = base + (float(off) if off else 0)
            snd, gain = SND.get(e.get("kind", "pop"), SND["pop"])
            add(s["start"] + at, snd, gain * float(e.get("gain", 1)))
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def render(ep, out_path, consts_dir="dotaconstants/build"):
    apply_voice_settings(ep)
    WORK.mkdir(exist_ok=True)
    items = load_consts("items.json", consts_dir)
    heroes = {v["name"].replace("npc_dota_hero_", ""): v
              for v in load_consts("heroes.json", consts_dir).values()}
    segs, total = prepare(ep, heroes, items)
    out_path = Path(out_path)
    video, wav = WORK / "video.mp4", WORK / "audio.wav"
    qa = out_path.with_name("qa_" + out_path.stem + ".jpg")
    problems = render_frames(segs, total, video, qa, ep.get("theme", ""), ep)
    mix_audio(segs, total, wav)
    # Громкость к стандарту площадок (−14 LUFS, пики не выше −1,5 dBTP): TikTok и Shorts всё равно выравнивают,
    # а тихий ролик рядом с соседними звучит слабее
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav),
                    *([] if os.environ.get("FV_SILENT") else ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]), "-ar", "48000",   # без голоса не выравниваем: иначе фон раздувается
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)], check=True)
    stem = out_path.stem
    cover = out_path.with_name((stem.replace("facts_", "cover_", 1) if stem.startswith("facts_") else "cover_" + stem) + ".png")
    if (WORK / "cover.png").exists() and not os.environ.get("FV_QA_ONLY") and not os.environ.get("FV_DRAFT"):
        shutil.copy(WORK / "cover.png", cover)
        print(f"обложка: {cover}")
    print(f"готово: {out_path} ({total:.1f} с)")
    if problems:
        print("ПРОВЕРКА РАСКЛАДКИ: элементы за безопасной зоной:")
        for pr in problems:
            print("  ", pr)
    else:
        print("проверка раскладки: всё в безопасной зоне")


def apply_voice_settings(ep):
    """Настройки голоса из выпуска: fish_temp ниже — ровнее, без срывов; fish_speed — темп речи."""
    global FISH_TEMP, FISH_SPEED
    FISH_TEMP = float(ep.get("fish_temp", FISH_TEMP))
    FISH_SPEED = float(ep.get("fish_speed", FISH_SPEED))


def voice_takes(ep, out_dir, n=3):
    """Несколько дублей озвучки каждого факта (и вариантов финала) — выбрать на слух."""
    apply_voice_settings(ep)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    global FISH_SPEED
    base_speed = FISH_SPEED
    # Задание: имя, текст, число дублей, темп (speed во фрагменте — свой темп, например медленнее для хука)
    jobs = [(f"f{i}", f["voice"], n, f.get("speed")) for i, f in enumerate(ep["parts"], 1) if not f.get("voice_file")]   # выбранные не трогаем
    for name in ("hook", "outro"):           # хук и финал — тоже дублями, если дубль ещё не выбран
        part = ep.get(name)
        if part and part.get("voice") and not part.get("voice_file"):
            jobs.append(("hook" if name == "hook" else "end", part["voice"], n, part.get("speed")))
    jobs += [(f"end{i}", t, 2, None) for i, t in enumerate(ep.get("outro_variants", []), 1)]
    jobs += [(x[0], x[1], x[2] if len(x) > 2 else 2, x[3] if len(x) > 3 else None) for x in ep.get("take_texts", [])]   # варианты: имя, текст, число дублей, темп
    for name, text, k, speed in jobs:
        FISH_SPEED = float(speed) if speed else base_speed
        for t in range(1, k + 1):
            path = out / f"take_{name}_{t}.mp3"
            tts_fish(text, path, ep.get("voice_id"), align=False)
            print(f"  {path.name}: {text}")
            if os.environ.get("FV_TAKES_ANALYZE"):
                summary[path.name] = analyze_take(path)
                (out / "takes.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


def analyze_take(path):
    """Слова с таймингами и громкость пауз между ними: смех/вздохи видны как «шум» в паузе."""
    words = align_words(path)
    pcm = mp3_to_pcm(path)
    line = []
    for (w, a, b), nxt in zip(words, words[1:] + [None]):
        line.append(f"{w}[{a:.2f}-{b:.2f}]")
        if nxt and nxt[1] - b > 0.12:
            seg = pcm[int(b * SR):int(nxt[1] * SR)]
            db = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9)
            line.append(f"<пауза {nxt[1] - b:.2f}с {db:.0f}дБ>")
    print("    " + " ".join(line))
    probs = list(_PROBS)
    weak = [f"{w}:{p:.2f}" for (w, _, _), p in zip(words, probs) if p < 0.6]
    loud = [x for x in line if x.startswith("<пауза") and float(x.split()[1][:-1]) > 0.3 and int(x.split()[2][:-3]) > -35]
    res = dict(prob=round(float(np.mean(probs)) if probs else 0, 3), weak=weak, loud_pauses=loud,
               dur=round(len(pcm) / SR, 2), words=len(words))
    print(f"    ИТОГ: {res}")
    return res


def voices(arg, out_dir):
    """Подбор голоса: «list» — список популярных русских голосов Fish Audio в voices.json,
    иначе — id через запятую: одна и та же фраза каждым голосом (voice_<id>.mp3)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if arg == "list" or arg.startswith("list:"):
        import urllib.parse
        found = {}
        # «list:слово;слово» — поиск по своим словам в названии (например, пират;капитан;бас)
        words = arg[5:].split(";") if arg.startswith("list:") else ["мем", "смеш", "угар", "прикол", "мульт", "озвучк"]
        queries = ([dict(language="ru", sort_by="task_count")] if arg == "list" else []) + \
                  [dict(language="ru", title=t.strip()) for t in words if t.strip()]
        for q in queries:
            url = "https://api.fish.audio/model?" + urllib.parse.urlencode(dict(q, page_size=60))
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {FISH_KEY}"})
            for m in json.loads(urllib.request.urlopen(req, timeout=60).read())["items"]:
                found[m["_id"]] = dict(title=m["title"], tags=m.get("tags"), uses=m.get("task_count"),
                                       likes=m.get("like_count"), desc=(m.get("description") or "")[:120])
        top = sorted(found.items(), key=lambda kv: -(kv[1]["uses"] or 0))
        (out / "voices.json").write_text(json.dumps(dict(top), ensure_ascii=False, indent=1), encoding="utf-8")
        for vid, m in top[:120]:
            print(vid, m["uses"], m["title"], m["tags"])
        return
    # Фраза для прослушки: можно задать своей через FV_VOICE_TEXT
    text = os.environ.get("FV_VOICE_TEXT") or (
        "[curious] Может ли Мипо в одиночку собрать баскетбольную команду? [excited] Может! "
        "[sarcastic] Пять Мипо, и все отдают пас самому себе.")
    for vid in arg.split(","):
        try:
            tts_fish(text, out / f"voice_{vid.strip()}.mp3", vid.strip(), align=False)
            print("  готово", vid)
        except Exception as e:
            print("  ошибка", vid, e)


def audition(ep_path, voices_arg, out_dir):
    """Прослушка голосов прямо на видео: хук и первый факт выпуска каждым голосом, сверху плашка с номером.
    voices_arg: «id:Название,id:Название,…». Итог — out_dir/golosa_<выпуск>.mp4."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = json.load(open(ep_path, encoding="utf-8"))
    parts = []
    pairs = [x.split(":", 1) for x in voices_arg.split(",") if x.strip()]
    for k, (vid, name) in enumerate(pairs, 1):
        ep = json.loads(json.dumps(base))
        ep["voice_id"] = vid.strip()
        ep["parts"] = ep["parts"][:1]
        ep.pop("outro", None)
        for part in [ep.get("hook")] + ep["parts"]:
            if part:
                part.pop("voice_file", None)
        for f in WORK.glob("v*.mp3"):
            f.unlink()
        os.environ["FV_BADGE"] = f"Голос {k} · {name.strip()}"
        mp4 = out / f"aud_{k}.mp4"
        render(ep, mp4)
        parts.append(mp4)
    os.environ.pop("FV_BADGE", None)
    lst = WORK / "aud.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    name = Path(ep_path).stem
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out / f"golosa_{name}.mp4")], check=True)
    for p in parts:
        p.unlink()
        q = p.with_name("qa_" + p.stem + ".jpg")
        if q.exists():
            q.unlink()
    print("прослушка:", out / f"golosa_{name}.mp4")


if __name__ == "__main__":
    if sys.argv[1] == "--audition":
        audition(sys.argv[2], sys.argv[3], sys.argv[4])
    elif sys.argv[1] == "--voices":
        voices(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "--takes":
        with open(sys.argv[2], encoding="utf-8") as f:
            voice_takes(json.load(f), sys.argv[3])
    else:
        with open(sys.argv[1], encoding="utf-8") as f:
            render(json.load(f), sys.argv[2])
