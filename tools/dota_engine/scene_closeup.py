# Проба «как в кино»: крупные планы на уровне глаз и склейки (восьмёрка), портретные анимации героев.
#   0–2,5 с  общий план сбоку: Пудж и Снайпер стоят друг напротив друга
#   2,5–5 с  крупно Пудж через плечо Снайпера
#   5–7 с    ответный план: Снайпер через плечо Пуджа
# Поляна на светлой стороне, за героями лес. Камера: z — высота точки взгляда над землёй.
# Крупные планы режут фигуры краем намеренно — решатель площадки здесь не нужен, сцена пишется как есть.
# py -3.11 tools/dota_engine/scene_closeup.py
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage
from ground_map import Ground

DUR = 7.0
PUDGE, SNIPER = (-3900.0, -3250.0), (-3700.0, -3250.0)
MIDP = ((PUDGE[0] + SNIPER[0]) / 2, PUDGE[1])


def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def lerp(a, b, k):
    return a + (b - a) * k


def cam(t):
    if t < 2.5:                                    # общий план сбоку (с юга, смотрим на север, на лес), лёгкий наезд
        k = sm(0, 2.5, t)
        return (MIDP[0], MIDP[1], 105, lerp(560, 520, k), 7, 0)
    if t < 5.0:                                    # крупно Пудж через плечо Снайпера (смотрим на запад)
        k = sm(2.5, 5.0, t)
        return (PUDGE[0] + 20, PUDGE[1] - 25, 150, lerp(360, 335, k), 5, 90 - 12)
    k = sm(5.0, 7.0, t)                            # ответный: Снайпер через плечо Пуджа — с той же (южной) стороны, что и
    return (SNIPER[0] - 15, SNIPER[1], 95, lerp(350, 325, k), 4, 300)   # второй план, сбоку от Пуджа, иначе он закрывает Снайпера


st = Stage(cam, DUR, kf=30, ground=Ground(), trees=(-3800, -3200, 2200, 0))   # деревья карты — кино-версии (иначе пни)
st.actor("pudge", None, lambda t, p: (PUDGE[0], PUDGE[1], 0, 0, 0, 0), [(0, "portrait")], hero="pudge", world=[PUDGE])
st.actor("sniper", None, lambda t, p: (SNIPER[0], SNIPER[1], 0, 0, 180, 0), [(0, "sniper_portrait")], hero="sniper", world=[SNIPER])
# деревья в 200 ед. за спиной камеры общего плана в кадр не попадают — проверку камеры здесь не делаем
st.write()
