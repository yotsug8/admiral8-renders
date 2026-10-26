# Анимации разговора для любой сценки (tools/skit/skit.py) — исполняется внутри render_scene.py и anim_to_dmx.py
# (там есть arm, sc, ACTS, FPS). Что делать — из A8_TALK (JSON, список на одного актёра):
#   {name, base, line, off, dur, jaw, head, mood}
#   base — стойка, line — реплика (громкость из A8_VOICES), off — когда в анимации начинается голос, dur — длина;
#   jaw — кость челюсти (есть у Пуджа, Акса, Тайда; нет — говорит головой), head — кость головы;
#   mood — «down»: опускает голову (сник), «up»: задирает подбородок (хвастается), иначе ровно;
#   live — живость (плечи и голова всё время плавно движутся, 1 — по эталону), lean — на громком корпус вперёд (крик), jaw_max.
# Поза — игровая стойка, поверх неё повороты суставов в мире; ключи запекаются покадрово (bake).
import json, math, os
import bpy
from mathutils import Matrix, Quaternion, Vector

R = math.radians
MW = arm.matrix_world
X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))
VOICES = json.load(open(os.environ["A8_VOICES"], encoding="utf-8"))   # voices.json сценки (tools/skit/voices.py)
JAW_K = 0.35 if os.environ.get("A8_FACE") else 1.0      # в Blender рот ведут морфы лица (face.py), кость челюсти — только помогает


def sm(a, b, t):
    t = min(1.0, max(0.0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def world(name):
    return MW @ arm.pose.bones[name].matrix


def turn(name, axis, ang):
    M = world(name); p = M.translation.copy()
    arm.pose.bones[name].matrix = MW.inverted() @ (Matrix.Translation(p) @ Matrix.Rotation(ang, 4, axis) @ Matrix.Translation(-p) @ M)
    bpy.context.view_layer.update()


def aim(root, tip, dirv, k):
    """Развернуть кость root вокруг её начала так, чтобы tip (кость ниже по цепи) лёг на направление dirv; k — доля."""
    p = world(root).translation.copy(); v0 = world(tip).translation - p
    q = Quaternion().slerp(v0.rotation_difference(dirv.normalized() * v0.length), k)
    M = world(root)
    arm.pose.bones[root].matrix = MW.inverted() @ (Matrix.Translation(p) @ q.to_matrix().to_4x4() @ Matrix.Translation(-p) @ M)
    bpy.context.view_layer.update()


def base_pose(action, t):
    ad = arm.animation_data or arm.animation_data_create(); ad.action = ACTS[action]
    try: ad.action_slot = ACTS[action].slots[0]
    except Exception: pass
    n = ACTS[action].frame_range[1]; f = (t * globals().get("IMPORT_FPS", 24.0)) % n   # анимации glb легли в кадры с частотой импорта
    sc.frame_set(int(f), subframe=f - int(f))


def voice(name, off):
    """Громкость реплики в момент t сцены анимации (0…1), сглаженная: рот открывается быстро, закрывается мягче."""
    env = VOICES[name]["env"]
    def at(t):
        i = int((t - off) * 30)
        return env[i] if 0 <= i < len(env) else 0.0
    return at


def smooth_series(fn, n, up=0.6, down=0.25):
    vals, v = [], 0.0
    for k in range(n + 1):
        x = fn(k / FPS); v += (x - v) * (up if x > v else down); vals.append(v)
    return vals


def soft(vals, tau=0.25):
    """Сглаживание без запаздывания (вперёд и назад, постоянная времени tau с): движения головы без рывков."""
    a = 1 - math.exp(-1 / (FPS * tau)); out = list(vals)
    for rng in (range(1, len(out)), range(len(out) - 2, -1, -1)):
        for i in rng:
            j = i - 1 if rng.step > 0 else i + 1
            out[i] = out[j] + (out[i] - out[j]) * a
    return out


def bake(name, dur, pose):
    n = int(dur * FPS); keyed = []
    for k in range(n + 1):
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        pose(k / FPS, k)
        keyed.append({pb.name: pb.matrix.copy() for pb in arm.pose.bones})
    act = bpy.data.actions.new(name); ad = arm.animation_data; ad.action = act
    try: ad.action_slot = act.slots.new(id_type="OBJECT", name=arm.name)
    except Exception: pass
    for k, P in enumerate(keyed):
        sc.frame_set(k)
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        for pb in sorted(arm.pose.bones, key=lambda b: len(b.parent_recursive)):
            pb.matrix = P[pb.name]; bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            for path in ("location", "rotation_quaternion", "scale"):
                pb.keyframe_insert(path, frame=k)
    act.frame_range = (0, n)
    return act


def talker(base, line, off, dur, jaw_max=22, nod=5, grin=0.0, head="head", jaw="jaw0_0"):
    """Говорит: челюсть по громкости, кивок на нарастании громкости; grin — рот чуть приоткрыт после реплики.
    Без челюсти (jaw=None) — только голова: кивки на ударениях."""
    loud = smooth_series(voice(line, off), int(dur * FPS))
    end = off + VOICES[line]["dur"]
    # кивок — только на ударениях (рост громкости), слабый и сглаженный 0,25 с: без рывков
    nods = soft([(nod * max(0.0, loud[k] - loud[max(0, k - 3)]) * 3 + 2 * loud[k]) / 3.5 for k in range(len(loud))])

    base_pose(base, 0.0)                                 # покачивание головы самой стойки — приглушить к её начальной позе
    calm = {b.name: b.rotation_quaternion.copy() for b in arm.pose.bones if b.name == head or "neck" in b.name}

    def pose(t, k):
        base_pose(base, t)
        for nm, q in calm.items():
            b = arm.pose.bones[nm]; b.rotation_quaternion = b.rotation_quaternion.slerp(q, 0.65)
        bpy.context.view_layer.update()
        v = loud[k]
        turn(head, X, R(nods[k]))
        if jaw:
            turn(jaw, X, R(JAW_K * (jaw_max * v + grin * sm(end, end + 0.4, t))))
    return pose


# Свои жесты (docs/ANIMATION.md: свои анимации, игровые — только если к месту): повороты костей в мире
# (оси сцены: X — вбок, Y — назад от лица, Z — вверх; +X наклоняет вперёд-вниз), (кость, ось, градусы, дрожь°);
# SPINE и HEAD — кости спины и головы этого героя (у Пуджа spine3, у Снайпера Spine_2);
# руку — прицелом: ("aim", плечо, кисть, направление) — кисть ложится на направление при любой стойке.
# Вход 0,25 с с перелётом (рука «выстреливает»), удержание с дрожью кисти, выход 0,45 с.
GESTURES = {
    # «крюк»: рука с крюком выброшена к камере (вперёд, на своей стороне — лицо открыто) и трясёт им, корпус вперёд
    "крюк": [("SPINE", X, 6, 0), ("aim", "bicep_R", "wrist_R", Vector((-0.45, -1, 0.05))), ("wrist_R", X, -15, 10),
             ("HEAD", X, -6, 0)],
    # «тпоза»: всё тело плавно встаёт в позу скелета по умолчанию (Т-поза) — мемная странность (участник: «прикольно»)
    "тпоза": [("TPOSE", None, 0, 0), ("aim", "bicep_L", "wrist_L", Vector((1, 0, 0.05))), ("aim", "elbow_L", "wrist_L", Vector((1, 0, 0.05))),
              ("aim", "bicep_R", "wrist_R", Vector((-1, 0, 0.05))), ("aim", "elbow_R", "wrist_R", Vector((-1, 0, 0.05)))],   # руки в стороны — буква «Т»
    # нелепые позы (участник: «летать без движения, в странных позах выгибаться»)
    "парит": [("LIFT", None, 1.4, 0.08)],                         # поднимается и висит (м, покачивание м), тело застыло
    "выгнуться": [("SPINE", X, -35, 0), ("HEAD", X, -40, 0), ("aim", "bicep_L", "wrist_L", Vector((0.3, 0.8, -0.4))),
                  ("aim", "bicep_R", "wrist_R", Vector((-0.3, 0.8, -0.4)))],   # дуга назад, руки заломлены за спину
    "скрутиться": [("SPINE", Z, 55, 0), ("HEAD", Z, -110, 0)],     # корпус в одну сторону, голова — в другую, как у совы
    "дрожь": [("SPINE", Y, 0, 4), ("HEAD", Z, 0, 6), ("clavicle_L", X, 0, 5), ("clavicle_R", X, 0, 5)],
    # «гордо»: грудь вперёд (корпус назад), подбородок вверх, голова набок — хвастается
    "гордо": [("SPINE", X, -9, 0), ("HEAD", X, -12, 0), ("HEAD", Y, 8, 0)],   # без рук: у Снайпера обе на винтовке
    # «кулак»: свободная рука сжата и поднята к плечу, плечи вверх
    "кулак": [("clavicle_L", X, -10, 0), ("bicep_L", X, -40, 0), ("elbow_L", X, -70, 0), ("wrist_L", X, 10, 6)],
    # «пожал плечами»: обе ключицы вверх, руки чуть в стороны, голова набок
    "плечи": [("clavicle_R", Y, 12, 0), ("clavicle_L", Y, -12, 0), ("bicep_R", Y, 10, 0), ("bicep_L", Y, -10, 0), ("HEAD", Y, 7, 0)],
}


SLOW = {"гордо", "плечи", "тпоза", "парит", "выгнуться", "скрутиться"}   # позы — входят плавно за 0,6 с (иначе голова дёргается)


def gesture_env(t, a, b, slow=False):
    if t <= a or t >= b + 0.45:
        return 0.0
    if slow:
        return sm(a, a + 0.6, t) * (1 - sm(b, b + 0.6, t))
    if t < a + 0.25:
        x = (t - a) / 0.25; c = 1.7; return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2   # ease-out-back: перелёт
    if t <= b:
        return 1.0
    return 1 - sm(b, b + 0.45, t)


TALK = json.loads(os.environ.get("A8_TALK", "[]"))
MOOD = {"down": (14, 22), "up": (-5, -9)}              # (шея, голова) в градусах: наклон вперёд +


def speaker(s):
    pose = talker(s["base"], s["line"], s["off"], s["dur"], head=s["head"], jaw=s.get("jaw"),
                  jaw_max=s.get("jaw_max", 22), nod=s.get("nod", 5 if s.get("jaw") else 7), grin=s.get("grin", 0.0))
    neck = next((b.name for b in arm.pose.bones if "neck" in b.name.lower()), None)
    mood = MOOD.get(s.get("mood"))
    loud = smooth_series(voice(s["line"], s["off"]), int(s["dur"] * FPS))
    # без челюсти голова ещё и покачивается в такт речи — слабо и плавно, как Снайпер в «Крюке»
    sway = soft([(0 if s.get("jaw") else 1.6) * loud[k] * math.sin(k / FPS * 4) for k in range(len(loud))])
    # живое тело (эталон: голова и плечи всё время движутся, но плавно): медленные синусы разных частот — плечи
    # качаются и наклоняются, голова поворачивается и склоняется; lean — на громком подаётся корпусом вперёд (крик)
    live = s.get("live", 1.0); ph = sum(map(ord, s["line"])) % 7
    spine = next((b.name for nm in ("spine3", "spine_2", "spine2", "spine_1", "spine1") for b in arm.pose.bones if b.name.lower() == nm), None)
    push = soft([s.get("lean", 0.0) * v for v in loud], 0.3)
    w = lambda t, *fa: sum(a * math.sin(2 * math.pi * f * t + ph + i * 1.7) for i, (f, a) in enumerate(fa))
    walk = s.get("walk")
    # земля — по стопам в обычной стойке; если поза их поднимает или опускает (шаг, Т-поза), таз сдвигается так,
    # чтобы нижняя стопа стояла на земле (иначе ступни висели в воздухе)
    feet_ground = None; feet = []
    if walk or any(g["kind"] in ("тпоза", "выгнуться") for g in s.get("gest") or []):
        Bf = {b.name.lower(): b.name for b in arm.pose.bones}
        feet = [Bf[n] for n in ("ankle_l", "ankle_r") if n in Bf]
        if feet:
            base_pose(s["base"], 0.0); feet_ground = min(world(a).translation.z for a in feet)

    def plant():
        dz = min(world(a).translation.z for a in feet) - feet_ground
        rb = arm.pose.bones[0]; M = world(rb.name)
        rb.matrix = MW.inverted() @ (Matrix.Translation(Vector((0, 0, -dz))) @ M); bpy.context.view_layer.update()
    if walk:
        # шаг: бедро вперёд-назад, колено сгибается на выносе, стопа ровно, таз качается, руки в противоход, плечи скручиваются;
        # частота — от скорости и длины ноги (шаг 0,7 ноги): ступни не скользят по земле
        B = {b.name.lower(): b.name for b in arm.pose.bones}
        leg = {sd: (B.get(f"thigh_{sd.lower()}") or B.get(f"hip_{sd.lower()}"), B.get(f"knee_{sd.lower()}"), B.get(f"ankle_{sd.lower()}"))
               for sd in ("L", "R")}
        base_pose(s["base"], 0.0)
        thl, ank = leg["L"][0], leg["L"][2]
        ankles = [leg[sd][2] for sd in ("L", "R") if leg[sd][2]]
        Lg = (world(thl).translation - world(ank).translation).length if thl and ank else 1.0
        stride = 0.7 * Lg; wa, wl = walk["at"], walk["len"]

        def stride_walk(t):
            e_ = sm(wa, wa + 0.3, t) * (1 - sm(wa + wl - 0.3, wa + wl, t))
            if e_ <= 0:
                return
            phi = math.pi * walk["v"] / stride * (t - wa)          # один период — два шага
            for sd, sg in (("L", 1), ("R", -1)):
                th, kn, an = leg[sd]
                if not th:
                    continue
                a_th = -26 * sg * math.sin(phi); a_kn = 38 * max(0.0, sg * math.cos(phi)) + 6
                turn(th, X, R(e_ * a_th))
                if kn:
                    turn(kn, X, R(e_ * a_kn))
                if an:
                    turn(an, X, R(-e_ * (a_th + a_kn) * 0.55))
            for nm, sg in (("bicep_l", 1), ("bicep_r", -1)):
                if nm in B:
                    turn(B[nm], X, R(e_ * 16 * sg * math.sin(phi)))
            if spine:
                turn(spine, Z, R(e_ * 5 * math.sin(phi)))
            bpy.context.view_layer.update()

    def full(t, k):
        pose(t, k)
        if mood:
            d = sm(0.1, 1.1, t)                         # входит в настроение за секунду
            if neck:
                turn(neck, X, R(mood[0] * d))
            turn(s["head"], X, R(mood[1] * d))
        if sway[k]:
            turn(s["head"], X, R(sway[k])); turn(s["head"], Z, R(sway[k] * 0.8))
        if live:
            e = sm(0.0, 0.4, t) * sm(s["dur"], s["dur"] - 0.4, t)   # к краям анимации — к стойке, стык без рывка
            if spine:
                turn(spine, X, R(e * live * (w(t, (0.42, 2.5), (0.9, 0.8)) + 9 * push[k])))
                turn(spine, Y, R(e * live * w(t, (0.31, 3.0))))
            turn(s["head"], Z, R(e * live * w(t, (0.27, 6.0), (0.63, 1.5))))
            turn(s["head"], Y, R(e * live * w(t, (0.36, 4.0))))
            turn(s["head"], X, R(e * live * (w(t, (0.5, 1.8)) - 6 * push[k])))
        for g in s.get("gest") or []:                   # свои жесты поверх разговора
            ge = gesture_env(t, g["at"], g["at"] + g["len"], g["kind"] in SLOW)
            if ge:
                for bone, ax, ang, wob in GESTURES[g["kind"]]:
                    bone = {"SPINE": spine, "HEAD": s["head"]}.get(bone, bone)   # спина и голова — какие есть у героя
                    if bone is None:
                        continue
                    if bone == "LIFT":                          # корень скелета вверх: висит в воздухе, лёгкое покачивание
                        rb = arm.pose.bones[0]; M = world(rb.name)
                        up = ge * ang + wob * math.sin(t * 2.2) * min(1.0, ge)
                        rb.matrix = MW.inverted() @ (Matrix.Translation(Vector((0, 0, up))) @ M); bpy.context.view_layer.update()
                    elif bone == "TPOSE":
                        for pb in arm.pose.bones:
                            pb.rotation_mode = "QUATERNION"
                            pb.rotation_quaternion = pb.rotation_quaternion.slerp(Quaternion(), min(1.0, ge))
                            pb.location = pb.location.lerp(Vector(), min(1.0, ge))
                        bpy.context.view_layer.update()
                    elif bone == "aim":
                        if ax in arm.pose.bones and ang in arm.pose.bones:
                            aim(ax, ang, wob, min(1.0, ge))
                    elif bone in arm.pose.bones:
                        turn(bone, ax, R(ge * ang + (wob * math.sin(t * 15) * min(1.0, ge) if wob else 0)))
        if walk:                                        # шаг — после жестов (Т-поза сбрасывала и ноги — Пудж плыл, не шагая)
            stride_walk(t)
        if feet_ground is not None:                     # стопы на земле: Т-поза выпрямляет полусогнутые ноги стойки
            plant()
    return full


CUSTOM = {s["name"]: bake(s["name"], s["dur"], speaker(s)) for s in TALK}
LOOPING = {k: False for k in CUSTOM}
