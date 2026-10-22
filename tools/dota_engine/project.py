# Проекция камеры доты: мир → кадр. Нужна, чтобы до записи проверять композицию —
# не выходит ли кто за кадр и не слипаются ли фигуры. Угол обзора подобран калибровкой (calib.py).
import math

FOV_Y = 66.3                 # вертикальный угол обзора окна 1080×1440 (горизонтальный 52,2°).
                             # Подобран по снимку калибровки (calib.py, 6 Пуджей в известных точках):
                             # сходится на всех шести до 1,3 %. Высота точки, куда смотрит камера,
                             # игрой берётся с земли — в сцене это уровень воды, z = 0.
GAME_W, GAME_H = 1080, 1440  # что рисует игра
CROP_W = 810                 # ролик — центральные 810 px, значит |x| ≤ 0.75
EDGE = CROP_W / GAME_W


class Cam:
    """Камера доты: точка, на которую смотрит, дальность, наклон вниз и поворот (0 — на север)."""

    def __init__(self, target, dist, pitch, yaw=0.0):
        p, y = math.radians(pitch), math.radians(yaw)
        fh = (-math.sin(y), math.cos(y))                                   # куда смотрит по горизонтали
        self.f = (fh[0] * math.cos(p), fh[1] * math.cos(p), -math.sin(p))  # вперёд
        self.r = (math.cos(y), math.sin(y), 0.0)                           # вправо в кадре
        self.u = (fh[0] * math.sin(p), fh[1] * math.sin(p), math.cos(p))   # вверх в кадре
        self.pos = tuple(target[i] - dist * self.f[i] for i in range(3))
        self.ty = math.tan(math.radians(FOV_Y) / 2)
        self.tx = self.ty * GAME_W / GAME_H

    def view(self, x, y, z):
        d = (x - self.pos[0], y - self.pos[1], z - self.pos[2])
        dot = lambda v: d[0] * v[0] + d[1] * v[1] + d[2] * v[2]
        return dot(self.f), dot(self.r), dot(self.u)

    def screen(self, x, y, z):
        """Доли половины кадра: x ±1 — края кадра игры (±0.75 — края ролика), y ±1 — верх и низ."""
        fwd, right, up = self.view(x, y, z)
        fwd = max(fwd, 1.0)
        return right / fwd / self.tx, -up / fwd / self.ty

    def box(self, x, y, z, half_w=55.0, low=-10.0, high=150.0):
        """Рамка фигуры в кадре: (x0, y0, x1, y1)."""
        cx, _ = self.screen(x, y, z)
        fwd = max(self.view(x, y, z)[0], 1.0)
        w = half_w / fwd / self.tx
        _, y_top = self.screen(x, y, z + high)
        _, y_bot = self.screen(x, y, z + low)
        return (cx - w, y_top, cx + w, y_bot)


    def place(self, sx, sy, z):
        """Обратно: мировая точка на высоте z, которая попадёт в кадр в (sx, sy).
        Так сцену ставят по кадру — «этого сюда», а не подбором координат карты."""
        d = [self.f[i] + self.r[i] * (sx * self.tx) + self.u[i] * (-sy * self.ty) for i in range(3)]
        k = (z - self.pos[2]) / d[2]
        return (self.pos[0] + d[0] * k, self.pos[1] + d[1] * k, z)


def overlap(a, b):
    """Какая доля меньшей фигуры перекрыта другой (0 — не касаются)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / small if small > 0 else 1.0
