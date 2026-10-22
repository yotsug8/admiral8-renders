# Эффекты 006 (исполняется внутри build_006.py): ветер для листвы и травы, брызги от Пуджей.
import bpy, math, re

# ---------- ветер: узлы геометрии на листве, траве, камыше ----------
FOL = re.compile(r"tree|leaves|frond|bamboo|plant|grass|cattail|flower|bush|fern|vine|reed|petal|blossom", re.I)
def wind_group():
    ng = bpy.data.node_groups.new("Wind006", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    pos = N.new("GeometryNodeInputPosition"); st = N.new("GeometryNodeInputSceneTime")
    sep = N.new("ShaderNodeSeparateXYZ"); L.new(pos.outputs[0], sep.inputs[0])
    def m(op, a, b=None, clamp=False):
        n = N.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, x in enumerate((a, b)):
            if x is None: continue
            if isinstance(x, (int, float)): n.inputs[i].default_value = x
            else: L.new(x, n.inputs[i])
        return n.outputs[0]
    t = st.outputs["Seconds"]
    h = m("POWER", m("DIVIDE", m("SUBTRACT", sep.outputs["Z"], 0.6), 7.0, clamp=True), 1.5)     # у земли не качается
    ph = m("ADD", m("MULTIPLY", sep.outputs["X"], 0.35), m("MULTIPLY", sep.outputs["Y"], 0.22))
    gust = m("ADD", 0.75, m("MULTIPLY", m("SINE", m("MULTIPLY", t, 0.45)), 0.25))
    ox = m("MULTIPLY", m("MULTIPLY", m("SINE", m("ADD", m("MULTIPLY", t, 1.7), ph)), 0.16), m("MULTIPLY", h, gust))
    oy = m("MULTIPLY", m("MULTIPLY", m("SINE", m("ADD", m("MULTIPLY", t, 1.3), m("MULTIPLY", ph, 1.3))), 0.11), m("MULTIPLY", h, gust))
    cv = N.new("ShaderNodeCombineXYZ"); L.new(ox, cv.inputs[0]); L.new(oy, cv.inputs[1])
    sp = N.new("GeometryNodeSetPosition"); L.new(gi.outputs[0], sp.inputs["Geometry"]); L.new(cv.outputs[0], sp.inputs["Offset"])
    L.new(sp.outputs[0], go.inputs[0])
    return ng
WIND = wind_group(); nw = 0
from mathutils import Vector as _V
VIEWC = C + DIR * 15                        # середина видимой части реки
def visible_near(o):
    bb = [o.matrix_world @ _V(c) for c in o.bound_box]
    cx = sum(v.x for v in bb) / 8; cy = sum(v.y for v in bb) / 8
    big = max(max(v.x for v in bb) - min(v.x for v in bb), max(v.y for v in bb) - min(v.y for v in bb)) > 60
    return big or (_V((cx - VIEWC.x, cy - VIEWC.y, 0)).length < 60)
for o in mapobjs:
    if o.type != "MESH" or o.hide_render or not visible_near(o): continue
    if any(ms.material and FOL.search(ms.material.name) for ms in o.material_slots) or FOL.search(o.name):
        o.modifiers.new("wind", "NODES").node_group = WIND; nw += 1
log("ветер на объектах:", nw)

# ---------- брызги ----------
drop_m = bpy.data.materials.new("Drop"); drop_m.use_nodes = True
bd = drop_m.node_tree.nodes["Principled BSDF"]
bd.inputs["Base Color"].default_value = (0.78, 0.92, 0.95, 1); bd.inputs["Roughness"].default_value = 0.05
bd.inputs["Alpha"].default_value = 0.7; drop_m.surface_render_method = "DITHERED"
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0, location=(0, 0, -50))
bpy.ops.object.shade_smooth()
DROP = bpy.context.active_object; DROP.name = "Drop"; DROP.data.materials.append(drop_m)
DROP.hide_render = False

ARM = {o.parent.name.replace("Mover_", ""): o for o in pudge_objs if o.parent}
INVIS = bpy.data.materials.new("Invisible"); INVIS.use_nodes = True; INVIS.surface_render_method = "DITHERED"
_n = INVIS.node_tree.nodes; _n.clear(); _o = _n.new("ShaderNodeOutputMaterial"); _t = _n.new("ShaderNodeBsdfTransparent")
INVIS.node_tree.links.new(_t.outputs[0], _o.inputs[0])
def emitter(name, parent, bone=None, radius=0.3, shape="ball", loc=(0, 0, 0)):
    if shape == "ring":
        bpy.ops.mesh.primitive_circle_add(vertices=48, radius=radius, fill_type="NGON", location=(0, 0, 0))
    else:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=(0, 0, 0))
    e = bpy.context.active_object; e.name = name
    e.parent = parent
    if bone:
        e.parent_type = "BONE"; e.parent_bone = bone
    e.location = loc
    e.show_instancer_for_render = False; e.show_instancer_for_viewport = False
    e.visible_shadow = False
    return e
def splash(e, f0, f1, count, up=3.0, rnd=2.0, life=20, size=0.07, inherit=0.6, src="FACE"):
    mod = e.modifiers.new("splash", "PARTICLE_SYSTEM"); s = mod.particle_system.settings
    s.count = count; s.frame_start = f0; s.frame_end = f1; s.lifetime = life; s.lifetime_random = 0.5
    s.emit_from = src; s.use_emit_random = True
    s.normal_factor = up
    s.factor_random = rnd; s.object_factor = inherit
    s.render_type = "OBJECT"; s.instance_object = DROP
    s.particle_size = size; s.size_random = 0.8
    s.physics_type = "NEWTON"; s.effector_weights.gravity = 1.0
    s.use_rotations = False
    mod.particle_system.seed = hash(e.name) % 997
    e.show_instancer_for_render = False; e.show_instancer_for_viewport = False   # сам источник не рендерится
    e.data.materials.clear(); e.data.materials.append(INVIS)                  # и на всякий случай прозрачный
    return s
PS = 0.85   # масштаб Пуджей
# руки при кроле: капли с ладоней на каждом гребке
for b in ("wrist_R", "wrist_L"):
    splash(emitter(f"sp_swim_{b}", ARM["SWIM"], b, 0.25), -10, 205, 1400, up=2.2, rnd=1.6, life=16, size=0.025)
# флейл: руки и оружие разбрызгивают воду
for who, f0, f1 in (("P2", 252, 300), ("BOB", 172, 216)):
    for b in ("wrist_R", "wrist_L"):
        splash(emitter(f"sp_flail_{who}_{b}", ARM[who], b, 0.3), f0, f1, 600, up=2.5, rnd=2.5, life=18, size=0.03)
# всплески кольцом у воды: выпрыгивание, плюх обратно, переворот, лежебока садится, вращение
def ring(who, f0, f1, count, r=1.3, up=4.0, size=0.03):
    mv = bpy.data.objects["Mover_" + who]
    e = emitter(f"sp_ring_{who}_{f0}", None, None, r, "ring")
    e.location = (0, 0, WATER_Z + 0.05)
    # кольцо едет за Пуджем по воде (только X/Y)
    for ax in (0, 1):
        d = e.driver_add("location", ax).driver; d.type = "AVERAGE"
        v = d.variables.new(); v.type = "TRANSFORMS"; v.targets[0].id = mv
        v.targets[0].transform_type = "LOC_X" if ax == 0 else "LOC_Y"; v.targets[0].transform_space = "WORLD_SPACE"
    return splash(e, f0, f1, count, up=up, rnd=1.8, life=24, size=size, inherit=0.0, src="FACE")
ring("BOB", 172, 186, 1500, r=1.2, up=5.5, size=0.035)      # пулей из воды
ring("BOB", 204, 220, 900, r=1.3, up=3.2)                 # плюх обратно
ring("SWIM", 196, 222, 800, r=1.6, up=3.0)                # переворот на спину
ring("FLOAT", 180, 206, 700, r=1.6, up=2.6)               # садится
ring("SPIN", 40, 130, 1100, r=1.5, up=2.0, size=0.025)      # крутится — брызги по кругу
ring("P2", -7, 118, 500, r=1.2, up=2.4, size=0.025)        # топает
log("брызги готовы")
