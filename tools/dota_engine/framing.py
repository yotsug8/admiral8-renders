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
        return dict(head_z=120, top=140, radius=60)

    def _side_ok(self, cam_xy, t):
        if not self.line:
            return 0.0
        a, b = self._pos(self.line[0], t)[:2], self._pos(self.line[1], t)[:2]
        cross = (b[0] - a[0]) * (cam_xy[1] - a[1]) - (b[1] - a[1]) * (cam_xy[0] - a[0])
        return 0.0 if cross * self.side > 0 else 1.0

    def _solve(self, t, wants, pitch, zoff, look_from, D=250.0, widths=()):
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
            for P, r, mx in widths:                       # ширина героя в кадре (с одеждой: плащ, наплечники, крюк)
                fwd = cm.view(*P)[0]
                hw = r / max(fwd, 1.0) / cm.tx
                if hw > mx:
                    c += 6 * (hw - mx) ** 2 + 0.6 * (hw - mx)
            for n in self.st.actors:                     # не влезать в героя: ближе его габарита (руки, оружие) нельзя
                if n in self.skip:
                    continue
                q = self._pos(n, t); r = 1.6 * self._info(n).get("radius", 80) + 40   # ширина героя (руки, горб) + запас
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

    # ---- планы — операторские шаблоны: камера считается формулами (свободный подбор уводил её в траву и вдаль)
    def _aim(self, C, L, t, aims):
        """Камера в точке C (мир) смотрит в точку L → (цель x, y, высота взгляда над землёй, дальность, наклон, поворот)."""
        gz = self.st.gz
        C = np.array(C, float); C[2] = max(C[2], gz(C[0], C[1]) + 70)          # не ниже травы
        L = np.array(L, float)
        h0 = math.hypot(L[0] - C[0], L[1] - C[1])
        C[2] = max(C[2], L[2] + h0 * math.tan(math.radians(1.5)))   # вверх дота смотреть не даёт (берёт свой наклон — вид сверху)
        dirv = (L - C) / (np.linalg.norm(L - C) + 1e-6)
        L = C + dirv * 250                                 # точка взгляда на том же луче в 250 ед.: большая дальность у доты ломает вид
        d = L - C; h = math.hypot(d[0], d[1])
        yaw = math.degrees(math.atan2(-d[0], d[1])); pitch = math.degrees(math.atan2(-d[2], h))
        cam = (float(L[0]), float(L[1]), float(L[2] - gz(L[0], L[1])), float(math.hypot(h, d[2])), float(pitch), float(yaw))
        cm = Cam((L[0], L[1], L[2]), cam[3], pitch, yaw)
        bad = (self.st.cam_blocked(cm, aims=[tuple(a) for a in aims]) if self.st.ground else None) or (self._side_ok(C[:2], t) and "не та сторона")
        if self.st.ground and (self.st.ground.blocked(C[0], C[1], 80) or gz(C[0], C[1]) > C[2] - 40):
            bad = bad or "камера в скале, здании или под землёй"
        return cam, bad or None

    def _best(self, variants):
        """Из вариантов (камера, помеха): без помех; иначе — хотя бы не в стене и без деревьев (пусть с другой стороны
        от линии героев); иначе первый. Помеха печатается."""
        for c, bad in variants:
            if not bad:
                return c, 0.0
        for c, bad in variants:
            if bad == "не та сторона":
                return c, 0.5
        print("    все варианты с помехой:", variants[0][1])
        return variants[0][0], 1.0

    @staticmethod
    def _rot(v, deg):
        a = math.radians(deg); return np.array([v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)])

    def close(self, name, size=0.55):
        """Крупно: перед героем под углом 35° (с нужной стороны), на уровне глаз; глаза — в верхней трети."""
        def shot(t0):
            i = self._info(name); P = self._pos(name, t0); yaw = math.radians(self.st.keys(name, t0)[4])
            face = np.array([math.cos(yaw), math.sin(yaw)])
            eye = P + [0, 0, i["head_z"] + 8]
            span = i["head_z"] * size + 8                         # от груди до глаз
            d = span / ((0.33 + 0.62) * 0.653)                    # глаза на −0.33, грудь на +0.62 доли полукадра
            d = max(d, 1.6 * i.get("radius", 60) + 30)
            L = eye + [0, 0, -0.14 * d * 0.653 * 2 / 2]           # смотрим чуть ниже глаз: глаза уходят в верхнюю треть
            vs = []
            for ang in (35, -35, 50, -50, 20, -20):
                dirv = self._rot(face, ang)
                C = np.array([P[0] + dirv[0] * d, P[1] + dirv[1] * d, eye[2]])
                vs.append(self._aim(C, L, t0, [eye]))
            return self._best(vs)
        return shot

    def over(self, fg, bg):
        """Через плечо: за передним на продолжении линии от дальнего, сдвиг вбок на ширину переднего; смотрим на дальнего."""
        def shot(t0):
            fi, bi = self._info(fg), self._info(bg); F, B = self._pos(fg, t0), self._pos(bg, t0)
            u = (F[:2] - B[:2]) / (np.linalg.norm(F[:2] - B[:2]) + 1e-6); n = np.array([-u[1], u[0]])
            r = 1.8 * fi.get("radius", 60)
            L = B + [0, 0, bi["head_z"] * 0.75]
            vs = []
            for up in (0.95, 1.4, 1.9):                 # выше — если позади переднего ступени или склон
                for sg in (1, -1):
                    for back, side in ((2.6, 1.15), (2.0, 1.0), (1.5, 0.9), (1.2, 0.8), (1.0, 0.7), (0.6, 0.5), (0.45, 0.45), (3.2, 1.3)):
                        x, y = F[0] + u[0] * r * back + n[0] * r * side * sg, F[1] + u[1] * r * back + n[1] * r * side * sg
                        C = np.array([x, y, max(F[2], self.st.gz(x, y)) + fi["head_z"] * up])
                        vs.append(self._aim(C, L, t0, [L]))
            c, err = self._best(vs)
            if err >= 1.0:                                   # за передним некуда встать (скалы, деревья) — общий план двоих
                print(f"    через плечо {fg} не встать — план «двое»")
                return self.two(fg, bg)(t0)
            return c, err
        return shot

    def two(self, a, b):
        """Двое: на перпендикуляре к середине между героями; оба с одеждой помещаются в 70 % ширины кадра."""
        def shot(t0):
            ai, bi = self._info(a), self._info(b); A, B = self._pos(a, t0), self._pos(b, t0)
            mid = (A + B) / 2; u = (B[:2] - A[:2]) / (np.linalg.norm(B[:2] - A[:2]) + 1e-6); n = np.array([-u[1], u[0]])
            half = np.linalg.norm(B[:2] - A[:2]) / 2 + 1.6 * max(ai.get("radius", 60), bi.get("radius", 60))
            tx = 0.653 * 1080 / 1440
            d = half / (0.70 * tx)
            hz = max(ai["head_z"], bi["head_z"])
            L = mid + [0, 0, hz * 0.6]
            vs = []
            for sg in (self.side, -self.side):
                for ang in (0, 15, -15):
                    nn = self._rot(n * sg, ang)
                    C = np.array([mid[0] + nn[0] * d, mid[1] + nn[1] * d, mid[2] + hz * 0.85])
                    vs.append(self._aim(C, L, t0, [A + [0, 0, ai["head_z"]], B + [0, 0, bi["head_z"]]]))
            return self._best(vs)
        return shot

    def wide(self, *names):
        """Общий: все целиком, сбоку от линии героев, чуть сверху."""
        def shot(t0):
            P = [self._pos(n, t0) for n in names]; I = [self._info(n) for n in names]
            ctr = np.mean(P, 0)
            if len(names) > 1:
                d = P[-1][:2] - P[0][:2]; u = d / (np.linalg.norm(d) + 1e-6); n = np.array([-u[1], u[0]])
                half = np.linalg.norm(d) / 2 + 2 * max(i.get("radius", 60) for i in I)
            else:
                n = np.array([0.0, -1.0]); half = 2.5 * I[0].get("radius", 60)
            tx = 0.653 * 1080 / 1440
            dist = max(half / (0.6 * tx), max(i["top"] for i in I) * 1.6 / (2 * 0.653 * 0.6))
            top = max(i["top"] for i in I)
            L = ctr + [0, 0, top * 0.45]
            vs = []
            for sg in (self.side, -self.side):
                for ang in (0, 20, -20):
                    nn = self._rot(n * sg, ang)
                    C = np.array([ctr[0] + nn[0] * dist, ctr[1] + nn[1] * dist, ctr[2] + top * 1.1])
                    vs.append(self._aim(C, L, t0, [p + [0, 0, i["head_z"]] for p, i in zip(P, I)]))
            return self._best(vs)
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
