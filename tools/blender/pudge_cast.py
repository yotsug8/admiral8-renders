# Труппа Пуджей для build_006.py (исполняется внутри него, общие переменные: arm, body, ACTS, sc, FPS, FRAMES, WATER_Z,
# PUDGE_Z, C, DIR, PERP, CAM0, log). Свои анимации костей (кроль, на спине) + «носитель» у каждого Пуджа: покадровые
# положение и наклон (заплыв, переворот, нырок, вращение). Дотовские анимации — через NLA, как раньше.
import math
from mathutils import Vector, Matrix, Quaternion

SPEED = FPS / 24.0
R = math.radians

def smooth(a, b, t):
    t = min(1.0, max(0.0, (t - a) / (b - a))); return t * t * (3 - 2 * t)

def lat_al(al, lat):
    return C + DIR * al + PERP * lat

def face_cam(p):
    return math.atan2(CAM0[0] - p.x, -(CAM0[1] - p.y))      # поворот вокруг Z, при котором Пудж (лицо в −Y) смотрит в камеру

def heading_yaw(h):
    return math.atan2(h.x, -h.y)                             # поворот, при котором голова лежащего Пуджа (+Z тела) идёт по h

# ---------- свои анимации костей ----------
bones_order = []
def _walk(b):
    bones_order.append(b.name)
    for c in b.children: _walk(c)
for b in arm.data.bones:
    if b.parent is None: _walk(b)

def aim(child, target_dir_fn):
    """Повернуть кость так, чтобы голова дочерней кости смотрела по направлению (в пространстве скелета)."""
    def rule(name, M0, Dp, baseM, newM):
        piv = M0.translation
        cur = (Dp @ baseM[child]).translation - piv
        tgt = target_dir_fn(piv, newM)
        return cur.normalized().rotation_difference(tgt.normalized())
    return rule

def rot(q):
    return lambda *a: q

def bake(name, nframes, base_name, rules_at):
    base = ACTS[base_name]; f0, f1 = base.frame_range; L = f1 - f0
    ad = arm.animation_data_create()
    ad.action = base
    try: ad.action_slot = base.slots[0]
    except Exception: pass
    data = []
    for f in range(nframes + 1):
        bf = f0 + (f / SPEED) % L
        sc.frame_set(int(bf), subframe=bf - int(bf))
        baseM = {pb.name: pb.matrix.copy() for pb in arm.pose.bones}
        rules = rules_at(f)
        newM, basis = {}, {}
        for n in bones_order:
            b = arm.data.bones[n]
            Dp = (newM[b.parent.name] @ baseM[b.parent.name].inverted()) if b.parent else Matrix.Identity(4)
            M0 = Dp @ baseM[n]
            r = rules.get(n)
            if r:
                q = r(n, M0, Dp, baseM, newM)
                piv = M0.translation
                M0 = Matrix.Translation(piv) @ q.to_matrix().to_4x4() @ Matrix.Translation(-piv) @ M0
            newM[n] = M0
            Br = b.matrix_local
            basis[n] = ((newM[b.parent.name] @ b.parent.matrix_local.inverted() @ Br).inverted() @ M0) if b.parent else (Br.inverted() @ M0)
        data.append(basis)
    act = bpy.data.actions.new(name); ad.action = act
    prev = {}
    for f, B in enumerate(data):
        for n, M in B.items():
            pb = arm.pose.bones[n]
            loc, q, s = M.decompose()
            if n in prev and prev[n].dot(q) < 0: q.negate()
            prev[n] = q
            pb.location, pb.rotation_quaternion, pb.scale = loc, q, s
            pb.keyframe_insert("location", frame=f); pb.keyframe_insert("rotation_quaternion", frame=f); pb.keyframe_insert("scale", frame=f)
    for fc in _fcurves(act):
        for kp in fc.keyframe_points: kp.interpolation = "LINEAR"
    ad.action = None
    ACTS[name] = act
    return act

SWIM_P = 46                                                # кадров на полный цикл кроля (два гребка)
def swim_rules(f, period=SWIM_P):
    th = 2 * math.pi * f / period
    def armdir(t, s):
        # гребок: рука вытянута вперёд (к голове), тянет под телом наружу, проносится над водой согнутой
        out = 0.42 + 0.18 * max(0.0, math.sin(t))              # под телом рука идёт шире — лезвия не задевают торс
        return Vector((s * out, -math.sin(t), math.cos(t)))
    def fore(t, s):
        rec = max(0.0, -math.sin(t))                            # над водой локоть согнут
        return armdir(t - 0.35 - 0.9 * rec, s)
    roll = 18 * math.sin(th)                                   # корпус перекатывается к гребущей руке
    breath = max(0.0, math.sin(th - 0.6)) ** 2                 # вдох раз в цикл — голова поворачивается в сторону
    kick = 3 * th                                              # шесть ударов ногами на цикл
    return {
        "spine1": rot(Quaternion((0, 0, 1), R(roll))),
        "spine2": rot(Quaternion((0, 0, 1), R(-0.35 * roll)) @ Quaternion((1, 0, 0), R(3 * math.sin(2 * th)))),
        "bicep_R": aim("elbow_R", lambda p, M: armdir(th, -1)),
        "elbow_R": aim("wrist_R", lambda p, M: fore(th, -1)),
        "bicep_L": aim("elbow_L", lambda p, M: armdir(th + math.pi, 1)),
        "elbow_L": aim("wrist_L", lambda p, M: fore(th + math.pi, 1)),
        "neck1": rot(Quaternion((0, 0, 1), R(-roll * 0.6 + 38 * breath)) @ Quaternion((1, 0, 0), R(-55 + 6 * math.sin(2 * th)))),
        "thigh_R": rot(Quaternion((1, 0, 0), R(22 * math.sin(kick)))),
        "thigh_L": rot(Quaternion((1, 0, 0), R(-22 * math.sin(kick)))),
        "knee_R": rot(Quaternion((1, 0, 0), R(-14 * max(0.0, math.sin(kick + 0.8))))),
        "knee_L": rot(Quaternion((1, 0, 0), R(-14 * max(0.0, math.sin(kick + 0.8 + math.pi))))),
    }

def float_rules(f, period=60):
    th = 2 * math.pi * f / period
    look = 22 * math.sin(2 * math.pi * f / 150) + 6 * math.sin(2 * math.pi * f / 47)   # лениво оглядывается
    def arm(s, ph):
        return lambda p, M: Vector((s * 0.72, 0.22, 0.55 + 0.1 * math.sin(th + ph)))   # руки разведены вверх-в-стороны
    def fore(s, ph):
        return lambda p, M: Vector((s * 0.55, 0.05 + 0.3 * math.sin(th + ph + 0.7), 0.8))   # кисти лениво гребут у головы
    return {
        "spine1": rot(Quaternion((0, 1, 0), R(3 * math.sin(th * 0.5)))),
        "bicep_R": aim("elbow_R", arm(-1, 0.0)),
        "elbow_R": aim("wrist_R", fore(-1, 0.0)),
        "bicep_L": aim("elbow_L", arm(1, 1.9)),
        "elbow_L": aim("wrist_L", fore(1, 1.9)),
        "neck1": rot(Quaternion((0, 0, 1), R(look)) @ Quaternion((1, 0, 0), R(16 + 5 * math.sin(th)))),
        "thigh_R": rot(Quaternion((0, 1, 0), R(-10)) @ Quaternion((1, 0, 0), R(8 * math.sin(th * 0.7)))),
        "thigh_L": rot(Quaternion((0, 1, 0), R(10)) @ Quaternion((1, 0, 0), R(-8 * math.sin(th * 0.7 + 1)))),
        "knee_R": rot(Quaternion((1, 0, 0), R(-10 - 6 * math.sin(th * 0.7)))),
        "knee_L": rot(Quaternion((1, 0, 0), R(-10 - 6 * math.sin(th * 0.7 + 1)))),
    }

bake("swim_crawl", SWIM_P * 3, "pudge_idle", swim_rules)     # 138 кадров = 3 цикла, стыкуется с собой
bake("back_float", 150, "pudge_idle", float_rules)
log("свои анимации: swim_crawl, back_float; выровнено ключей", align_signs([ACTS["swim_crawl"], ACTS["back_float"]]))

# ---------- траектории носителей ----------
SC = 0.85                                                  # масштаб Пуджей: меньше места при том же виде
PRONE, SUPINE_Z = R(55), WATER_Z - 1.55 * SC
def q_prone(h):
    return Quaternion((0, 0, 1), heading_yaw(h)) @ Quaternion((1, 0, 0), PRONE)
def q_supine(h):
    return q_prone(h) @ Quaternion((0, 0, 1), math.pi)
def q_up(p, off=0.0):
    return Quaternion((0, 0, 1), face_cam(p) + R(off))
def ease_io(a, b, t):
    t = min(1.0, max(0.0, (t - a) / (b - a))); return t * t * t * (t * (6 * t - 15) + 10)
def back_out(a, b, t, k=1.7):                              # с перехлёстом в конце
    t = min(1.0, max(0.0, (t - a) / (b - a))); t -= 1; return t * t * ((k + 1) * t + k) + 1
def damp(a, t, amp, freq, decay):                          # затухающее покачивание после движения
    if t < a: return 0.0
    x = (t - a) / 30.0; return amp * math.exp(-decay * x) * math.sin(2 * math.pi * freq * x)

def static(al, lat, off):
    p = lat_al(al, lat)
    return lambda f: (Vector((p.x, p.y, PUDGE_Z)), q_up(p, off))

# Пловец: кролем вниз по течению на камеру, рывок на каждом гребке; у камеры переворачивается на спину
SW0, SW1 = lat_al(18.5, 3.4), lat_al(8.5, 3.4)
SW_H = (SW1 - SW0).normalized()
PRONE_Z = WATER_Z - 1.25 * SC
_SW_T1 = 200
def _swim_s(f):
    f = min(max(f, -30), _SW_T1)
    base = (f + 30) / (_SW_T1 + 30)
    surge = 0.012 * math.sin(4 * math.pi * f / SWIM_P)    # рывок на каждом гребке
    return min(1.0, max(0.0, base + surge))
def swimmer(f):
    p = SW0.lerp(SW1, _swim_s(f))
    th = 2 * math.pi * f / SWIM_P
    q = q_prone(SW_H) @ Quaternion((0, 0, 1), R(5 * math.sin(th))) @ Quaternion((0, 1, 0), R(3 * math.sin(th)))
    z = PRONE_Z + 0.07 * math.sin(2 * th) + 0.12
    roll = ease_io(196, 224, f)
    if roll > 0:
        q = q_prone(SW_H) @ Quaternion((0, 0, 1), math.pi * roll)
        z = PRONE_Z + (SUPINE_Z - PRONE_Z) * roll + 0.4 * math.sin(math.pi * roll)
    if f > 224:
        lazy = R(15 * ease_io(224, 340, f))   # от «синхронистки», к своему берегу
        q = Quaternion((0, 0, 1), lazy) @ q_supine(SW_H) @ Quaternion((1, 0, 0), R(3 * math.sin(f * 2 * math.pi / 60)))
        z = SUPINE_Z + 0.05 * math.sin(f * 2 * math.pi / 60) + damp(224, f, 0.12, 1.4, 3.0)
        p = p + PERP * (0.15 * ease_io(224, 345, f)) + SW_H * (0.4 * ease_io(224, 300, f))   # по инерции ещё проплывает
    return Vector((p.x, p.y, z)), q

# Лежебока: лежит на спине, дрейфует, проседает, садится с перехлёстом и празднует
FL_H = DIR
def floater(f):
    al = 14.0 - 0.9 * ease_io(1, 185, f)
    p = lat_al(al, -1.8)
    lying = q_supine(FL_H) @ Quaternion((0, 1, 0), R(4 * math.sin(f * 2 * math.pi / 70)))
    up = q_up(p, -10)
    s = back_out(180, 204, f, 1.4)
    q = lying.slerp(up, max(0.0, min(1.0, s))) if s <= 1 else up @ Quaternion((1, 0, 0), R(-80 * (s - 1)))
    z = SUPINE_Z + 0.06 * math.sin(f * 2 * math.pi / 60) - 0.18 * ease_io(170, 180, f) * (1 - ease_io(180, 190, f))
    z = z + (PUDGE_Z - z) * ease_io(180, 204, f) + 0.25 * math.sin(math.pi * ease_io(180, 204, f)) + damp(204, f, 0.06, 1.2, 2.5)
    return Vector((p.x, p.y, z)), q

# Поплавок: подаётся вверх, ныряет вперёд и ложится на дно с головой; приседает и выстреливает из воды, падает и пружинит
def bobber(f):
    p = lat_al(9.5, -1.1)
    turn = 75 * ease_io(70, 92, f) * (1 - ease_io(166, 178, f))                # разворачивается к своему берегу
    face = q_up(p, -15 - turn)
    z = PUDGE_Z + 0.18 * ease_io(78, 90, f) * (1 - ease_io(90, 100, f))        # замах вверх перед нырком
    dive = ease_io(90, 118, f) * (1 - ease_io(160, 172, f))
    q = face @ Quaternion((1, 0, 0), R(82 * dive))                              # ныряет вперёд, ложится на дно
    if 120 < f < 162:
        q = q @ Quaternion((0, 0, 1), R(4 * math.sin(f * 0.21)))                 # шевелится под водой
    z -= 0.15 * ease_io(162, 170, f) * (1 - ease_io(170, 174, f))               # присел перед прыжком
    jump = ease_io(170, 182, f) * (1 - ease_io(182, 200, f) ** 1.6)
    z += 1.3 * jump + damp(200, f, 0.12, 1.6, 3.0)
    return Vector((p.x, p.y, max(z, PUDGE_Z - 0.3))), q

# Синхронное плавание: замах в обратную сторону, разгон, три оборота, торможение с перекрутом, шатается
def spinner(f):
    p = lat_al(3.3, -1.7)
    wind = -35 * ease_io(28, 40, f) * (1 - ease_io(40, 50, f))
    turns = 3 * ease_io(40, 128, f)
    over = damp(128, f, 22, 0.9, 2.2)
    wob = ease_io(128, 150, f) * (1 - ease_io(250, 290, f))
    yaw = 25 + wind + 360 * turns + over + 25 * wob * math.sin(f * 0.18)
    spin_v = math.sin(math.pi * ease_io(40, 128, f))
    q = q_up(p, yaw) @ Quaternion((0, 1, 0), R(7 * spin_v + 9 * wob * math.sin(f * 0.23))) @ Quaternion((1, 0, 0), R(4 * wob * math.sin(f * 0.13)))
    return Vector((p.x, p.y, PUDGE_Z + 0.12 * spin_v)), q

CAST = [  # имя, носитель, цепочка [(анимация, начало, конец)], центры кругов на воде (в координатах тела)
    ("P1", static(-3.5, -1.6, 20), [("pudge_idle", 0, 70), ("ftp_dendi_idle_look", 62, 230), ("victory", 222, 360)], [(0, 0, 2)]),
    ("P2", static(-1.0, 2.8, -30), [("ftp_dendi_idle_stomp", -7, 120), ("pudge_rot", 112, 260), ("pudge_flail", 252, 300), ("pudge_idle", 292, 360)], [(0, 0, 2)]),
    ("SWIM", swimmer, [("swim_crawl", -10, 214), ("back_float", 204, 360)], [(0, 0, 0.8), (0, 0, 2.2), (0, 0, 3.6)]),
    ("BOB", bobber, [("pudge_idle_alt", -5, 175), ("pudge_flail", 168, 216), ("pudge_idle_alt", 208, 360)], [(0, 0, 2)]),
    ("SPIN", spinner, [("victory", -3, 135), ("pudge_stun", 128, 272), ("pudge_idle", 264, 360)], [(0, 0, 2)]),
    ("FLOAT", floater, [("back_float", -20, 196), ("pudge_idle", 186, 215), ("victory", 207, 360)], [(0, 0, 0.8), (0, 0, 2.2), (0, 0, 3.6)]),
    # P7 убран: 7 Пуджей с размахом крюка не помещаются в брод без касаний
]

arm.animation_data_clear()
base_rest = arm.matrix_world.copy()
RING_CENTERS = []
pudge_objs = []
for name, traj, chain, centers in CAST:
    mv = bpy.data.objects.new("Mover_" + name, None); sc.collection.objects.link(mv)
    mv.rotation_mode = "QUATERNION"; mv.scale = (SC, SC, SC)
    prevq = None
    for f in range(-25, FRAMES + 6):
        loc, q = traj(f)
        if prevq is not None and prevq.dot(q) < 0: q = -q
        prevq = q
        mv.location = loc; mv.rotation_quaternion = q
        mv.keyframe_insert("location", frame=f); mv.keyframe_insert("rotation_quaternion", frame=f)
    for fc in _fcurves(mv.animation_data.action):
        for kp in fc.keyframe_points: kp.interpolation = "LINEAR"
    a = arm.copy(); sc.collection.objects.link(a)
    a.parent = mv; a.matrix_parent_inverse = Matrix.Identity(4); a.matrix_basis = base_rest
    a.hide_render = False; a.hide_viewport = False
    for o in body:
        c = o.copy(); sc.collection.objects.link(c); c.parent = a
        c.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        for m in c.modifiers:
            if m.type == "ARMATURE": m.object = a
    for cpos in centers:
        e = bpy.data.objects.new(f"Ring_{name}", None); sc.collection.objects.link(e)
        e.parent = mv; e.location = cpos
        RING_CENTERS.append(e)
    ad = a.animation_data_create(); ad.action = None
    for i, (an, s0, s1) in enumerate(chain):
        act = ACTS[an]; tr = ad.nla_tracks.new(); tr.name = f"{i}_{an}"
        st = tr.strips.new(an, int(s0), act)
        try:
            if len(act.slots): st.action_slot = act.slots[0]
        except Exception as e_:
            log("slot", e_)
        st.use_auto_blend = False
        st.action_frame_start, st.action_frame_end = act.frame_range[0], act.frame_range[1]   # иначе часть отрезков 0–1 и Пудж замирает
        own = an in ("swim_crawl", "back_float")
        st.scale = 1.0 if own else SPEED
        ln = (act.frame_range[1] - act.frame_range[0]) * st.scale
        st.repeat = max(0.1, (s1 - s0) / ln)
        st.blend_in = (14 if own or i and chain[i - 1][0] in ("swim_crawl", "back_float") else 8) if i else 0
        st.extrapolation = "HOLD" if i == 0 else "HOLD_FORWARD"
    pudge_objs.append(a)
arm.hide_render = True; arm.hide_viewport = True
for o in body:
    o.hide_render = True; o.hide_viewport = True
log("Пуджей", len(pudge_objs), "кругов на воде", len(RING_CENTERS))
