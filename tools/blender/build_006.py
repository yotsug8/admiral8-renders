# Сцена 006 «Пуджи на водопое» в Blender 5.2 (Eevee): настоящая река из карты, свой шейдер multiblend, вода, 7 Пуджей с цепочками анимаций.
# blender -b --factory-startup -P tools/blender/build_006.py -- [preview|render] [кадры через запятую]
import bpy, math, sys, os, time
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
G = os.path.normpath(os.path.join(HERE, "..", "..", "_game"))   # файлы игры и рендеры — только локально (.gitignore)
TEX = G + r"\world"
PUDGE = G + r"\models\pudge"
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = ARGS[0] if ARGS else "preview"
FPS, FRAMES = 30, 345
WATER_Z = 1.6   # по пояс Пуджу (0.85), дно реки на высоте 0
DECAL_UP = WATER_Z - 0.4   # кувшинки и пена у берега в карте лежат на старом уровне 0.4
# Свет как в доте: ent_dota_lightinfo default_RF (сторона Света, день); сила и вода сверены пипеткой со скриншотом Valve 7.38
SUN_C, SUN_S = (255, 232, 190), 6.2   # тёплее игрового (216,208,207): по эталонным скриншотам Дениса
AMB, AMB_S = (63, 144, 169), 1.1
SPEC_C = (81, 196, 232)
WTINT = (0.42, 0.84, 0.82, 1)       # от g_vRefractionTint к бирюзе, как река на скриншоте
WBODY = (0.015, 0.14, 0.15, 1)
WOPAC = 0.52
FOG_K = 0.1
EXPO = 0.1
VIEW = "Standard"   # как в игре: без тонмаппинга, матовое освещение (GAME=1); сверено с эталонными скриншотами
SAT = 1.15
FIRST = 1  # 1 — вид первого присланного кадра (его Денис счёл самым похожим на доту)
GAME = 1   # 1 — освещение по формуле доты: матово, цвет текстуры × (солнце + окружающий), без тонмаппинга
import os as _os, json as _json
if _os.environ.get("LOOK"): globals().update(_json.loads(_os.environ["LOOK"]))   # подбор вида без правки файла
if FIRST:
    GAME = 0; VIEW = "AgX"; EXPO = 0.15; SAT = 1.18
t0 = time.time()
def log(*a): print("[006]", round(time.time() - t0, 1), *a, flush=True)

def srgb2lin(c):
    c = c / 255 if c > 1.0 else c

    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

# ---------------- карта ----------------
bpy.ops.import_scene.gltf(filepath=G + r"\maps\river.glb", bone_heuristic="BLENDER")
mapobjs = list(bpy.data.objects)
log("карта", len(mapobjs))

_img = {}
def img(name, color=True):
    if not name: return None
    fn = name.replace(".vtex", ".png")
    key = (fn, color)
    if key in _img: return _img[key]
    p = os.path.join(TEX, fn)
    if not os.path.exists(p):
        log("нет текстуры", fn); _img[key] = None; return None
    im = bpy.data.images.load(p, check_existing=False)
    im.colorspace_settings.name = "sRGB" if color else "Non-Color"
    im.alpha_mode = "CHANNEL_PACKED"
    _img[key] = im
    return im

def underwater(nt, color_out):
    """Подводная муть: чем глубже под уровнем воды, тем зеленее и темнее (по мировой высоте)."""
    N, L = nt.nodes, nt.links
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sep.inputs[0])
    mr = N.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = WATER_Z; mr.inputs["From Max"].default_value = WATER_Z - 3.0
    L.new(sep.outputs["Z"], mr.inputs["Value"])
    if FIRST:
        mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
        mix.inputs["B"].default_value = (0.22, 0.55, 0.5, 1)
        L.new(mr.outputs["Result"], mix.inputs["Factor"]); L.new(color_out, mix.inputs["A"])
        return mix.outputs["Result"]
    # как в water_dota: туман толщи g_vWaterFogColor, не больше g_flForceFogOverrideMax (0.3), глубина ~35 ед. (0.9 м)
    mr.inputs["From Max"].default_value = WATER_Z - 0.9; mr.interpolation_type = "SMOOTHSTEP"
    fac = N.new("ShaderNodeMath"); fac.operation = "MULTIPLY"; fac.inputs[1].default_value = 0.3
    L.new(mr.outputs["Result"], fac.inputs[0])
    mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MIX"
    mix.inputs["B"].default_value = (0.258824, 0.137255, 0.05098, 1)   # g_vWaterFogColor как есть
    L.new(fac.outputs[0], mix.inputs["Factor"]); L.new(color_out, mix.inputs["A"])
    return mix.outputs["Result"]

class NB:
    """Короткая запись узлов."""
    def __init__(s, nt): s.N, s.L = nt.nodes, nt.links
    def _in(s, sock, x):
        if x is None: return
        if isinstance(x, (int, float, tuple)): sock.default_value = x
        else: s.L.new(x, sock)
    def m(s, op, a, b=None, c=None, clamp=False):
        n = s.N.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, x in enumerate((a, b, c)): s._in(n.inputs[i], x)
        return n.outputs[0]
    def v(s, op, a, b=None, scale=None):
        n = s.N.new("ShaderNodeVectorMath"); n.operation = op
        s._in(n.inputs[0], a); s._in(n.inputs[1], b)
        if scale is not None: s._in(n.inputs["Scale"], scale)
        return n.outputs["Value"] if op in ("DISTANCE", "LENGTH", "DOT_PRODUCT") else n.outputs["Vector"]
    def mixc(s, a, b, f=1.0, blend="MIX"):
        n = s.N.new("ShaderNodeMix"); n.data_type = "RGBA"; n.blend_type = blend
        s._in(n.inputs["Factor"], f); s._in(n.inputs["A"], a); s._in(n.inputs["B"], b)
        return n.outputs["Result"]

def multiblend(mat, v):
    T = v.get("TextureParams", {}); F = v.get("FloatParams", {}); V = v.get("VectorParams", {}); I = v.get("IntParams", {})
    mat.use_nodes = True; nt = mat.node_tree; N, L = nt.nodes, nt.links; N.clear(); nb = NB(nt)
    out = N.new("ShaderNodeOutputMaterial"); bsdf = N.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 1.0 if GAME else 0.85
    bsdf.inputs["Specular IOR Level"].default_value = 0.05 if GAME else 0.25
    L.new(bsdf.outputs[0], out.inputs[0])
    uv = N.new("ShaderNodeUVMap"); uv.uv_map = "UVMap"
    def attr(n):
        a = N.new("ShaderNodeAttribute"); a.attribute_name = n; a.attribute_type = "GEOMETRY"; return a
    W = N.new("ShaderNodeSeparateColor"); L.new(attr("_TEXCOORD_1").outputs["Color"], W.inputs[0])
    A = N.new("ShaderNodeSeparateColor"); L.new(attr("_TEXCOORD_2").outputs["Color"], A.inputs[0])
    VC = attr("_TEXCOORD_3")
    has_mask = bool(I.get("F_TINT_MASK")) and bool(T.get("g_tTintMasks"))
    def col(k):
        c = list(V.get(k, [1, 1, 1, 1]))[:3]
        return tuple(srgb2lin(x) for x in c) + (1.0,)
    cols, alphas, tints, norms = [], [], [], []
    for i in range(4):
        ang = math.radians(F.get(f"g_flTexCoordRotate{i}", 0))
        rot = N.new("ShaderNodeVectorRotate"); rot.rotation_type = "Z_AXIS"; rot.inputs["Angle"].default_value = ang
        L.new(uv.outputs["UV"], rot.inputs["Vector"])
        s = F.get(f"g_flTexCoordScale{i}", 1) or 1
        uvi = nb.v("MULTIPLY_ADD", rot.outputs[0], (1 / s, 1 / s, 1))
        # MULTIPLY_ADD: третий вход — сдвиг
        uvi.node.inputs[2].default_value = (0.5, 0.5, 0)
        tx = N.new("ShaderNodeTexImage"); tx.image = img(T.get(f"g_tColor{i}"), True)
        L.new(uvi, tx.inputs[0]); cols.append(tx.outputs["Color"]); alphas.append(tx.outputs["Alpha"])
        if has_mask:
            mk = N.new("ShaderNodeTexImage"); mk.image = img(T["g_tTintMasks"], False); L.new(uvi, mk.inputs[0])
            if i < 3:
                sp = N.new("ShaderNodeSeparateColor"); L.new(mk.outputs["Color"], sp.inputs[0]); ch = sp.outputs[i]
            else:
                ch = mk.outputs["Alpha"]
            tints.append(nb.mixc(col(f"g_vColorTintB{i}"), col(f"g_vColorTint{i}"), ch))
        else:
            rgb = N.new("ShaderNodeRGB"); rgb.outputs[0].default_value = col(f"g_vColorTint{i}"); tints.append(rgb.outputs[0])
        ni = img(T.get(f"g_tNormal{i}"), False)
        if ni:
            nx = N.new("ShaderNodeTexImage"); nx.image = ni; L.new(uvi, nx.inputs[0])
            dec = nb.v("MULTIPLY_ADD", nx.outputs["Color"], (2, 2, 2)); dec.node.inputs[2].default_value = (-1, -1, -1)
            back = N.new("ShaderNodeVectorRotate"); back.rotation_type = "Z_AXIS"; back.inputs["Angle"].default_value = -ang
            L.new(dec, back.inputs["Vector"]); norms.append(back.outputs[0])
        else:
            norms.append(None)
    def bm(f, mval, sval):
        lo = nb.m("MAXIMUM", nb.m("SUBTRACT", mval, sval), 0.0)
        hi = nb.m("MINIMUM", nb.m("ADD", mval, sval), 1.0)
        mr = N.new("ShaderNodeMapRange"); mr.interpolation_type = "SMOOTHSTEP"
        L.new(f, mr.inputs["Value"]); L.new(lo, mr.inputs["From Min"]); L.new(hi, mr.inputs["From Max"])
        return mr.outputs["Result"]
    w1 = bm(W.outputs[0], alphas[1], A.outputs[0]); i1 = nb.m("SUBTRACT", 1.0, w1)
    w2 = nb.m("MINIMUM", bm(W.outputs[1], alphas[2], A.outputs[1]), i1); i2 = nb.m("SUBTRACT", i1, w2)
    w3 = nb.m("MINIMUM", bm(W.outputs[2], alphas[3], A.outputs[2]), i2); w0 = nb.m("SUBTRACT", i2, w3)
    ws = [w0, w1, w2, w3]
    acc = nacc = None
    for i in range(4):
        c = nb.v("SCALE", nb.mixc(cols[i], tints[i], 1.0, "MULTIPLY"), None, ws[i])
        acc = c if acc is None else nb.v("ADD", acc, c)
        if norms[i] is not None:
            n_ = nb.v("SCALE", norms[i], None, ws[i])
            nacc = n_ if nacc is None else nb.v("ADD", nacc, n_)
    pw = N.new("ShaderNodeGamma"); pw.inputs["Gamma"].default_value = 2.2; L.new(VC.outputs["Color"], pw.inputs["Color"])
    base = nb.mixc(acc, pw.outputs[0], 1.0, "MULTIPLY")
    L.new(underwater(nt, base), bsdf.inputs["Base Color"])
    if nacc is not None:
        nn = nb.v("MULTIPLY_ADD", nacc, (0.5, 0.5, 0.5)); nn.node.inputs[2].default_value = (0.5, 0.5, 0.5)
        nm = N.new("ShaderNodeNormalMap"); nm.uv_map = "UVMap"; nm.inputs["Strength"].default_value = 1.0
        L.new(nn, nm.inputs["Color"]); L.new(nm.outputs[0], bsdf.inputs["Normal"])

def fix_prop(mat, v):
    """Прочие материалы карты: дизеринг для альфы, аддитивные — как свечение, подводная муть."""
    I = v.get("IntParams", {})
    mat.surface_render_method = "DITHERED"
    if not mat.use_nodes or not mat.node_tree: return
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not bsdf: return
    src = bsdf.inputs["Base Color"].links[0].from_socket if bsdf.inputs["Base Color"].links else None
    if I.get("F_ADDITIVE_BLEND"):
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        em = nt.nodes.new("ShaderNodeEmission"); tr = nt.nodes.new("ShaderNodeBsdfTransparent"); add = nt.nodes.new("ShaderNodeAddShader")
        if src: nt.links.new(src, em.inputs["Color"])
        em.inputs["Strength"].default_value = 0.6
        nt.links.new(em.outputs[0], add.inputs[0]); nt.links.new(tr.outputs[0], add.inputs[1]); nt.links.new(add.outputs[0], out.inputs[0])
        return
    if not bsdf.inputs["Roughness"].links:
        bsdf.inputs["Roughness"].default_value = max(0.6, bsdf.inputs["Roughness"].default_value)
    if GAME: bsdf.inputs["Specular IOR Level"].default_value = 0.1
    if src:
        nt.links.new(underwater(nt, src), bsdf.inputs["Base Color"])

nmb = 0
for mat in list(bpy.data.materials):
    v = mat.get("vmat")
    v = v.to_dict() if hasattr(v, "to_dict") else (v or {})
    sh = v.get("ShaderName", "")
    if sh == "multiblend.vfx":
        multiblend(mat, v); nmb += 1
    elif sh == "water_dota.vfx":
        mat["_water"] = 1
    else:
        fix_prop(mat, v)
log("multiblend", nmb)

for o in mapobjs:
    if o.type != "MESH": continue
    names = [ms.material.name for ms in o.material_slots if ms.material]
    if any(("water_edges" in n or "lily" in n) for n in names) or "lily" in o.name or "water_edges" in o.name:
        o.location.z += DECAL_UP
    if any(bpy.data.materials[n].get("_water") for n in names) or any(n.startswith(("tools", "black")) for n in names):
        o.hide_render = True; o.hide_viewport = True

# ---------------- Пуджи ----------------
# Пуджи лесенкой вдоль реки: (вдоль от центра, поперёк) в метрах; камера ниже по течению
C, DIR = Vector((-20.0, -1.0, 0)), Vector((0.52, 0.85, 0)).normalized()
PERP = Vector((DIR.y, -DIR.x, 0))
def at(al, lat): p = C + DIR * al + PERP * lat; return (round(p.x, 2), round(p.y, 2))
CAM0 = tuple(C - DIR * 17 + Vector((0, 0, 13.0))); CAM1 = tuple(C - DIR * 15 + Vector((0.3, 0, 11.8)))
LOOK0, LOOK1 = tuple(C + DIR * 6.5 + Vector((0, 0, 1.0))), tuple(C + DIR * 6.5 + Vector((0, 0, 1.0)))
PUDGE_Z = 0.0   # ногами на дне
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=PUDGE + r"\pudge.glb", bone_heuristic="BLENDER")
new = [o for o in bpy.data.objects if o not in before]
arm = next(o for o in new if o.type == "ARMATURE")
body = []
for o in new:
    if o.type == "MESH" and o.parent == arm:   # hitbox_fix — не хитбокс, а заплатка шеи с материалом тела
        body.append(o)
    elif o is not arm:
        o.hide_render = True; o.hide_viewport = True
mainbones = {b.name: b for b in arm.data.bones}
for part in ("back", "belt", "bracer", "hair", "leftarm", "leftweapon", "righthook", "weapon"):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=PUDGE + rf"\{part}.glb", bone_heuristic="BLENDER")
    pn = [o for o in bpy.data.objects if o not in before]
    pa = next((o for o in pn if o.type == "ARMATURE"), None)
    if not pa:
        log("ВНИМАНИЕ: у части нет скелета", part)
    for o in pn:
        if o.type != "MESH" or not pa: continue
        if o.name.startswith("Icosphere") or not o.data.materials:   # форма отображения кости, не часть модели
            continue
        # веса костей ткани/меха, которых нет у героя, — к ближайшему предку, который есть у героя
        for vg in list(o.vertex_groups):
            if vg.name in mainbones: continue
            b = pa.data.bones.get(vg.name); tgt = None
            while b is not None:
                if b.name in mainbones: tgt = b.name; break
                b = b.parent
            if not tgt: continue
            tg = o.vertex_groups.get(tgt) or o.vertex_groups.new(name=tgt)
            idx = vg.index
            for vx in o.data.vertices:
                for g in vx.groups:
                    if g.group == idx and g.weight > 0: tg.add([vx.index], g.weight, "ADD")
            o.vertex_groups.remove(vg)
        mw = o.matrix_world.copy()
        for m in o.modifiers:
            if m.type == "ARMATURE": m.object = arm
        o.parent = arm; o.matrix_world = mw
        body.append(o)
    if pa:
        d = max(((b.head_local - mainbones[b.name].head_local).length for b in pa.data.bones if b.name in mainbones), default=0)
        log("часть", part, "расхождение позы", round(d, 4))
    for o in pn:
        if o.type != "MESH" or o.name.startswith("Icosphere") or not o.data.materials: bpy.data.objects.remove(o, do_unlink=True)
log("Пудж: мешей", len(body), "анимаций", len(bpy.data.actions))

for o in body:
    for ms in o.material_slots:
        m = ms.material
        if not m or m.get("_done"): continue
        m["_done"] = 1; m.surface_render_method = "DITHERED"
        m.use_backface_culling = False; m.use_backface_culling_shadow = False   # горловина и швы изнутри не просвечивают
        nt = m.node_tree; bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf and bsdf.inputs["Base Color"].links:
            src = bsdf.inputs["Base Color"].links[0].from_socket
            hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.inputs["Saturation"].default_value = 1.0   # цвета героя как в игре (без двойной насыщенности)
            nt.links.new(src, hs.inputs["Color"])
            # мокрая кожа: полоса 0–45 см над водой темнее
            g_ = nt.nodes.new("ShaderNodeNewGeometry"); sz = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(g_.outputs["Position"], sz.inputs[0])
            wr = nt.nodes.new("ShaderNodeMapRange"); wr.interpolation_type = "SMOOTHSTEP"
            wr.inputs["From Min"].default_value = WATER_Z + 0.45; wr.inputs["From Max"].default_value = WATER_Z
            nt.links.new(sz.outputs["Z"], wr.inputs["Value"])
            wm_ = nt.nodes.new("ShaderNodeMix"); wm_.data_type = "RGBA"; wm_.blend_type = "MULTIPLY"
            wm_.inputs["B"].default_value = (0.62, 0.6, 0.58, 1)
            nt.links.new(wr.outputs["Result"], wm_.inputs["Factor"]); nt.links.new(hs.outputs["Color"], wm_.inputs["A"])
            nt.links.new(underwater(nt, wm_.outputs["Result"]), bsdf.inputs["Base Color"])

ACTS = {a.name: a for a in bpy.data.actions}

# Переходы NLA смешивают кватернионы покомпонентно: если у двух анимаций знак поворота кости разный (q и −q — один поворот),
# на стыке голова выворачивается и шея рвётся. Приводим все ключи к одной полусфере с опорной стойкой.
def _fcurves(act):
    out = []
    for ly in act.layers:
        for st in ly.strips:
            for cb in st.channelbags: out += list(cb.fcurves)
    return out
def _quats(act):
    q = {}
    for fc in _fcurves(act):
        if fc.data_path.endswith("rotation_quaternion"): q.setdefault(fc.data_path, [None] * 4)[fc.array_index] = fc
    return {k: v for k, v in q.items() if all(v)}
ref = {k: [fc.keyframe_points[0].co[1] for fc in v] for k, v in _quats(ACTS["pudge_idle"]).items()}
flips = 0
for act in ACTS.values():
    for path, fcs in _quats(act).items():
        r = ref.get(path)
        if not r: continue
        n = min(len(fc.keyframe_points) for fc in fcs)
        for i in range(n):
            v = [fc.keyframe_points[i].co[1] for fc in fcs]
            if sum(a_ * b_ for a_, b_ in zip(v, r)) < 0:
                for fc, x in zip(fcs, v):
                    kp = fc.keyframe_points[i]; d = -x - x
                    kp.co[1] = -x; kp.handle_left[1] += d; kp.handle_right[1] += d
                flips += 1
        for fc in fcs: fc.update()
log("кватернионы: перевёрнуто ключей", flips)
def align_signs(acts):
    n = 0
    for act in acts:
        for path, fcs in _quats(act).items():
            r = ref.get(path)
            if not r: continue
            for i in range(min(len(fc.keyframe_points) for fc in fcs)):
                v = [fc.keyframe_points[i].co[1] for fc in fcs]
                if sum(a_ * b_ for a_, b_ in zip(v, r)) < 0:
                    for fc, x in zip(fcs, v):
                        kp = fc.keyframe_points[i]; d = -2 * x
                        kp.co[1] = -x; kp.handle_left[1] += d; kp.handle_right[1] += d
                    n += 1
            for fc in fcs: fc.update()
    return n
exec(compile(open(os.path.join(HERE, "pudge_cast.py"), encoding="utf-8").read(), "pudge_cast.py", "exec"))

# ---------------- вода ----------------
bpy.ops.mesh.primitive_plane_add(size=1, location=(10, 40, WATER_Z))
water = bpy.context.active_object; water.name = "WATER"; water.scale = (900, 900, 1)   # до горизонта, без обрыва
wm = bpy.data.materials.new("WaterNice"); wm.use_nodes = True
wm.surface_render_method = "DITHERED"
try: wm.thickness_mode = "SLAB"
except Exception: pass
nt = wm.node_tree; N, L = nt.nodes, nt.links; N.clear(); nb = NB(nt)
out = N.new("ShaderNodeOutputMaterial"); b = N.new("ShaderNodeBsdfPrincipled")
b.inputs["Base Color"].default_value = (0.015, 0.11, 0.10, 1) if FIRST else WBODY
b.inputs["Roughness"].default_value = 0.03
b.inputs["IOR"].default_value = 1.333
tr_ = N.new("ShaderNodeBsdfTransparent"); tr_.inputs["Color"].default_value = (0.62, 0.96, 0.86, 1) if FIRST else WTINT   # g_vRefractionTint как есть (множитель шейдера)
fr = N.new("ShaderNodeFresnel"); fr.inputs["IOR"].default_value = 1.333
body_mix = N.new("ShaderNodeMixShader")
tv = N.new("ShaderNodeValue"); tv.label = "time"
fc = tv.outputs[0].driver_add("default_value"); fc.driver.expression = f"frame/{FPS}"
T_ = tv.outputs[0]
geo = N.new("ShaderNodeNewGeometry"); P = geo.outputs["Position"]
flow = (0.7, 0.7, 0.0)
def ripple(scale_, speed, detail, w):
    off = nb.v("SCALE", flow, None, nb.m("MULTIPLY", T_, speed))
    nz = N.new("ShaderNodeTexNoise"); nz.noise_dimensions = "4D"
    nz.inputs["Scale"].default_value = scale_; nz.inputs["Detail"].default_value = detail
    L.new(nb.v("ADD", P, off), nz.inputs["Vector"]); L.new(nb.m("MULTIPLY", T_, 0.25), nz.inputs["W"])
    return nb.m("MULTIPLY", nz.outputs["Fac"], w)
h = nb.m("MULTIPLY", ripple(1.4, 1.4, 2, 0.45), 0.4)
WN_IMG = img("water_river_normal_sharp_temp_normal_tga_4ab60bd5.vtex", False)
def wlayer(scale_m, speed, ang):
    off = nb.v("SCALE", (math.cos(ang), math.sin(ang), 0), None, nb.m("MULTIPLY", T_, speed))
    uv = nb.v("SCALE", nb.v("ADD", P, off), None, 1.0 / scale_m)
    tx = N.new("ShaderNodeTexImage"); tx.image = WN_IMG; L.new(uv, tx.inputs[0])
    return tx.outputs["Color"]
nmix = nb.mixc(wlayer(12.7, 0.55, math.atan2(0.85, 0.52)), wlayer(7.3, 0.35, math.atan2(0.85, 0.52) + 0.6), 0.5)
wnm = N.new("ShaderNodeNormalMap"); wnm.space = "WORLD" if False else "TANGENT"; wnm.inputs["Strength"].default_value = 0.8
L.new(nmix, wnm.inputs["Color"])
foam = None
for k, e in enumerate(RING_CENTERS):
    cx = N.new("ShaderNodeCombineXYZ"); cx.inputs[2].default_value = WATER_Z
    for i_, ax in enumerate(("LOC_X", "LOC_Y")):
        dr = cx.inputs[i_].driver_add("default_value").driver; dr.type = "AVERAGE"
        v_ = dr.variables.new(); v_.type = "TRANSFORMS"
        v_.targets[0].id = e; v_.targets[0].transform_type = ax; v_.targets[0].transform_space = "WORLD_SPACE"
    d = nb.v("DISTANCE", P, cx.outputs[0])
    wave = nb.m("SINE", nb.m("SUBTRACT", nb.m("MULTIPLY", d, 4.2), nb.m("MULTIPLY", T_, 5.0 + k * 0.3)))
    env = nb.m("MULTIPLY", nb.m("EXPONENT", nb.m("MULTIPLY", d, -0.45)), nb.m("MULTIPLY", nb.m("SUBTRACT", d, 1.3), 2.0, clamp=True))
    h = nb.m("ADD", h, nb.m("MULTIPLY", nb.m("MULTIPLY", wave, env), 0.9))
    f = nb.m("SUBTRACT", 1.0, nb.m("MULTIPLY", nb.m("SUBTRACT", d, 1.25), 2.6), clamp=True)
    foam = f if foam is None else nb.m("MAXIMUM", foam, f)
bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.35; bump.inputs["Distance"].default_value = 0.08
L.new(h, bump.inputs["Height"]); L.new(wnm.outputs[0], bump.inputs["Normal"]); L.new(bump.outputs[0], b.inputs["Normal"]); L.new(bump.outputs[0], fr.inputs["Normal"])
opac = nb.m("MULTIPLY_ADD", fr.outputs[0], 0.6 if FIRST else 0.5, 0.38 if FIRST else WOPAC, clamp=True)   # g_flReflectance 0.33 + Френель   # g_flReflectionAmount 0.2 + Френель
L.new(opac, body_mix.inputs[0]); L.new(tr_.outputs[0], body_mix.inputs[1]); L.new(b.outputs[0], body_mix.inputs[2])
fn = N.new("ShaderNodeTexNoise"); fn.noise_dimensions = "4D"; fn.inputs["Scale"].default_value = 3.5; fn.inputs["Detail"].default_value = 4
L.new(P, fn.inputs["Vector"]); L.new(T_, fn.inputs["W"])
fm = nb.m("MULTIPLY", nb.m("MULTIPLY", foam, nb.m("MULTIPLY", nb.m("SUBTRACT", fn.outputs["Fac"], 0.45), 3.0, clamp=True), clamp=True), 0.75)
FD = (-0.52, -0.85, 0.0)                     # вниз по течению (к камере)
along = nb.v("DOT_PRODUCT", P, FD); across = nb.v("DOT_PRODUCT", P, (-0.85, 0.52, 0.0))
stc = N.new("ShaderNodeCombineXYZ")
L.new(nb.m("MULTIPLY", nb.m("SUBTRACT", along, nb.m("MULTIPLY", T_, 0.9)), 0.22), stc.inputs[0])
L.new(nb.m("MULTIPLY", across, 0.9), stc.inputs[1]); L.new(nb.m("MULTIPLY", T_, 0.05), stc.inputs[2])
stx = N.new("ShaderNodeTexNoise"); stx.inputs["Scale"].default_value = 1.0; stx.inputs["Detail"].default_value = 3
L.new(stc.outputs[0], stx.inputs["Vector"])
streak = nb.m("MULTIPLY", nb.m("MULTIPLY", nb.m("SUBTRACT", stx.outputs["Fac"], 0.58), 2.5, clamp=True), 0.1)
fm = nb.m("MAXIMUM", fm, streak)
foam_b = N.new("ShaderNodeBsdfPrincipled"); foam_b.inputs["Base Color"].default_value = (0.92, 0.97, 0.97, 1); foam_b.inputs["Roughness"].default_value = 0.6
ms = N.new("ShaderNodeMixShader"); L.new(fm, ms.inputs[0]); L.new(body_mix.outputs[0], ms.inputs[1]); L.new(foam_b.outputs[0], ms.inputs[2])
L.new(ms.outputs[0], out.inputs[0])
water.data.materials.append(wm)
water.visible_shadow = False

# ---------------- небо, свет ----------------
world = bpy.data.worlds.new("Sky"); sc.world = world; world.use_nodes = True
wt = world.node_tree; WN, WL = wt.nodes, wt.links; WN.clear()
wo = WN.new("ShaderNodeOutputWorld"); tc = WN.new("ShaderNodeTexCoord"); sep = WN.new("ShaderNodeSeparateXYZ")
WL.new(tc.outputs["Generated"], sep.inputs[0])
ramp = WN.new("ShaderNodeValToRGB"); WL.new(sep.outputs["Z"], ramp.inputs[0])
cr = ramp.color_ramp; cr.elements[0].position = 0.0; cr.elements[0].color = (0.7, 0.88, 0.98, 1)
cr.elements[1].position = 0.25; cr.elements[1].color = (0.12, 0.38, 0.92, 1)
bg_cam = WN.new("ShaderNodeBackground"); WL.new(ramp.outputs[0], bg_cam.inputs[0])
bg_amb = WN.new("ShaderNodeBackground"); bg_amb.inputs["Color"].default_value = (0.5, 0.7, 0.95, 1) if FIRST else tuple(srgb2lin(c) for c in AMB) + (1,); bg_amb.inputs["Strength"].default_value = 0.55 if FIRST else AMB_S
lp = WN.new("ShaderNodeLightPath"); mx = WN.new("ShaderNodeMixShader")
WL.new(lp.outputs["Is Camera Ray"], mx.inputs[0]); WL.new(bg_amb.outputs[0], mx.inputs[1]); WL.new(bg_cam.outputs[0], mx.inputs[2])
WL.new(mx.outputs[0], wo.inputs[0])
world.mist_settings.start = 32; world.mist_settings.depth = 140; world.mist_settings.falloff = "LINEAR"
if FIRST: world.mist_settings.start = 70; world.mist_settings.depth = 220; world.mist_settings.falloff = "QUADRATIC"

def sun(name, energy, color, elev, azim, angle, shadow=True):
    ld = bpy.data.lights.new(name, "SUN"); ld.energy = energy; ld.color = color; ld.angle = math.radians(angle); ld.use_shadow = shadow
    o = bpy.data.objects.new(name, ld); sc.collection.objects.link(o)
    e, z = math.radians(elev), math.radians(azim)
    d = Vector((math.cos(e) * math.cos(z), math.cos(e) * math.sin(z), math.sin(e)))   # направление на солнце
    o.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    return o
# В доте камера смотрит на север, солнце (light_direction_day [66, 0]) светит слева направо по экрану, блик
# (specular_direction_day [64, 283]) — спереди чуть слева. Ставим их так же относительно нашей камеры.
CAM_AZ = math.degrees(math.atan2(LOOK0[1] - CAM0[1], LOOK0[0] - CAM0[0]))
if FIRST:   # как на первом кадре: тёплое солнце сзади-слева от камеры (126.5° от взгляда) и холодный контровой
    sun("Sun", 8.5, (1.0, 0.9, 0.74), 42, CAM_AZ + 126.5, 1.5)
    sun("Rim", 1.6, (0.75, 0.88, 1.0), 25, CAM_AZ - 78.5, 5.0, False)
else:
    sun("Sun", SUN_S, tuple(srgb2lin(c) for c in SUN_C), 66, CAM_AZ + 90, 1.5)
    spec = sun("Spec", 4.0, tuple(srgb2lin(c) for c in SPEC_C), 64, CAM_AZ + 13, 3.0, False)
    spec.data.diffuse_factor = 0.0; spec.data.volume_factor = 0.0

# ---------------- камера ----------------
cam_d = bpy.data.cameras.new("Cam"); cam_d.sensor_fit = "VERTICAL"; cam_d.angle_y = math.radians(50)
cam = bpy.data.objects.new("Cam", cam_d); sc.collection.objects.link(cam); sc.camera = cam
tgt = bpy.data.objects.new("CamTarget", None); sc.collection.objects.link(tgt)
c = cam.constraints.new("TRACK_TO"); c.target = tgt; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
for f, p, l in ((1, CAM0, LOOK0), (FRAMES, CAM1, LOOK1)):
    cam.location = p; cam.keyframe_insert("location", frame=f)
    tgt.location = l; tgt.keyframe_insert("location", frame=f)
cam_d.dof.use_dof = True; cam_d.dof.focus_object = tgt; cam_d.dof.aperture_fstop = 5.6

exec(compile(open(os.path.join(HERE, "fx_006.py"), encoding="utf-8").read(), "fx_006.py", "exec"))
# ---------------- рендер ----------------
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1080, 1920, 100
sc.render.use_persistent_data = True   # статичная карта готовится один раз, а не перед каждым кадром
sc.render.fps = FPS; sc.frame_start = 1; sc.frame_end = FRAMES
ee = sc.eevee
ee.taa_render_samples = 64 if MODE == "render" else 32
ee.use_raytracing = True; ee.ray_tracing_method = "SCREEN"
ee.use_shadows = True; ee.shadow_ray_count = 2; ee.shadow_step_count = 8
ee.use_fast_gi = True
sc.render.use_motion_blur = True; sc.render.motion_blur_shutter = 0.5   # брызги и быстрые руки смазываются, как на видео
sc.view_settings.view_transform = VIEW
if VIEW == "AgX": sc.view_settings.look = "AgX - Punchy"
sc.view_settings.exposure = EXPO
sc.view_layers[0].use_pass_mist = True
try:
    ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers"); go = ng.nodes.new("NodeGroupOutput")
    mxc = ng.nodes.new("ShaderNodeMix"); mxc.data_type = "RGBA"
    mf = ng.nodes.new("ShaderNodeMath"); mf.operation = "MULTIPLY"; mf.inputs[1].default_value = 0.35 if FIRST else FOG_K
    ng.links.new(rl.outputs["Mist"], mf.inputs[0]); ng.links.new(mf.outputs[0], mxc.inputs["Factor"])
    ng.links.new(rl.outputs["Image"], mxc.inputs["A"]); mxc.inputs["B"].default_value = (0.62, 0.82, 0.95, 1) if FIRST else tuple(srgb2lin(c) for c in (175, 190, 191)) + (1,)
    hs = ng.nodes.new("CompositorNodeHueSat"); hs.inputs["Saturation"].default_value = SAT
    ng.links.new(mxc.outputs["Result"], hs.inputs["Image"]); ng.links.new(hs.outputs["Image"], go.inputs[0])
    sc.compositing_node_group = ng
except Exception as e:
    log("композитинг не собран:", e)

bpy.ops.wm.save_as_mainfile(filepath=G + r"\blend\scene006.blend")
log("сохранено")

outdir = G + (r"\renders\frames" if MODE == "render" else r"\renders\preview")
os.makedirs(outdir, exist_ok=True)
sc.render.image_settings.file_format = "PNG"
if MODE == "top":
    cam_d.type = "ORTHO"; cam_d.ortho_scale = 110; cam.constraints.clear(); cam.animation_data_clear()
    cam.location = (-20, -1, 120); cam.rotation_euler = (0, 0, 0); cam_d.dof.use_dof = False
    sc.render.resolution_x = sc.render.resolution_y = 1400; ee.taa_render_samples = 8
    world.mist_settings.start = 1000
    sc.frame_set(1); sc.render.filepath = os.path.join(outdir, "top.png"); bpy.ops.render.render(write_still=True)
elif MODE == "check":
    pass
elif MODE == "sheet":
    sc.render.resolution_percentage = 30; ee.taa_render_samples = 8
    for f in range(1, FRAMES + 1, 23):
        sc.frame_set(f); sc.render.filepath = os.path.join(outdir, f"s_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
elif MODE == "quick":
    sc.render.resolution_percentage = 50; ee.taa_render_samples = 16
    sc.frame_set(200); sc.render.filepath = os.path.join(outdir, "q.png"); bpy.ops.render.render(write_still=True)
elif MODE == "preview":
    frames = [int(x) for x in ARGS[1].split(",")] if len(ARGS) > 1 else [1]
    for f in frames:
        sc.frame_set(f); sc.render.filepath = os.path.join(outdir, f"p_{f:04d}.png")
        bpy.ops.render.render(write_still=True); log("кадр", f)
else:
    sc.render.use_overwrite = False; sc.render.use_placeholder = True   # готовые кадры не пересчитываются
    if len(ARGS) > 2: sc.frame_start, sc.frame_end = int(ARGS[1]), int(ARGS[2])   # render <с> <по> — часть кадров для параллельного рендера
    sc.render.filepath = outdir + "\\f_"
    bpy.ops.render.render(animation=True)
log("готово")
