# «Забег»: ноги проигрывают хвосту. Верхняя линия Тьмы, одна непрерывная камера впереди героев.
#   0–4,4 с   старт: Кунка разминается всерьёз (своя a8_warmup), Нага спокойно оглядывается, позади Акс кричит «давай!»
#   4,4 с     бегут рядом с настоящими базовыми скоростями: Нага 330, Кунка 315 (scripts/npc/heroes игры);
#             скорость проигрывания бега = скорость / шаг анимации — ноги и хвост не скользят
#   ~10,5 с   Нага первой на финише, останавливается и поворачивается к Кунке
#   ~10,1 с   Кунка добегает, поворачивается к ней: согнулся, руки на коленях, задыхается (a8_tired)
#   13,2 с    смотрит на её хвост, потом на свои ноги (a8_look); стоят друг к другу боком к камере — наклон читается
# Свои анимации Кунки — tools/blender/kunkka_race.py → anim_to_dmx.py → models/a8/kunkka/kunkka_a8.vmdl.
# py -3.11 tools/dota_engine/scene_race.py   (CHECK=1 — только проверки; картинка композиции — qa/frame_map_race.jpg)
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage, path
from ground_map import Ground
from anims import Model
from hero_parts import hero_model

DUR = 17.0
T_GO = 4.4                                 # старт
# верхняя линия Тьмы: прямая на восток, ровная (высота 128), без деревьев на ±150; камере по оси свободно до s ≈ 2800
O, HEAD = (528.0, 5776.0), math.radians(0)
AXIS = [O, (O[0] + 3000 * math.cos(HEAD), O[1] + 3000 * math.sin(HEAD))]
S0, S1 = 300.0, 2100.0                     # старт и финиш вдоль оси
LANE = 80.0                                # Нага справа по ходу (+), Кунка слева (−): он смотрит на неё вправо
V_NAGA, V_KUNKKA = 330, 315
T_NAGA = T_GO + (S1 - S0) / V_NAGA         # на финише
T_KUNKKA = T_GO + (S1 - S0) / V_KUNKKA
T_LOOK = 13.2
YAW = math.degrees(HEAD)


def along(s, off=0.0):
    """Точка оси на расстоянии s от начала, сдвинутая вбок на off (вправо по ходу)."""
    dx, dy = math.cos(HEAD), math.sin(HEAD)
    return O[0] + dx * s + dy * off, O[1] + dy * s - dx * off


def rate(hero, anim, speed):
    m = Model(hero); feet, _f, drift = m.stride(anim)
    return round(speed / (feet or drift / m.duration(anim)), 3)   # у Наги нет ног — шаг по сдвигу корня


def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def lerp(a, b, k):
    return a + (b - a) * k


def naga_motion():
    run = path(None, V_NAGA, start=T_GO)

    def m(t, p):
        x, y, z, pi, yaw, ro = run(t, p)
        return (x, y, z, pi, yaw + 90 * sm(T_NAGA + 0.6, T_NAGA + 1.5, t), ro)   # на финише поворачивается к Кунке
    return m


def pos_s(v, t):
    return min(S0 + v * max(0.0, t - T_GO), S1)


# камера на оси линии впереди героев, смотрит на середину пары; на старте и на финише медленно наезжает
def cam(t):
    c = (pos_s(V_NAGA, t) + pos_s(V_KUNKKA, t)) / 2
    gap = lerp(600, 540, sm(0, T_GO, t))                         # старт: наезд
    gap = lerp(gap, 640, sm(T_GO, T_GO + 1.5, t))                 # гонка: чуть шире
    gap = lerp(gap, float(os.environ.get("GAP_END", 410)), sm(T_KUNKKA, T_LOOK + 1.5, t))           # финиш: наезд на развязку
    h = lerp(330, float(os.environ.get("H_END", 190)), sm(T_KUNKKA, T_LOOK + 1.5, t))
    back = float(os.environ.get("AIM_BACK", 200)) * sm(T_KUNKKA, T_LOOK + 1.5, t)   # к развязке смотрим за них: герои ниже в кадре
    tx, ty = along(c - back); px, py = along(c + gap)
    hd = math.dist((tx, ty), (px, py))
    yaw = math.degrees(math.atan2(-(tx - px), ty - py))          # Cam: вперёд = (−sin yaw, cos yaw)
    return (tx, ty, 0, math.hypot(hd, h), math.degrees(math.atan2(h, hd)), yaw)


def lane(off):
    return [along(S0 + (S1 - S0) * i / 10, off) for i in range(11)]


def stand(at, yaw):
    return lambda t, p: (at[0], at[1], 0, 0, yaw, 0)


st = Stage(cam, DUR, ground=Ground(), trees=(1400, 5776, 2400, 0), min_gap=150,
           max_h=0.95)                     # развязка — крупный план: фигуры крупнее обычного
st.actor("naga", None, naga_motion(),
         [(0, "idle_headTurn"), (T_GO, "run_haste", rate("naga_siren", "run_haste", V_NAGA)), (round(T_NAGA, 2), "idle")],
         hero="naga_siren", world=lane(LANE), box=(70, -15, 190))
K_PARTS = hero_model("kunkka")[1]
def kunkka_motion():
    run = path(None, V_KUNKKA, start=T_GO)

    def m(t, p):
        x, y, z, pi, yaw, ro = run(t, p)
        return (x, y, z, pi, yaw - 90 * sm(T_KUNKKA + 0.1, T_KUNKKA + 0.8, t), ro)   # добежав, поворачивается к Наге
    return m


st.actor("kunkka", None, kunkka_motion(),
         [(0, "idle"), (0.3, "a8_warmup"), (T_GO, "run", rate("kunkka", "run", V_KUNKKA)),
          (round(T_KUNKKA, 2), "a8_tired"), (T_LOOK, "a8_look")],
         hero="kunkka", model="models/a8/kunkka/kunkka_a8.vmdl", parts=K_PARTS, world=lane(-LANE), box=(70, -15, 200))
AXE_AT = along(S0 - float(os.environ.get("AXE_BACK", 330)), float(os.environ.get("AXE_OFF", 0)))
st.actor("axe", None, stand(AXE_AT, YAW), [(0, "idle"), (3.0, "axe_taunt_01_come_get_it"), (4.8, "idle_alt")],
         hero="axe", world=[AXE_AT], box=(80, -15, 200))
print(f"  Нага на финише в {T_NAGA:.2f} с, Кунка в {T_KUNKKA:.2f} с (отстал на {(T_KUNKKA - T_NAGA) * V_KUNKKA:.0f} ед.)")

if os.environ.get("CHECK"):                        # быстро: какие проверки не проходят (без решателя)
    for (kind, who), (v, t) in sorted(st.problems().items(), key=lambda x: -x[1][0]):
        print(f"  {kind} {'/'.join(who)}: {v:.2f} в {t:.1f} с")
    sys.exit()
st.solve()
st.frame_map(os.path.join(HERE, "..", "..", "qa", "frame_map_race.jpg"))
st.write()
