# Сцена 006 «Пуджи на водопое» для движка доты → scripts/a8_scene.txt в моде admiral8.
# py -3.11 tools/dota_engine/scene_006.py   (картинка композиции — qa/frame_map_006.jpg)
#
# Фигуры ставятся по кадру (x вправо, y вниз; ±0.75 — края ролика), площадка (stage.py) сама
# переводит это в точки карты, раздвигает тех, кто касается или сливается, и проверяет всю длину.
# Вода в этом кадре лежит ниже y ≈ -0,2: выше — дальний берег с деревьями.
# У низа кадра в ширину помещается всего ~300 ед. мира — там место для одного крупного Пуджа,
# остальных ставить глубже. Камера у земли, поэтому её проворот сильно сносит ближних — он маленький.
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage, water_map

DUR = 11.5
C = (1516.0, -1660.0)                      # середина широкой воды у нижней руны
YAW_CAM = 270.0                            # лицом к камере (модель с yaw 270 смотрит на юг)
CAM_PITCH = float(os.environ.get("CAM_PITCH", 19))   # ниже — больше неба (его подставляет sky_comp.py)
WAIST = -45                                # по пояс: река в доте по щиколотку
SWIM_Z = float(os.environ.get("SWIM_Z", 0))   # лёжа: тело у поверхности, иначе его закрывает дно
FLOAT_Z = float(os.environ.get("FLOAT_Z", 5))


def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def lerp(a, b, k):
    return a + (b - a) * k


# камера: смотрит в воду перед группой, плавный наезд и лёгкий проворот
def cam(t):
    k = sm(0, DUR, t)
    return (C[0] - 10, C[1] + lerp(250, 270, k), 0, lerp(1000, 940, k), CAM_PITCH, lerp(-2, 2, k))


def still(yaw_off):
    return lambda t, p: (p[0][0], p[0][1], WAIST, 0, YAW_CAM + yaw_off, 0)


# пловец: кролем вниз по течению к камере, у камеры переворачивается на спину
def swim(t, p):
    k = sm(-0.5, 7.0, t)
    z = SWIM_Z + 6 * math.sin(t * 2 * math.pi / 0.77) + 25 * math.sin(math.pi * sm(6.6, 7.6, t))
    return (lerp(p[0][0], p[1][0], k), lerp(p[0][1], p[1][1], k), z,
            74 - 148 * sm(6.6, 7.6, t), YAW_CAM + 4 * math.sin(t * 2 * math.pi / 1.53), 0)


# лежебока: на спине дрейфует, садится и празднует
def floater(t, p):
    k = sm(0, 6, t); s = sm(6.0, 6.8, t)
    return (lerp(p[0][0], p[1][0], k), lerp(p[0][1], p[1][1], k), lerp(FLOAT_Z, WAIST, s) + 4 * math.sin(t * 2.1),
            lerp(-68, 0, s), YAW_CAM - 10 + 6 * math.sin(t * 0.9), 0)


# поплавок: ныряет вперёд с головой, выстреливает из воды и плюхается
def bobber(t, p):
    dive = sm(2.9, 3.8, t) * (1 - sm(5.4, 5.8, t))
    jump = sm(5.7, 6.1, t) * (1 - sm(6.1, 6.7, t) ** 1.6)
    return (p[0][0], p[0][1], WAIST - 150 * dive + 120 * jump, 80 * dive, YAW_CAM - 15, 0)


# синхронистка: три оборота с разгоном, потом шатается
def spinner(t, p):
    turns = 3 * sm(1.3, 4.3, t); wob = sm(4.3, 5.0, t) * (1 - sm(8.3, 9.6, t))
    return (p[0][0], p[0][1], WAIST + 8 * math.sin(math.pi * sm(1.3, 4.3, t)), 7 * wob * math.sin(t * 6.9),
            YAW_CAM + 25 + 360 * turns + 25 * wob * math.sin(t * 5.4), 0)


st = Stage(cam, DUR, ref=DUR, wet=water_map())   # якоря — по последнему, самому тесному кадру
LYING = (100, -20, 90)                      # рамка лежащего: шире и ниже стоящего
# у каждого свои анимации: ни одна не повторяется у двух Пуджей; разовые — ровно на свою длину (иначе замирают)
st.actor("swim",  [(0.02, -0.18), (0.22, 0.10)], swim, [(0, "a8_swim"), (6.8, "a8_backfloat")], z=SWIM_Z, box=LYING)
st.actor("float", [(-0.40, -0.14), (-0.44, -0.10)], floater, [(0, "pudge_stun"), (6.0, "ftp_dendi_victory")], z=FLOAT_Z, box=LYING)
st.actor("bob",   [(0.42, -0.10)], bobber,
         [(0, "pudge_idle_alt"), (2.9, "pudge_ti7_immortal_idle"), (5.6, "ti7_hh_flail"), (7.6, "hh_idle")])
st.actor("spin",  [(-0.48, 0.12)], spinner,
         [(0, "trapper_victory_animation"), (4.3, "pudge_ti7_immortal_stun"), (8.8, "hh_victory")])
st.actor("p1",    [(-0.30, 0.40)], still(15), [(0, "pudge_idle"), (1.0, "pudge_taunt_money_maker"), (7.93, "victory")])
st.actor("p2",    [(0.42, 0.26)], still(-30), [(0, "ftp_dendi_idle_stomp"), (2.07, "ftp_dendi_idle_look"), (9.07, "pudge_flail")])

st.solve()
st.frame_map(os.path.join(HERE, "..", "..", "qa", "frame_map_006.jpg"))
st.write()
