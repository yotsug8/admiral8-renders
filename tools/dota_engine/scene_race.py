# Гэг «Забег»: на старте Нага, Кунка и Тайдхантер. Нага честно бежит (330 ед./с — её базовая скорость),
# Кунка остаётся на старте танцевать с саблей, Тайд «плывёт» по суше на спине. Стартёр — Акс. Скорость бега Наги = её скорость / шаг анимации — хвост не скользит.
# Камера едет впереди Наги и смотрит ей навстречу: остальные остаются позади, в глубине кадра.
# py -3.11 tools/dota_engine/scene_race.py   (картинка композиции — qa/frame_map_race.jpg; CHECK=1 — только проверки)
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage, path
from ground_map import Ground
from anims import Model

DUR = 6.0
T0 = 1.2                                   # старт: до него стоят на линии
# верхняя линия Тьмы: прямая на восток, ровная (высота 128), без деревьев на ±150 по всей длине 2800 ед.;
# камере место дальше по той же прямой (s ≥ 1250). Мид не подошёл: посередине зажат деревьями, луч их задевает.
O, HEAD = (528.0, 5776.0), math.radians(0)
AXIS = [O, (O[0] + 3000 * math.cos(HEAD), O[1] + 3000 * math.sin(HEAD))]
S0, S1 = float(os.environ.get("S0", 300)), float(os.environ.get("S1", 900))


def along(s, off=0.0):
    """Точка оси на расстоянии s от начала, сдвинутая вбок на off (вправо по ходу бега)."""
    for a, b in zip(AXIS, AXIS[1:]):
        L = math.dist(a, b)
        if s <= L or b == AXIS[-1]:
            k = s / L; dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            return a[0] + dx * L * k + dy * off, a[1] + dy * L * k - dx * off, (dx, dy)
        s -= L


def lane(off, n=10):
    return [along(S0 + (S1 - S0) * i / n, off)[:2] for i in range(n + 1)]


def rate(hero, anim, speed):
    m = Model(hero); feet, _f, drift = m.stride(anim)
    step = feet or drift / m.duration(anim)         # у Наги нет ног — шаг по сдвигу корня за цикл
    return round(speed / step, 3)


LANE = float(os.environ.get("LANE", 110))
V = 330                                    # Нага
T_FIN = T0 + (S1 - S0) / V                 # Нага на финише


def stand(at, yaw):
    return lambda t, p: (at[0], at[1], 0, 0, yaw, 0)


def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


H = float(os.environ.get("CAM_H", 380))


def pack(t):
    """За кем едет камера: Нага (остальные остаются позади)."""
    return min(S0 + V * max(0.0, t - T0), S1)


AIM = float(os.environ.get("AIM", 0.45))
GAP = (float(os.environ.get("GAP_A", 640)), float(os.environ.get("GAP_B", 470)))   # камера впереди стаи по линии


def cam(t):
    # камера едет по оси линии перед стаей (по оси деревьев нет) и смотрит на её середину; к финишу чуть ближе
    sc = pack(t); s_cam = sc + GAP[0] + (GAP[1] - GAP[0]) * sm(T0, DUR, t)
    # смотрим между Нагой и стартом: внизу кадра Нага, выше — те, кто остался (иначе низ кадра — пустая земля)
    tx, ty, _ = along(sc - AIM * (sc - S0)); px, py, _ = along(s_cam)
    hd = math.dist((tx, ty), (px, py))
    yaw = math.degrees(math.atan2(-(tx - px), ty - py))          # Cam: вперёд = (−sin yaw, cos yaw)
    return (tx, ty, 0, math.hypot(hd, H), math.degrees(math.atan2(H, hd)), yaw)


st = Stage(cam, DUR, ground=Ground(), trees=(1400, 5776, 2400, 0), min_gap=min(150, LANE))
YAW = math.degrees(HEAD)                   # лицом по ходу забега
st.actor("naga", None, path(None, V, start=T0),
         [(0, "idle"), (T0, "run_haste", rate("naga_siren", "run_haste", V)), (round(T_FIN, 2), "Victory")],
         hero="naga_siren", world=lane(0), box=(70, -15, 190))
st.actor("kunkka", None, stand(along(S0, LANE)[:2], YAW), [(0, "idle"), (T0 + 0.2, "taunt_sword_dance", round(3.8 / (DUR - T0 - 0.2) * 0.9, 3))],
         hero="kunkka", world=[along(S0, LANE)[:2]], box=(70, -15, 200))
# Тайд: ложится на спину и гребёт по суше; таунт 3,6 с растянут дольше остатка сцены: в конце таунта он встаёт
SWIM_T = T0 + 0.4
st.actor("tide", None, path(None, float(os.environ.get("TIDE_V", 40)), start=SWIM_T),
         [(0, "idle"), (SWIM_T, "taunt_back_stroke", round(3.6 / (DUR - SWIM_T) * 0.8, 3))],
         hero="tidehunter", world=lane(-LANE - 20), box=(90, -15, 190))
# стартёр Акс: позади линии старта, между Нагой и Тайдом, лицом по ходу, за секунду до старта кричит «давай!»
AXE_AT = along(S0 - float(os.environ.get("AXE_BACK", 370)), float(os.environ.get("AXE_OFF", -55)))[:2]
st.actor("axe", None, stand(AXE_AT, YAW), [(0, "idle"), (T0 - 1.0, "axe_taunt_01_come_get_it"), (T0 + 0.8, "idle_alt")],
         hero="axe", world=[AXE_AT], box=(80, -15, 200))
print(f"  Нага на финише в {T_FIN:.2f} с, Тайд гребёт ×{3.6 / (DUR - SWIM_T) * 0.8:.2f}")

if os.environ.get("CHECK"):                        # быстро: какие проверки не проходят (без решателя)
    for (kind, who), (v, t) in sorted(st.problems().items(), key=lambda x: -x[1][0]):
        print(f"  {kind} {'/'.join(who)}: {v:.2f} в {t:.1f} с")
    sys.exit()
st.solve()
st.frame_map(os.path.join(HERE, "..", "..", "qa", "frame_map_race.jpg"))
st.write()
