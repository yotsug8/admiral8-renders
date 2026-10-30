# Сведение сценки: видео кадров + голоса по своим местам (−14 LUFS) + звуки действий; субтитры канала — только с SUBS=1
# (Manrope 800, 56 px, y 1468, по 1–3 слова, звучащее слово — на жёлтой плашке).
# Время слов — по громкости реплики: начало и конец речи по звуку, слова распределены по длине.
#   py -3.11 tools/skit/mix.py <видео> <выход> <scene.json>     GRADE=1 — цветокоррекция по примерам (grade.py)
# Реплики и их места — из scene.json (voices: {имя: [актёр, сек]}), тексты и громкость — voices.json рядом с ним.
import json, os, re, subprocess, sys
import numpy as np
import imageio_ffmpeg
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.stdout.reconfigure(encoding="utf-8")
if len(sys.argv) < 4:
    raise SystemExit("py -3.11 tools/skit/mix.py <видео> <выход> <scene.json>")
TAKE, OUT, SCENE = sys.argv[1:4]
VO = os.path.dirname(os.path.abspath(SCENE))
FF = imageio_ffmpeg.get_ffmpeg_exe()
V = json.load(open(os.path.join(VO, "voices.json"), encoding="utf-8"))
_D = json.load(open(SCENE, encoding="utf-8"))
OFFS = {k: float(v[1]) for k, v in _D["voices"].items()}; DUR = float(_D["dur"])
from footsteps import plan_footsteps
FOOTSTEPS = plan_footsteps(_D, os.path.join(REPO, "_game", "sfx"))

# ---- субтитры только по запросу; иначе не вычислять слова и не запускать Chromium
chunks = []
cache = {}
if os.environ.get("SUBS") == "1":
    for name, off in OFFS.items():
        env = np.array(V[name]["env"]); on = np.where(env > 0.08)[0]
        if not len(on):
            continue
        a, b = off + on[0] / 30, off + (on[-1] + 1) / 30
        words = V[name]["text"].replace("—", "").split()
        w = np.array([len(re.sub(r"\W", "", x)) + 2 for x in words], float)
        starts = a + (b - a) * np.concatenate([[0], np.cumsum(w)[:-1]]) / w.sum()
        line, group, gt = [], [], []
        for i, word in enumerate(words):
            group.append(word); gt.append(float(starts[i]))
            if len(group) == 3 or re.search(r"[.?!…]$", word) or i == len(words) - 1:
                line.append([gt[0], None, group, gt]); group, gt = [], []
        for j, c in enumerate(line):                 # кусок держится до следующего куска реплики, последний — до конца речи
            c[1] = line[j + 1][0] if j + 1 < len(line) else b + 0.35
        chunks += [tuple(c) for c in line]
    chunks.sort(key=lambda c: c[0])                  # хвост реплики (+0,35 с) не налезает на следующую
    chunks = [(a, min(b, chunks[i + 1][0]) if i + 1 < len(chunks) else b, w, wt) for i, (a, b, w, wt) in enumerate(chunks)]
    print("субтитры:", " | ".join(f"{c[0]:.2f}–{c[1]:.2f} {' '.join(c[2])}" for c in chunks))

    # ---- картинки субтитров: каждое состояние (кусок, звучащее слово) — один раз через Chromium
    from playwright.sync_api import sync_playwright
    from pathlib import Path
    FONTS = Path(REPO, "fonts").as_uri()                # file:///C:/… и file:///home/… — одинаково
    CSS = f"""
    @font-face {{ font-family: Manrope; font-weight: 800; src: url({FONTS}/manrope-cyrillic-800-normal.woff2) format("woff2"); }}
    @font-face {{ font-family: Manrope; font-weight: 800; src: url({FONTS}/manrope-latin-800-normal.woff2) format("woff2"); unicode-range: U+0000-00FF; }}
    html, body {{ margin: 0; background: transparent; }}
    #subs {{ position: absolute; left: 60px; width: 880px; top: 1468px; display: flex; justify-content: center; text-align: center;
             font: 800 56px/1.2 Manrope; white-space: nowrap; color: #fff; }}
    #subs span {{ display: inline-block; margin: 0 4px; padding: 2px 12px; border-radius: 12px; text-shadow: 0 5px 0 #15171c; border: 4px solid transparent; }}
    #subs span.on {{ background: #ffd23f; color: #15171c; text-shadow: none; box-shadow: 6px 6px 0 #0b0c10; border-color: #15171c; }}
    """
    with sync_playwright() as pw:
        br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1080, "height": 1920})
        for ci, (_, _, words, _) in enumerate(chunks):
            for wi in range(len(words)):
                html = "<style>" + CSS + "</style><div id=subs>" + "".join(
                    f'<span class="{"on" if i == wi else ""}">{w}</span>' for i, w in enumerate(words)) + "</div>"
                page = os.path.join(VO, "sub.html")             # страница из файла: со страницы в памяти шрифты file:// не грузятся
                open(page, "w", encoding="utf-8").write("<meta charset=utf-8>" + html)
                pg.goto(Path(page).as_uri()); pg.evaluate("document.fonts.ready")
                assert pg.evaluate("document.fonts.check('800 56px Manrope', 'Ж')"), "Manrope не загрузился"
                path = os.path.join(VO, f"sub_{ci}_{wi}.png")
                pg.screenshot(path=path, omit_background=True, clip={"x": 0, "y": 1400, "width": 1080, "height": 200})
                cache[(ci, wi)] = Image.open(path).convert("RGBA")
        br.close()


def overlay(t):
    for ci, (a, b, words, wt) in enumerate(chunks):
        if a <= t < b:
            wi = max(i for i in range(len(words)) if wt[i] <= t)
            return cache[(ci, wi)]
    return None


# ---- звук: голоса по местам, громкость −14 LUFS
SR = 48000; mix = np.zeros(int(DUR * SR) + SR, np.float32)
for name, off in OFFS.items():
    raw = subprocess.run([FF, "-v", "error", "-i", os.path.join(VO, f"{name}.wav"), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768; i = int(off * SR)
    mix[i:i + len(a)] += a[:len(mix) - i]

# ---- звуки действий (из игры, _game/sfx; только под смысловое событие): крюк — бросок, попадание, лязг цепи на возврате, стоп.
# Время — из сцены: бросок — начало эффекта, попадание — остриё дальше всего от Пуджа, возврат — остриё снова у него
SFX = os.path.join(REPO, "_game", "sfx")


def sfx(name, t, gain, length=None):
    """Звук name в момент t; length — обрезать по длине действия (затухание 0,08 с), чтобы не налезал на реплику."""
    p = os.path.join(SFX, name)
    if not os.path.exists(p):
        print("  звука нет:", name); return
    raw = subprocess.run([FF, "-v", "error", "-i", p, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768 * gain; i = max(0, int(t * SR))
    if length:
        a = a[:int(length * SR)].copy(); k = min(len(a), int(0.08 * SR)); a[len(a) - k:] *= np.linspace(1, 0, k)
    mix[i:i + len(a)] += a[:max(0, len(mix) - i)]


FPS_ = float(_D.get("fps", 30))
for t0, fxname, at, _z, dur, *rest in _D.get("fx", []):
    if "meathook" not in fxname or not rest or rest[0] not in _D["actors"] or at[0] not in _D["actors"]:
        continue
    tip, who = _D["actors"][rest[0]]["keys"], _D["actors"][at[0]]["keys"]
    f0, f1 = int(t0 * FPS_), min(len(tip), int((t0 + dur) * FPS_) + 1)
    dist = [np.hypot(tip[f][0] - who[f][0], tip[f][1] - who[f][1]) for f in range(f0, f1)]
    hit = f0 + int(np.argmax(dist)); back = next((f for f in range(hit, f1) if dist[f - f0] < dist[0] + 40), f1 - 1)
    sfx("hook_throw", t0, 0.5, hit / FPS_ - t0 + 0.05); sfx("hook_impact", hit / FPS_, 0.9)
    sfx("hook_throw", hit / FPS_ + 0.05, 0.35, (back - hit) / FPS_); sfx("hook_retract_stop", back / FPS_, 0.6)   # возврат — лязг, как в игре
    print(f"  звук крюка: бросок {t0:.2f} с, попадание {hit / FPS_:.2f} с, возврат {back / FPS_:.2f} с")
for name, at, gain in FOOTSTEPS:
    sfx(name, at, gain)
mix = mix[:int(DUR * SR)]
wav = os.path.join(VO, "mix.wav")
raw_wav = os.path.join(VO, "mix_raw.wav")             # громкость к −14 LUFS в два прохода (video.loudnorm): без «качания»
subprocess.run([FF, "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "pcm_f32le", raw_wav], input=mix.tobytes(), check=True)
sys.path.insert(0, REPO)
from video import loudnorm
subprocess.run([FF, "-y", "-v", "error", "-i", raw_wav, "-af", loudnorm(raw_wav), "-ar", str(SR), wav], check=True)

# ---- кадры с субтитрами → mp4 со звуком
r = imageio_ffmpeg.read_frames(TAKE); meta = next(r); W, H = meta["size"]
enc = subprocess.Popen([FF, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "30", "-i", "-", "-i", wav,
                        "-c:v", "libx264", "-crf", "15", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", OUT],
                       stdin=subprocess.PIPE)
MATCH = None
if os.environ.get("GRADE"):                        # цветокоррекция по образцу — tools/skit/grade.py (skit.py --all ставит сам)
    import grade as _g
    MATCH = _g.Grade(_g.sample(TAKE)); print("цвет:", MATCH.info)
n = 0
for k, b in enumerate(r):
    img = Image.frombytes("RGB", (W, H), b)
    if MATCH:
        img = Image.fromarray(MATCH(np.asarray(img)))
    ov = overlay(k / 30)
    if ov is not None:
        img.paste(ov, (0, 1400), ov)
    enc.stdin.write(img.tobytes()); n += 1
enc.stdin.close(); enc.wait()
print(f"готово: {OUT} ({n} кадров, {n / 30:.1f} с)")
