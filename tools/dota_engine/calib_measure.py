# Где Пуджи на снимке калибровки: ищет в кадре розово-красные пятна (кожа и кровь) и печатает их середины
# в долях половины кадра. py -3.11 tools/dota_engine/calib_measure.py [снимок.tga]
import glob, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from paths import GAME

shot = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(GAME, "screenshots", "shot_*.tga")))[-1]
a = np.fromfile(shot, dtype=np.uint8, offset=18).reshape(1440, 1080, 4)[:, :, :3].astype(int)
b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]        # TGA: BGRA
m = (r > 90) & (r > g * 1.25) & (r > b * 1.25)      # кожа и кровь Пуджа
S = 4                                               # сетка грубее: быстрее искать пятна
mm = m[::S, ::S]
H, W = mm.shape
lab = np.zeros((H, W), int); cur = 0; blobs = []
for y0 in range(H):
    for x0 in range(W):
        if not mm[y0, x0] or lab[y0, x0]:
            continue
        cur += 1; st = [(y0, x0)]; lab[y0, x0] = cur; pts = []
        while st:
            y, x = st.pop(); pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    v, u = y + dy, x + dx
                    if 0 <= v < H and 0 <= u < W and mm[v, u] and not lab[v, u]:
                        lab[v, u] = cur; st.append((v, u))
        if len(pts) > 40:
            blobs.append(pts)
print(shot.split("/")[-1], "пятен:", len(blobs))
out = []
for p in sorted(blobs, key=lambda p: -len(p)):
    ys = [q[0] * S for q in p]; xs = [q[1] * S for q in p]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    out.append((cx, cy, min(xs), max(xs), min(ys), max(ys), len(p) * S * S))
for cx, cy, x0, x1, y0, y1, n in sorted(out, key=lambda v: v[0]):
    print(f"  x {(cx - 540) / 540:+.3f} y {(cy - 720) / 720:+.3f} "
          f"ширина {(x1 - x0) / 540:.3f} высота {(y1 - y0) / 720:.3f} пикселей {n}")
