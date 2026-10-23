# Съёмочная площадка для движка доты: сцена задаётся по кадру, остальное считается и проверяется само.
#
#   st = Stage(cam, dur=11.5)                       # cam(t) -> (x, y, z, дальность, наклон, поворот)
#   st.actor("p1", [(-0.3, 0.6)], motion, anims)    # где в кадре (x вправо, y вниз; ±0.75 — края ролика)
#   st.solve(); st.write()                          # развести фигуры, проверить, записать scripts/a8_scene.txt
#
# motion(t, pts) получает мировые точки якорей и возвращает (x, y, z, наклон, поворот, крен) — так
# движение описывается «от якоря к якорю», а сами якоря решатель может сдвигать.
# Проверки по всей длине: все в воде (если задана карта воды), на суше — не в скале, здании или дереве
# (если задана карта земли), модели не касаются в мире, никто не обрезан краем кадра, фигуры не
# сливаются в одно пятно, луч камеры к каждой фигуре не задевает деревья и землю. Решатель понемногу раздвигает нарушителей.
#
# Любой герой или модель: st.actor(..., hero="kunkka") или model="models/..vmdl", parts=[...].
# Земля: Stage(..., ground=Ground()) — z актёров считается от земли (в игре — GetGroundHeight), без неё
# z абсолютный (так стоят Пуджи 006 в реке). Точки можно задавать и на карте: world=[(x, y), ...].
# Движение по пути: path(точки, скорость) — положение, поворот по ходу; скорость бега — anims.stride.
# Частицы: st.fx(t, "particles/...vpcf", at=(x, y) или at="актёр", z=0, dur=0).
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
    AIR = 120                                  # выше этого над своей высотой фигура в полёте

    def __init__(self, cam, dur, kf=10, ref=None, wet=None, min_gap=185, min_wet=60,
                 safe_x=0.72, safe_y=0.96, max_over=0.35, under=-110, max_h=0.62, ground=None, trees=None):
        self.cam, self.dur, self.kf = cam, dur, kf
        self.ground = ground                               # карта земли (ground_map.Ground) или None
        self.trees = trees                                 # (cx, cy, r, clear) — где ставить деревья
        self.fxs, self.heroes = [], []
        self.ref = dur * 0.6 if ref is None else ref      # по какому моменту якоря переводятся в мир
        self.wet, self.min_gap, self.min_wet = wet, min_gap, min_wet
        self.safe_x, self.safe_y, self.max_over, self.under = safe_x, safe_y, max_over, under
        self.max_h = max_h                                 # самая крупная фигура: доля высоты кадра ×2
        self.actors = {}

    def cam_at(self, t):
        x, y, z, d, p, yw = self.cam(t)
        if self.ground:                                    # высоту точки, куда смотрит камера, дота берёт с земли
            z = self.gz(x, y)
        return Cam((x, y, z), d, p, yw)

    def cam_blocked(self, cm, tree_r=150, aims=()):
        """Что мешает камере: земля или дерево на луче к актёрам (aims — их точки) или деревья у самой
        камеры (None — всё чисто)."""
        if not self.ground:
            return None
        P = cm.pos
        for A in aims:
            for k in range(1, 19):
                q = [P[i] + (A[i] - P[i]) * k / 20 for i in range(3)]
                if self.gz(q[0], q[1]) > q[2] - 40:
                    return f"земля на луче камеры ({q[0]:.0f}, {q[1]:.0f})"
                # деревья: убирать их у камеры нельзя — от деревьев карты остаются пни, которые не спрятать
                if q[2] - self.gz(q[0], q[1]) < 520 and self.ground.blocked(q[0], q[1], tree_r) == 2:
                    return f"дерево на луче камеры ({q[0]:.0f}, {q[1]:.0f})"
                if q[2] - self.gz(q[0], q[1]) < 450 and self.ground.building(q[0], q[1], 60):
                    return f"{self.ground.building(q[0], q[1], 60)[0]} на луче камеры ({q[0]:.0f}, {q[1]:.0f})"
        if self.ground.blocked(P[0], P[1], tree_r + 60) == 2:
            return f"камера в деревьях ({P[0]:.0f}, {P[1]:.0f})"
        return None

    def actor(self, name, anchors, motion, anims, z=None, box=(75, -25, 190),
              hero=None, model=None, parts=None, world=None):
        """anchors — точки в кадре (или world — точки карты, их решатель не двигает);
        z — высота фигуры: от земли, если у площадки есть карта земли (по умолчанию 0), иначе абсолютная (−45).
        hero — герой игры (тело и стандартные части сами); model/parts — любая модель.
        anims — [(время, анимация) или (время, анимация, скорость проигрывания)]."""
        if z is None:
            z = 0 if self.ground else -45
        if hero:
            from hero_parts import hero_model
            if model is None:
                model, parts = hero_model(hero)
            self.heroes.append("npc_dota_hero_" + hero)
        self.actors[name] = dict(anchors=[list(a) for a in (anchors or [])], motion=motion, anims=anims, z=z, box=box,
                                 model=model, parts=parts, world=[tuple(w) for w in world] if world else None)

    def fx(self, t, name, at=(0, 0), z=0, dur=0):
        """Частица в момент t: at — точка карты (x, y) или имя актёра (или (имя, dx, dy)); z — от земли."""
        if isinstance(at, str):
            at = (at, 0, 0)
        self.fxs.append((t, name, at, z, dur))

    def gz(self, x, y):
        """Высота земли под точкой (0 без карты земли — z актёров тогда абсолютный)."""
        return self.ground.h(x, y) if self.ground else 0.0

    def pts(self, name):
        a = self.actors[name]
        if a["world"]:
            return [(x, y, a["z"]) for x, y in a["world"]]
        c = self.cam_at(self.ref); out = []
        for sx, sy in a["anchors"]:
            g = 0.0
            for _ in range(4):                             # высота зависит от места, место — от высоты
                x, y, _z = c.place(sx, sy, g + a["z"] + MID)
                g = self.gz(x, y)
            out.append((x, y, a["z"]))
        return out

    def keys(self, name, t, pts=None):
        return self.actors[name]["motion"](t, pts or self.pts(name))

    # ---- проверки ----
    def problems(self):
        ck = min(self.kf, 10)                              # проверки — 10 раз в секунду, ключи пишутся с kf
        n = int(self.dur * ck) + 1
        names = list(self.actors); P = {k: self.pts(k) for k in names}
        worst = {}                                         # (вид, кто) -> (насколько, время)

        def note(kind, who, v, t):
            if v > worst.get((kind, who), (0, 0))[0]:
                worst[(kind, who)] = (v, t)
        for i in range(n):
            t = i / ck; cm = self.cam_at(t)
            pos = {k: self.keys(k, t, P[k]) for k in names}
            vis = {k: pos[k][2] - self.actors[k]["z"] >= self.under for k in names}
            box = {k: cm.box(pos[k][0], pos[k][1], pos[k][2] + self.gz(*pos[k][:2]), *self.actors[k]["box"])
                   for k in names if vis[k]}
            if self.cam_blocked(cm):                        # сама камера в деревьях — менять её путь
                note("камера", ("камера",), 1.0, t)
            else:
                for k in names:                            # дерево или земля на луче к фигуре — её сдвинуть
                    if vis[k] and self.cam_blocked(cm, aims=[(pos[k][0], pos[k][1], pos[k][2] + self.gz(*pos[k][:2]) + MID)]):
                        note("луч", (k,), 1.0, t)
            air = {k: pos[k][2] - self.actors[k]["z"] > self.AIR for k in names}   # в полёте
            for k in names:
                if self.wet and not air[k] and self.wet(*pos[k][:2]) < self.min_wet:
                    note("вода", (k,), self.min_wet - self.wet(*pos[k][:2]), t)
                if self.ground and self.ground.blocked(*pos[k][:2]):
                    note("занято", (k,), 1.0, t)
                if k in box:
                    b = box[k]
                    note("край", (k,), max(-self.safe_x - b[0], b[2] - self.safe_x,
                                           -self.safe_y - b[1], b[3] - self.safe_y), t)
                    note("крупно", (k,), (b[3] - b[1]) - self.max_h, t)
            for x in range(len(names)):
                for y in range(x + 1, len(names)):
                    a, b = names[x], names[y]
                    note("касание", (a, b), self.min_gap - math.dist(pos[a][:3], pos[b][:3]), t)   # с высотой: летящий не касается стоящих
                    if a in box and b in box and not air[a] and not air[b]:   # пролёт перед кем-то — движение, не слипание
                        ha, hb = box[a][3] - box[a][1], box[b][3] - box[b][1]
                        if max(ha, hb) < 2 * min(ha, hb):          # передний план вдвое крупнее заднего — не пятно
                            note("пятно", (a, b), overlap(box[a], box[b]) - self.max_over, t)
        return {k: v for k, v in worst.items() if v[0] > 0}

    def _center(self, name, t):
        p = self.keys(name, t)
        return self.cam_at(t).screen(p[0], p[1], p[2] + self.gz(p[0], p[1]) + MID)

    def _shift(self, name, dx, dy):
        if self.actors[name]["world"]:                     # точки карты заданы жёстко — не двигаем
            return
        c = self.cam_at(self.ref)                          # не выше горизонта (с запасом): иначе точка улетает в бесконечность
        top = -c.f[2] / math.hypot(c.f[0], c.f[1]) / c.ty + 0.12
        for a in self.actors[name]["anchors"]:
            a[0] += dx; a[1] = max(a[1] + dy, top)

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
                    b = self.cam_at(t).box(pp[0], pp[1], pp[2] + self.gz(pp[0], pp[1]), *a["box"])
                    self._shift(k, -step * (b[2] > self.safe_x) + step * (b[0] < -self.safe_x),
                                -step * (b[3] > self.safe_y) + step * (b[1] < -self.safe_y))
                elif kind == "крупно":                     # слишком близко к камере — дальше, то есть выше в кадре
                    self._shift(who[0], 0, -step)
                elif kind == "луч":                        # к середине кадра и ближе: там луч идёт над открытым местом
                    k = who[0]; c = self._center(k, t)
                    self._shift(k, -step * (1 if c[0] > 0 else -1), step * 0.5)
                elif kind == "вода":                       # к камере: вода в кадре лежит внизу
                    self._shift(who[0], 0, step)
                elif kind == "занято":                     # к ближайшему свободному месту, в долях кадра
                    k = who[0]; pp = self.keys(k, t); d = self.ground.free_dir(pp[0], pp[1])
                    if d is None or self.actors[k]["world"]:
                        raise SystemExit(f"площадка: {k} в {t:.1f} с стоит в скале/дереве ({pp[0]:.0f}, {pp[1]:.0f})")
                    cm = self.cam_at(t); z0 = pp[2] + self.gz(pp[0], pp[1]) + MID
                    a0 = cm.screen(pp[0], pp[1], z0); a1 = cm.screen(pp[0] + 30 * d[0], pp[1] + 30 * d[1], z0)
                    L = math.hypot(a1[0] - a0[0], a1[1] - a0[1]) or 1.0
                    self._shift(k, step * (a1[0] - a0[0]) / L, step * (a1[1] - a0[1]) / L)
            if any(kind == "камера" for kind, _ in bad):
                (_, _), (_, t) = next((k, v) for k, v in bad.items() if k[0] == "камера")
                P = {k: self.keys(k, t) for k in self.actors}
                aims = [(p[0], p[1], p[2] + self.gz(p[0], p[1]) + MID) for p in P.values()]
                raise SystemExit(f"площадка: камере мешает {self.cam_blocked(self.cam_at(t), aims=aims)} в {t:.1f} с — поменять её путь")
        else:
            raise SystemExit("площадка: не удалось развести фигуры — " +
                             "; ".join(f"{k} {'/'.join(w)} {v:.2f} в {t:.1f} с" for (k, w), (v, t) in bad.items()))
        moved = []
        for k, v in self.actors.items():
            d = max((math.dist(a, b) for a, b in zip(start[k], v["anchors"])), default=0)
            if d > 0.005:
                moved.append(f"{k} на {d:.2f}")
        print(f"  площадка: проверки пройдены за {r} шагов" + (", сдвинуты: " + ", ".join(moved) if moved else ""))
        for k, v in self.actors.items():
            print(f"    {k}: " + "  ".join(f"({a[0]:+.2f}, {a[1]:+.2f})" for a in v["anchors"]))

    # ---- запись ----
    def write(self, out=OUT):
        n = int(self.dur * self.kf) + 1
        seen = {}                                          # у одинаковых моделей анимации не повторяются
        for k, a in self.actors.items():
            for _, sq, *_r in a["anims"]:
                key = (a["model"], sq)
                assert seen.get(key, k) == k, f"анимация {sq} повторяется у {k} и {seen[key]}"
                seen[key] = k
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
            a = self.actors[name]
            act = {"keys": keys, "anims": {str(i): " ".join(str(v) for v in an) for i, an in enumerate(a["anims"])}}
            if a["model"]:
                act["model"] = a["model"]
                act["parts"] = {str(i + 1): p for i, p in enumerate(a["parts"] or [])}
            if self.ground:
                act["ground"] = 1
            scene["actors"][name] = act
        scene["camera"] = {str(i): "%.1f %.1f %.1f %.1f %.1f %.1f" % self.cam(i / self.kf) for i in range(n)}
        scene["kf"] = self.kf
        if self.fxs:
            fx = {}
            for i, (t, nm, at, z, dur) in enumerate(self.fxs):
                if isinstance(at[0], str):
                    fx[str(i + 1)] = f"{t} {nm} {at[1]} {at[2]} {z} {dur} {at[0]}"
                else:
                    fx[str(i + 1)] = f"{t} {nm} {at[0]:.1f} {at[1]:.1f} {z} {dur}"
            scene["fx"] = fx
        if self.heroes:
            scene["heroes"] = {str(i + 1): h for i, h in enumerate(dict.fromkeys(self.heroes))}
        if self.trees:
            scene["trees"] = " ".join(str(v) for v in self.trees)
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
                b = cm.box(p[0], p[1], p[2] + self.gz(p[0], p[1]), *a["box"])
                X = lambda v: ox + W / 2 + v * W / 2; Y = lambda v: oy + H / 2 + v * H / 2
                d.rectangle([X(b[0]), Y(b[1]), X(b[2]), Y(b[3])], outline=(120, 220, 140))
                d.text((X(b[0]) + 2, Y(b[1]) + 2), k, fill=(230, 230, 230))
            d.text((ox + 6, oy - 14), f"{t:.1f} c", fill=(255, 220, 90))
        img.save(out, quality=92)
        print("  карта кадра:", out)


def path(points, speed, start=0.0, turn=0.25, yaw_off=0.0, z=0.0):
    """Движение по точкам с постоянной скоростью (ед./с): motion(t, pts) для st.actor.
    points — индексы якорей актёра (по умолчанию все) или None; углы сглажены (дуга радиусом ~turn·отрезка),
    поворот — по ходу движения (yaw доты: 0 — восток, 90 — север, 270 — на юг, к камере с поворотом 0).
    До start стоит в первой точке, в конце пути — останавливается."""
    def curve(P):
        # сглаживание углов: каждую внутреннюю точку заменяем дугой Безье между точками на отрезках
        pts = [P[0]]
        for i in range(1, len(P) - 1):
            a, b, c = P[i - 1], P[i], P[i + 1]
            u = (b[0] + (a[0] - b[0]) * turn, b[1] + (a[1] - b[1]) * turn)
            v = (b[0] + (c[0] - b[0]) * turn, b[1] + (c[1] - b[1]) * turn)
            for k in range(9):
                s = k / 8
                pts.append(((1 - s) ** 2 * u[0] + 2 * s * (1 - s) * b[0] + s * s * v[0],
                            (1 - s) ** 2 * u[1] + 2 * s * (1 - s) * b[1] + s * s * v[1]))
        pts.append(P[-1])
        L = [0.0]
        for i in range(1, len(pts)):
            L.append(L[-1] + math.dist(pts[i - 1], pts[i]))
        return pts, L

    cache = {}

    def at(s, pts, L):
        s = max(0.0, min(s, L[-1]))
        i = max(1, next((j for j in range(1, len(L)) if L[j] >= s), len(L) - 1))
        k = (s - L[i - 1]) / ((L[i] - L[i - 1]) or 1)
        a, b = pts[i - 1], pts[i]
        return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k

    def motion(t, p):
        P = [q[:2] for q in (p if points is None else [p[i] for i in points])]
        key = tuple(P)
        if key not in cache:
            cache.clear(); cache[key] = curve(P)
        pts, L = cache[key]
        s = speed * max(0.0, t - start)
        x, y = at(s, pts, L)
        a, b = at(s - 15, pts, L), at(s + 15, pts, L)            # направление — по соседним точкам пути
        if s >= L[-1]:
            a, b = at(L[-1] - 30, pts, L), at(L[-1], pts, L)
        if s <= 0:
            a, b = at(0, pts, L), at(30, pts, L)
        yaw = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) + yaw_off
        return (x, y, z, 0.0, yaw, 0.0)

    motion.length = lambda p: curve([q[:2] for q in (p if points is None else [p[i] for i in points])])[1][-1]
    return motion


def _kv(name, d, ind=0):
    s = "\t" * ind
    if isinstance(d, dict):
        return f'{s}"{name}"\n{s}{{\n' + "".join(_kv(k, v, ind + 1) for k, v in d.items()) + f"{s}}}\n"
    return f'{s}"{name}"\t"{d}"\n'
