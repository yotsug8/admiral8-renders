"""
Ролик из нескольких фактов о Доте: озвучка, субтитры по словам, графика на HTML/CSS.

Кадры рисует браузер (Playwright + Chromium) по шаблону facts_video.html,
Python готовит данные: озвучку (edge-tts), вырезанных героев (rembg), числа из данных игры, звук.

Запуск:
    python facts_video.py episodes_fv/001.json out/facts_001.mp4
    python facts_video.py --samples out          # пробы голосов
Голос: переменные окружения FV_VOICE, FV_PITCH, FV_RATE.
"""
import asyncio
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image

import quiz as Q
from quiz import fetch_image, load_consts, placeholder

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


# ---------- данные игры ----------

def plural(n, one, few, many):
    """Русское склонение: 1 дерево, 2 дерева, 5 деревьев."""
    n = abs(int(n)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def calc_values(heroes, items):
    """Числа для текста считаются из данных игры, а не пишутся руками."""
    pudge, tango = heroes["pudge"], items["tango"]
    attr = {a["key"]: float(a["value"]) for a in tango["attrib"]}
    heal = int(attr["health_regen"] * attr["buff_duration"])          # лечение одного Танго
    charges = int(attr.get("tooltip_charges", 3))
    hp30 = int(pudge["base_health"] + (pudge["base_str"] + pudge["str_gain"] * 29) * 22)  # 22 HP за силу
    trees = math.ceil(hp30 / heal)
    packs = math.ceil(trees / charges)
    return dict(tango_heal=heal, pudge_hp30=hp30, trees=trees, packs=packs, gold=packs * tango["cost"],
                trees_word=plural(trees, "дерево", "дерева", "деревьев"),
                packs_word=plural(packs, "пачка", "пачки", "пачек"))


# ---------- озвучка ----------

def tts(text, path_mp3, voice=None, pitch=None, rate=None):
    """Синтез речи + тайминги слов [(слово, старт, конец)] в секундах."""
    if os.environ.get("FV_FAKE_TTS"):           # локальная проверка вёрстки без интернета
        ws = text.replace(",", "").replace(".", "").replace("?", "").split()
        dur = 0.34 * len(ws)
        subprocess.run([Q.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
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


def tts_fish(text, path_mp3, voice=None, align=True):
    """Озвучка через Fish Audio + тайминги слов распознаванием (faster-whisper)."""
    import urllib.request
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
    raw = subprocess.run([Q.ffmpeg_exe(), "-loglevel", "error", "-i", str(path), "-f", "f32le",
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
    text = re.sub(r"\[[^\]]*\]", " ", text)            # теги эмоций/пауз Fish Audio не показываем
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


def speak(text, path_mp3, voice_file=None):
    """Озвучка фрагмента: выбранный дубль, иначе Fish Audio (если есть ключ), иначе edge-tts."""
    if voice_file and (HERE / voice_file).exists() and not os.environ.get("FV_FAKE_TTS"):
        import shutil
        shutil.copy(HERE / voice_file, path_mp3)
        return align_to_script(text.replace("\u0301", ""), align_words(path_mp3))
    if FISH_KEY and not os.environ.get("FV_FAKE_TTS"):
        try:
            return align_to_script(text.replace("\u0301", ""), tts_fish(text, path_mp3))
        except Exception as e:                 # ролик всё равно соберётся, но с запасным голосом
            print(f"  ВНИМАНИЕ: Fish Audio не сработал ({e}), озвучка запасным голосом edge-tts")
    elif not FISH_KEY:
        print("  ВНИМАНИЕ: нет FISH_API_KEY, озвучка запасным голосом edge-tts")
    import re
    return tts(re.sub(r"\s*\[[^\]]*\]\s*", " ", text).strip(), path_mp3)


def mp3_to_pcm(path):
    raw = subprocess.run([Q.ffmpeg_exe(), "-loglevel", "error", "-i", str(path), "-f", "s16le",
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
        img = fetch_image(h["img"]) or placeholder(256, 144, h["localized_name"], 0)
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
        img = fetch_image(items[key]["img"]) or placeholder(88, 64, items[key]["dname"], 0)
        img.save(out)
    return out


# ---------- подготовка ----------

def prepare(ep, heroes, items):
    vals = calc_values(heroes, items)
    segs, t = [], 0.0
    parts = ep["facts"] + ([dict(ep["outro"], outro=True)] if ep.get("outro") else [])   # финал по желанию
    for i, f in enumerate(parts):
        text = f["voice"].format(**vals)
        mp3 = WORK / f"v{i}.mp3"
        words = speak(text, mp3, f.get("voice_file"))
        pcm = mp3_to_pcm(mp3)
        dur = len(pcm) / SR + PAD + (0.6 if i == len(parts) - 1 else 0)   # в конце чуть дольше пауза
        seg = dict(start=t, dur=dur, words=[[w, round(a, 3), round(b, 3)] for w, a, b in words], _pcm=pcm)
        if f.get("outro"):
            thumbs = []
            for fact in ep["facts"]:
                v = fact.get("visual", {})
                # Для сетки и таймера — иконка предмета, иначе герой
                if v.get("icons") and (fact["layout"] in ("grid", "timer") or not v.get("heroes")):
                    thumbs.append(item_icon(v["icons"], items).as_uri())
                elif v.get("heroes"):
                    thumbs.append(hero_cutout(v["heroes"][0], heroes).as_uri())
                else:
                    thumbs.append(None)
            seg.update(outro=True, question=f["question"], cta=f["cta"], thumbs=thumbs)
        else:
            v = dict(f.get("visual", {}))
            if v.get("heroes"):
                v["heroes"] = [hero_cutout(k, heroes).as_uri() for k in v["heroes"]]
            if v.get("icons"):
                v["icons"] = dict(src=item_icon(v["icons"], items).as_uri(),
                                  count=int(str(v["count"]).format(**vals)))
            for key in ("team_logos", "ability_icons"):     # картинки, лежащие в репозитории
                if v.get(key):
                    v[key] = [(HERE / x).as_uri() if x else None for x in v[key]]
            if v.get("event_logo"):
                v["event_logo"] = (HERE / v["event_logo"]).as_uri()
            for key in ("number", "label", "caption"):
                if v.get(key):
                    v[key] = str(v[key]).format(**vals)
            seg.update(headline=f["headline"], layout=f["layout"], visual=v)
        segs.append(seg)
        print(f"  [{i + 1}] {dur:.1f}с: {text}")
        t += dur
    return segs, t


# ---------- финальный клип ----------

CLIP_BOX = (100, 500, 880)        # x, y, сторона квадрата клипа — внутри безопасной зоны
SHADOW = 16                       # жёсткая жёлтая тень, как у плашек в шаблоне


def clip_frames(src, trim):
    """Кадры клипа 1080x1920: размытый клип на фоне + клип в рамке с жёсткой тенью."""
    from PIL import ImageDraw, ImageFilter
    w = h = 480
    probe = subprocess.run([Q.ffmpeg_exe(), "-loglevel", "error", "-ss", str(trim), "-i", str(src),
                            "-vf", f"fps={FPS},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True).stdout
    raw = np.frombuffer(probe, np.uint8).reshape(-1, h, w, 3)
    x0, y0, side = CLIP_BOX
    # Маска скруглённого квадрата и подложка-тень — одни на все кадры
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), 28, fill=255)
    for fr in raw:
        im = Image.fromarray(fr)
        # Фон: клип, растянутый на весь экран, размытый и затемнённый (размываем в малом размере — быстро)
        bg = im.resize((240, 240)).crop((52, 0, 187, 240)).filter(ImageFilter.GaussianBlur(6))
        bg = bg.resize((1080, 1920), Image.BILINEAR).point(lambda v: int(v * 0.45))
        d = ImageDraw.Draw(bg)
        d.rounded_rectangle((x0 + SHADOW, y0 + SHADOW, x0 + side + SHADOW, y0 + side + SHADOW), 28, fill=(255, 210, 63))
        bg.paste(im.resize((side, side), Image.LANCZOS), (x0, y0), mask)
        yield bg


def clip_pcm(src, trim):
    raw = subprocess.run([Q.ffmpeg_exe(), "-loglevel", "error", "-ss", str(trim), "-i", str(src), "-vn",
                          "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


# ---------- рендер кадров в браузере ----------

def render_frames(segs, total, video_path, qa_path, clip=None):
    from playwright.sync_api import sync_playwright

    data = dict(watermark=WATERMARK, end_at=total if clip else None,
                segs=[{k: v for k, v in s.items() if not k.startswith("_")} for s in segs])
    ff = subprocess.Popen([Q.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "mjpeg",
                           "-framerate", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-crf", "19", "-preset", "medium", str(video_path)], stdin=subprocess.PIPE)
    # Ключевые моменты для проверки и контрольного листа
    checks = []
    for s in segs:
        checks += [s["start"] + 1.2, s["start"] + s["dur"] * 0.55, s["start"] + s["dur"] - 0.5]
    qa_frames, problems = [], []
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security"])
        page = br.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.on("pageerror", lambda e: problems.append(f"JS-ошибка: {e}"))
        page.goto((HERE / "facts_video.html").as_uri())
        page.evaluate("d => init(d)", data)
        n = int(total * FPS)
        ci = 0
        frames = range(n)
        if os.environ.get("FV_QA_ONLY"):        # быстрая проверка: только ключевые кадры
            frames = sorted({int(c * FPS) + 1 for c in checks})
        for fi in frames:
            t = fi / FPS
            page.evaluate("t => seek(t)", t)
            jpg = page.screenshot(type="jpeg", quality=92)
            ff.stdin.write(jpg)
            if ci < len(checks) and t >= checks[ci]:
                for b in page.evaluate("() => audit()"):
                    problems.append(f"{t:.1f}с: {b}")
                from io import BytesIO
                full = Image.open(BytesIO(jpg)).convert("RGB")
                if os.environ.get("FV_QA_DIR"):        # полноразмерные кадры для просмотра
                    full.save(os.path.join(os.environ["FV_QA_DIR"], f"frame_{t:05.1f}.jpg"), quality=90)
                qa_frames.append(full.resize((270, 480)))
                ci += 1
            if fi % 150 == 0:
                print(f"  кадр {fi}/{n}")
        if clip:
            # Поверх клипа: съезжающая шторка в первые кадры, дальше только водяной знак
            from io import BytesIO
            static = None
            for k, fr in enumerate(clip_frames(clip["src"], clip.get("trim", 0))):
                d = k / FPS
                if d < 0.4 or static is None:
                    page.evaluate("d => overlayAt(d)", d)
                    ov = Image.open(BytesIO(page.screenshot(type="png", omit_background=True))).convert("RGBA")
                    if d >= 0.4:
                        static = ov
                else:
                    ov = static
                fr = Image.alpha_composite(fr.convert("RGBA"), ov).convert("RGB")
                buf = BytesIO()
                fr.save(buf, "JPEG", quality=92)
                ff.stdin.write(buf.getvalue())
                if k in (3, 45, 120):
                    qa_frames.append(fr.resize((270, 480)))
                    if os.environ.get("FV_QA_DIR"):
                        fr.save(os.path.join(os.environ["FV_QA_DIR"], f"clip_{d:04.1f}.jpg"), quality=90)
                if os.environ.get("FV_QA_ONLY") and k > 120:
                    break
        br.close()
    ff.stdin.close()
    ff.wait()
    # Контрольный лист: ключевые кадры сеткой
    cols = 4
    rows = math.ceil(len(qa_frames) / cols)
    sheet = Image.new("RGB", (cols * 270, rows * 480), (0, 0, 0))
    for k, im in enumerate(qa_frames):
        sheet.paste(im, ((k % cols) * 270, (k // cols) * 480))
    sheet.save(qa_path, quality=85)
    return problems


def mix_audio(segs, total, wav_path, clip_audio=None):
    """Голос + фоновый бит + «вжух» на переходах (+ звук финального клипа после total)."""
    tail = len(clip_audio) / SR if clip_audio is not None else 0.5
    n = int((total + tail) * SR)
    mix = np.zeros(n, np.float32)
    beat = 60 / 100
    for k in range(int(total / beat) + 1):
        i = int(k * beat * SR)
        L = min(int(0.12 * SR), n - i)
        if L <= 0:
            break
        tt = np.arange(L) / SR
        mix[i:i + L] += np.sin(2 * np.pi * 60 * tt) * np.exp(-tt * 30) * 0.10   # мягкая бочка, без шипящего хэта
    if clip_audio is not None:
        i = int(total * SR)
        mix[i:i + len(clip_audio)] += clip_audio[:n - i] * 0.9
        L = min(int(0.4 * SR), n - i)        # «вжух» шторки на входе в клип
        env = np.sin(np.linspace(0, np.pi, L)) * 0.14
        mix[i:i + L] += np.random.default_rng(i).normal(0, 1, L) * env
    for s in segs:
        i = int(s["start"] * SR)
        p = s["_pcm"] * 1.15
        L = min(len(p), n - i)
        mix[i:i + L] += p[:L]
        if s["start"] > 0:
            L = min(int(0.4 * SR), n - i)
            env = np.sin(np.linspace(0, np.pi, L)) * 0.14
            mix[i:i + L] += np.random.default_rng(i).normal(0, 1, L) * env
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def render(ep, out_path, consts_dir="dotaconstants/build"):
    WORK.mkdir(exist_ok=True)
    items = load_consts("items.json", consts_dir)
    heroes = {v["name"].replace("npc_dota_hero_", ""): v
              for v in load_consts("heroes.json", consts_dir).values()}
    segs, total = prepare(ep, heroes, items)
    out_path = Path(out_path)
    video, wav = WORK / "video.mp4", WORK / "audio.wav"
    qa = out_path.with_name("qa_" + out_path.stem + ".jpg")
    clip = ep.get("end_clip")
    if clip:
        clip = dict(clip, src=HERE / clip["src"])
    problems = render_frames(segs, total, video, qa, clip)
    mix_audio(segs, total, wav, clip_pcm(clip["src"], clip.get("trim", 0)) if clip else None)
    if clip:
        total += len(clip_pcm(clip["src"], clip.get("trim", 0))) / SR
    subprocess.run([Q.ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)], check=True)
    print(f"готово: {out_path} ({total:.1f} с)")
    if problems:
        print("ПРОВЕРКА РАСКЛАДКИ: элементы за безопасной зоной:")
        for pr in problems:
            print("  ", pr)
    else:
        print("проверка раскладки: всё в безопасной зоне")


def voice_samples(out_dir):
    """Пробы голосов одной фразой — выбрать на слух."""
    text = "Valve однажды тайно усилила героя, без патчноута. За одну ночь её винрейт подскочил с тридцати девяти до пятидесяти одного процента!"
    if FISH_KEY:
        fish = [("energichny", "48ec28a45588422b977a86460c11977f"), ("incidenty", "2270bb203a424d1881678ba5e4b82b54"),
                ("analitik", "868377a7b08f4c0d9acf8c9f059571aa")]
        for name, vid in fish:
            try:
                words = tts_fish(text, Path(out_dir) / f"voice_fish_{name}.mp3", vid)
                print(f"  fish {name}: {len(words)} слов распознано")
            except RuntimeError as e:
                print(f"  fish {name}: ошибка {e}")
        return
    variants = [("ru-RU-DmitryNeural", "-25Hz", "+0%"),
                ("en-US-AndrewMultilingualNeural", "+0Hz", "+5%"),
                ("en-US-BrianMultilingualNeural", "+0Hz", "+5%"),
                ("de-DE-FlorianMultilingualNeural", "+0Hz", "+5%"),
                ("fr-FR-RemyMultilingualNeural", "+0Hz", "+5%"),
                ("ru-RU-SvetlanaNeural", "+0Hz", "+10%")]
    for n, (v, p, r) in enumerate(variants, 1):
        try:
            tts(text, Path(out_dir) / f"voice_{n}.mp3", v, p, r)
            print(f"  голос {n}: {v} {p} {r}")
        except RuntimeError as e:
            print(f"  голос {n}: {v} недоступен ({e})")


def voice_takes(ep, out_dir, n=3):
    """Несколько дублей озвучки каждого факта (и вариантов финала) — выбрать на слух."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    jobs = [(f"f{i}", f["voice"], n) for i, f in enumerate(ep["facts"], 1) if not f.get("voice_file")]   # выбранные не трогаем
    jobs += [(f"end{i}", t, 2) for i, t in enumerate(ep.get("outro_variants", []), 1)]
    jobs += [(x[0], x[1], x[2] if len(x) > 2 else 2) for x in ep.get("take_texts", [])]   # варианты: имя, текст, число дублей
    for name, text, k in jobs:
        for t in range(1, k + 1):
            path = out / f"take_{name}_{t}.mp3"
            tts_fish(text, path, align=False)
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


if __name__ == "__main__":
    if sys.argv[1] == "--samples":
        voice_samples(sys.argv[2])
    elif sys.argv[1] == "--takes":
        with open(sys.argv[2], encoding="utf-8") as f:
            voice_takes(json.load(f), sys.argv[3])
    else:
        with open(sys.argv[1], encoding="utf-8") as f:
            render(json.load(f), sys.argv[2])
