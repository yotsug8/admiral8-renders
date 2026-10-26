# Рендер сцены площадки в Blender: тот же сценарий, что в движке доты, но «киношная» картинка —
# свет (тёплое солнце + холодный контровой), небо, деревья карты на своих местах, размытие фона, герои с текстурами.
# Сцена — из stage.dump_json (положения покадрово, анимации, камера, на кого резкость).
# blender -b --factory-startup -P tools/blender/render_scene.py -- <scene.json> <папка кадров> [кадры: все | 75,150,300] [half]
#   half — пробные кадры в половинном размере
import bpy, sys, os, json, math, re
from mathutils import Matrix, Vector

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


def fix_hero_mats(objs):
    """Материалы героев из выгрузки S2V: прозрачность и металличность там взяты из маски доты (detailmask) — кожа
    просвечивала (дыра под шеей Пуджа) и блестела как металл. Непрозрачно, не металл, матовость кожи."""
    for o in objs:
        for ms in getattr(o, "material_slots", []):
            m = ms.material
            if not m or not m.node_tree or m.get("_a8"):
                continue
            b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if not b:
                continue
            for name, val in (("Alpha", 1.0), ("Metallic", 0.0), ("Roughness", 0.62), ("Emission Strength", 0.0)):
                for l in list(b.inputs[name].links):
                    m.node_tree.links.remove(l)
                b.inputs[name].default_value = val
            for l in list(b.inputs["Specular IOR Level"].links):           # блик из маски доты (specmask) — серый налёт на всём герое,
                m.node_tree.links.remove(l)                                # «выцветшая» кожа (насыщенность 0,2 при текстуре 0,43)
            b.inputs["Specular IOR Level"].default_value = 0.2; b.inputs["Specular Tint"].default_value = (1, 1, 1, 1)
            m.surface_render_method = "DITHERED"; m["_a8"] = 1


def close_neck(head, objs):
    """Шея: у героев доты голова и тело — отдельные сетки, под подбородком щель (камера игры её не видит — всегда сверху).
    Нижняя открытая кромка головы соединяется перемычкой с ближайшими точками тела; вершины перемычки привязаны к костям,
    как эти точки тела, — шея тянется при любом наклоне головы."""
    import bmesh
    from mathutils.kdtree import KDTree
    body = [o for o in objs if o.type == "MESH" and o is not head and len(o.data.vertices) > 50]
    if not body:
        return
    bm = bmesh.new(); bm.from_mesh(head.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0003)   # glTF режет сетку по швам развёртки — сшить, иначе кромка дробится
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    loops, used = [], set()                               # открытые кромки → петли
    for e0 in edges:
        if e0.index in used:
            continue
        loop = [e0.verts[0]]; used.add(e0.index); v = e0.verts[1]
        while v is not loop[0]:
            loop.append(v)
            nxt = next((e for e in v.link_edges if len(e.link_faces) == 1 and e.index not in used), None)
            if nxt is None:
                break
            used.add(nxt.index); v = nxt.other_vert(v)
        if len(loop) > 5:
            loops.append(loop)
    if not loops:
        bm.free(); return
    neck = min(loops, key=lambda L: sum(v.co.z for v in L) / len(L))   # самая нижняя петля — шея
    if neck[0].co.z > sum(v.co.z for v in bm.verts) / len(bm.verts):  # не ниже середины головы — это не шея
        bm.free(); return
    # ближайшие точки тела (в координатах головы; у всех частей героя одна система)
    pts = []
    for o in body:
        M = head.matrix_world.inverted() @ o.matrix_world
        for v in o.data.vertices:
            pts.append((M @ v.co, o, v.index))
    kd = KDTree(len(pts))
    for i, (co, _, _) in enumerate(pts):
        kd.insert(co, i)
    kd.balance()
    ctr = sum((v.co for v in neck), Vector()) / len(neck)
    dl = bm.verts.layers.deform.verify(); uvl = bm.loops.layers.uv.active
    shapes = list(bm.verts.layers.shape.values())
    gname = {g.index: g.name for g in head.vertex_groups}
    new = []
    hh = max(v.co.z for v in bm.verts) - min(v.co.z for v in bm.verts)   # высота головы
    for v in neck:
        tgt = v.co + (ctr - v.co) * 0.3                    # «юбка» вниз и внутрь — уходит в грудь, щели не остаётся
        tgt.z -= 0.35 * hh
        co, o, vi = pts[kd.find(tgt)[1]]                   # кости — как у ближайшей точки тела
        w = bm.verts.new(tgt)
        for sh in shapes:
            w[sh] = tgt.copy()
        for g in o.data.vertices[vi].groups:              # кости — как у этой точки тела
            name = o.vertex_groups[g.group].name
            if name not in head.vertex_groups:
                head.vertex_groups.new(name=name)
            w[dl][head.vertex_groups[name].index] = g.weight
        new.append(w)
    for i in range(len(neck)):
        j = (i + 1) % len(neck)
        try:
            f = bm.faces.new((neck[i], neck[j], new[j], new[i]))
        except ValueError:
            continue
        if uvl:                                           # текстура — с кромки подбородка
            src = next(iter(neck[i].link_loops))[uvl].uv.copy()
            for l in f.loops:
                l[uvl].uv = src
    bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if any(v in new for v in f.verts)])
    bm.to_mesh(head.data); bm.free(); head.data.update()
    print(f"  шея {head.name[:30]}: перемычка из {len(neck)} вершин, петель-кромок {len(loops)}: {sorted(len(L) for L in loops)}")


def mouth_dark(head):
    """Рот изнутри: у голов доты рот не прорезан — губы соединены гранями кожи, и на крике (jawOpen до предела) они
    растягиваются в большие серые полосы вместо темноты рта. Грани, которые морф jawOpen растягивает (площадь больше
    чем в 2 раза), получают атрибут a8_mouth = 1 по углам граней (вершины губ не трогаются); материал головы — своя
    копия, цвет × тёмный по этому атрибуту."""
    me = head.data; kb = me.shape_keys.key_blocks if me.shape_keys else None
    if not kb or "jawOpen" not in kb:
        return
    base, jo = kb[0].data, kb["jawOpen"].data
    def area(p, co):
        v = [co[i].co for i in p.vertices]
        return sum(((v[j] - v[0]).cross(v[j + 1] - v[0])).length / 2 for j in range(1, len(v) - 1))
    attr = me.color_attributes.get("a8_mouth") or me.color_attributes.new("a8_mouth", "FLOAT_COLOR", "CORNER")
    n_dark = 0
    for p in me.polygons:
        r = area(p, jo) / max(area(p, base), 1e-9)
        x = min(1.0, max(0.0, (r - 1.6) / 1.4)); n_dark += x > 0.5
        for li in p.loop_indices:
            attr.data[li].color = (x, x, x, 1)
    for ms in head.material_slots:
        m = ms.material
        if not m or not m.node_tree:
            continue
        m = m.copy(); ms.material = m                                 # своя копия: материал общий с телом
        nt = m.node_tree; bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if not bsdf:
            continue
        ca = nt.nodes.new("ShaderNodeVertexColor"); ca.layer_name = "a8_mouth"
        mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["B"].default_value = (0.03, 0.005, 0.005, 1)
        src = bsdf.inputs["Base Color"].links[0].from_socket if bsdf.inputs["Base Color"].links else None
        if src:
            nt.links.new(src, mx.inputs["A"])
        else:
            mx.inputs["A"].default_value = bsdf.inputs["Base Color"].default_value
        nt.links.new(ca.outputs["Color"], mx.inputs["Factor"]); nt.links.new(mx.outputs["Result"], bsdf.inputs["Base Color"])
    print(f"  рот изнутри {head.name[:30]}: тёмных граней {n_dark} из {len(me.polygons)}")


def glb_of(model):
    return os.path.join(RND, model.replace("/", "_").replace(".vmdl", ".glb"))


# ---------- герои
JAW_CAP = {"pudge": 0.55}                             # раскрытие рта морфом: дальше рот у модели не прорезан — кожа рвётся полосами
ACTORS = {}
HERO_OBJS = set()                                     # всё, из чего собраны герои: луч камеры сквозь них не проверяется
for name, a in D["actors"].items():
    if not a["hero"]:
        continue
    info = TROUPE[a["hero"]]
    objs, acts = imp(os.path.join(RND, os.path.basename(info["glb"])))   # с текстурами
    HERO_OBJS.update(objs); fix_hero_mats(objs)
    head = next((o for o in objs if o.type == "MESH" and o.data.shape_keys), None)   # голова с морфами лица
    if head:
        mouth_dark(head)                                          # до шеи: перемычка — снаружи
        close_neck(head, objs)
    arm = next(o for o in objs if o.type == "ARMATURE")
    ACTS = {re.sub(r"\.\d{3}$", "", x.name): x for x in acts}
    PARTS = []
    root = bpy.data.objects.new(name + "_root", None); sc.collection.objects.link(root)
    arm.parent = root
    for p in a["parts"] or []:
        if not os.path.exists(glb_of(p)):
            continue
        po, _ = imp(glb_of(p)); HERO_OBJS.update(po); fix_hero_mats(po)
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
        os.environ["A8_WHO"] = a["hero"]; os.environ["A8_FACE"] = "1" if head else ""   # рот морфами — челюсть костью слабее
        os.environ["A8_VOICES"] = os.path.join(os.path.dirname(SCENE), "voices.json")
        os.environ["A8_TALK"] = json.dumps((D.get("talk") or {}).get(name) or [])   # разговор актёра по описанию сценки (tools/skit)
        g = {"arm": arm, "sc": sc, "ACTS": ACTS, "FPS": FPS, "IMPORT_FPS": FPS, "__file__": os.path.join(REPO, "tools", "blender", "skit_talk.py")}
        exec(compile(open(g["__file__"], encoding="utf-8").read(), g["__file__"], "exec"), g)
        ACTS.update(g["CUSTOM"])
    if head:                                          # ширина головы по модели (крупность планов), а не Пуджа на всех
        bb = [head.matrix_world @ Vector(c) for c in head.bound_box]
        info["head_w"] = round(max(max(v.x for v in bb) - min(v.x for v in bb), max(v.y for v in bb) - min(v.y for v in bb)), 3)
    ACTORS[name] = dict(arm=arm, root=root, acts=ACTS, info=info)
    if head:                                          # мимика: речь по тексту и громкости, эмоции из сценария, моргание
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import face
        face.animate(head, name, D, json.load(open(os.path.join(os.path.dirname(SCENE), "voices.json"), encoding="utf-8")), FPS, N,
                     jaw=0.75 if info.get("jaw") else 1.0, jaw_cap=JAW_CAP.get(a["hero"], 1.0))

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
        if i:                                         # стык анимаций — плавно за 6 кадров (иначе голова скачет на 7° за кадр)
            st.use_auto_blend = False; st.blend_in = min(6.0, (st.frame_end - st.frame_start) / 2)
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
# облака (как в примерах — небо не плоское): шум по направлению, порог рампой, белое поверх градиента
cn = wn.nodes.new("ShaderNodeTexNoise"); cn.inputs["Scale"].default_value = 2.2; cn.inputs["Detail"].default_value = 8
cn.inputs["Roughness"].default_value = 0.6
cr = wn.nodes.new("ShaderNodeValToRGB"); cr.color_ramp.elements[0].position = 0.5; cr.color_ramp.elements[1].position = 0.72
cmx = wn.nodes.new("ShaderNodeMix"); cmx.data_type = "RGBA"; cmx.inputs["B"].default_value = (0.86, 0.89, 0.96, 1)
wn.links.new(tcw.outputs["Generated"], cn.inputs["Vector"]); wn.links.new(cn.outputs["Fac"], cr.inputs["Fac"])
wn.links.new(cr.outputs["Color"], cmx.inputs["Factor"]); wn.links.new(skyr.outputs["Color"], cmx.inputs["A"])
wn.links.new(cmx.outputs["Result"], bg.inputs["Color"]); bg.inputs["Strength"].default_value = 0.9
# небо в кадре — яркое, а на героев светит тёплее и слабее (голубой свет неба делал кожу серо-сиреневой, «выцветшей»)
lp = wn.nodes.new("ShaderNodeLightPath"); amb = wn.nodes.new("ShaderNodeBackground"); tint = wn.nodes.new("ShaderNodeMix")
tint.data_type = "RGBA"; tint.blend_type = "MULTIPLY"; tint.inputs["Factor"].default_value = 1.0; tint.inputs["B"].default_value = (1.0, 0.86, 0.72, 1)
wn.links.new(cmx.outputs["Result"], tint.inputs["A"]); wn.links.new(tint.outputs["Result"], amb.inputs["Color"])
wmix = wn.nodes.new("ShaderNodeMixShader"); wout = next(n for n in wn.nodes if n.type == "OUTPUT_WORLD")
wn.links.new(lp.outputs["Is Camera Ray"], wmix.inputs[0]); wn.links.new(amb.outputs["Background"], wmix.inputs[1])
wn.links.new(bg.outputs["Background"], wmix.inputs[2]); wn.links.new(wmix.outputs["Shader"], wout.inputs["Surface"])


def light(kind, rot, energy, color):
    d = bpy.data.lights.new(kind + str(energy), kind); d.energy = energy; d.color = color
    if kind == "SUN":
        d.angle = math.radians(10)                        # мягкий край тени (участник: «тени зачастую портят кадры»)
    o = bpy.data.objects.new(d.name, d); sc.collection.objects.link(o); o.rotation_euler = [math.radians(a) for a in rot]
    return o
# свет и тон: солнце, контровое солнце, ключевой и контровой плана (Вт), экспозиция, обработка; A8_LOOK — подбор на пробах
LOOK = dict(sun=3.0, back=1.0, key=300, rim=200, expo=0.0, amb=1.5, fog=1.0, horizon=(0.66, 0.76, 0.90, 1), bg_gain=1.55, bg_warm=0.04, bg_sat=1.2, view="Khronos PBR Neutral", look="None", sky=0.9)   # по гистограмме как в доте: без выбитых белых, насыщенность ~0,45
for kv in filter(None, os.environ.get("A8_LOOK", "").split(";")):
    k, v = kv.split("="); LOOK[k] = v if k in ("view", "look") else tuple(map(float, v.split(","))) + (1,) if k == "horizon" else float(v)
bg.inputs["Strength"].default_value = LOOK["sky"]; amb.inputs["Strength"].default_value = LOOK["amb"]
skyr.color_ramp.elements[0].color = LOOK["horizon"]                # горизонт — светлее и теплее (фон не плоский)
if MAP:                                         # дымка: даль светлеет и голубеет — глубина, как в доте;
    haze = (0.62, 0.74, 0.92, 1)                                      # в материалах карты по расстоянию до камеры (объём гасил солнце)
    for m in {ms.material for o in bpy.data.objects if o.type == "MESH" and o not in HERO_OBJS for ms in o.material_slots if ms.material}:
        nt = m.node_tree if m.use_nodes else None
        out = nt and next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if not out or not out.inputs["Surface"].links or m.get("_haze"):
            continue
        b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if not b:
            continue
        cd = nt.nodes.new("ShaderNodeCameraData"); mr = nt.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = 40; mr.inputs["From Max"].default_value = 280
        mr.inputs["To Max"].default_value = min(0.7, 0.35 * LOOK["fog"])          # fog=0 — без дымки
        nt.links.new(cd.outputs["View Distance"], mr.inputs["Value"])
        # фон под героев (участник: «подкорректируй фон по освещению, контрасту, цвету»): листва и земля карты темнее и холоднее
        # героев — светлее (bg_gain), зелень к жёлтому (bg_warm, доля круга оттенков), сочнее (bg_sat)
        hs = nt.nodes.new("ShaderNodeHueSaturation")
        hs.inputs["Hue"].default_value = 0.5 - LOOK["bg_warm"]; hs.inputs["Saturation"].default_value = LOOK["bg_sat"]
        hs.inputs["Value"].default_value = LOOK["bg_gain"]
        srcb = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].links else None
        if srcb:
            nt.links.new(srcb, hs.inputs["Color"])
        else:
            hs.inputs["Color"].default_value = b.inputs["Base Color"].default_value
        nt.links.new(hs.outputs["Color"], b.inputs["Base Color"])
        # в саму поверхность: цвет тускнеет к дымке, она же светится — прозрачность листвы сохраняется (иначе «снег» на листьях)
        dim = nt.nodes.new("ShaderNodeMix"); dim.data_type = "RGBA"; dim.inputs["B"].default_value = (0, 0, 0, 1)
        srcc = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].links else None
        if srcc:
            nt.links.new(srcc, dim.inputs["A"])
        else:
            dim.inputs["A"].default_value = b.inputs["Base Color"].default_value
        nt.links.new(mr.outputs["Result"], dim.inputs["Factor"]); nt.links.new(dim.outputs["Result"], b.inputs["Base Color"])
        for l in list(b.inputs["Emission Color"].links):
            nt.links.remove(l)
        b.inputs["Emission Color"].default_value = haze
        nt.links.new(mr.outputs["Result"], b.inputs["Emission Strength"])
        m["_haze"] = 1
SUN = light("SUN", (50, 0, 45), LOOK["sun"], (1.0, 0.84, 0.64))  # тёплое солнце; на планах — спереди-сбоку от камеры (ниже)
light("SUN", (68, 0, -150), LOOK["back"], (0.58, 0.74, 1.0))   # холодный контровой с северо-запада — обводит силуэты
LIGHT_KEY, LIGHT_RIM = LOOK["key"], LOOK["rim"]             # свет плана (Вт): ключевой у камеры, контровой за героем

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
            C.z = H.z + o.get("cz", 0.05) * d            # на уровне глаз, чуть сверху: снизу у героев доты виден стык головы и тела (игра смотрит сверху)
            return C
        C, hide = clear([at(a_) for a_ in (ang, ang + 15, ang - 15, ang + 30)], [H], who)
        T = H - Vector((0, 0, vis * 0.17))             # глаза — в верхней трети
        plans.append((f0, f1, C, T, fov, who, H, o.get("fstop", 1.2), who, hide))
    elif kind == "selfie":
        # селфи (эталон solevix, arbuzprodota): широкий объектив вплотную, лицо — width ширины кадра, камера ниже лица
        # (below — доля отступа) смотрит вверх на небо и качается как в руке: вперёд-назад, вбок, с креном.
        # Камера ведёт голову со сглаживанием 0,35 с — голова гуляет по кадру, но не уходит из него.
        # наезд (push: [начало, конец], с): крупность растёт от width0 до width — на смене эмоции, плавно
        hw = ACTORS[who]["info"].get("head_w", 0.95)        # ширина головы, м (Пудж ~0,95)
        dist = lambda wf: hw / wf / (2 * math.tan(fov / 2) * 9 / 16)
        d = dist(o.get("width", 0.7)); push = o.get("push"); sw = o.get("sway", 1.0)
        def d_at(tt):
            if not push:
                return d
            k_ = min(1.0, max(0.0, (tt - push[0]) / max(0.05, push[1] - push[0]))); k_ = k_ * k_ * (3 - 2 * k_)
            return dist(o.get("width0", 0.4) + (o.get("width", 0.7) - o.get("width0", 0.4)) * k_)
        hs = [head(who, f) for f in range(f0, f1)]
        up = Vector((0, 0, o.get("hup", 0.3)))             # центр лица выше кости головы (кость — у основания черепа)
        def softv(vs, tau=0.35):
            a_ = 1 - math.exp(-1 / (FPS * tau)); out = [v.copy() for v in vs]
            for rng in (range(1, len(out)), range(len(out) - 2, -1, -1)):
                for i_ in rng:
                    j_ = i_ - 1 if rng.step > 0 else i_ + 1
                    out[i_] = out[j_] + (out[i_] - out[j_]) * a_
            return out
        Hs = softv([h + up for h, _ in hs]); Fs = softv([fc for _, fc in hs], 0.6)
        if o.get("static"):                            # камера стоит: герой может уйти из кадра (крюк утаскивает жертву)
            Hs = [Hs[0]] * len(Hs); Fs = [Fs[0]] * len(Fs)
        C0, hide = clear([Hs[0] + rotz(Fs[0], a_) * d_at(f0 / FPS) for a_ in (o.get("ang", 12), -o.get("ang", 12), 30, -30)], [Hs[0]], who)
        sgn = 1 if (C0 - Hs[0]).xy.angle_signed(Fs[0].xy, 0) <= 0 else -1
        track = {}
        for i_, f in enumerate(range(f0, f1)):
            tt = f / FPS
            a_ = sgn * o.get("ang", 12) + sw * (9 * math.sin(tt * 2.0) + 3 * math.sin(tt * 4.7 + 1))      # вбок
            dd = d_at(tt) * (1 + sw * (0.10 * math.sin(tt * 2.6 + 0.5) + 0.04 * math.sin(tt * 5.3)))      # к лицу и от него
            C = Hs[i_] + rotz(Fs[i_].normalized(), a_) * dd
            C.z = Hs[i_].z - o.get("below", 0.45) * dd + sw * 0.05 * dd * math.sin(tt * 3.1)
            roll = math.radians(sw * (4 * math.sin(tt * 1.7 + 2) + 1.5 * math.sin(tt * 4.1)))
            track[f] = (C, Hs[i_] + Vector((0, 0, o.get("aim", 0.08) * dd)), roll)
        plans.append((f0, f1, C0, Hs[0], fov, who, Hs[0], o.get("fstop", 1.4), who, hide, track))
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
    for f0, f1, C, T, fov, fw, FP, fst, lw, hide, *trk in plans:
        trk = trk[0] if trk else None
        for h in hidden:                               # убранные деревья — только на своём плане
            h.hide_render = h in hide; h.keyframe_insert("hide_render", frame=f0)
        L, _ = avg_head(lw, f0, f1)
        tocam = C - L; tocam.z = 0; tocam.normalize()
        # солнце плана — спереди-сбоку от камеры, 45° над горизонтом: у лица ясная светлая сторона и форма (как в примерах)
        sd = rotz(tocam, 40); sd.z = 1.0; SUN.rotation_euler = (-sd).to_track_quat("-Z", "Y").to_euler()
        SUN.keyframe_insert("rotation_euler", frame=f0)
        for f in range(f0, f1):
            fp = head(fw, f)[0] if fw in ACTORS else FP   # до установки камеры: frame_set сбрасывает её к ключам
            k = (f - f0) / max(1, f1 - f0); k = k * k * (3 - 2 * k)
            if trk:                                    # селфи: камера покадрово (см. выше), крен — вокруг оси взгляда
                Cf, Tf, roll = trk[f]; cam.location = Cf
                q = (Tf - Cf).to_track_quat("-Z", "Y"); q.rotate(Matrix.Rotation(roll, 4, Tf - Cf)); cam.rotation_euler = q.to_euler()
                fp = (Tf if fw not in ACTORS else fp)
            else:
                cam.location = C + (T - C) * 0.06 * k      # медленный наезд
                cam.rotation_euler = (T - cam.location).to_track_quat("-Z", "Y").to_euler()
                hand_held(f)
            cam_d.angle_y = fov; cam_d.keyframe_insert("lens", frame=f)
            cam_d.dof.focus_distance = (fp - cam.location).length; cam_d.dof.aperture_fstop = fst
            cam_d.dof.keyframe_insert("focus_distance", frame=f); cam_d.dof.keyframe_insert("aperture_fstop", frame=f)
            cam.keyframe_insert("location", frame=f); cam.keyframe_insert("rotation_euler", frame=f)
            lights = ((key, rotz(tocam, 50), 3.5, 2.2, LIGHT_KEY), (rim, rotz(-tocam, -35), 3.5, 2.6, LIGHT_RIM))
            if trk:                                    # селфи: камера снизу, небо за головой — ключевой ниже и ближе к камере
                lights = ((key, rotz(tocam, 35), 3.0, 0.5, LIGHT_KEY * 1.3), (rim, rotz(-tocam, -35), 3.5, 2.6, LIGHT_RIM))
            for lo, dirv, dist, up, en in lights:
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
for idb in [cam, cam_d, SUN, bpy.data.objects.get("key"), bpy.data.objects.get("rim")] + sorted(hidden if plans else [], key=lambda o: o.name):
    if idb is None:
        continue
    for owner in (idb, getattr(idb, "data", None)):
        ad = getattr(owner, "animation_data", None)
        act = ad.action if ad else None
        for fc in (getattr(act, "fcurves", None) or []):
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"          # склейки — без промежуточных кадров

# ---------- проверка движения (эталон: голова всё время плавно движется, без рывков): поворот кости головы за кадр
# и доля ширины кадра, которую занимает голова, на крупных планах (close, selfie)
for t0_, kind_, who_, *_r in SHOTS:
    if kind_ not in ("close", "selfie") or who_ not in ACTORS:
        continue
    A = ACTORS[who_]; pb = A["arm"].pose.bones.get(A["info"].get("head_bone") or "head"); hw = A["info"].get("head_w", 0.95)
    f0 = int(round(t0_ * FPS)); f1 = min(N, next((int(round(x[0] * FPS)) for x in SHOTS if x[0] > t0_), N))
    rot, wid, prev = [], [], None
    for f in range(f0, f1):
        sc.frame_set(f)
        M = A["arm"].matrix_world @ pb.matrix; q = M.to_quaternion()
        if prev is not None:
            rot.append(math.degrees(prev.rotation_difference(q).angle))
        prev = q
        Hc = M.translation; z_ = -(cam.matrix_world.inverted() @ Hc).z   # глубина головы по оси взгляда
        wid.append(hw / (2 * z_ * math.tan(cam_d.angle_y / 2) * 9 / 16))
    if os.environ.get("A8_DEBUG"):
        print("  поворот по кадрам:", " ".join(f"{f0 + 1 + i}:{v:.1f}" for i, v in enumerate(rot)))
        print("  ширина по кадрам:", " ".join(f"{v * 100:.0f}" for v in wid), "дальность", round((cam.matrix_world.translation - Hc).length, 2))
    if rot:
        rs = sorted(rot); jerk = max(abs(rot[i] - rot[i - 1]) for i in range(1, len(rot))) if len(rot) > 1 else 0
        print(f"  ДВИЖЕНИЕ {who_} {kind_}: поворот головы за кадр медиана {rs[len(rs) // 2]:.2f}°, макс {rs[-1]:.2f}°, "
              f"скачок {jerk:.2f}°; голова {min(wid) * 100:.0f}–{max(wid) * 100:.0f} % ширины кадра")

if os.environ.get("A8_IDS"):                               # отладка: каждый объект — свой цвет (найти объект по пикселю)
    ids = {}
    for i, o in enumerate([o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render], 1):
        m = bpy.data.materials.new(f"id{i}"); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
        e = nt.nodes.new("ShaderNodeEmission"); outn = nt.nodes.new("ShaderNodeOutputMaterial")
        e.inputs["Color"].default_value = ((i % 64) * 4 / 255, (i // 64 % 64) * 4 / 255, (i // 4096 % 64) * 4 / 255, 1)
        nt.links.new(e.outputs[0], outn.inputs[0])
        o.data = o.data.copy(); o.data.materials.clear(); o.data.materials.append(m)
        ids[i] = o.name
    sc.world = bpy.data.worlds.new("black"); sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
    sc.view_settings.exposure = 0; sc.render.filter_size = 0; cam_d.dof.use_dof = False
    os.makedirs(OUT, exist_ok=True); json.dump(ids, open(os.path.join(OUT, "ids.json"), "w", encoding="utf-8"), ensure_ascii=False)

# ---------- рендер
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        sc.render.engine = eng; break
    except TypeError:
        pass
sc.render.resolution_x, sc.render.resolution_y = 1080, 1920
sc.render.resolution_percentage = 50 if HALF else 100
try:
    sc.eevee.taa_render_samples = int(os.environ.get("A8_SAMPLES", 24))   # 64 — без зерна (пробы для сравнения с примерами)
    sc.eevee.bokeh_max_size = 260
except AttributeError:
    pass
try:
    sc.view_settings.view_transform = LOOK["view"]; sc.view_settings.look = LOOK["look"]
    sc.view_settings.exposure = LOOK["expo"]
except TypeError:
    pass
sc.render.image_settings.file_format = "PNG"
os.makedirs(OUT, exist_ok=True)
if os.environ.get("A8_BLEND"):                            # сцена для ручной работы: голоса дорожками звука, файл .blend — без рендера
    sc.frame_start, sc.frame_end = 0, N - 1; sc.frame_set(0)
    sc.render.filepath = os.path.join(OUT, "f#####")
    sc.sync_mode = "AUDIO_SYNC"
    se = sc.sequence_editor_create()
    strips = se.strips if hasattr(se, "strips") else se.sequences
    for i, (nm, (who, off)) in enumerate((D.get("voices") or {}).items()):
        wav = os.path.join(os.path.dirname(SCENE), nm + ".wav")
        if os.path.exists(wav):
            strips.new_sound(nm, wav, channel=1 + i % 3, frame_start=int(round(off * FPS)))
    bpy.ops.wm.save_as_mainfile(filepath=os.environ["A8_BLEND"])
    print("СЦЕНА", os.environ["A8_BLEND"])
    raise SystemExit
import time
t_start = time.time()
if PICK is None:                                          # весь ролик — анимацией: сцена не пересобирается на каждом кадре,
    sc.frame_start, sc.frame_end = 0, N - 1               # готовые кадры пропускаются (продолжение после сбоя; A8_REDO=1 — заново)
    sc.render.use_overwrite = bool(os.environ.get("A8_REDO"))
    sc.render.use_placeholder = True                      # параллельный второй Blender возьмёт другие кадры
    sc.render.filepath = os.path.join(OUT, "f#####")
    bpy.ops.render.render(animation=True)
    print("ГОТОВО", OUT, N, "кадров", f"{time.time() - t_start:.0f} с")
else:
    for i, f in enumerate(PICK):
        sc.frame_set(f)
        sc.render.filepath = os.path.join(OUT, f"f{f:05d}.png")
        bpy.ops.render.render(write_still=True)
    print("ГОТОВО", OUT, len(PICK), "кадров", f"{time.time() - t_start:.0f} с")
