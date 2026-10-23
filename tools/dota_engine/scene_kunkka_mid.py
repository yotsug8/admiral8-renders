# Пробная сцена площадки на суше: Кунка бежит по миду от первой вышки Света через реку к первой вышке
# Тьмы, камера ведёт сзади-сбоку; добежав, он останавливается, и под вражеской вышкой бьёт Торрент.
# py -3.11 tools/dota_engine/scene_kunkka_mid.py   (картинка композиции — qa/frame_map_kunkka_mid.jpg)
#
# Как ставится любая сцена: герой — hero="kunkka" (тело и части сами), точки пути — на карте (world=)
# или в кадре (anchors), z — от земли (карта земли из игры: ground_map.py --grab), скорость бега —
# из самой анимации (anims.py: шаг run ≈ 376 ед./с — с ней ноги не скользят).
# Камера — только над открытым местом: деревья у камеры убирать нельзя (от деревьев карты остаются
# пни, которые не спрятать), площадка это проверяет. Вышки — препятствия (обегать, камерой не задевать).
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage, path
from ground_map import Ground
from anims import Model

DUR = 7.5
A, B = (-1050.0, -875.5), (360.0, 415.0)           # мид: от вышки Света через реку к вышке Тьмы
TOWER = (524.0, 652.0)
RUN = Model("kunkka").stride("run")[0]              # ед./с — скорость шага анимации бега
run = path(None, RUN)
T_STOP = run.length([A, B]) / RUN                   # добегает к этому моменту
DIR = math.degrees(math.atan2(B[1] - A[1], B[0] - A[0]))   # куда бежит (≈ 42°)
CAM_YAW = DIR - 90 + 15                             # камера сзади и чуть справа: смотрит почти по ходу бега


def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def cam(t):
    x, y = run(t, [A, B])[:2]
    k = sm(T_STOP - 0.5, T_STOP + 1.2, t)            # после остановки — выше и шире: видно и его, и Торрент
    d = (B[0] - A[0]) / math.dist(A, B), (B[1] - A[1]) / math.dist(A, B)
    lead = 160 + 140 * k                             # смотрим вперёд него: ему есть куда бежать
    return (x + d[0] * lead, y + d[1] * lead, 0, 760 + 160 * k, 28 + 8 * k, CAM_YAW + 10 * k)


st = Stage(cam, DUR, ground=Ground(), trees=(-400, -300, 3400, 0))   # деревья везде, у камеры не убираются
st.actor("kunkka", None, run, [(0, "run"), (round(T_STOP, 2), "idle")], hero="kunkka",
         world=[A, B], box=(60, -10, 200))
st.fx(round(T_STOP + 0.4, 2), "particles/units/heroes/hero_kunkka/kunkka_spell_torrent_splash.vpcf", at=TOWER)

st.solve()
st.frame_map(os.path.join(HERE, "..", "..", "qa", "frame_map_kunkka_mid.jpg"))
st.write()
print(f"  бег {RUN:.0f} ед./с, добегает в {T_STOP:.2f} с")
