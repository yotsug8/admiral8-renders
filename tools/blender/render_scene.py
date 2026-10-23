# Рендер сцены площадки в Blender: тот же сценарий, что в движке доты, но «киношная» картинка —
# свет (тёплое солнце + холодный контровой), небо, деревья карты на своих местах, размытие фона, герои с текстурами.
# Сцена — из stage.dump_json (положения покадрово, анимации, камера, на кого резкость).
# blender -b --factory-startup -P tools/blender/render_scene.py -- <scene.json> <папка кадров> [кадры: все | 75,150,300] [half]
#   half — пробные кадры в половинном размере
import bpy, sys, os, json, math, re
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
SCENE, OUT = os.path.abspath(args[0]), os.path.abspath(args[1])   # Blender пишет относительные пути от корня диска
PICK = None if len(args) < 3 or args[2] in ("all", "") else [int(x) for x in args[2].split(",")]
HALF = len(args) > 3 and args[3] == "half"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RND = os.path.join(REPO, "_game", "models", "render")
TROUPE = json.load(open(os.path.join(REPO, "_game", "data", "troupe.json"), encoding="utf-8"))
D = json.load(open(SCENE, encoding="utf-8"))
FPS = D["fps"]; N = D["frames"]
S = 1 / 39.37                                         # единица игры → метр (так выгружены модели)
BASE = min(k[0][2] for k in (a["keys"] for a in D["actors"].values()))   # уровень земли под героями
FOV_Y = 66.3                                          # как у камеры доты: планы автокамеры совпадут

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = FPS                                   # до импорта: анимации glb лягут в кадры 30 в секунду


MAP = D.get("map")                                    # кусок настоящей карты (tools/map_crop.mjs) — оси как у выгрузки карты


def W(x, y, z):
    if MAP:                                           # Blender x = игра y, Blender y = −игра x (так выгружена карта)
        return Vector((y * S, -x * S, z * S))
    return Vector((x * S, y * S, (z - BASE) * S))


YAW0 = 0 if MAP else 90                               # поворот модели: при осях карты поворот доты переходит как есть


def imp(path):
    before = set(bpy.data.objects); acts = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=path, bone_heuristic="BLENDER")
    new = [o for o in bpy.data.objects if o not in before]
    for o in [o for o in new if o.type == "MESH" and o.name.startswith("Icosphere")]:
        bpy.data.objects.remove(o)
    new = [o for o in bpy.data.objects if o not in before]
    return new, [a for a in bpy.data.actions if a not in acts]


def glb_of(model):
    return os.path.join(RND, model.replace("/", "_").replace(".vmdl", ".glb"))


# ---------- герои
ACTORS = {}
HERO_OBJS = set()                                     # всё, из чего собраны герои: луч камеры сквозь них не проверяется
for name, a in D["actors"].items():
    if not a["hero"]:
        continue
    info = TROUPE[a["hero"]]
    objs, acts = imp(os.path.join(RND, os.path.basename(info["glb"])))   # с текстурами
    HERO_OBJS.update(objs)
    arm = next(o for o in objs if o.type == "ARMATURE")
    ACTS = {re.sub(r"\.\d{3}$", "", x.name): x for x in acts}
    PARTS = []
    root = bpy.data.objects.new(name + "_root", None); sc.collection.objects.link(root)
    arm.parent = root
    for p in a["parts"] or []:
        if not os.path.exists(glb_of(p)):
            continue
        po, _ = imp(glb_of(p)); HERO_OBJS.update(po)
        # как в игре (bone merge): скелет части остаётся, его кости с теми же именами повторяют кости тела,
        # свои кости части (шапка, борода, полы плаща) едут за ними — иначе такие куски отрываются и пропадают
        for pa in [o for o in po if o.type == "ARMATURE"]:
            for pb in pa.pose.bones:
                if pb.name in arm.pose.bones:
                    c = pb.constraints.new("COPY_TRANSFORMS"); c.target = arm; c.subtarget = pb.name
            pa.parent = arm.parent; pa.matrix_world = arm.matrix_world.copy()
            PARTS.append(pa)
    for pa in PARTS:
        pa.parent = root; pa.matrix_world = arm.matrix_world.copy()
    # свои анимации (рот под голос и т. п.) — тем же скриптом, что для доты
    if any(str(x[1]).startswith("a8_") for x in a["anims"]):
        os.environ["A8_WHO"] = a["hero"]
        g = {"arm": arm, "sc": sc, "ACTS": ACTS, "FPS": FPS, "IMPORT_FPS": FPS, "__file__": os.path.join(REPO, "tools", "blender", "hook_talk.py")}
        exec(compile(open(g["__file__"], encoding="utf-8").read(), g["__file__"], "exec"), g)
        ACTS.update(g["CUSTOM"])
    ACTORS[name] = dict(arm=arm, root=root, acts=ACTS, info=info)

    # анимации — дорожками NLA: каждая следующая поверх, разовые держат последний кадр
    ad = arm.animation_data or arm.animation_data_create(); ad.action = None
    an = sorted(a["anims"], key=lambda x: float(x[0]))
    for i, x in enumerate(an):
        t0 = float(x[0]); nm = str(x[1]); rate = float(x[2]) if len(x) > 2 else 1.0
        t1 = float(an[i + 1][0]) if i + 1 < len(an) else D["dur"] + 1
        act = ACTS.get(nm) or ACTS.get(nm + "_anim")
        if act is None:
            print("  нет анимации", name, nm); continue
        tr = ad.nla_tracks.new(); tr.name = f"{i:02d}_{nm}"
        st = tr.strips.new(nm, int(round(t0 * FPS)), act)
        st.scale = 1.0 / rate
        length = (act.frame_range[1] - act.frame_range[0]) * st.scale
        seg = (t1 - t0) * FPS
        loop = any(k in nm for k in ("idle", "run", "flail", "portrait", "stun", "walk"))
        if loop and length > 0:
            st.repeat = max(1.0, seg / length)
        st.extrapolation = "HOLD_FORWARD"
        st.blend_type = "REPLACE"
    # положение и поворот покадрово (модель смотрит в −Y, поворот доты 0 — на восток)
    for f, (x, y, z, pi, ya, ro) in enumerate(a["keys"]):
        root.location = W(x, y, z); root.rotation_euler = (0, 0, math.radians(ya + YAW0))
        root.keyframe_insert("location", frame=f); root.keyframe_insert("rotation_euler", frame=f)

# ---------- цепь крюка: от правой руки Пуджа (weapon_rt_1) к острию (актёр tip)
for t0, fxname, at, z, dur, *rest in D["fx"]:
    to = rest[0] if rest else None
    if "meathook" not in fxname or not to or at[0] not in ACTORS:
        continue
    arm = ACTORS[at[0]]["arm"]; pb = arm.pose.bones.get("weapon_rt_1") or arm.pose.bones.get("wrist_R")
    f0, f1 = int(round(t0 * FPS)), int(round((t0 + dur) * FPS))
    bpy.ops.mesh.primitive_torus_add(major_radius=0.13, minor_radius=0.035, rotation=(math.radians(90), 0, 0))
    link = bpy.context.object; link.name = "chain"
    metal = bpy.data.materials.new("chain"); metal.use_nodes = True
    b = next(n for n in metal.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (0.05, 0.045, 0.04, 1); b.inputs["Metallic"].default_value = 1; b.inputs["Roughness"].default_value = 0.35
    link.data.materials.append(metal)
    arr = link.modifiers.new("arr", "ARRAY"); arr.fit_type = "FIT_LENGTH"; arr.relative_offset_displace = (0.72, 0, 0)
    bpy.ops.mesh.primitive_cone_add(radius1=0.16, depth=0.55, rotation=(0, math.radians(90), 0))
    head = bpy.context.object; head.name = "hook_head"
    redm = bpy.data.materials.new("hook"); redm.use_nodes = True
    b = next(n for n in redm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (0.35, 0.05, 0.04, 1); b.inputs["Metallic"].default_value = 0.8; b.inputs["Roughness"].default_value = 0.3
    head.data.materials.append(redm)
    tipk = D["actors"][to]["keys"]
    for f in range(max(0, f0 - 1), min(N, f1 + 2)):
        on = f0 <= f <= f1
        sc.frame_set(f)
        hand = arm.matrix_world @ pb.head
        tp = W(*tipk[f][:3])
        v = tp - hand; L = max(v.length, 0.01)
        link.location = hand; link.rotation_euler = v.to_track_quat("X", "Z").to_euler()
        arr.fit_length = L
        head.location = tp; head.rotation_euler = v.to_track_quat("X", "Z").to_euler()
        for o in (link, head):
            o.hide_render = not on; o.keyframe_insert("hide_render", frame=f)
            o.keyframe_insert("location", frame=f); o.keyframe_insert("rotation_euler", frame=f)
        arr.keyframe_insert("fit_length", frame=f)
    for f in (0, N - 1):
        for o in (link, head):
            o.hide_render = True; o.keyframe_insert("hide_render", frame=f)

# ---------- земля: настоящая карта (если есть) или поле; деревья карты; небо
MAP_HAS_TREES = False
if MAP:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import dota_map
    mobjs = dota_map.load(os.path.join(REPO, "_game", MAP), os.path.join(REPO, "_game", "world"),
                         ground_z=min(W(*a["keys"][0][:3]).z for a in D["actors"].values()))
    MAP_HAS_TREES = any("tree" in o.name.lower() for o in mobjs)
    print("  карта:", MAP, "объектов", len(mobjs), "деревья в карте" if MAP_HAS_TREES else "деревьев в карте нет")
else:
    bpy.ops.mesh.primitive_plane_add(size=400, location=(D["actors"][next(iter(D["actors"]))]["keys"][0][0] * S,
                                                        D["actors"][next(iter(D["actors"]))]["keys"][0][1] * S, -0.02))
    ground = bpy.context.object; gm = bpy.data.materials.new("ground"); gm.use_nodes = True; nt = gm.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (90, 90, 90)
    img = nt.nodes.new("ShaderNodeTexImage"); img.image = bpy.data.images.load(os.path.join(REPO, "assets", "tex", "forest.jpg"))
    nt.links.new(tc.outputs["UV"], mp.inputs["Vector"]); nt.links.new(mp.outputs["Vector"], img.inputs["Vector"])
    noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 0.35; noise.inputs["Detail"].default_value = 6
    grass = nt.nodes.new("ShaderNodeValToRGB")                      # трава: два оттенка зелёного пятнами
    grass.color_ramp.elements[0].color = (0.07, 0.17, 0.03, 1); grass.color_ramp.elements[1].color = (0.20, 0.34, 0.06, 1)
    nt.links.new(noise.outputs["Fac"], grass.inputs["Fac"])
    mix = nt.nodes.new("ShaderNodeMixRGB"); mix.blend_type = "OVERLAY"; mix.inputs["Fac"].default_value = 0.6   # трава + фактура земли
    nt.links.new(grass.outputs["Color"], mix.inputs["Color1"]); nt.links.new(img.outputs["Color"], mix.inputs["Color2"])
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.25
    nt.links.new(img.outputs["Color"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = 0.95; ground.data.materials.append(gm)

trees = [] if MAP_HAS_TREES else json.load(open(os.path.join(os.path.dirname(SCENE), "trees.json"), encoding="utf-8"))
tcol = {}
for x, y, z, model, yaw, scale in trees:
    if model not in tcol:
        c = bpy.data.collections.new(os.path.basename(model)); objs, _ = imp(glb_of(model))
        for o in objs:
            for uc in list(o.users_collection):
                uc.objects.unlink(o)
            c.objects.link(o)
        tcol[model] = c
    e = bpy.data.objects.new("tree", None); e.instance_type = "COLLECTION"; e.instance_collection = tcol[model]
    sc.collection.objects.link(e); e.location = W(x, y, z); e.rotation_euler = (0, 0, math.radians(yaw + YAW0 - 90)); e.scale = (scale,) * 3

world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True; wn = world.node_tree
bg = next(n for n in wn.nodes if n.type == "BACKGROUND")
tcw = wn.nodes.new("ShaderNodeTexCoord"); sep = wn.nodes.new("ShaderNodeSeparateXYZ")
skyr = wn.nodes.new("ShaderNodeValToRGB")
skyr.color_ramp.elements[0].position = 0.0; skyr.color_ramp.elements[0].color = (0.42, 0.60, 0.86, 1)   # у горизонта
skyr.color_ramp.elements[1].position = 0.35; skyr.color_ramp.elements[1].color = (0.08, 0.26, 0.74, 1)  # зенит
wn.links.new(tcw.outputs["Generated"], sep.inputs["Vector"]); wn.links.new(sep.outputs["Z"], skyr.inputs["Fac"])
wn.links.new(skyr.outputs["Color"], bg.inputs["Color"]); bg.inputs["Strength"].default_value = 0.9


def light(kind, rot, energy, color):
    d = bpy.data.lights.new(kind + str(energy), kind); d.energy = energy; d.color = color
    o = bpy.data.objects.new(d.name, d); sc.collection.objects.link(o); o.rotation_euler = [math.radians(a) for a in rot]
    return o
light("SUN", (50, 0, 45), 4.6, (1.0, 0.84, 0.64))          # тёплое солнце с юго-востока (камеры в основном с юга)
light("SUN", (68, 0, -150), 4.2, (0.58, 0.74, 1.0))         # холодный контровой с северо-запада — обводит силуэты
LIGHT_KEY, LIGHT_RIM = 900, 1400                            # свет плана (Вт): ключевой у камеры, контровой за героем

# ---------- камера
# Если в сцене есть планы (shots: [начало, план, кто, на кого, настройки]) — камера и свет плана считаются здесь,
# по настоящим костям головы (лица крупно, у каждого плана свой объектив). Иначе — камера доты из сцены как есть.
#   close  кто            крупно: голова и плечи, глаза в верхней трети, сбоку-спереди (ang, °), чуть снизу
#   over   кто, на_кого   через плечо «кто» на «на_кого», длинный объектив сжимает расстояние между ними
# Камера всегда с южной стороны от линии героев (правило 180°). Свет плана: мягкий ключевой сбоку от камеры
# и холодный контровой из-за героя плана — лица светлые и обведены, как в примерах.
cam_d = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_d); sc.collection.objects.link(cam); sc.camera = cam
cam_d.sensor_fit = "VERTICAL"; cam_d.angle_y = math.radians(FOV_Y); cam_d.clip_start = 0.05; cam_d.clip_end = 400
cam_d.dof.use_dof = True


def hand_held(f):
    tt = f / FPS                                       # «с рук»: медленное дыхание кадра, без тряски
    cam.rotation_euler.x += math.radians(0.35 * math.sin(tt * 1.3) + 0.15 * math.sin(tt * 3.1))
    cam.rotation_euler.z += math.radians(0.30 * math.sin(tt * 0.9 + 1.0) + 0.12 * math.sin(tt * 2.7))


def head(name, f):
    """Глаза героя в кадре f (кость головы) и куда он смотрит (по горизонтали)."""
    A = ACTORS[name]; sc.frame_set(f)
    pb = A["arm"].pose.bones.get(A["info"].get("head_bone") or "head")
    h = A["arm"].matrix_world @ pb.head
    face = A["root"].matrix_world.to_3x3() @ Vector((0, -1, 0)); face.z = 0
    return h, face.normalized()


def avg_head(name, f0, f1):
    hs = [head(name, f) for f in range(f0, max(f0 + 1, f1), 6)]
    return sum((h for h, _ in hs), Vector()) / len(hs), hs[0][1]


def rotz(v, deg):
    a = math.radians(deg); return Vector((v.x * math.cos(a) - v.y * math.sin(a), v.x * math.sin(a) + v.y * math.cos(a), v.z))


def clear(cands, aims, who):
    """Позиция камеры, откуда лучи к героям чистые. Если на луче только деревья карты — их убираем на время плана
    (киношный приём: кадр важнее дерева); камни и здания не трогаем — тогда следующий вариант."""
    dg = bpy.context.evaluated_depsgraph_get()
    for C in cands:
        hits = set()
        for P in aims:
            o_ = C.copy()
            for _ in range(12):                        # все помехи на луче, не только первая
                d = P - o_
                if d.length < 0.8:
                    break
                hit, loc, nor, idx, obj, _m = sc.ray_cast(dg, o_, d.normalized(), distance=d.length - 0.8)
                if not hit:
                    break
                if obj.original not in HERO_OBJS:
                    hits.add(obj.original)
                o_ = loc + d.normalized() * 0.02
        if all("tree" in h.name.lower() for h in hits):
            if hits:
                print(f"    камера {who}: убираю на план деревья", sorted(h.name for h in hits))
            return C, hits
        print(f"    камера {who}: луч задевает", sorted(h.name for h in hits)[:3], "— другой вариант")
    return cands[0], set()


SOUTH = lambda v: -v.x                                 # юг карты (игра −y) — это −x в Blender
SHOTS = sorted(D.get("shots") or [], key=lambda x: x[0])
plans = []                                             # (f0, f1, позиция, точка взгляда, угол, резкость на, точка резкости, f-число, герой света)
for i, (t0, kind, who, other, o) in enumerate(SHOTS):
    f0 = int(round(t0 * FPS)); f1 = int(round(SHOTS[i + 1][0] * FPS)) if i + 1 < len(SHOTS) else N
    fov = math.radians(o.get("fov", 40))
    if kind == "close":
        H, face = avg_head(who, f0, f1)
        hz = ACTORS[who]["info"]["head_z"] * S
        vis = o.get("size", 0.42) * hz                 # высота кадра: от груди до макушки
        d = vis / (2 * math.tan(fov / 2))
        ang = o.get("ang", 35)
        def at(a_):
            C = max((H + rotz(face, sg * a_) * d for sg in (1, -1)), key=SOUTH)
            C.z = H.z - 0.06 * d                       # чуть снизу — герой весомее
            return C
        C, hide = clear([at(a_) for a_ in (ang, ang + 15, ang - 15, ang + 30)], [H], who)
        T = H - Vector((0, 0, vis * 0.17))             # глаза — в верхней трети
        plans.append((f0, f1, C, T, fov, who, H, o.get("fstop", 1.2), who, hide))
    else:                                              # over
        F, _ = avg_head(who, f0, min(f1, f0 + 6)); B, _ = avg_head(other, f0, min(f1, f0 + 6))
        u = F - B; u.z = 0; u.normalize(); n = Vector((-u.y, u.x, 0))
        n = n if SOUTH(n) > 0 else -n
        # передний — у края кадра (x_f доли полукадра), дальний — по другую сторону (x_b): отступ назад b подбирается,
        # сбоку — на ширину плеч переднего; чем длиннее объектив, тем дальше камера и тем крупнее дальний
        def at(side):
            s_ = ACTORS[who]["info"].get("radius", 60) * S * side
            tx = math.tan(fov / 2) * 9 / 16
            xf, xb = o.get("xf", 0.55), o.get("xb", -0.3)
            L_ = (F - B).xy.length
            lo_, hi_ = 0.3, 200.0
            for _ in range(60):                        # угол между передним и дальним падает с отступом
                b_ = (lo_ + hi_) / 2
                if math.atan(s_ / b_) - math.atan(s_ / (b_ + L_)) > math.atan((xf - xb) * tx):
                    lo_ = b_
                else:
                    hi_ = b_
            C = F + u * b_ + n * s_
            C.z = F.z + o.get("up", 0.12) * ACTORS[who]["info"]["head_z"] * S
            v = F - C; v.z = 0
            v = max((rotz(v, sg * math.degrees(math.atan(xf * tx))) for sg in (1, -1)), key=lambda w: w.dot(n))
            v = v.normalized() * (B - C).xy.length
            v.z = (B.z - C.z) - o.get("down", 0) * ACTORS[other]["info"]["head_z"] * S   # на голову дальнего (down — ниже, чтобы передний поднялся в кадр)
            return C, v, b_, s_
        sd = o.get("side", 0.8)
        opts = [at(k * sd) for k in (1, 0.7, 1.4, 0.5, 2.0)]
        C, hide = clear([x[0] for x in opts], [F, B], who)
        C, v, b_, s_ = next(x for x in opts if x[0] is C)
        print(f"  через плечо {who}: отступ {b_:.1f} м, сбоку {s_:.1f} м")
        plans.append((f0, f1, C, C + v, fov, other, B, o.get("fstop", 2.0), other, hide))

if plans:
    key = bpy.data.objects.new("key", bpy.data.lights.new("key", "AREA")); sc.collection.objects.link(key)
    key.data.shape = "DISK"; key.data.size = 3.0; key.data.color = (1.0, 0.9, 0.78)
    rim = bpy.data.objects.new("rim", bpy.data.lights.new("rim", "AREA")); sc.collection.objects.link(rim)
    rim.data.shape = "DISK"; rim.data.size = 2.0; rim.data.color = (0.62, 0.78, 1.0)
    hidden = set().union(*[p[9] for p in plans])
    for f0, f1, C, T, fov, fw, FP, fst, lw, hide in plans:
        for h in hidden:                               # убранные деревья — только на своём плане
            h.hide_render = h in hide; h.keyframe_insert("hide_render", frame=f0)
        L, _ = avg_head(lw, f0, f1)
        tocam = C - L; tocam.z = 0; tocam.normalize()
        for f in range(f0, f1):
            fp = head(fw, f)[0] if fw in ACTORS else FP   # до установки камеры: frame_set сбрасывает её к ключам
            k = (f - f0) / max(1, f1 - f0); k = k * k * (3 - 2 * k)
            cam.location = C + (T - C) * 0.06 * k      # медленный наезд
            cam.rotation_euler = (T - cam.location).to_track_quat("-Z", "Y").to_euler()
            hand_held(f)
            cam_d.angle_y = fov; cam_d.keyframe_insert("lens", frame=f)
            cam_d.dof.focus_distance = (fp - cam.location).length; cam_d.dof.aperture_fstop = fst
            cam_d.dof.keyframe_insert("focus_distance", frame=f); cam_d.dof.keyframe_insert("aperture_fstop", frame=f)
            cam.keyframe_insert("location", frame=f); cam.keyframe_insert("rotation_euler", frame=f)
            for lo, dirv, dist, up, en in ((key, rotz(tocam, 50), 3.5, 2.2, LIGHT_KEY), (rim, rotz(-tocam, -35), 3.5, 2.6, LIGHT_RIM)):
                lo.location = L + dirv * dist + Vector((0, 0, up))
                lo.rotation_euler = (L - lo.location).to_track_quat("-Z", "Y").to_euler()
                lo.data.energy = en
                lo.keyframe_insert("location", frame=f); lo.keyframe_insert("rotation_euler", frame=f); lo.data.keyframe_insert("energy", frame=f)
    print("  планы:", [(p[0], p[1], p[5]) for p in plans])
else:
    focus = sorted(D["focus"])
    for f, (tx, ty, tz, dist, pitch, yaw) in enumerate(D["camera"]):
        p, y_ = math.radians(pitch), math.radians(yaw)
        fwd = Vector((-math.sin(y_) * math.cos(p), math.cos(y_) * math.cos(p), -math.sin(p)))
        tgt = Vector((tx, ty, tz)); pos = tgt - fwd * dist
        cam.location = W(*pos); cam.rotation_euler = (W(*tgt) - W(*pos)).to_track_quat("-Z", "Y").to_euler()
        hand_held(f)
        who = [w for t, w in focus if t <= f / FPS + 1e-6]
        who = who[-1] if who else None
        if who and who in D["actors"]:
            k = D["actors"][who]["keys"][f]; hz = ACTORS[who]["info"]["head_z"] if who in ACTORS else 100
            fd = (W(k[0], k[1], k[2] + hz * 0.85) - cam.location).length
            cam_d.dof.focus_distance = fd; cam_d.dof.aperture_fstop = 0.5 if fd < 6 else 1.0   # фон сильно размыт, как в примерах
            cam_d.dof.keyframe_insert("focus_distance", frame=f); cam_d.dof.keyframe_insert("aperture_fstop", frame=f)
        cam.keyframe_insert("location", frame=f); cam.keyframe_insert("rotation_euler", frame=f)
for idb in [cam, cam_d, bpy.data.objects.get("key"), bpy.data.objects.get("rim")] + sorted(hidden if plans else [], key=lambda o: o.name):
    if idb is None:
        continue
    for owner in (idb, getattr(idb, "data", None)):
        ad = getattr(owner, "animation_data", None)
        act = ad.action if ad else None
        for fc in (getattr(act, "fcurves", None) or []):
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"          # склейки — без промежуточных кадров

# ---------- рендер
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        sc.render.engine = eng; break
    except TypeError:
        pass
sc.render.resolution_x, sc.render.resolution_y = 1080, 1920
sc.render.resolution_percentage = 50 if HALF else 100
try:
    sc.eevee.taa_render_samples = 24
    sc.eevee.bokeh_max_size = 260
except AttributeError:
    pass
try:                                                      # свечение светлого и виньетка
    sc.use_nodes = True; ct = sc.node_tree
    rl = next(n for n in ct.nodes if n.type == 'R_LAYERS'); comp = next(n for n in ct.nodes if n.type == 'COMPOSITE')
    gl = ct.nodes.new('CompositorNodeGlare'); gl.glare_type = 'FOG_GLOW'; gl.threshold = 0.85; gl.size = 7
    lens = ct.nodes.new('CompositorNodeLensdist'); lens.inputs['Distortion'].default_value = -0.012; lens.inputs['Dispersion'].default_value = 0.004
    ct.links.new(rl.outputs['Image'], gl.inputs['Image']); ct.links.new(gl.outputs['Image'], lens.inputs['Image']); ct.links.new(lens.outputs['Image'], comp.inputs['Image'])
except Exception as e:
    print('композитор:', e)
try:
    sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast"
    sc.view_settings.exposure = 0.35 if MAP else 0.0          # карта темнее поля: тени деревьев и зданий
except TypeError:
    pass
sc.render.image_settings.file_format = "PNG"
os.makedirs(OUT, exist_ok=True)
frames = PICK if PICK is not None else range(N)
import time
t_start = time.time()
for i, f in enumerate(frames):
    sc.frame_set(f)
    sc.render.filepath = os.path.join(OUT, f"f{f:05d}.png")
    bpy.ops.render.render(write_still=True)
    if i % 30 == 0:
        el = time.time() - t_start
        print(f"РЕНДЕР кадр {f} ({i + 1}/{len(frames)}), {el / (i + 1):.1f} с/кадр", flush=True)
print("ГОТОВО", OUT, len(frames), "кадров", f"{time.time() - t_start:.0f} с")
