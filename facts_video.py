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
# Fish Audio: живой голос (если задан ключ). Голос «Да да» из библиотеки fish.audio
FISH_KEY = os.environ.get("FISH_API_KEY", "")
FISH_VOICE = os.environ.get("FISH_VOICE", "ee1f00ee4b0f4f15b685bf1738a33a0d")
FISH_MODEL = os.environ.get("FISH_MODEL", "s2.1-pro-free")
FISH_SPEED = float(os.environ.get("FISH_SPEED", "1.1"))
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


def tts_fish(text, path_mp3, voice=None):
    """Озвучка через Fish Audio + тайминги слов распознаванием (faster-whisper)."""
    import urllib.request
    body = json.dumps({"text": text, "reference_id": voice or FISH_VOICE, "format": "mp3",
                       "mp3_bitrate": 192, "prosody": {"speed": FISH_SPEED}, "language": "ru",
                       "normalize": True}).encode()
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
            last = e
            print(f"  fish повтор {attempt + 1}: {e}")
    else:
        raise RuntimeError(f"Fish Audio не ответил: {last}")
    return align_words(path_mp3)


_WHISPER = None


def align_words(path):
    """Слова с таймингами из готовой озвучки (субтитры совпадают с тем, что звучит)."""
    global _WHISPER
    from faster_whisper import WhisperModel
    if _WHISPER is None:
        _WHISPER = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = _WHISPER.transcribe(str(path), language="ru", word_timestamps=True, vad_filter=False)
    words = []
    for sg in segs:
        for w in sg.words or []:
            t = w.word.strip()
            if t:
                words.append((t, float(w.start), float(w.end)))
    return words


def speak(text, path_mp3):
    """Озвучка фрагмента: Fish Audio, если есть ключ, иначе бесплатный edge-tts."""
    if FISH_KEY and not os.environ.get("FV_FAKE_TTS"):
        return tts_fish(text, path_mp3)
    return tts(text, path_mp3)


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
        words = speak(text, mp3)
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
            for key in ("number", "label", "caption"):
                if v.get(key):
                    v[key] = str(v[key]).format(**vals)
            seg.update(headline=f["headline"], layout=f["layout"], visual=v)
        segs.append(seg)
        print(f"  [{i + 1}] {dur:.1f}с: {text}")
        t += dur
    return segs, t


# ---------- рендер кадров в браузере ----------

def render_frames(segs, total, video_path, qa_path):
    from playwright.sync_api import sync_playwright

    data = dict(watermark=WATERMARK,
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
                qa_frames.append(Image.open(BytesIO(jpg)).convert("RGB").resize((270, 480)))
                ci += 1
            if fi % 150 == 0:
                print(f"  кадр {fi}/{n}")
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
        mix[i:i + L] += np.sin(2 * np.pi * 60 * tt) * np.exp(-tt * 30) * 0.16
        if k % 2:
            h = min(int(0.03 * SR), n - i)
            mix[i:i + h] += np.random.default_rng(k).normal(0, 1, h) * 0.025
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
    problems = render_frames(segs, total, video, qa)
    mix_audio(segs, total, wav)
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


if __name__ == "__main__":
    if sys.argv[1] == "--samples":
        voice_samples(sys.argv[2])
    else:
        with open(sys.argv[1], encoding="utf-8") as f:
            render(json.load(f), sys.argv[2])
