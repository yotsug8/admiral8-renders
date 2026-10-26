# Карта земли для площадки: высота и проходимость по всей карте доты.
# Выгружается из игры командой мода a8_map (шаг 64): py -3.11 ground_map.py --grab  (дота должна быть запущена)
# Потом в сценах: g = Ground(); g.h(x, y) — высота земли, g.code(x, y) — 0 проходимо, 1 скала/здание, 2 дерево.
import os, re, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "_game", "data", "ground.npz")
BUILD = os.path.join(HERE, "..", "..", "_game", "data", "buildings.txt")   # здания карты (a8_where), класс x y z
# сколько места занимает здание вокруг своей точки (ед.): сквозь них путь не проложить
RADIUS = {"npc_dota_tower": 150, "npc_dota_barracks": 220, "npc_dota_fort": 380, "npc_dota_filler": 110,
          "ent_dota_shop": 150, "ent_dota_fountain": 450, "npc_dota_watch_tower": 110, "npc_dota_roshan_spawner": 0}
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from paths import GAME                              # папка игры — tools/paths.py
LOG = os.path.join(GAME, "console.log")


def grab(step=64, rad=8192):
    """Попросить мод выгрузить карту в лог и разобрать её в _game/data/ground.npz."""
    import subprocess
    start = os.path.getsize(LOG)
    subprocess.run([sys.executable, os.path.join(HERE, "dota_console.py"), f"a8_map {step} {rad}"], check=True)
    for _ in range(120):
        time.sleep(1)
        txt = open(LOG, "rb").read()[start:].decode("utf-8", "replace")   # срез по байтам, не по буквам
        if "[a8m] done" in txt:
            break
    else:
        sys.exit("a8_map не ответил за 2 минуты")
    H, N, ys = [], [], []
    for line in txt.splitlines():
        m = re.search(r"\[a8m\] (-?\d+) (.+)", line)
        if m and not line.strip().endswith("done") and "done" not in m.group(2):
            ys.append(int(m.group(1))); H.append([int(v) for v in m.group(2).split()])
        m = re.search(r"\[a8n\] (-?\d+) ([012]+)", line)
        if m:
            N.append([int(c) for c in m.group(2)])
    H, N = np.array(H, np.int16), np.array(N, np.int8)
    assert H.shape == N.shape and H.shape[0] == len(range(rad, -rad - 1, -step)), (H.shape, N.shape)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez_compressed(OUT, h=H, n=N, step=step, rad=rad)
    # здания: точки из a8_where
    start = os.path.getsize(LOG)
    subprocess.run([sys.executable, os.path.join(HERE, "dota_console.py"), "a8_where"], check=True)
    time.sleep(2)
    t = open(LOG, "rb").read()[start:].decode("utf-8", "replace")
    rows = re.findall(r"\[a8w\] (\S+) Vector \S+ \[(\S+) (\S+) (\S+)\]", t)
    open(BUILD, "w").write("\n".join(" ".join(r) for r in rows))
    print(f"зданий: {len(rows)} → {BUILD}")
    print(f"карта земли: {H.shape}, высоты {H.min()}…{H.max()}, занято {np.mean(N == 1):.0%}, деревья {np.mean(N == 2):.0%} → {OUT}")


class Ground:
    """Строка 0 — y = +rad (север), столбец 0 — x = −rad."""

    def __init__(self, path=OUT):
        if not os.path.exists(path):
            raise SystemExit("нет _game/data/ground.npz — выгрузить из игры: py -3.11 ground_map.py --grab")
        d = np.load(path)
        self.H, self.N, self.S, self.R = d["h"].astype(float), d["n"], int(d["step"]), int(d["rad"])
        self.build = []                                     # (класс, x, y, радиус)
        if os.path.exists(BUILD):
            for line in open(BUILD):
                c, x, y, _z = line.split()
                if RADIUS.get(c, 0) > 0:
                    self.build.append((c, float(x), float(y), RADIUS[c]))

    def _ij(self, x, y):
        return (self.R - y) / self.S, (x + self.R) / self.S

    def h(self, x, y):
        """Высота земли (билинейно)."""
        i, j = self._ij(x, y)
        i0, j0 = int(np.clip(np.floor(i), 0, self.H.shape[0] - 2)), int(np.clip(np.floor(j), 0, self.H.shape[1] - 2))
        a, b = i - i0, j - j0
        H = self.H
        return float((1 - a) * ((1 - b) * H[i0, j0] + b * H[i0, j0 + 1]) + a * ((1 - b) * H[i0 + 1, j0] + b * H[i0 + 1, j0 + 1]))

    def code(self, x, y):
        i, j = self._ij(x, y)
        i, j = int(round(i)), int(round(j))
        if not (0 <= i < self.N.shape[0] and 0 <= j < self.N.shape[1]):
            return 1
        return int(self.N[i, j])

    def building(self, x, y, r=40):
        """Здание, в которое попадает фигура радиуса r в точке (x, y), или None."""
        for c, bx, by, br in self.build:
            if (x - bx) ** 2 + (y - by) ** 2 < (br + r) ** 2:
                return c, bx, by
        return None

    def blocked(self, x, y, r=40):
        """Занята ли точка или её окрестность r (скала, дерево — по сетке игры; здания — по их точкам)."""
        if self.building(x, y, r):
            return 1
        return max(self.code(x + dx, y + dy) for dx in (-r, 0, r) for dy in (-r, 0, r))

    def free_dir(self, x, y, r=40, reach=400):
        """Куда ближе всего свободно: единичный вектор от (x, y) или None."""
        for d in range(32, reach, 32):
            for k in range(16):
                a = k * np.pi / 8
                if not self.blocked(x + d * np.cos(a), y + d * np.sin(a), r):
                    return np.cos(a), np.sin(a)
        return None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--grab" in sys.argv:
        grab()
    else:
        g = Ground(); x, y = float(sys.argv[1]), float(sys.argv[2])
        print(f"({x:.0f}, {y:.0f}): высота {g.h(x, y):.0f}, клетка {g.code(x, y)}")
