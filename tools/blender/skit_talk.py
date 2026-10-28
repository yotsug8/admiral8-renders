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


_BN = {b.name.lower(): b.name for b in arm.pose.bones}
ALIAS = {"thigh": "hip", "hip": "thigh", "spine3": "spine_2", "spine_2": "spine3"}   # одна кость — разные имена у героев


def bone(name):
    """Кость героя по имени общего скелета доты (регистр и синонимы не важны: thigh_L у Пуджа = hip_L у Снайпера)."""
    if name is None or name in arm.pose.bones:
        return name
    n = name.lower(); hit = _BN.get(n)
    if not hit:
        stem, _, side = n.rpartition("_")
        hit = _BN.get(f"{ALIAS.get(stem, stem)}_{side}") if stem else _BN.get(ALIAS.get(n, n))
    return hit


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


def bend_axis(th, kn, an):
    """Ось сгиба сустава в текущей позе (колено, локоть) — для leg_ik: сгиб всегда в эту сторону."""
    H = world(th).translation; K = world(kn).translation; A = world(an).translation
    ax = (K - H).cross(A - K); return ax.normalized() if ax.length > 1e-6 else None


def leg_ik(th, kn, an, T, ref=None):
    """Нога (рука) на точку T (мир): колено сгибается на нужное расстояние бедро–стопа, бедро прицелом кладёт стопу на T.
    ref — ось сгиба из стойки (bend_axis): сгиб считается со знаком вокруг неё — почти прямая рука не перескакивает
    сгибом на другую сторону (локоть выворачивался на кадр — рывок)."""
    H = world(th).translation; K = world(kn).translation; A = world(an).translation
    l1, l2 = (K - H).length, (A - K).length
    D = min((T - H).length, 0.995 * (l1 + l2))
    want = math.pi - math.acos(max(-1.0, min(1.0, (l1 * l1 + l2 * l2 - D * D) / (2 * l1 * l2))))   # нужный сгиб
    u, v = (K - H).normalized(), (A - K).normalized()
    if ref is not None:
        cur = math.atan2(u.cross(v).dot(ref), u.dot(v))   # сгиб со знаком вокруг оси стойки
        turn(kn, ref, want - cur)
    else:
        ax = u.cross(v)
        if ax.length > 1e-6:                             # прямую ногу не согнуть — ось сгиба неизвестна
            turn(kn, ax.normalized(), want - u.angle(v))
    aim(th, an, T - world(th).translation, 1.0)


PHASE = 0.0   # с какого места стойки начинается своя анимация (skit.py: где стойка идёт в сцене на её начале), с


def base_pose(action, t):
    ad = arm.animation_data or arm.animation_data_create(); ad.action = ACTS[action]
    try: ad.action_slot = ACTS[action].slots[0]
    except Exception: pass
    a0, a1 = ACTS[action].frame_range                    # как дорожка NLA: от начала действия, по кругу длиной a1 − a0
    f = a0 + ((t + PHASE) * globals().get("IMPORT_FPS", 24.0)) % max(1.0, a1 - a0)   # анимации glb легли в кадры с частотой импорта
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


def bake(name, dur, pose, base=None):
    """Ключи позы покадрово. Знак кватерниона — как у игровой стойки base в тот же миг: у поворота два кватерниона (q и −q),
    при переходе стойка ↔ своя анимация (смешение NLA) с разными знаками середина выворачивала локоть на 180° — рывок."""
    n = int(dur * FPS); keyed = []
    for k in range(n + 1):
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        pose(k / FPS, k)
        keyed.append({pb.name: pb.matrix.copy() for pb in arm.pose.bones})
    act = bpy.data.actions.new(name); ad = arm.animation_data; ad.action = act
    try: ad.action_slot = act.slots.new(id_type="OBJECT", name=arm.name)
    except Exception: pass
    prev = {}
    for k, P in enumerate(keyed):
        ref = {}
        if base:
            base_pose(base, k / FPS); ref = {pb.name: pb.rotation_quaternion.copy() for pb in arm.pose.bones}
            ad = arm.animation_data; ad.action = act
            try: ad.action_slot = act.slots[0]
            except Exception: pass
        sc.frame_set(k)
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        for pb in sorted(arm.pose.bones, key=lambda b: len(b.parent_recursive)):
            pb.matrix = P[pb.name]; bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            q = pb.rotation_quaternion; r = ref.get(pb.name) or prev.get(pb.name)
            if r is not None and q.dot(r) < 0:
                pb.rotation_quaternion = -q
            prev[pb.name] = pb.rotation_quaternion.copy()
            for path in ("location", "rotation_quaternion", "scale"):
                pb.keyframe_insert(path, frame=k)
    act.frame_range = (0, n)
    return act


def talker(base, line, off, dur, jaw_max=22, nod=5, grin=0.0, head="head", jaw="jaw0_0", freeze=False):
    """Говорит: челюсть по громкости, кивок на нарастании громкости; grin — рот чуть приоткрыт после реплики.
    Без челюсти (jaw=None) — только голова: кивки на ударениях."""
    loud = smooth_series(voice(line, off), int(dur * FPS))
    end = off + VOICES[line]["dur"]
    # кивок — только на ударениях (рост громкости), слабый и сглаженный 0,25 с: без рывков
    nods = soft([(nod * max(0.0, loud[k] - loud[max(0, k - 3)]) * 3 + 2 * loud[k]) / 3.5 for k in range(len(loud))])

    base_pose(base, 0.0)                                 # покачивание головы самой стойки — приглушить к её начальной позе
    calm = {b.name: b.rotation_quaternion.copy() for b in arm.pose.bones if b.name == head or "neck" in b.name}

    def pose(t, k):
        base_pose(base, 0.0 if freeze else t)          # замер: стойка на одном кадре, тело не шевелится
        for nm, q in calm.items():
            b = arm.pose.bones[nm]; b.rotation_quaternion = b.rotation_quaternion.slerp(q, 0.65)
        bpy.context.view_layer.update()
        v = loud[k]
        if freeze:                                      # замер: ни кивков, ни челюсти костью — только лицо (морфы)
            return
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
    # «указать»: прямая рука на собеседника (вперёд, чуть к своей стороне), корпус подаётся следом — на «ты»
    "указать": [("SPINE", X, 5, 0), ("aim", "bicep_L", "wrist_L", Vector((0.3, -1, 0.12))),
                ("aim", "elbow_L", "wrist_L", Vector((0.3, -1, 0.12))), ("HEAD", X, -3, 0)],
    # «себя»: рука к груди (плечо вниз-вперёд, предплечье поперёк к середине груди), подбородок вверх — на «я»
    "себя": [("aim", "bicep_L", "elbow_L", Vector((0.35, -0.55, -0.75))), ("aim", "elbow_L", "wrist_L", Vector((-0.9, -0.35, 0.3))),
             ("SPINE", X, -4, 0), ("HEAD", X, -6, 0)],
    "себя_грудь": [("SPINE", X, -10, 0), ("HEAD", X, -12, 0), ("clavicle_L", X, 8, 0), ("clavicle_R", X, 8, 0)],   # с оружием в руке:
                                                                                  # грудь колесом, плечи назад, подбородок вверх
    # «крюк»: рука с крюком выброшена к камере (вперёд, на своей стороне — лицо открыто) и трясёт им, корпус вперёд
    "крюк": [("SPINE", X, 6, 0), ("aim", "bicep_R", "wrist_R", Vector((-0.45, -1, 0.05))), ("wrist_R", X, -15, 10),
             ("HEAD", X, -6, 0)],
    # «тпоза»: всё тело плавно встаёт в позу скелета по умолчанию (Т-поза) — мемная странность (участник: «прикольно»)
    # только руки прицелом: сброс всех костей в позу по умолчанию выворачивал ноги и отрывал оружие от кисти
    "тпоза": [("aim", "bicep_L", "wrist_L", Vector((1, 0, 0.05))), ("aim", "elbow_L", "wrist_L", Vector((1, 0, 0.05))),
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


SLOW = {"указать", "себя", "себя_грудь", "гордо", "плечи", "тпоза", "парит", "выгнуться", "скрутиться"}   # позы — входят плавно за 0,6 с (иначе голова дёргается)


# жесты из нескольких поз подряд: (с от начала, вход за с, поза); последняя держится до конца жеста и уходит за 0,45 с
SEQ = {
    # «отмахнуться»: кисть перед собой — и отброшена в сторону наружу, голова отворачивается
    "отмахнуться": [(0.0, 0.4, [("aim", "bicep_L", "wrist_L", Vector((0.25, -1, 0.1))), ("aim", "elbow_L", "wrist_L", Vector((-0.2, -1, 0.3)))]),
                    (0.5, 0.45, [("aim", "bicep_L", "wrist_L", Vector((1, -0.35, -0.1))), ("aim", "elbow_L", "wrist_L", Vector((1, -0.2, 0.2))),
                                 ("HEAD", Z, -12, 0)])],
    # «замах»: крюк заносится назад-вверх за плечо (корпус скручен вправо, голова держит собеседника), пауза — и бросок
    # вперёд с перелётом (корпус раскручивается, подаётся вперёд); правая рука — крюк, левая с тесаком не трогается
    "замах": [(0.0, 0.5, [("SPINE", Z, -24, 0), ("aim", "bicep_R", "wrist_R", Vector((-0.55, 0.45, 0.75))), ("HEAD", Z, 14, 0)]),
              # сбоку: рука уходит вбок от плеча — иначе по пути от заноса к броску крюк проходил сквозь спину и голову
              (0.75, 0.15, [("SPINE", Z, -6, 0), ("aim", "bicep_R", "wrist_R", Vector((-1, -0.15, 0.35))), ("HEAD", Z, 6, 0)]),
              (0.9, 0.3, [("SPINE", Z, 14, 0), ("SPINE", X, 9, 0), ("aim", "bicep_R", "wrist_R", Vector((-0.55, -1, -0.1))),
                          ("wrist_R", X, 30, 0),   # кисть вперёд: крюк острием к цели, а не вверх
                          ("HEAD", Z, -8, 0)])],
}


def seq_env(t, a, b, phases, i):
    """Вес i-й позы жеста SEQ в момент t: входит за свой вход (бросок — с перелётом), уходит, когда входит следующая."""
    s0, sin_, _ = phases[i]; s0 += a
    if t <= s0:
        return 0.0
    x = min(1.0, (t - s0) / sin_)
    w = sm(0, 1, x) * (1 + 0.12 * math.sin(math.pi * x)) if i else sm(0, 1, x)   # плавный вход, лёгкий перелёт (резкий старт — рывок)
    if i + 1 < len(phases):
        n0 = a + phases[i + 1][0]; w *= 1 - sm(n0, n0 + phases[i + 1][1], t)
    else:
        w *= 1 - sm(b, b + 0.45, t)
    return w


def gesture_env(t, a, b, slow=False):
    if t <= a or t >= b + (0.6 if slow else 0.45):      # медленная поза уходит за 0,6 с — не обрывать раньше (рывок головы)
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
    global PHASE
    PHASE = s.get("phase", 0.0)
    pose = talker(s["base"], s["line"], s["off"], s["dur"], head=s["head"], jaw=s.get("jaw"),
                  jaw_max=s.get("jaw_max", 22), nod=s.get("nod", 5 if s.get("jaw") else 7), grin=s.get("grin", 0.0),
                  freeze=bool(s.get("freeze")))
    neck = next((b.name for b in arm.pose.bones if "neck" in b.name.lower()), None)
    mood = MOOD.get(s.get("mood"))
    loud = smooth_series(voice(s["line"], s["off"]), int(s["dur"] * FPS))
    # без челюсти голова ещё и покачивается в такт речи — слабо и плавно, как Снайпер в «Крюке»
    sway = soft([(0 if s.get("jaw") or s.get("freeze") else 1.6) * loud[k] * math.sin(k / FPS * 4) for k in range(len(loud))])
    # живое тело (эталон: голова и плечи всё время движутся, но плавно): медленные синусы разных частот — плечи
    # качаются и наклоняются, голова поворачивается и склоняется; lean — на громком подаётся корпусом вперёд (крик)
    live = 0.0 if s.get("freeze") else s.get("live", 1.0); ph = sum(map(ord, s["line"])) % 7
    spine = next((b.name for nm in ("spine3", "spine_2", "spine2", "spine_1", "spine1") for b in arm.pose.bones if b.name.lower() == nm), None)
    push = soft([s.get("lean", 0.0) * v for v in loud], 0.3)
    w = lambda t, *fa: sum(a * math.sin(2 * math.pi * f * t + ph + i * 1.7) for i, (f, a) in enumerate(fa))
    walk = s.get("walk")
    tpose = any(g["kind"] == "тпоза" for g in s.get("gest") or [])
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
        Lg = (world(thl).translation - world(ank).translation).length if thl and ank else 1.0
        stride = 0.7 * Lg; wa, wl = walk["at"], walk["len"]
        # переваливание (тяжёлый герой): вес на опорную ногу — таз к ней, корпус над ней, голова ровнее корпуса,
        # ноги шире; жир (живот, грудь, спина) колышется за тазом с запаздыванием; waddle — сила (1 — Пудж)
        wd = walk.get("waddle", 0.0)
        sL = 1.0 if not (leg["L"][2] and leg["R"][2]) or world(leg["L"][2]).translation.x > world(leg["R"][2]).translation.x else -1.0
        fat = [(B[n], a, lag) for n, a, lag in (("stomach1_0", 7, 0.9), ("booby_lf", 9, 1.3), ("booby_rt", 9, 1.3),
                                                ("backfat5_0", 5, 1.1), ("backfat7_0", 5, 1.1)) if n in B]
        pelvis = B.get("spine1")

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
                if nm in B and not tpose:                   # в Т-позе руки при шаге не качаются
                    turn(B[nm], X, R(e_ * 16 * (1 - 0.6 * wd) * sg * math.sin(phi)))   # тяжёлые качают руками меньше
            if spine:
                turn(spine, Z, R(e_ * 5 * math.sin(phi)))
            if wd:
                wL = -math.cos(phi)                              # +1 — вес на левой (правая на выносе), −1 — на правой
                for sd, sg in (("L", 1), ("R", -1)):             # ноги шире: бедро наружу
                    if leg[sd][0]:
                        turn(leg[sd][0], Y, R(e_ * wd * 5 * sg * sL))
                if pelvis:                                       # корпус над опорной ногой
                    turn(pelvis, Y, R(e_ * wd * 7 * sL * wL))
                turn(s["head"], Y, R(-e_ * wd * 5 * sL * wL))   # голова держится ровнее
                rb = arm.pose.bones[0]; M = world(rb.name)       # таз к опорной ноге
                rb.matrix = MW.inverted() @ (Matrix.Translation(Vector((e_ * wd * 0.06 * Lg * sL * wL, 0, 0))) @ M)
                bpy.context.view_layer.update()
                for b, a, lag in fat:                            # подскок таза — два раза за период; жир догоняет
                    turn(b, X, R(e_ * wd * a * math.cos(2 * phi - lag)))
            bpy.context.view_layer.update()

    tn = s.get("turn")
    if tn:
        # поворот на месте (корень героя поворачивается в render_scene по ключам skit.py тем же плавным ходом):
        # голова ведёт, корпус за ней, ноги переступают — стопа стоит на земле, пока не шагнёт (в скелете её держит
        # обратный поворот), шаг — подъём и перенос на новый угол; первой шагает нога со стороны поворота.
        # Больше 100° — в два круга шагов (иначе нога перекручивается)
        legs_t = [tuple(bone(f"{p}_{sd}") for p in ("thigh", "knee", "ankle")) for sd in ("l", "r")]
        legs_t = [l for l in legs_t if all(l)]
        base_pose(s["base"], 0.0)
        Lt = (world(legs_t[0][0]).translation - world(legs_t[0][2]).translation).length if legs_t else 1.0
        ta, tl, tg = tn["at"], tn["len"], tn["ang"]
        if legs_t:                                       # первой — нога со стороны поворота (влево — левая, она у +X)
            legs_t.sort(key=lambda l: -world(l[2]).translation.x * (1 if tg > 0 else -1))
        rounds = max(1, math.ceil(abs(tg) / 100))
        neck_t = next((b.name for b in arm.pose.bones if "neck" in b.name.lower()), None)

        def turn_body(t):
            if t <= ta - 0.15 or t >= ta + tl + 0.05:
                return
            psi = tg * sm(ta, ta + tl, t)                 # корень уже повёрнут на столько
            head_lead = tg * sm(ta - 0.15, ta + 0.55 * tl, t) - psi   # голова первой
            spine_lead = tg * sm(ta - 0.08, ta + 0.8 * tl, t) - psi
            for i, (th, kn, an) in enumerate(legs_t):
                T = tl / rounds; phi = 0.0; lift = 0.0
                for r in range(rounds):
                    a0_ = ta + r * T + (0.02 if i == 0 else 0.52) * T; b0_ = a0_ + 0.46 * T   # ноги по очереди, без прыжка
                    phi += tg / rounds * sm(a0_, b0_, t)
                    if a0_ < t < b0_:
                        lift = math.sin(math.pi * (t - a0_) / (b0_ - a0_))
                d = R(phi - psi)
                if abs(d) < 1e-4 and not lift:
                    continue
                Ma = world(an); p = Ma.translation.copy()
                Rz = Matrix.Rotation(d, 4, Z)
                T_ = Rz @ Vector((p.x, p.y, 0)) + Vector((0, 0, p.z + 0.09 * Lt * lift))
                leg_ik(th, kn, an, T_)
                q = Rz @ Matrix.Translation(-p) @ Ma            # стопа плоско, носком на свой угол
                arm.pose.bones[an].matrix = MW.inverted() @ (Matrix.Translation(world(an).translation) @ q)
                bpy.context.view_layer.update()
            if spine:
                turn(spine, Z, R(spine_lead))
            if neck_t:
                turn(neck_t, Z, R(0.4 * (head_lead - spine_lead)))
            turn(s["head"], Z, R(0.6 * (head_lead - spine_lead)))

    arm_l = tuple(bone(f"{p}_L") for p in ("bicep", "elbow", "wrist"))
    arm_r = tuple(bone(f"{p}_R") for p in ("bicep", "elbow", "wrist"))

    WRIST_OUT = float(os.environ.get("A8_WRIST_OUT", 80))   # подобрано по проверке пересечений (A8_CLIP): 80° — тесак Пуджа мимо головы

    def contact(g, t):
        """Касание собеседника (skit.py, CONTACT): рука прицелом (aim, плавный поворот — расчёт кисти на точку дёргал
        локоть) на точку target на нём (оси скелета); не достаёт — наклон корпуса к нему (до 35°).
        «хлопнуть»: левая рука на его плечо за 0,6 с, два мягких хлопка кистью (CONTACT_PATS в skit.py), назад;
        «толкнуть»: обе руки к нему за 0,4 с, корпус вперёд, держит 0,25 с, назад за 0,5 с (резче — дёргало, участник)."""
        a = g["at"]; T = Vector(g["target"])
        if g["kind"] == "хлопнуть":
            e_ = sm(a, a + 0.6, t) * (1 - sm(a + 1.4, a + 1.9, t))
            pat = sum(math.sin(math.pi * (t - a - tp) / 0.3) ** 2 for tp in (0.7, 1.05) if 0 < t - a - tp < 0.3)
            hands = [(arm_l, T)]
        else:                                            # толкнуть
            e_ = sm(a, a + 0.4, t) * (1 - sm(a + 0.65, a + 1.15, t)); pat = 0.0
            hands = [(arm_l, T + Vector((0.18, 0, 0))), (arm_r, T + Vector((-0.18, 0, 0)))]
        if g["kind"] == "толкнуть_корпусом":           # оружие в двух руках (винтовка Снайпера): руки не вытянуть — толкает
            hands = []                                   # корпусом с оружием вперёд
        if e_ <= 0:
            return
        lean = {"толкнуть": 10.0, "толкнуть_корпусом": 12.0}.get(g["kind"], 0.0)   # сильнее — оружие уходит в своё тело
        if not hands:
            if spine:
                turn(spine, X, R(e_ * lean))
            turn(s["head"], X, R(-e_ * 10))
            return
        bi, el, wr = hands[0][0]
        if spine and bi and el and wr:                   # не достаёт — наклон корпуса к собеседнику
            L = (world(el).translation - world(bi).translation).length + (world(wr).translation - world(el).translation).length
            S = world(bi).translation; dz = max(0.3, S.z - world(spine).translation.z + 0.5)
            lack = (hands[0][1] - S).length - 0.95 * L
            lean = max(lean, min(35.0, math.degrees(lack / dz)) if lack > 0 else 0.0)
        if spine and lean:
            turn(spine, X, R(e_ * lean))
        for (bi, el, wr), P in hands:
            if bi and el and wr:
                d = P - world(bi).translation
                aim(bi, wr, d, e_); aim(el, wr, d, 0.8 * e_)   # рука почти прямая к цели
                turn(wr, Y, R(WRIST_OUT * e_ * (1 if wr == arm_l[2] else -1)))   # оружие в кисти — наружу, не в свою голову
                if pat:                                         # хлопок — всей рукой вверх-вниз (кистью тесак бил в свою спину)
                    turn(bi, X, R(-8 * pat))

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
            if g.get("target"):
                contact(g, t); continue
            if g["kind"] in SEQ:
                ph = SEQ[g["kind"]]
                poses = [(seq_env(t, g["at"], g["at"] + g["len"], ph, i), ph[i][2]) for i in range(len(ph))]
            else:
                poses = [(gesture_env(t, g["at"], g["at"] + g["len"], g["kind"] in SLOW), GESTURES[g["kind"]])]
            for ge, gp in poses:
                if not ge:
                    continue
                for bn, ax, ang, wob in gp:
                    bn = {"SPINE": spine, "HEAD": s["head"]}.get(bn, bn)   # спина и голова — какие есть у героя
                    if bn is None:
                        continue
                    if bn == "LIFT":                            # корень скелета вверх: висит в воздухе, лёгкое покачивание
                        rb = arm.pose.bones[0]; M = world(rb.name)
                        up = ge * ang + wob * math.sin(t * 2.2) * min(1.0, ge)
                        rb.matrix = MW.inverted() @ (Matrix.Translation(Vector((0, 0, up))) @ M); bpy.context.view_layer.update()
                    elif bn == "aim":
                        if bone(ax) and bone(ang):
                            aim(bone(ax), bone(ang), wob, min(1.0, ge))
                    elif bone(bn):
                        turn(bone(bn), ax, R(ge * ang + (wob * math.sin(t * 15) * min(1.0, ge) if wob else 0)))
        if walk:                                        # шаг — после жестов (Т-поза сбрасывала и ноги — Пудж плыл, не шагая)
            stride_walk(t)
            if s.get("recoil") and spine:               # отшатнулся от толчка: корпус и голова назад, руки чуть в стороны
                r_ = sm(walk["at"], walk["at"] + 0.25, t) * (1 - sm(walk["at"] + walk["len"], walk["at"] + walk["len"] + 0.6, t))
                turn(spine, X, R(-14 * r_)); turn(s["head"], X, R(-8 * r_))
        if tn:
            turn_body(t)
        if feet_ground is not None:                     # стопы на земле: Т-поза выпрямляет полусогнутые ноги стойки
            plant()
    return full


CUSTOM = {s["name"]: bake(s["name"], s["dur"], speaker(s), s["base"]) for s in TALK}
LOOPING = {k: False for k in CUSTOM}
