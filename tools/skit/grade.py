# Цветокоррекция по образцу: картинка подгоняется под примеры участник (_game/study/examples) по цифрам в Lab —
# кривая яркости (процентили), сила цвета в тенях, полутонах и светах, теплота полутонов. Одна кривая на весь ролик
# (без мигания): строится по кадрам ролика, применяется к каждому кадру.
#   py -3.11 tools/skit/grade.py target                     цель из примеров → _game/study/grade_target.json
#   py -3.11 tools/skit/grade.py <видео> <выход.mp4>        прогнать ролик (для проверки; в сведении — GRADE=match в mix.py)
import glob, json, math, os, subprocess, sys
import numpy as np
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
TARGET = os.path.join(REPO, "_game", "study", "grade_target.json")
FF = imageio_ffmpeg.get_ffmpeg_exe()
PCT = [1, 5, 15, 25, 40, 50, 60, 75, 85, 95, 99]
M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
W3 = np.array([0.9505, 1.0, 1.089])


def to_lab(rgb):
    x = rgb / 255.0; x = np.where(x > 0.04045, ((x + 0.055) / 1.055) ** 2.4, x / 12.92)
    xyz = x @ M.T / W3
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def to_rgb(lab):
    fy = (lab[..., 0] + 16) / 116; fx = fy + lab[..., 1] / 500; fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f > 0.2069, f ** 3, (f - 16 / 116) / 7.787) * W3
    x = xyz @ np.linalg.inv(M).T
    x = np.where(x > 0.0031308, 1.055 * np.clip(x, 0, None) ** (1 / 2.4) - 0.055, 12.92 * x)
    return np.clip(x * 255, 0, 255).astype(np.uint8)


def sample(path, w=270, h=480, fps=2):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def measure(frames):
    L = to_lab(frames.astype(np.float32)); l = L[..., 0]; C = np.hypot(L[..., 1], L[..., 2])
    band = lambda a, b: (l >= a) & (l < b)
    return {"L": np.percentile(l, PCT).tolist(),
            "C": [float(C[band(*r)].mean()) if band(*r).any() else 0.0 for r in ((0, 30), (30, 70), (70, 101))],
            "b_mid": float(L[..., 2][band(30, 70)].mean())}


def target():
    """Цель — медиана по всем цветным примерам (у каждого свой свет, медиана — «как они в среднем»)."""
    ms = [measure(sample(p)) for p in sorted(glob.glob(os.path.join(REPO, "_game", "study", "examples", "*.mp4")))]
    ms = [m for m in ms if m["L"][5] > 35 and m["C"][1] > 15]       # дневные цветные (сцены дневные); молочность была не от них,
                                                                     # а от низкого контраста и поднятых теней — теперь контраст свой
    t = {"L": np.median([m["L"] for m in ms], 0).tolist(), "C": np.median([m["C"] for m in ms], 0).tolist(),
         "b_mid": float(np.median([m["b_mid"] for m in ms])), "n": len(ms)}
    json.dump(t, open(TARGET, "w"), indent=1)
    return t


class Grade:
    """Кривая яркости и усиление цвета под цель; strength — доля (1 — точно под примеры)."""
    def __init__(self, src_frames, strength=0.4, color=1.0, warm_hue=-4.0, contrast=0.8):
        # strength — яркость (0,85 — пересвет, участник: «засвечено сильно»); color — цвет отдельно (кожа героев в текстурах
        # доты блёклая, игровой шейдер её досыщает); warm_hue — тёплые оттенки к красному (кожа была бежевой: 44° против 40°)
        t = json.load(open(TARGET)) if os.path.exists(TARGET) else target()
        s = measure(src_frames)
        xs = np.array([0.0] + s["L"] + [100.0]); ys = np.array([0.0] + t["L"] + [100.0])
        ys = xs + (ys - xs) * strength
        hi = xs > 70; ys[hi] = np.minimum(ys[hi], xs[hi])                # света не поднимать — блики не выбеливать
        ys[xs < 40] = np.minimum(ys[xs < 40], xs[xs < 40] * 1.05)       # тени не поднимать: тёмные места дают глубину (примеры 6 против 18)
        xs, idx = np.unique(xs, return_index=True); ys = np.maximum.accumulate(ys[idx])   # монотонно
        self.lut = np.interp(np.arange(0, 100.25, 0.25), xs, ys)
        # контраст под примеры (у них 24 против наших 16 — картинка молочная): растяжение вокруг середины кадра
        sd_t = 23.6; sd_s = float(np.std(to_lab(src_frames.astype(np.float32))[..., 0])) or sd_t
        kc_ = min(1.45, max(1.0, 1 + (sd_t / sd_s - 1) * contrast)); mid = float(np.interp(s["L"][5], xs, ys))
        self.lut = np.clip(mid + (self.lut - mid) * kc_, 0, 100); self.kcon = kc_
        k = [min(2.2, max(1.0, 1 + (tc / max(sc, 1) - 1) * color)) for tc, sc in zip(t["C"], s["C"])]   # цвет не убавлять — тускло
        self.hue = math.radians(warm_hue)
        self.kc = k                                                     # усиление цвета: тени, полутона, света
        self.db = (t["b_mid"] - s["b_mid"]) * color * 0.3            # теплота — вполовину (у примеров свет разный)
        self.info = f"тени/полутона/света: цвет ×{k[0]:.2f} ×{k[1]:.2f} ×{k[2]:.2f}, теплее на {self.db:.1f}; " \
                    f"яркость {s['L'][3]:.0f}→{np.interp(s['L'][3], xs, ys):.0f} (25%), {s['L'][5]:.0f}→{np.interp(s['L'][5], xs, ys):.0f} (50%), контраст ×{self.kcon:.2f}"

    def __call__(self, rgb):
        lab = to_lab(rgb.astype(np.float32)); l = lab[..., 0]
        lab[..., 0] = self.lut[np.clip((l * 4).astype(int), 0, len(self.lut) - 1)]
        w_sh = np.clip((40 - l) / 20, 0, 1); w_hi = np.clip((l - 60) / 20, 0, 1); w_mid = 1 - w_sh - w_hi
        k = (self.kc[0] * w_sh + self.kc[1] * w_mid + self.kc[2] * w_hi)[..., None]
        lab[..., 1:] *= k
        if self.hue:                                                    # тёплые (10–75°) поворачиваются к красному
            h = np.arctan2(lab[..., 2], lab[..., 1]); w = np.clip(1 - np.abs(np.degrees(h) - 42) / 33, 0, 1) * self.hue
            a_, b_ = lab[..., 1].copy(), lab[..., 2].copy()
            lab[..., 1] = a_ * np.cos(w) - b_ * np.sin(w); lab[..., 2] = a_ * np.sin(w) + b_ * np.cos(w)
        C = np.hypot(lab[..., 1], lab[..., 2]); top = 62.0              # мягкий потолок: серое поднимается, а уже яркое
        lab[..., 1:] *= (top * np.tanh(C / top) / np.maximum(C, 1e-3))[..., None]   # (кровь, фартук) не кислотное
        lab[..., 2] += self.db * w_mid
        return to_rgb(lab)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["target"]:
        print(target()); return
    src, out = sys.argv[1:3]
    g = Grade(sample(src)); print(g.info)
    info = subprocess.run([FF, "-i", src], capture_output=True, text=True, errors="replace").stderr
    import re
    w, h = map(int, re.search(r", (\d{3,5})x(\d{3,5})", info).groups())
    dec = subprocess.Popen([FF, "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([FF, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
                            "-i", src, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "15", "-pix_fmt", "yuv420p", "-c:a", "copy", out],
                           stdin=subprocess.PIPE)
    while True:
        b = dec.stdout.read(w * h * 3)
        if len(b) < w * h * 3:
            break
        enc.stdin.write(g(np.frombuffer(b, np.uint8).reshape(h, w, 3)).tobytes())
    enc.stdin.close(); enc.wait()
    print("готово:", out)


if __name__ == "__main__":
    main()
