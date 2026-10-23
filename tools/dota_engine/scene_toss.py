# «Как летают Пуджи»: Тини стоит в реке, рядом очередь Пуджей. По одному Пудж подходит, Тини швыряет его (Toss),
# тот летит дугой, барахтаясь, и плюхается в реку. Последнего Тини, развернувшись, кидает прямо в камеру.
# Только игровые анимации (свои выглядели неестественно), полёт — честная парабола, лёгкий кувырок вперёд.
# У каждого Пуджа свои анимации, без повторов. Место и камера — как у пробы 006 (широкая вода у нижней руны, небо видно).
# py -3.11 tools/dota_engine/scene_toss.py   (CHECK=1 — только проверки; картинка композиции — qa/frame_map_toss.jpg)
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage, water_map, MID
from ground_map import Ground

DUR = 10.5
C = (1516.0, -1660.0)                      # середина широкой воды у нижней руны
WALK = 325                                 # шаг Пуджа (pudge_walkN: корень 325 ед./с за цикл)
RELEASE = 0.35                             # в анимации броска Тини отпускает на 0,35 с
FLIGHT = 1.3                               # полёт Toss в игре — 1,3 с
SINK = -30                                 # приводнился: по пояс (река в доте по щиколотку)


def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def lerp(a, b, k):
    return a + (b - a) * k


# нижний конец реки (у нижней линии): ровная вода ~1250×1000 ед.; камера с юга смотрит на север — в кадре ни деревьев,
# ни скал на луче, вдали скальная стена. (У нижней руны посреди воды островки с деревьями — луч камеры их задевал.)
# Карта воды этот участок не покрывает — проверка воды выключена, вода видна в кадрах.
T = (3900.0, -2420.0)
YAW = 0.0
FWD = (-math.sin(math.radians(YAW)), math.cos(math.radians(YAW)))
RIGHT = (math.cos(math.radians(YAW)), math.sin(math.radians(YAW)))
PITCH = float(os.environ.get("PITCH", 18))
DIST = 900.0


def cam(t):
    k = sm(0, DUR, t)
    return (T[0], T[1], 0, lerp(DIST, DIST - 12, k), PITCH, YAW + lerp(-2, 2, k))


st = Stage(cam, DUR, kf=30, ref=0.0, ground=Ground(), max_h=0.9, max_over=0.9)   # всё в движении, а очередь в перспективе прячет хвост за впереди стоящим — норма


def P(dx, dy):
    """Точка от цели камеры: dx — вправо в кадре, dy — вглубь."""
    return (T[0] + RIGHT[0] * dx + FWD[0] * dy, T[1] + RIGHT[1] * dx + FWD[1] * dy)


def FR(dx, dy):
    """Та же точка в долях кадра в начале сцены — якорь для решателя."""
    x, y = P(dx, dy)
    return st.cam_at(0).screen(x, y, st.gz(x, y) + MID)


def yaw_to(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


TINY = P(-120, -270)
SLOT = P(70, -240)                         # куда подходит очередной Пудж: справа от Тини
TOSS = [1.0, 3.4, 6.2]                     # когда Тини бросает
WALK_AT = [None, 2.1, 4.5]                 # когда очередной идёт к Тини (первый уже стоит рядом)
# очередь уходит вправо вглубь, полёты — влево вдаль и в центр (слева вдали деревья); последний — в камеру; шаг ≥ 190 ед.
SPOTS = [None, P(205, -105), P(290, 180)]
LAND = [P(-110, 345), P(235, 305), P(60, -430)]
PEAK = [270, 290, 195]
# у каждого свои: стойка, шаг, полёт, после приводнения
ANIMS = [("pudge_idle", None, "pudge_flail", "pudge_stun"),
         ("hh_idle", "pudge_walkN", "hh_flail", "hh_stun"),
         ("pudge_ti7_immortal_idle", "pudge_walk_chase", "pudge_ti7_immortal_flail", "pudge_ti7_immortal_stun")]


def pudge(i):
    t_go, t_walk = TOSS[i] + RELEASE, WALK_AT[i]
    t_arrive = (t_walk or 0) + 0.9                                 # к Тини идёт 0,9 с (скорость шага — по расстоянию)

    def m(t, p):
        spot = p[0][:2] if t_walk is not None else SLOT
        land = p[-1][:2]
        walk_d = max(1.0, math.dist(spot, SLOT))
        fly_yaw = yaw_to(SLOT, land)
        if t_walk is not None and t < t_arrive:                    # стоит в очереди, потом идёт к Тини
            k = max(0.0, (t - t_walk) / 0.9) if t >= t_walk else 0.0
            x, y = lerp(spot[0], SLOT[0], k), lerp(spot[1], SLOT[1], k)
            yaw = yaw_to(spot, SLOT) if t >= t_walk else yaw_to(spot, TINY)
            return (x, y, 0, 0, yaw, 0)
        if t < t_go:                                               # рядом с Тини, повернулся по броску
            return (SLOT[0], SLOT[1], 0, 0, lerp(yaw_to(SLOT, TINY), fly_yaw, sm(t_go - 0.5, t_go, t)), 0)
        s = min(1.0, (t - t_go) / FLIGHT)
        if s < 1.0:                                                # полёт: парабола и кувырок вперёд
            x, y = lerp(SLOT[0], land[0], s), lerp(SLOT[1], land[1], s)
            z = 4 * PEAK[i] * s * (1 - s)
            return (x, y, z, lerp(-20, 55, s), fly_yaw, 10 * math.sin(s * 7))
        k = sm(t_go + FLIGHT, t_go + FLIGHT + 0.35, t)             # приводнился: осел по пояс, выпрямился
        return (land[0], land[1], lerp(0, SINK, k), lerp(55, 0, k), fly_yaw, 0)

    idle, walk, flail, stun = ANIMS[i]
    an = [(0, idle)]
    if walk:
        an.append((t_walk, walk)); an.append((round(t_arrive, 2), idle))
    an += [(round(t_go, 2), flail), (round(t_go + FLIGHT, 2), stun)]
    return m, an


# Тини: стоит, к каждому броску поворачивается к Пуджу; последнего — разворачивается к камере
def tiny(t, p):
    yaw = yaw_to(TINY, LAND[0])
    yaw = lerp(yaw, yaw_to(TINY, LAND[1]), sm(TOSS[1] - 0.8, TOSS[1] - 0.3, t))
    yaw = lerp(yaw, yaw_to(TINY, LAND[2]), sm(TOSS[2] - 1.2, TOSS[2] - 0.4, t))    # последнего — к камере
    return (TINY[0], TINY[1], 0, 0, yaw, 0)


tiny_an = [(0, "tiny_1_idle")]
for tt in TOSS:
    tiny_an += [(tt, "tiny_1_toss"), (round(tt + 0.77, 2), "tiny_1_idle")]
tiny_an[-1] = (tiny_an[-1][0], "tiny_1_idle")
tiny_an.append((round(TOSS[2] + RELEASE + FLIGHT + 0.6, 2), "tiny_01_victory"))
tiny_an.append((round(TOSS[2] + RELEASE + FLIGHT + 0.6 + 1.13, 2), "tiny_1_idle_alt"))
st.actor("tiny", None, tiny, tiny_an, hero="tiny", world=[TINY], box=(85, -20, 250))
for i in range(3):
    m, an = pudge(i)
    st.actor(f"p{i + 1}", None, m, an, hero="pudge", world=[a for a in (SPOTS[i], LAND[i]) if a])
    st.fx(round(TOSS[i] + RELEASE + FLIGHT, 2), "maps/cavern_assets/particles/cavern_water_splash_hero.vpcf", at=f"p{i + 1}")

if os.environ.get("CHECK"):
    for (kind, who), (v, t) in sorted(st.problems().items(), key=lambda x: -x[1][0]):
        print(f"  {kind} {'/'.join(who)}: {v:.2f} в {t:.1f} с")
        if kind == "камера":
            from stage import MID as _M
            aims = [(q[0], q[1], q[2] + st.gz(q[0], q[1]) + _M) for q in (st.keys(k, t) for k in st.actors)]
            print("    мешает:", st.cam_blocked(st.cam_at(t), aims=aims))
    sys.exit()
st.solve()
st.frame_map(os.path.join(HERE, "..", "..", "qa", "frame_map_toss.jpg"))
st.write()
