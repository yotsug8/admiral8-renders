# Сцена 006 «Пуджи на водопое» для движка доты → scripts/a8_scene.txt в моде admiral8.
# py -3.11 tools/dota_engine/scene_006.py
# Координаты — единицы игры. Ключи по 10 в секунду; углы Source: pitch (вперёд +), yaw, roll.
import math, os
OUT = r"D:\SteamLibrary\steamapps\common\dota 2 beta\game\dota_addons\admiral8\scripts\a8_scene.txt"
DUR, KF = 11.5, 10
C = (1516.0, -1660.0)                      # середина широкой воды у нижней руны
D = (0.0, 1.0)                             # камера смотрит на север (поворот камеры 0), «вдаль» = +y
P = (1.0, 0.0)                             # вправо в кадре
YAW_UP = 0.0                               # поворот камеры (GameUI)
YAW_CAM = 270.0                            # лицом к камере (модель с yaw 270 смотрит на юг)
WAIST = -45                                # по пояс: река в доте по щиколотку
SWIM_Z = float(os.environ.get("SWIM_Z", 0))   # лёжа: тело у поверхности, иначе его закрывает дно
FLOAT_Z = float(os.environ.get("FLOAT_Z", 5))

def at(al, lat, dz=WAIST): return (C[0] + D[0] * al + P[0] * lat, C[1] + D[1] * al + P[1] * lat, dz)
def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)
def lerp(a, b, k): return a + (b - a) * k

def actor_static(al, lat, yaw_off, anims):
    x, y, z = at(al, lat)
    return dict(keys=lambda t: (x, y, z, 0, YAW_CAM + yaw_off, 0), anims=anims)

# пловец: кролем вниз по течению к камере, у камеры переворачивается на спину
def swim(t):
    al = lerp(560, 200, sm(-0.5, 7.0, t))
    x, y, _ = at(al, 215)
    roll = 180 * sm(6.6, 7.6, t)
    pitch = 74 - 148 * sm(6.6, 7.6, t)
    z = SWIM_Z + 6 * math.sin(t * 2 * math.pi / 0.77) + 25 * math.sin(math.pi * sm(6.6, 7.6, t))
    return (x, y, z, pitch, YAW_CAM + 4 * math.sin(t * 2 * math.pi / 1.53), roll * 0)
# лежебока: на спине дрейфует, садится и празднует
def floater(t):
    al = lerp(620, 585, sm(0, 6, t)); x, y, _ = at(al, -150)
    s = sm(6.0, 6.8, t)
    pitch = lerp(-68, 0, s); z = lerp(FLOAT_Z, WAIST, s) + 4 * math.sin(t * 2.1)
    return (x, y, z, pitch, YAW_CAM - 10 + 6 * math.sin(t * 0.9), 0)
# поплавок: ныряет вперёд с головой, выстреливает из воды и плюхается
def bobber(t):
    x, y, _ = at(360, 10)
    dive = sm(2.9, 3.8, t) * (1 - sm(5.4, 5.8, t))
    jump = sm(5.7, 6.1, t) * (1 - sm(6.1, 6.7, t) ** 1.6)
    z = WAIST - 150 * dive + 120 * jump
    return (x, y, z, 80 * dive, YAW_CAM - 15, 0)
# синхронистка: три оборота с разгоном, потом шатается
def spinner(t):
    x, y, _ = at(205, -150)
    turns = 3 * sm(1.3, 4.3, t); wob = sm(4.3, 5.0, t) * (1 - sm(8.3, 9.6, t))
    return (x, y, WAIST + 8 * math.sin(math.pi * sm(1.3, 4.3, t)), 7 * wob * math.sin(t * 6.9),
            YAW_CAM + 25 + 360 * turns + 25 * wob * math.sin(t * 5.4), 0)

ACTORS = {
    "swim":   dict(keys=swim,   anims=[(0, "a8_swim"), (6.8, "a8_backfloat")]),
    "float":  dict(keys=floater, anims=[(0, "a8_backfloat"), (6.0, "pudge_idle"), (6.9, "victory")]),
    "bob":    dict(keys=bobber, anims=[(0, "pudge_idle_alt"), (5.6, "pudge_flail"), (7.2, "pudge_idle")]),
    "spin":   dict(keys=spinner, anims=[(0, "victory"), (4.3, "pudge_stun"), (8.8, "pudge_idle")]),
    "p1":     actor_static(-30, -175, 15, [(0, "pudge_idle"), (2.0, "ftp_dendi_idle_look"), (7.6, "victory")]),
    "p2":     actor_static(30, 20, -30, [(0, "ftp_dendi_idle_stomp"), (4.0, "pudge_rot"), (8.4, "pudge_flail")]),
}
# камера: ниже по течению, медленный наезд
def cam(t):
    x, y, _ = at(lerp(230, 260, sm(0, DUR, t)), 0)
    return (x, y, 0, lerp(1000, 880, sm(0, DUR, t)), 30, YAW_UP)

def kv(name, d, ind=0):
    s = "\t" * ind
    if isinstance(d, dict):
        out = f'{s}"{name}"\n{s}{{\n' + "".join(kv(k, v, ind + 1) for k, v in d.items()) + f"{s}}}\n"
        return out
    return f'{s}"{name}"\t"{d}"\n'

scene = {"duration": DUR, "actors": {}, "camera": {}}
n = int(DUR * KF) + 1
for name, a in ACTORS.items():
    keys = {}; prev = None
    for i in range(n):
        t = i / KF; x, y, z, pi, ya, ro = a["keys"](t)
        if prev is not None:          # без скачков угла через ±180
            while ya - prev > 180: ya -= 360
            while ya - prev < -180: ya += 360
        prev = ya
        keys[str(i)] = f"{x:.1f} {y:.1f} {z:.1f} {pi:.1f} {ya:.1f} {ro:.1f}"
    scene["actors"][name] = {"keys": keys, "anims": {str(i): f"{t} {s}" for i, (t, s) in enumerate(a["anims"])}}
scene["camera"] = {str(i): "%.1f %.1f %.1f %.1f %.1f %.1f" % cam(i / KF) for i in range(n)}
scene["kf"] = KF
import numpy as np
from PIL import Image
WD = np.asarray(Image.open(os.path.join(os.path.dirname(__file__), "..", "..", "_game", "water_dist.png"))).astype(float) / 6 * 10
def wet(x, y):
    ix, iy = int((x + 3000) / 10), int((3000 - y) / 10)
    return WD[iy, ix] if 0 <= ix < WD.shape[1] and 0 <= iy < WD.shape[0] else 0
for name, a in ACTORS.items():
    worst = min(wet(*a["keys"](i / KF)[:2]) for i in range(n))
    print(f"  {name}: до берега не меньше {worst:.0f} ед.")
    assert worst >= 60, name + " выходит из воды"
# Пуджи не касаются: центры не ближе MIN_GAP за весь ролик (крюк и тесак в размахе ~ 90 ед. от тела)
MIN_GAP = 185
names = list(ACTORS)
for i in range(n):
    t = i / KF; pos = {k: ACTORS[k]["keys"](t)[:2] for k in names}
    for a_ in range(len(names)):
        for b_ in range(a_ + 1, len(names)):
            d_ = math.dist(pos[names[a_]], pos[names[b_]])
            assert d_ >= MIN_GAP, f"{names[a_]} и {names[b_]} сближаются до {d_:.0f} в {t:.1f} с"
print("  касаний нет: все пары не ближе", MIN_GAP)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write(kv("Scene", scene))
print("сцена:", OUT, "актёров", len(ACTORS), "ключей", n, "камера yaw", round(YAW_UP, 1))
