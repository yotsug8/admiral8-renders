# Настоящая карта доты в Blender: кусок, вырезанный tools/map_crop.mjs из полной выгрузки (_game/world), с материалами
# как в игре — земля смешивается из 4 слоёв (свой шейдер multiblend по параметрам vmat), прочее — с дизерингом альфы.
# Взято из сборки сцены 006. Использование: import dota_map; objs = dota_map.load(путь_к_glb, папка_текстур)
# Оси: Blender x = игра y / 39.37, Blender y = −игра x / 39.37, z = игра z / 39.37.
import bpy, bmesh, math, os, re
from mathutils import Vector

GAME = 0; FIRST = 1
WATER_Z = -100.0                       # подводной мути нет (сцена на суше)
TEX = None
def log(*a): print("[карта]", *a, flush=True)

def srgb2lin(c):
    c = c / 255 if c > 1.0 else c

    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


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



def hide_mat(mat):
    """Материал невидим (и без тени)."""
    mat.use_nodes = True; nt = mat.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    nt.links.new(tr.outputs[0], out.inputs[0]); mat.surface_render_method = "DITHERED"


def load(glb, tex_dir, ground_z=None):
    """Импорт куска карты и настройка материалов. Возвращает объекты карты."""
    global TEX
    TEX = tex_dir
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb, bone_heuristic="BLENDER")
    objs = [o for o in bpy.data.objects if o not in before]
    nmb = 0
    for mat in list(bpy.data.materials):
        v = mat.get("vmat")
        v = v.to_dict() if hasattr(v, "to_dict") else (v or {})
        sh = v.get("ShaderName", "")
        if sh == "multiblend.vfx":
            multiblend(mat, v); nmb += 1
        elif re.search(r"tree_(magical|blossoms)", v.get("Name", "")):
            hide_mat(mat)                              # варианты листвы (события, сезоны): в выгрузке все сразу поверх обычной, в игре — нет
        elif sh == "water_dota.vfx":
            mat["_water"] = 1
        elif v:
            fix_prop(mat, v)
    for o in objs:
        if o.type != "MESH":
            continue
        names = [ms.material.name for ms in o.material_slots if ms.material]
        if any(bpy.data.materials[n].get("_water") for n in names) or any(n.startswith(("tools", "black")) for n in names):
            o.hide_render = True; o.hide_viewport = True
    # камни и стены на скалах: самих скал в выгрузке нет (сверху, как в игре, не видно) — снизу они висят в воздухе
    dg = bpy.context.evaluated_depsgraph_get(); floating = 0

    def floats(c, low):
        """Под куском нет земли ближе 2 м; или земли нет вовсе (край вырезанной карты), а кусок выше героев."""
        hit, loc, *_ = bpy.context.scene.ray_cast(dg, Vector((c.x, c.y, low - 0.05)), Vector((0, 0, -1)))
        return (hit and low - loc.z > 2.0) or (not hit and ground_z is not None and low > ground_z + 2.0)
    for o in objs:
        if o.type != "MESH" or o.hide_render:
            continue
        if re.search(r"glow_\d", o.name):              # плоские карточки «свечения» — в игре мягкие, здесь квадраты
            o.hide_render = True; o.hide_viewport = True; floating += 1; continue
        if not re.search(r"stone_wall|cliff|rock|mod_radiant|mod_dire", o.name, re.I):
            continue
        # слитые меши (agg_merge) несут и землю, и скалы — проверяется каждый связный кусок отдельно
        bm = bmesh.new(); bm.from_mesh(o.data); bm.faces.ensure_lookup_table()
        mw = o.matrix_world; seen = set(); drop = []
        for f0 in bm.faces:
            if f0.index in seen:
                continue
            part, stack = [], [f0]; seen.add(f0.index)
            while stack:
                f = stack.pop(); part.append(f)
                for e in f.edges:
                    for g in e.link_faces:
                        if g.index not in seen:
                            seen.add(g.index); stack.append(g)
            pts = [mw @ v.co for f in part for v in f.verts]
            low = min(q.z for q in pts); c = sum(pts, Vector()) / len(pts)
            if not floats(c, low):
                continue
            drop += part
        if drop and len(drop) == len(bm.faces):
            o.hide_render = True; o.hide_viewport = True; floating += 1
        elif drop and o.data.users == 1:
            bmesh.ops.delete(bm, geom=list(set(drop)), context="FACES"); bm.to_mesh(o.data); floating += 1
        bm.free()
    log("объектов", len(objs), "земля (multiblend)", nmb, "убрано висящих камней и карточек свечения", floating)
    return objs
