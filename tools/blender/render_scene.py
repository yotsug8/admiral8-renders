# Рендер сцены площадки в Blender: тот же сценарий, что в движке доты, но «киношная» картинка —
# свет (тёплое солнце + холодный контровой), небо, деревья карты на своих местах, размытие фона, герои с текстурами.
# Сцена — из stage.dump_json (положения покадрово, анимации, камера, на кого резкость).
# blender -b --factory-startup -P tools/blender/render_scene.py -- <scene.json> <папка кадров> [кадры: все | 75,150,300] [half]
#   half — пробные кадры в половинном размере
import bpy, sys, os, json, math, re
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
SCENE, OUT = args[0], args[1]
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


def W(x, y, z):
    return Vector((x * S, y * S, (z - BASE) * S))


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
for name, a in D["actors"].items():
    if not a["hero"]:
        continue
    info = TROUPE[a["hero"]]
    objs, acts = imp(os.path.join(RND, os.path.basename(info["glb"])))   # с текстурами
    arm = next(o for o in objs if o.type == "ARMATURE")
    ACTS = {re.sub(r"\.\d{3}$", "", x.name): x for x in acts}
    PARTS = []
    root = bpy.data.objects.new(name + "_root", None); sc.collection.objects.link(root)
    arm.parent = root
    for p in a["parts"] or []:
        if not os.path.exists(glb_of(p)):
            continue
        po, _ = imp(glb_of(p))
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
        root.location = W(x, y, z); root.rotation_euler = (0, 0, math.radians(ya + 90))
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

# ---------- земля, деревья карты, небо
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

trees = json.load(open(os.path.join(os.path.dirname(SCENE), "trees.json"), encoding="utf-8"))
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
    sc.collection.objects.link(e); e.location = W(x, y, z); e.rotation_euler = (0, 0, math.radians(yaw)); e.scale = (scale,) * 3

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
light("SUN", (68, 0, -150), 4.2, (0.58, 0.74, 1.0))         # контровой сильнее — обводка силуэтов        # холодный контровой с северо-запада — обводит силуэты

# ---------- камера: как у доты (цель, дальность, наклон, поворот), резкость — на герое плана
cam_d = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_d); sc.collection.objects.link(cam); sc.camera = cam
cam_d.sensor_fit = "VERTICAL"; cam_d.angle_y = math.radians(FOV_Y); cam_d.clip_start = 0.05; cam_d.clip_end = 400
cam_d.dof.use_dof = True
focus = sorted(D["focus"])
for f, (tx, ty, tz, dist, pitch, yaw) in enumerate(D["camera"]):
    p, y_ = math.radians(pitch), math.radians(yaw)
    fwd = Vector((-math.sin(y_) * math.cos(p), math.cos(y_) * math.cos(p), -math.sin(p)))
    tgt = Vector((tx, ty, tz)); pos = tgt - fwd * dist
    cam.location = W(*pos); cam.rotation_euler = (W(*tgt) - W(*pos)).to_track_quat("-Z", "Y").to_euler()
    tt = f / FPS                                       # «с рук»: медленное дыхание кадра, без тряски
    cam.rotation_euler.x += math.radians(0.35 * math.sin(tt * 1.3) + 0.15 * math.sin(tt * 3.1))
    cam.rotation_euler.z += math.radians(0.30 * math.sin(tt * 0.9 + 1.0) + 0.12 * math.sin(tt * 2.7))
    who = [w for t, w in focus if t <= f / FPS + 1e-6]
    who = who[-1] if who else None
    if who and who in D["actors"]:
        k = D["actors"][who]["keys"][f]; hz = ACTORS[who]["info"]["head_z"] if who in ACTORS else 100
        fd = (W(k[0], k[1], k[2] + hz * 0.85) - cam.location).length
        cam_d.dof.focus_distance = fd; cam_d.dof.aperture_fstop = 0.5 if fd < 6 else 1.0   # фон сильно размыт, как в примерах
        cam_d.dof.keyframe_insert("focus_distance", frame=f); cam_d.dof.keyframe_insert("aperture_fstop", frame=f)
    cam.keyframe_insert("location", frame=f); cam.keyframe_insert("rotation_euler", frame=f)
for fc in (cam.animation_data.action.fcurves if hasattr(cam.animation_data.action, "fcurves") else []):
    for kp in fc.keyframe_points:
        kp.interpolation = "CONSTANT"                      # склейки — без промежуточных кадров

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
