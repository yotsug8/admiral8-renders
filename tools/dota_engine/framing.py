# Автокамера: планы задаются словами, угол и расстояние считаются сами.
#   fr = Framer(st, line=("pudge", "sniper"), side=+1)     # сторона от линии между героями (правило 180°)
#   cam = fr.cut([(0.0, fr.over("sniper", "pudge")), (3.8, fr.close("pudge")), (8.5, fr.close("sniper")),
#                 (11.2, fr.over("pudge", "sniper")), (13.1, fr.two("pudge", "sniper"))])
#   st.cam = cam                                            # камера сцены: план держится до следующей склейки, медленный наезд
# Планы:
#   close(кто)          крупно: глаза в верхней трети, голова и плечи (у низкорослых — по пояс)
#   over(кто, на_кого)  через плечо: «кто» на переднем плане сбоку, «на_кого» вдали ближе к центру
#   two(a, b)           двое по сторонам центра, по пояс
#   wide(*кто)          общий: все целиком
# Положения героев берутся в момент склейки (motion актёров). Подбор — по проекции камеры доты (project.Cam),
# луч к каждому герою проверяется на деревья и землю (stage.cam_blocked), камера — по нужную сторону от линии.
import math
import numpy as np
from project import Cam
from troupe import cast


def _nm(f, x0, step, iters=500):
    """Нелдер — Мид без внешних библиотек."""
    n = len(x0); pts = [np.array(x0, float)] + [np.array(x0, float) + np.eye(n)[i] * step[i] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        o = np.argsort(vals); pts = [pts[i] for i in o]; vals = [vals[i] for i in o]
        c = np.mean(pts[:-1], 0); r = c + (c - pts[-1]); fr = f(r)
        if fr < vals[0]:
            e = c + 2 * (c - pts[-1]); fe = f(e)
            pts[-1], vals[-1] = (e, fe) if fe < fr else (r, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = r, fr
        else:
            k = c + 0.5 * (pts[-1] - c); fk = f(k)
            if fk < vals[-1]:
                pts[-1], vals[-1] = k, fk
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]; vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = int(np.argmin(vals)); return pts[i], vals[i]


class Framer:
    def __init__(self, st, line=None, side=+1, push=0.07):
        self.st, self.side, self.push = st, side, push
        self.line = line                                   # два актёра: камера держится стороны side от линии между ними
        self.skip = set()                                  # служебные актёры (острие крюка) — к ним можно близко

    def _pos(self, name, t):
        p = self.st.keys(name, t)
        return np.array([p[0], p[1], p[2] + self.st.gz(p[0], p[1])])

    def _info(self, name):
        a = self.st.actors[name]
        hero = next((h[len("npc_dota_hero_"):] for h in self.st.heroes if a["model"] and h[len("npc_dota_hero_"):] in a["model"]), None)
        if hero:
            return cast(hero)[2]
        return dict(head_z=120, top=140)

    def _side_ok(self, cam_xy, t):
        if not self.line:
            return 0.0
        a, b = self._pos(self.line[0], t)[:2], self._pos(self.line[1], t)[:2]
        cross = (b[0] - a[0]) * (cam_xy[1] - a[1]) - (b[1] - a[1]) * (cam_xy[0] - a[0])
        return 0.0 if cross * self.side > 0 else 1.0

    def _solve(self, t, wants, pitch, zoff, look_from, D=250.0):
        """wants: [(мировая точка, x, y, вес)] — где в кадре должна оказаться точка. Подбираются положение камеры (x, y)
        и поворот; точка взгляда — на расстоянии D перед камерой (дальность сама по себе ничего не решает)."""
        ctr = np.mean([w[0][:2] for w in wants], 0)
        gz = self.st.gz

        def cam_of(v):
            cx, cy, yaw = v; f = (-math.sin(math.radians(yaw)), math.cos(math.radians(yaw)))
            tx, ty = cx + f[0] * D * math.cos(math.radians(pitch)), cy + f[1] * D * math.cos(math.radians(pitch))
            return Cam((tx, ty, gz(tx, ty) + zoff), D, pitch, yaw), (tx, ty)

        def cost(v):
            cm, _ = cam_of(v); c = 0.0
            for P, x, y, w in wants:
                if cm.view(*P)[0] < 40:
                    return 1e6
                sx, sy = cm.screen(*P)
                c += w * ((sx - x) ** 2 + (0 if y is None else (sy - y) ** 2))
            c += 5 * self._side_ok(cm.pos[:2], t)
            for n in self.st.actors:                     # не влезать в героя: ближе его габарита (руки, оружие) нельзя
                if n in self.skip:
                    continue
                q = self._pos(n, t); r = max(90.0, 0.75 * self._info(n)["top"])
                dd = math.hypot(cm.pos[0] - q[0], cm.pos[1] - q[1])
                if dd < r:
                    c += 4 * (1 - dd / r)
            if self.st.ground and self.st.cam_blocked(cm, aims=[tuple(P) for P, *_ in wants if P[2] - gz(P[0], P[1]) > 60]):   # луч к ступням всегда «у земли»
                c += 2
            return c
        best = None
        for dyaw in (0, -30, 30):
            yaw0 = math.degrees(math.atan2(-(ctr[0] - look_from[0]), ctr[1] - look_from[1])) + dyaw
            v, c = _nm(cost, [look_from[0], look_from[1], yaw0], [80, 80, 12])
            if best is None or c < best[1]:
                best = (v, c)
        v, c = best
        _, (tx, ty) = cam_of(v)
        return (float(tx), float(ty), float(zoff), float(D), float(pitch), float(v[2])), c

    def _either(self, make):
        """Решить план в двух зеркальных вариантах (кто слева) и взять точный."""
        a, b = make(+1), make(-1)
        return a if a[1] <= b[1] else b

    def _front(self, name, t, off_deg):
        """Точка «спереди-сбоку» героя, откуда смотреть: из двух сторон — та, что по нужную сторону от линии героев."""
        p = self._pos(name, t)
        for o in (off_deg, -off_deg):
            yaw = math.radians(self.st.keys(name, t)[4] + o)
            q = p[:2] + 400 * np.array([math.cos(yaw), math.sin(yaw)])
            if not self._side_ok(q, t):
                return q
        return q

    # ---- планы: каждый — функция t0 → камера (решается в момент склейки)
    def close(self, name, size=0.55):
        def shot(t0):
            i = self._info(name); P = self._pos(name, t0)
            eye = P + [0, 0, i["head_z"] + 8]; chest = P + [0, 0, i["head_z"] * (1 - size)]
            lf = self._front(name, t0, 35)
            return self._solve(t0, [(eye, 0.0, -0.33, 3), (chest, 0.0, 0.62, 1)], 2.0, i["head_z"], lf, 150)
        return shot

    def over(self, fg, bg):
        def shot(t0):
            fi, bi = self._info(fg), self._info(bg)
            F, B = self._pos(fg, t0), self._pos(bg, t0)
            back = F[:2] + (F[:2] - B[:2]) / (np.linalg.norm(F[:2] - B[:2]) + 1e-6) * 300
            def make(sg):
                wants = [(F + [0, 0, fi["head_z"] * 0.85], 0.55 * sg, 0.2, 2),            # плечо — сбоку, не на весь кадр
                         (B + [0, 0, bi["head_z"]], -0.12 * sg, -0.18, 3), (B, -0.12 * sg, 0.35, 1)]
                return self._solve(t0, wants, 5.0, fi["head_z"] * 0.75, back)
            return self._either(make)
        return shot

    def two(self, a, b):
        def shot(t0):
            ai, bi = self._info(a), self._info(b); A, B = self._pos(a, t0), self._pos(b, t0)
            mid = (A[:2] + B[:2]) / 2; d = B[:2] - A[:2]; n = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-6)
            lf = mid + n * 500 * self.side
            def make(sg):
                sa, sb = -0.36 * sg, 0.36 * sg
                wants = [(A + [0, 0, ai["head_z"]], sa, -0.25, 2), (B + [0, 0, bi["head_z"]], sb, -0.25, 2),
                         (A + [0, 0, ai["head_z"] * 0.3], sa, 0.75, 0.5), (B + [0, 0, bi["head_z"] * 0.3], sb, 0.75, 0.5)]
                return self._solve(t0, wants, 3.0, max(ai["head_z"], bi["head_z"]) * 0.8, lf)
            return self._either(make)
        return shot

    def wide(self, *names):
        def shot(t0):
            P = [self._pos(n, t0) for n in names]; I = [self._info(n) for n in names]
            ctr = np.mean([p[:2] for p in P], 0)
            if len(names) > 1:
                d = P[-1][:2] - P[0][:2]; n = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-6)
            else:
                n = np.array([0.0, -1.0])
            lf = ctr + n * 900 * self.side
            xs = np.linspace(-0.45, 0.45, len(names)) if len(names) > 1 else [0.0]
            wants = [(p + [0, 0, i["top"]], x, -0.1, 1) for p, i, x in zip(P, I, xs)] + [(p, x, 0.55, 1) for p, x in zip(P, xs)]
            return self._solve(t0, wants, 8.0, 90, lf, 500)
        return shot

    def cut(self, plan):
        """[(время склейки, план)] → cam(t): план держится до следующей склейки, медленный наезд (push)."""
        plan = sorted(plan, key=lambda x: x[0]); ends = [p[0] for p in plan[1:]] + [self.st.dur]
        shots = []
        for (t0, f), t1 in zip(plan, ends):
            c, err = f(t0)
            shots.append((t0, t1, c, err))
            print(f"  план {t0:5.2f}–{t1:5.2f} с: цель ({c[0]:.0f}, {c[1]:.0f}) поворот {c[5]:.0f} дальность {c[3]:.0f} ошибка {err:.3f}")

        def cam(t):
            for t0, t1, c, _ in shots:
                if t < t1 or (t1 == self.st.dur):
                    k = min(1.0, max(0.0, (t - t0) / max(t1 - t0, 1e-6))); k = k * k * (3 - 2 * k)
                    return (c[0], c[1], c[2], c[3] * (1 - self.push * k), c[4], c[5])
            return shots[-1][2]
        self.shots = shots
        return cam
