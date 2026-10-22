# Съёмочная площадка для движка доты: сцена задаётся по кадру, остальное считается и проверяется само.
#
#   st = Stage(cam, dur=11.5)                       # cam(t) -> (x, y, z, дальность, наклон, поворот)
#   st.actor("p1", [(-0.3, 0.6)], motion, anims)    # где в кадре (x вправо, y вниз; ±0.75 — края ролика)
#   st.solve(); st.write()                          # развести фигуры, проверить, записать scripts/a8_scene.txt
#
# motion(t, pts) получает мировые точки якорей и возвращает (x, y, z, наклон, поворот, крен) — так
# движение описывается «от якоря к якорю», а сами якоря решатель может сдвигать.
# Проверки по всей длине: все в воде (если задана карта воды), модели не касаются в мире, никто не
# обрезан краем кадра, фигуры не сливаются в одно пятно. Решатель понемногу раздвигает нарушителей.
import math, os
from project import Cam, overlap

OUT = r"D:\SteamLibrary\steamapps\common\dota 2 beta\game\dota_addons\admiral8\scripts\a8_scene.txt"
HERE = os.path.dirname(os.path.abspath(__file__))
MID = 80                                   # середина фигуры над её точкой
# Рамка стоящего Пуджа с крюком и тесаком (75, -25, 190): полуширина, низ, верх — сверено со снимками игры.


def water_map():
    """Расстояние до берега по карте реки (_game/water_dist.png): wet(x, y) в единицах игры."""
    import numpy as np
    from PIL import Image
    wd = np.asarray(Image.open(os.path.join(HERE, "..", "..", "_game", "water_dist.png"))).astype(float) / 6 * 10

    def wet(x, y):
        ix, iy = int((x + 3000) / 10), int((3000 - y) / 10)
        return wd[iy, ix] if 0 <= ix < wd.shape[1] and 0 <= iy < wd.shape[0] else 0
    return wet


class Stage:
    def __init__(self, cam, dur, kf=10, ref=None, wet=None, min_gap=185, min_wet=60,
                 safe_x=0.72, safe_y=0.96, max_over=0.35, under=-110, max_h=0.62):
        self.cam, self.dur, self.kf = cam, dur, kf
        self.ref = dur * 0.6 if ref is None else ref      # по какому моменту якоря переводятся в мир
        self.wet, self.min_gap, self.min_wet = wet, min_gap, min_wet
        self.safe_x, self.safe_y, self.max_over, self.under = safe_x, safe_y, max_over, under
        self.max_h = max_h                                 # самая крупная фигура: доля высоты кадра ×2
        self.actors = {}

    def cam_at(self, t):
        x, y, z, d, p, yw = self.cam(t)
        return Cam((x, y, z), d, p, yw)

    def actor(self, name, anchors, motion, anims, z=-45, box=(75, -25, 190)):
        """anchors — точки в кадре; z — высота, на которой стоит фигура (по ней якорь переводится в мир)."""
        self.actors[name] = dict(anchors=[list(a) for a in anchors], motion=motion, anims=anims, z=z, box=box)

    def pts(self, name):
        a = self.actors[name]; c = self.cam_at(self.ref)
        return [c.place(sx, sy, a["z"] + MID)[:2] + (a["z"],) for sx, sy in a["anchors"]]

    def keys(self, name, t, pts=None):
        return self.actors[name]["motion"](t, pts or self.pts(name))

    # ---- проверки ----
    def problems(self):
        n = int(self.dur * self.kf) + 1
        names = list(self.actors); P = {k: self.pts(k) for k in names}
        worst = {}                                         # (вид, кто) -> (насколько, время)

        def note(kind, who, v, t):
            if v > worst.get((kind, who), (0, 0))[0]:
                worst[(kind, who)] = (v, t)
        for i in range(n):
            t = i / self.kf; cm = self.cam_at(t)
            pos = {k: self.keys(k, t, P[k]) for k in names}
            vis = {k: pos[k][2] - self.actors[k]["z"] >= self.under for k in names}
            box = {k: cm.box(*pos[k][:3], *self.actors[k]["box"]) for k in names if vis[k]}
            for k in names:
                if self.wet and self.wet(*pos[k][:2]) < self.min_wet:
                    note("вода", (k,), self.min_wet - self.wet(*pos[k][:2]), t)
                if k in box:
                    b = box[k]
                    note("край", (k,), max(-self.safe_x - b[0], b[2] - self.safe_x,
                                           -self.safe_y - b[1], b[3] - self.safe_y), t)
                    note("крупно", (k,), (b[3] - b[1]) - self.max_h, t)
            for x in range(len(names)):
                for y in range(x + 1, len(names)):
                    a, b = names[x], names[y]
                    note("касание", (a, b), self.min_gap - math.dist(pos[a][:2], pos[b][:2]), t)
                    if a in box and b in box:
                        note("пятно", (a, b), overlap(box[a], box[b]) - self.max_over, t)
        return {k: v for k, v in worst.items() if v[0] > 0}

    def _center(self, name, t):
        p = self.keys(name, t)
        return self.cam_at(t).screen(p[0], p[1], p[2] + MID)

    def _shift(self, name, dx, dy):
        for a in self.actors[name]["anchors"]:
            a[0] += dx; a[1] += dy

    def solve(self, step=0.015, rounds=900):
        """Раздвигает якоря, пока все проверки не пройдут. Печатает, кого и насколько сдвинул."""
        start = {k: [tuple(a) for a in v["anchors"]] for k, v in self.actors.items()}
        for r in range(rounds):
            bad = self.problems()
            if not bad:
                break
            step = max(step * 0.996, 0.003)                # шаг мельчает: иначе решатель качается между запретами
            for (kind, who), (v, t) in bad.items():
                if kind in ("касание", "пятно"):
                    a, b = who
                    ca, cb = self._center(a, t), self._center(b, t)
                    dx, dy = ca[0] - cb[0], ca[1] - cb[1]
                    L = math.hypot(dx, dy) or 1.0
                    if L < 1e-6:
                        dx, dy, L = 1.0, 0.0, 1.0
                    self._shift(a, step * dx / L, step * dy / L)
                    self._shift(b, -step * dx / L, -step * dy / L)
                elif kind == "край":                       # внутрь кадра с той стороны, где вылезает
                    k = who[0]; a = self.actors[k]; pp = self.keys(k, t)
                    b = self.cam_at(t).box(*pp[:3], *a["box"])
                    self._shift(k, -step * (b[2] > self.safe_x) + step * (b[0] < -self.safe_x),
                                -step * (b[3] > self.safe_y) + step * (b[1] < -self.safe_y))
                elif kind == "крупно":                     # слишком близко к камере — дальше, то есть выше в кадре
                    self._shift(who[0], 0, -step)
                elif kind == "вода":                       # к камере: вода в кадре лежит внизу
                    self._shift(who[0], 0, step)
        else:
            raise SystemExit("площадка: не удалось развести фигуры — " +
                             "; ".join(f"{k} {'/'.join(w)} {v:.2f} в {t:.1f} с" for (k, w), (v, t) in bad.items()))
        moved = []
        for k, v in self.actors.items():
            d = max(math.dist(a, b) for a, b in zip(start[k], v["anchors"]))
            if d > 0.005:
                moved.append(f"{k} на {d:.2f}")
        print(f"  площадка: проверки пройдены за {r} шагов" + (", сдвинуты: " + ", ".join(moved) if moved else ""))
        for k, v in self.actors.items():
            print(f"    {k}: " + "  ".join(f"({a[0]:+.2f}, {a[1]:+.2f})" for a in v["anchors"]))

    # ---- запись ----
    def write(self, out=OUT):
        n = int(self.dur * self.kf) + 1
        seen = {}
        for k, a in self.actors.items():
            for _, sq in a["anims"]:
                assert sq not in seen, f"анимация {sq} повторяется у {k} и {seen[sq]}"
                seen[sq] = k
        scene = {"duration": self.dur, "actors": {}, "camera": {}}
        for name in self.actors:
            P = self.pts(name); keys = {}; prev = None
            for i in range(n):
                x, y, z, pi, ya, ro = self.keys(name, i / self.kf, P)
                if prev is not None:                       # без скачков угла через ±180
                    while ya - prev > 180: ya -= 360
                    while ya - prev < -180: ya += 360
                prev = ya
                keys[str(i)] = f"{x:.1f} {y:.1f} {z:.1f} {pi:.1f} {ya:.1f} {ro:.1f}"
            scene["actors"][name] = {"keys": keys, "anims": {str(i): f"{t} {s}" for i, (t, s) in enumerate(self.actors[name]["anims"])}}
        scene["camera"] = {str(i): "%.1f %.1f %.1f %.1f %.1f %.1f" % self.cam(i / self.kf) for i in range(n)}
        scene["kf"] = self.kf
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w", encoding="utf-8").write(_kv("Scene", scene))
        print("  сцена записана:", out, "актёров", len(self.actors), "ключей", n)

    def frame_map(self, out, cols=6, rows=2):
        """Картинка композиции по расчёту: рамки фигур в кадре в разные секунды."""
        from PIL import Image, ImageDraw
        from project import EDGE
        W, H = 180, 240; m = cols * rows
        img = Image.new("RGB", (W * cols, H * rows + 16), (24, 26, 30)); d = ImageDraw.Draw(img)
        for i in range(m):
            t = i * self.dur / (m - 1); ox, oy = (i % cols) * W, (i // cols) * H + 16
            d.rectangle([ox + W / 2 - EDGE * W / 2, oy + 2, ox + W / 2 + EDGE * W / 2, oy + H - 2], outline=(200, 180, 60))
            cm = self.cam_at(t)
            for k, a in self.actors.items():
                p = self.keys(k, t)
                if p[2] - a["z"] < self.under:
                    continue
                b = cm.box(*p[:3], *a["box"])
                X = lambda v: ox + W / 2 + v * W / 2; Y = lambda v: oy + H / 2 + v * H / 2
                d.rectangle([X(b[0]), Y(b[1]), X(b[2]), Y(b[3])], outline=(120, 220, 140))
                d.text((X(b[0]) + 2, Y(b[1]) + 2), k, fill=(230, 230, 230))
            d.text((ox + 6, oy - 14), f"{t:.1f} c", fill=(255, 220, 90))
        img.save(out, quality=92)
        print("  карта кадра:", out)


def _kv(name, d, ind=0):
    s = "\t" * ind
    if isinstance(d, dict):
        return f'{s}"{name}"\n{s}{{\n' + "".join(_kv(k, v, ind + 1) for k, v in d.items()) + f"{s}}}\n"
    return f'{s}"{name}"\t"{d}"\n'
