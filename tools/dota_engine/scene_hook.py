# Сценка «Крюк»: Снайпер хвастается, что стреляет дальше всех (дальность атаки 550), а крюк Пуджа бьёт на 1300
# (scripts/npc/heroes игры). Пудж стоит в 900 ед. — дальше выстрела, ближе крюка. 15 с, пять планов со склейками:
#   A 0–3,8    сбоку: Снайпер крупно справа, Пудж вдали слева. Снайпер: «Ближе не подходи. Я стреляю дальше всех.»
#   B 3,8–8,5  крупно Пудж (рот под звук — a8_p1): «Дальше всех? Мой крюк — тысяча триста.»
#   C 8,5–11,2 крупно Снайпер опускает голову к винтовке (a8_s2): «А у меня... пятьсот пятьдесят.»
#   D 11,2–13,1 из-за плеча Пуджа: бросок, цепь летит со скоростью крюка 1600, Снайпера дёргает к Пуджу
#   E 13,1–15  оба крупно, Снайпер оглушён. Пудж (a8_p2): «Привет.»
# Свои анимации — tools/blender/hook_talk.py (по громкости голосов _game/hook/voices.json). Звук и подписи — hook_mix.py.
# py -3.11 tools/dota_engine/scene_hook.py
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage
from ground_map import Ground
from hero_parts import hero_model

DUR = 15.0
P, S = (-4250.0, -3220.0), (-3350.0, -3220.0)      # Пудж и Снайпер: поляна на светлой стороне, 900 ед. по прямой
HOOK_V = 1600.0                                     # скорость крюка (scripts/npc/heroes/npc_dota_hero_pudge.txt)
T_THROW = 11.2                                      # Пудж замахивается
T_REL = T_THROW + 0.45                              # крюк вылетел
LAND = (P[0] + 150, P[1])                           # куда притянуло Снайпера: перед Пуджем
T_HIT = T_REL + math.dist(P, S) / HOOK_V            # крюк долетел до Снайпера
T_BACK = T_HIT + math.dist(S, LAND) / HOOK_V        # притянул
VOICE = {"s1": 0.5, "p1": 3.9, "s2": 8.8, "p2": 13.6}   # когда звучит каждая реплика (hook_mix.py берёт отсюда)


def sm(a, b, t):
    t = min(1, max(0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def lerp(a, b, k):
    return a + (b - a) * k


# камера: (x, y, высота взгляда над землёй, дальность, наклон, поворот); поворот 90 — смотрим на запад, −90 — на восток
def cam(t):
    if t < 3.8:                                     # A: сбоку — Снайпер крупно справа целится, Пудж вдали слева
        k = sm(0, 3.8, t)
        return (S[0] - 38, S[1] - 44, 105, lerp(315, 295, k), 4, 80)   # подобрано расчётом: Снайпер x ≈ 0.38, Пудж x ≈ −0.19
    if t < 8.5:                                     # B: крупно Пудж, чуть снизу и сбоку
        k = sm(3.8, 8.5, t)
        return (P[0] + 10, P[1] - 10, 175, lerp(285, 250, k), 2, 90 - 35)
    if t < 11.2:                                    # C: крупно Снайпер с той же (южной) стороны
        k = sm(8.5, 11.2, t)
        return (S[0] - 10, S[1] - 5, 115, lerp(240, 215, k), 4, -90 + 30)
    if t < 13.1:                                    # D: из-за плеча Пуджа — бросок и рывок
        return (P[0] + 380, P[1] + 80, 120, 470, 7, -90)
    k = sm(13.1, 15.0, t)                           # E: оба крупно
    return (LAND[0] - 75, LAND[1], 150, lerp(380, 350, k), 3, 0)


def stand(at, yaw):
    return lambda t, p: (at[0], at[1], 0, 0, yaw, 0)


def sniper(t, p):
    if t < T_HIT:
        return (S[0], S[1], 0, 0, 180, 0)
    k = min(1.0, (t - T_HIT) / (T_BACK - T_HIT))   # тянет со скоростью крюка, лёгкая дуга
    return (lerp(S[0], LAND[0], k), S[1], 45 * math.sin(math.pi * k), 0, 180, 0)


def tip(t, p):                                      # острие крюка: из руки к Снайперу и обратно вместе с ним
    hand = (P[0] + 40, P[1] - 30)
    if t < T_REL:
        return (hand[0], hand[1], 110, 0, 0, 0)
    if t < T_HIT:
        k = (t - T_REL) / (T_HIT - T_REL)
        return (lerp(hand[0], S[0], k), lerp(hand[1], S[1], k), 110, 0, 0, 0)
    x, y, z, *_ = sniper(t, p)
    return (x, y, z + 90, 0, 0, 0)


st = Stage(cam, DUR, kf=30, ground=Ground(), trees=(-3800, -3200, 2400, 0))
st.actor("pudge", None, stand(P, 0),
         [(0, "pudge_idle"), (3.8, "a8_p1"), (8.6, "pudge_idle"), (T_THROW, "pudge_meathook_start"),
          (round(T_THROW + 0.9, 2), "pudge_meathook_end"), (round(T_THROW + 1.5, 2), "pudge_idle"), (13.1, "a8_p2")],
         hero="pudge", model="models/a8/pudge/pudge_a8.vmdl", parts=hero_model("pudge")[1], world=[P])
st.actor("sniper", None, sniper,
         [(0, "sniper_idle_aggressive"), (8.5, "a8_s2"), (round(T_HIT, 2), "sniper_flail"), (round(T_BACK, 2), "sniper_stun")],
         hero="sniper", model="models/a8/sniper/sniper_a8.vmdl", parts=hero_model("sniper")[1], world=[S])
st.actor("tip", None, tip, [(0, "idle")], model="models/development/invisiblebox.vmdl", parts=[], world=[P])
st.fx(round(T_REL, 2), "particles/units/heroes/hero_pudge/pudge_meathook.vpcf", at="pudge", to="tip", dur=round(T_BACK - T_REL + 0.15, 2))
print(f"  крюк вылетел {T_REL:.2f} с, долетел {T_HIT:.2f}, притянул {T_BACK:.2f}")
st.write()
