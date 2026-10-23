# Свои анимации Кунки для «Забега» (исполняется внутри anim_to_dmx.py или preview_anims.py: есть arm, sc, ACTS, FPS).
# Поза строится от игровой стойки idle: таз, позвоночник и голова поворачиваются в мире вокруг своих суставов,
# ступни и кисти держит IK (ступни стоят на месте, кисти ложатся на колени), потом всё запекается в действие.
#   a8_warmup — разминка (цикл 2,4 с): мельница руками в противофазе, пружинка в коленях
#   a8_tired  — выдохся (цикл 1,2 с): согнулся, руки на коленях, частое дыхание
#   a8_look   — из «выдохся»: смотрит на хвост Наги перед собой, потом на свои ноги (4,4 с, в конце поза держится)
import math
import bpy
from mathutils import Matrix, Vector

R = math.radians
MW = arm.matrix_world
IDLE = ACTS["idle"]


def sm(a, b, t):
    t = min(1.0, max(0.0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def world(name):
    return MW @ arm.pose.bones[name].matrix


def set_world(name, M):
    arm.pose.bones[name].matrix = MW.inverted() @ M
    bpy.context.view_layer.update()


def turn(name, axis, ang, extra=None):
    """Повернуть кость в мире вокруг её сустава (дети едут следом)."""
    M = world(name); p = M.translation.copy()
    Rm = Matrix.Translation(p) @ Matrix.Rotation(ang, 4, axis) @ Matrix.Translation(-p)
    set_world(name, Rm @ M)


def shift(name, d):
    M = world(name); set_world(name, Matrix.Translation(Vector(d)) @ M)


def base_pose(t):
    """Игровая стойка idle в момент t (по кругу)."""
    ad = arm.animation_data or arm.animation_data_create(); ad.action = IDLE
    try: ad.action_slot = IDLE.slots[0]
    except Exception: pass
    n = IDLE.frame_range[1]
    f = (t * 24.0) % n
    sc.frame_set(int(f), subframe=f - int(f))


EMPTIES = {}


def empty(name):
    if name not in EMPTIES:
        e = bpy.data.objects.new("a8_" + name, None); sc.collection.objects.link(e); EMPTIES[name] = e
    return EMPTIES[name]


def ik(bone, target, pole, length=2):
    pb = arm.pose.bones[bone]
    c = pb.constraints.new("IK"); c.target = empty(target); c.pole_target = empty(pole)
    c.chain_count = length; c.pole_angle = R(-90); c.use_tail = True
    return c


# суставы в стойке: где стоят ступни и колени
base_pose(0)
ANK = {s: world("ankle_" + s).translation.copy() for s in "LR"}
KNEE = {s: world("knee_" + s).translation.copy() for s in "LR"}
FWD = Vector((0, -1, 0))                 # лицо модели смотрит в −Y
X = Vector((1, 0, 0))                    # поворот вокруг +X наклоняет верх вперёд (к −Y)
Z = Vector((0, 0, 1))
Y = Vector((0, 1, 0))


def bake(name, nframes, pose, hands_on_knees):
    """pose(t) ставит позу без IK и возвращает {цель: точка мира}; IK доводит ступни и кисти, всё запекается."""
    act = bpy.data.actions.new(name)
    cons = []
    for s in "LR":
        cons.append(ik("ankle_" + s, "foot_" + s, "kneepole_" + s))
        if hands_on_knees:
            cons.append(ik("wrist_" + s, "hand_" + s, "elbowpole_" + s))
    keyed = []
    for k in range(nframes + 1):
        t = k / FPS
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        targets = pose(t)
        for nm, p in targets.items():
            empty(nm).location = p
        bpy.context.view_layer.update()
        # запомнить итог с IK (визуальная поза) по кадрам
        keyed.append({pb.name: pb.matrix.copy() for pb in arm.pose.bones})
    for pb in arm.pose.bones:
        for c in list(pb.constraints):
            pb.constraints.remove(c)
    # запечь: позы кадров → ключи действия
    ad = arm.animation_data; ad.action = act
    try:
        slot = act.slots.new(id_type="OBJECT", name=arm.name); ad.action_slot = slot
    except Exception:
        pass
    for k, P in enumerate(keyed):
        sc.frame_set(k)                            # кадр до позы: иначе пересчёт действия затрёт её
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        for pb in sorted(arm.pose.bones, key=lambda b: len(b.parent_recursive)):
            pb.matrix = P[pb.name]
            bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            pb.keyframe_insert("location", frame=k); pb.keyframe_insert("rotation_quaternion", frame=k)
            pb.keyframe_insert("scale", frame=k)
    act.frame_range = (0, nframes)
    return act


# ---------- разминка: мельница руками в противофазе и пружинка в коленях
WARM_T = 2.4


def warmup(t):
    base_pose(0)                                   # без покачивания стойки — движение своё
    w = 2 * math.pi * t / (WARM_T / 2)            # два оборота рук за цикл
    shift("root", (0, 0.06, -0.10 - 0.10 * (0.5 - 0.5 * math.cos(2 * w))))   # пружинка дважды за оборот
    turn("spine1", X, R(6))
    turn("spine3", Z, R(10) * math.sin(w))         # корпус чуть за руками
    turn("bicep_R", X, -w)                        # мельница: правая вперёд-вверх
    turn("bicep_L", X, -w + math.pi)              # левая в противофазе
    turn("head", X, R(-6))
    return {"foot_L": ANK["L"], "foot_R": ANK["R"],
            "kneepole_L": KNEE["L"] + FWD * 2.0, "kneepole_R": KNEE["R"] + FWD * 2.0}


# ---------- выдохся: согнулся, руки на коленях, дыхание
TIRED_T = 1.2
DROP, BEND = 0.55, 58                              # насколько присел и согнулся (°)


def tired_pose(t, breath=1.0):
    base_pose(0)
    b = math.sin(2 * math.pi * t / (TIRED_T / 2)) * breath    # два вдоха за цикл: часто дышит
    shift("root", (0, 0.22, -DROP - 0.05 * b))                 # таз назад и вниз
    turn("root", X, R(18))                                    # таз наклоняется вперёд
    turn("spine1", X, R(BEND * 0.35 + 3.5 * b))
    turn("spine2", X, R(BEND * 0.25 + 3.0 * b))
    turn("spine3", X, R(BEND * 0.15 - 7.0 * b))               # на вдохе грудь и плечи заметно поднимаются
    turn("clavicle_L", Y, R(6) * b); turn("clavicle_R", Y, R(-6) * b)
    turn("neck1", X, R(-38 - 4 * b))                          # голову держит, на вдохе чуть запрокидывает
    hand = {s: KNEE[s] + Vector((0.08 if s == "L" else -0.08, -0.32, 0.38 + 0.02 * b)) for s in "LR"}
    for s in "LR":
        hand[s].z -= DROP * 0.55
    return {"foot_L": ANK["L"], "foot_R": ANK["R"],
            "kneepole_L": KNEE["L"] + FWD * 2.0, "kneepole_R": KNEE["R"] + FWD * 2.0,
            "hand_L": hand["L"], "hand_R": hand["R"],
            "elbowpole_L": KNEE["L"] + Vector((1.2, 0.6, 1.5)), "elbowpole_R": KNEE["R"] + Vector((-1.2, 0.6, 1.5))}


# ---------- взгляд: Нага стоит перед ним (он к ней повернулся) — смотрит вниз на её хвост, потом на свои ноги
LOOK_T = 4.4                                       # последние ~0,8 с поза держится: разовая анимация не должна кончиться раньше сцены


def look(t):
    tg = tired_pose(t, breath=1.0 - 0.6 * sm(1.0, 2.4, t))   # дыхание стихает
    k1 = sm(0.4, 1.0, t)                                     # поднял взгляд с земли на её хвост
    k2 = sm(2.1, 2.8, t)                                     # перевёл на свои ноги: голова вниз, плечи опустились
    turn("neck1", X, R(-14) * k1 + R(40) * k2)
    turn("head", X, R(10) * k1 + R(26) * k2)
    turn("spine3", X, R(8) * k2)
    return tg


CUSTOM = {
    "a8_warmup": bake("a8_warmup", int(WARM_T * FPS), warmup, False),
    "a8_tired": bake("a8_tired", int(TIRED_T * FPS), tired_pose, True),
    "a8_look": bake("a8_look", int(LOOK_T * FPS), look, True),
}
LOOPING = {"a8_warmup": True, "a8_tired": True, "a8_look": False}
