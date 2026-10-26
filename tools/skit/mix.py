# Сведение сценки: видео кадров + голоса по своим местам (−14 LUFS) + субтитры канала
# (Manrope 800, 56 px, y 1468, по 1–3 слова, звучащее слово — на жёлтой плашке).
# Время слов — по громкости реплики: начало и конец речи по звуку, слова распределены по длине.
#   py -3.11 tools/skit/mix.py <видео> <выход> <scene.json>     GRADE=1 — киношная обработка: свечение, виньетка, контраст
# Реплики и их места — из scene.json (voices: {имя: [актёр, сек]}), тексты и громкость — voices.json рядом с ним.
import json, os, re, subprocess, sys
import numpy as np
import imageio_ffmpeg
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if len(sys.argv) < 4:
    raise SystemExit("py -3.11 tools/skit/mix.py <видео> <выход> <scene.json>")
TAKE, OUT, SCENE = sys.argv[1:4]
VO = os.path.dirname(os.path.abspath(SCENE))
FF = imageio_ffmpeg.get_ffmpeg_exe()
V = json.load(open(os.path.join(VO, "voices.json"), encoding="utf-8"))
_D = json.load(open(SCENE, encoding="utf-8"))
OFFS = {k: float(v[1]) for k, v in _D["voices"].items()}; DUR = float(_D["dur"])

# ---- слова и их время
chunks = []                                     # (начало, конец, [слова], [время каждого слова])
for name, off in OFFS.items():
    env = np.array(V[name]["env"]); on = np.where(env > 0.08)[0]
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
cache = {}
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
mix = mix[:int(DUR * SR)]
wav = os.path.join(VO, "mix.wav")
subprocess.run([FF, "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), wav],
               input=mix.tobytes(), check=True)

# ---- кадры с субтитрами → mp4 со звуком
r = imageio_ffmpeg.read_frames(TAKE); meta = next(r); W, H = meta["size"]
enc = subprocess.Popen([FF, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "30", "-i", "-", "-i", wav,
                        "-c:v", "libx264", "-crf", "15", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", OUT],
                       stdin=subprocess.PIPE)
from PIL import ImageFilter, ImageEnhance
GRADE = os.environ.get("GRADE")                    # 1 — киношная обработка (для рендера Blender): свечение, виньетка, контраст
yy, xx = np.mgrid[0:H, 0:W]
VIG = (1 - 0.32 * np.clip((((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2) - 0.35, 0, 1) ** 1.2)[..., None]


def grade(img):
    a = np.asarray(img).astype(np.float32) / 255
    bright = np.clip((a - 0.72) / 0.28, 0, 1) * a                     # светлое — мягко светится
    glow = np.asarray(Image.fromarray((bright * 255).astype(np.uint8)).resize((W // 4, H // 4)).filter(ImageFilter.GaussianBlur(9)).resize((W, H))).astype(np.float32) / 255
    a = 1 - (1 - a) * (1 - glow * 0.2)                                # «экран» — слабо: сильнее белит картинку
    a = a * VIG
    img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    img = ImageEnhance.Contrast(img).enhance(1.05); img = ImageEnhance.Color(img).enhance(1.05)
    return img


n = 0
for k, b in enumerate(r):
    img = Image.frombytes("RGB", (W, H), b)
    if GRADE:
        img = grade(img)
    ov = overlay(k / 30)
    if ov is not None:
        img.paste(ov, (0, 1400), ov)
    enc.stdin.write(img.tobytes()); n += 1
enc.stdin.close(); enc.wait()
print(f"готово: {OUT} ({n} кадров, {n / 30:.1f} с)")
