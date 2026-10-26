# Разбор образцов анимаций (примеры Дениса): что измеримо — длина ролика, склейки и длина планов, яркость,
# насыщенность, контраст, движение в кадре (камера и герои), — плюс лист кадров (кадр каждую секунду, отмечены склейки).
# py -3.11 tools/skit/study.py <папка или файлы mp4> [--out _game/study]
# Итог: _game/study/<имя>_sheet.jpg и _game/study/metrics.json; печатает таблицу и средние — это «эталон» для своих проб.
import glob, json, os, sys
import numpy as np
import imageio_ffmpeg
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))


def frames(path, w=180):
    """Кадры, уменьшенные до w×(w·16/9), и частота кадров ролика."""
    import subprocess, re
    FF = imageio_ffmpeg.get_ffmpeg_exe(); H = int(w * 16 / 9)
    info = subprocess.run([FF, "-i", path], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = re.search(r"([\d.]+) fps", info); fps = float(m.group(1)) if m else 30.0
    p = subprocess.Popen([FF, "-v", "error", "-i", path, "-vf", f"scale={w}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    sz = w * H * 3
    while True:
        b = p.stdout.read(sz)
        if len(b) < sz:
            break
        yield fps, np.frombuffer(b, np.uint8).reshape(H, w, 3)
    p.wait()


def study(path, out):
    name = os.path.splitext(os.path.basename(path))[0].split("-", 1)[-1][:40]
    prev_h = prev = None; cuts = [0.0]; motion = []; L = []; S = []; C = []; thumbs = []; fps = 30; n = 0
    for fps, f in frames(path):
        t = n / fps; n += 1
        g = f.astype(np.float32).mean(2)
        hist = np.histogram(f, bins=48, range=(0, 255))[0] / f.size
        if prev_h is not None:
            d = np.abs(hist - prev_h).sum()                       # склейка — резкая смена гистограммы и картинки
            m = np.abs(g - prev).mean()
            if d > 0.35 and m > 18 and t - cuts[-1] > 0.25:
                cuts.append(t)
            else:
                motion.append(m)
        prev_h, prev = hist, g
        mx = f.max(2).astype(float); mn = f.min(2).astype(float)
        L.append(g.mean()); S.append(((mx - mn) / np.maximum(mx, 1)).mean()); C.append(g.std())
        if abs(t - round(t)) < 0.5 / fps or (cuts[-1] == t and t > 0):
            thumbs.append((t, Image.fromarray(f), cuts[-1] == t and t > 0))
    dur = n / fps
    shots = np.diff(cuts + [dur])
    met = dict(name=name, dur=round(dur, 1), cuts=len(cuts) - 1, shot_mean=round(float(shots.mean()), 2),
               shot_min=round(float(shots.min()), 2), shot_max=round(float(shots.max()), 2),
               bright=round(float(np.mean(L)), 1), sat=round(float(np.mean(S)), 3), contrast=round(float(np.mean(C)), 1),
               motion=round(float(np.median(motion)) if motion else 0, 2), motion_p90=round(float(np.percentile(motion, 90)) if motion else 0, 2))
    cols = 10; rows = (len(thumbs) + cols - 1) // cols; tw, th = 180, 320
    sheet = Image.new("RGB", (cols * tw, rows * (th + 16)), (18, 18, 22)); d = ImageDraw.Draw(sheet)
    for i, (t, im, cut) in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * (th + 16)
        sheet.paste(im, (x, y + 16)); d.text((x + 4, y + 2), f"{t:.1f}" + (" СКЛЕЙКА" if cut else ""), fill=(255, 90, 90) if cut else (230, 220, 120))
    sheet.save(os.path.join(out, name + "_sheet.jpg"), quality=82)
    return met


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = os.path.join(REPO, "_game", "study"); os.makedirs(out, exist_ok=True)
    files = []
    for a in args:
        files += sorted(glob.glob(os.path.join(a, "*.mp4"))) if os.path.isdir(a) else [a]
    res = [study(f, out) for f in files]
    json.dump(res, open(os.path.join(out, "metrics.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    keys = ["dur", "cuts", "shot_mean", "shot_min", "shot_max", "bright", "sat", "contrast", "motion", "motion_p90"]
    print("образец".ljust(28) + "".join(k[:9].rjust(10) for k in keys))
    for m in res:
        print(m["name"][:27].ljust(28) + "".join(str(m[k]).rjust(10) for k in keys))
    if len(res) > 1:
        print("медиана".ljust(28) + "".join(str(round(float(np.median([m[k] for m in res])), 2)).rjust(10) for k in keys))


if __name__ == "__main__":
    main()
