"""
Ролик «несколько фактов о Доте»: озвучка, субтитры по словам, графика на HTML/CSS.

Кадры рисует браузер (Playwright + Chromium) по шаблону facts_video.html.
Python готовит данные: озвучку (Fish Audio, запасной — edge-tts), героев и иконки, звук.

Запуск:
    python facts_video.py episodes_fv/002.json out/facts_002.mp4    # рендер выпуска
    python facts_video.py --takes episodes_fv/002.json out           # дубли озвучки на выбор
Локальная проверка вёрстки без сети: FV_QA_ONLY=1 FV_FAKE_TTS=1 FV_QA_DIR=папка
"""
import asyncio
import json
import math
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
    os.makedirs("cache", exist_ok=True)
    cached = os.path.join("cache", name)
    if not os.path.exists(cached):
        with urllib.request.urlopen(CONSTS_URL + name, timeout=30) as r:
            data = r.read()
        with open(cached, "wb") as f:
            f.write(data)
    return json.load(open(cached, encoding="utf-8"))


def fetch_image(path, cache_dir="cache"):
    """Картинка с CDN Steam (с кэшем и повтором). None, если не вышло."""
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
    print("  нет картинки:", path.split("?")[0])
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
    """Озвучка через Fish Audio + тайминги слов распознаванием (faster-whisper)."""
    import urllib.request
    text = say_text(text)
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
    """Слова с таймингами из готовой озвучки (субтитры совпадают с тем, что звучит)."""
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
    text = re.sub(r"\[[^\]]*\]", " ", show_text(text))   # теги эмоций/пауз не показываем; {показ|озвучка} → показ
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
            return align_to_script(text.replace("\u0301", ""), tts_fish(text, path_mp3, voice))
        except Exception as e:                 # ролик всё равно соберётся, но с запасным голосом
            print(f"  ВНИМАНИЕ: Fish Audio не сработал ({e}), озвучка запасным голосом edge-tts")
    elif not FISH_KEY:
        print("  ВНИМАНИЕ: нет FISH_API_KEY, озвучка запасным голосом edge-tts")
    import re
    return tts(re.sub(r"\s*\[[^\]]*\]\s*", " ", say_text(text)).replace("\u0301", "").strip(), path_mp3)


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
            print("  не удалось вырезать фон:", key, e)
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
            "file": lambda: HERE / key}[kind]()
    return path.as_uri()


def anim_frames(key):
    """Кадры анимированного рендера героя (assets/anim/<ключ>/*.webp, родная частота из meta.json, без потерь) → {fps, frames}.
    Свечение и тень запекаются в кадры один раз: CSS-фильтр на каждом кадре был самым дорогим местом рендера."""
    from PIL import ImageFilter
    fs = sorted((HERE / "assets" / "anim" / key).glob("*.webp"))
    if not fs:
        print("  нет анимации:", key)
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


def prepare(ep, heroes, items):
    segs, t = [], 0.0
    parts = ep["facts"] + ([dict(ep["outro"], outro=True)] if ep.get("outro") else [])   # финал по желанию
    if ep.get("hook"):                       # короткий хук перед фактами
        parts = [dict(ep["hook"], hook=True)] + parts
    for i, f in enumerate(parts):
        text = f["voice"]
        mp3 = WORK / f"v{i}.mp3"
        words = speak(text, mp3, f.get("voice_file"), ep.get("voice_id"))   # голос — свой у каждого выпуска
        pcm = mp3_to_pcm(mp3)
        pad = float(ep.get("pad", PAD))      # пауза после фрагмента: можно задать в выпуске, чтобы уложиться в 45 с
        dur = len(pcm) / SR + pad + (0.6 if i == len(parts) - 1 else 0)   # в конце чуть дольше пауза
        seg = dict(start=t, dur=dur, words=[[w, round(a, 3), round(b, 3)] for w, a, b in words], _pcm=pcm)
        if f.get("outro"):
            thumbs = []
            for fact in ep["facts"]:
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
    data, frames, checks, out_mp4 = args
    ff = subprocess.Popen([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "png",
                           "-framerate", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-crf", "16", "-preset", "veryfast", str(out_mp4)], stdin=subprocess.PIPE)
    problems, qa = [], []
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security"])
        page = br.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.on("pageerror", lambda e: problems.append(f"JS-ошибка: {e}"))
        page.goto((HERE / "facts_video.html").as_uri())
        page.evaluate("d => init(d)", data)
        cdp = page.context.new_cdp_session(page)
        for fi in frames:
            t = fi / FPS
            page.evaluate("t => seek(t)", t)
            # PNG без потерь, быстрый режим кодирования (в ~1,7 раза быстрее обычного скриншота)
            png = base64.b64decode(cdp.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True})["data"])
            ff.stdin.write(png)
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


def render_frames(segs, total, video_path, qa_path, theme=""):
    """Кадры рендерятся параллельно в нескольких браузерах (FV_WORKERS, по умолчанию — по числу ядер),
    куски склеиваются без перекодирования."""
    from concurrent.futures import ProcessPoolExecutor
    data = dict(watermark=WATERMARK, theme=theme,       # theme — вариант оформления выпуска
                badge=os.environ.get("FV_BADGE", ""),   # плашка сверху (для прослушки голосов на видео)
                segs=[{k: v for k, v in s.items() if not k.startswith("_")} for s in segs])
    # Ключевые моменты для проверки и контрольного листа
    checks = set()
    for s in segs:
        checks |= {int((s["start"] + x) * FPS) + 1 for x in (1.2, s["dur"] * 0.55, s["dur"] - 0.5)}
    n = int(total * FPS)
    frames = sorted(checks) if os.environ.get("FV_QA_ONLY") else list(range(n))   # быстрая проверка: только ключевые кадры
    workers = max(1, int(os.environ.get("FV_WORKERS", os.cpu_count() or 2)))
    size = math.ceil(len(frames) / workers)
    jobs = [(data, frames[k:k + size], checks, WORK / f"chunk_{j}.mp4") for j, k in enumerate(range(0, len(frames), size))]
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
    for k in range(int(total / beat) + 1):
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
            tr = sfx("Torrent_erupt", 1.3)
            if tr is not None:                     # переход — всплеск воды (звук Торрента из игры)
                j = max(0, i - int(0.35 * SR)); L = min(len(tr), n - j)
                mix[j:j + L] += tr[:L] * 0.32
            else:
                L = min(int(0.4 * SR), n - i)
                env = np.sin(np.linspace(0, np.pi, L)) * 0.14
                mix[i:i + L] += np.random.default_rng(i).normal(0, 1, L) * env
    # Звуки способностей из игры под события на экране: карточки хронологии (поле sfx) и значки хука (hook.sfx)
    def add(t, snd, gain):
        i = int(t * SR)
        if snd is not None and 0 <= i < n:
            L = min(len(snd), n - i)
            mix[i:i + L] += snd[:L] * gain
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
    problems = render_frames(segs, total, video, qa, ep.get("theme", ""))
    mix_audio(segs, total, wav)
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)], check=True)
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
    jobs = [(f"f{i}", f["voice"], n, f.get("speed")) for i, f in enumerate(ep["facts"], 1) if not f.get("voice_file")]   # выбранные не трогаем
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
        ep["facts"] = ep["facts"][:1]
        ep.pop("outro", None)
        for part in [ep.get("hook")] + ep["facts"]:
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
