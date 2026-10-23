# Сведение сценки «Крюк»: дубль из игры + голоса по своим местам (−14 LUFS) + субтитры как в роликах канала
# (Manrope 800, 56 px, y 1468, по 1–3 слова, звучащее слово — на жёлтой плашке).
# Время слов — по громкости реплики: начало и конец речи по звуку, слова распределены по длине.
# py -3.11 tools/dota_engine/hook_mix.py  [дубль=_game/engine_check/hook.mp4] [выход=_game/engine_check/hook_final.mp4]
import json, os, re, subprocess, sys
import numpy as np
import imageio_ffmpeg
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
TAKE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "_game", "engine_check", "hook.mp4")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(REPO, "_game", "engine_check", "hook_final.mp4")
VO = os.path.join(REPO, "_game", "hook")
FF = imageio_ffmpeg.get_ffmpeg_exe()
V = json.load(open(os.path.join(VO, "voices.json"), encoding="utf-8"))
src = open(os.path.join(HERE, "scene_hook.py"), encoding="utf-8").read()
OFFS = {k: float(v) for k, v in re.findall(r'"(\w+)":\s*([\d.]+)', re.search(r"VOICE = \{([^}]*)\}", src).group(1))}
DUR = float(re.search(r"^DUR = ([\d.]+)", src, re.M).group(1))

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
print("субтитры:", " | ".join(f"{c[0]:.2f}–{c[1]:.2f} {' '.join(c[2])}" for c in chunks))

# ---- картинки субтитров: каждое состояние (кусок, звучащее слово) — один раз через Chromium
from playwright.sync_api import sync_playwright
CSS = f"""
@font-face {{ font-family: Manrope; font-weight: 800; src: url(file:///{REPO.replace(os.sep, '/')}/fonts/manrope-cyrillic-800-normal.woff2) format("woff2"); }}
@font-face {{ font-family: Manrope; font-weight: 800; src: url(file:///{REPO.replace(os.sep, '/')}/fonts/manrope-latin-800-normal.woff2) format("woff2"); unicode-range: U+0000-00FF; }}
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
            pg.goto("file:///" + page.replace(os.sep, "/")); pg.evaluate("document.fonts.ready")
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
n = 0
for k, b in enumerate(r):
    img = Image.frombytes("RGB", (W, H), b)
    ov = overlay(k / 30)
    if ov is not None:
        img.paste(ov, (0, 1400), ov)
    enc.stdin.write(img.tobytes()); n += 1
enc.stdin.close(); enc.wait()
print(f"готово: {OUT} ({n} кадров, {n / 30:.1f} с)")
