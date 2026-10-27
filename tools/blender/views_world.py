# Проверка движения с неподвижных камер: сцена собирается render_scene.py (без его рендера), потом выбранные кадры
# снимаются камерами вокруг героя, стоящими на месте весь ролик (A8_VIEWS в render_scene ведёт камеру за взглядом героя —
# поворот на месте с ней не виден). Углы — от взгляда героя на первом из кадров; кадры подряд → ролик движения.
# blender -b --factory-startup -P tools/blender/views_world.py -- <scene.json> <папка> <кадры 0,2,4…> [half]
#   A8_WVIEWS=pudge:0,90      герой и углы, °
import bpy, os, math
from mathutils import Matrix, Vector

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_scene.py")
code = open(SRC, encoding="utf-8").read().replace("bpy.ops.render.render(", "_noop(")
os.environ.pop("A8_VIEWS", None)
g = {"__file__": SRC, "__name__": "__main__", "_noop": lambda **k: None}
exec(compile(code, SRC, "exec"), g)

R = math.radians
sc, ACTORS, HERO_OBJS, PICK, OUT = g["sc"], g["ACTORS"], g["HERO_OBJS"], g["PICK"], g["OUT"]
who, angs = os.environ["A8_WVIEWS"].split(":")
arm = ACTORS[who]["arm"]
vd = bpy.data.cameras.new("wview"); vc = bpy.data.objects.new("wview", vd); sc.collection.objects.link(vc)
vd.angle = R(40); vd.clip_start = 0.05; sc.camera = vc
sc.frame_set(PICK[0])
bones = [arm.matrix_world @ b.head for b in arm.pose.bones]
lo = min(p.z for p in bones); hi = max(p.z for p in bones); mid = sum(bones, Vector()) / len(bones)
d = ((hi - lo) * 1.6 + 0.6) / 2 / math.tan(R(20)) * 1.4
fwd = arm.matrix_world.to_3x3() @ Vector((0, -1, 0)); fwd.z = 0; fwd.normalize()
aimp = Vector((mid.x, mid.y, (lo + hi) / 2))
mine = HERO_OBJS | {arm} | set(arm.children_recursive)
for a in angs.split(","):
    vc.location = aimp + (Matrix.Rotation(R(float(a)), 3, "Z") @ fwd) * d + Vector((0, 0, 0.3))
    vc.rotation_euler = (aimp - vc.location).to_track_quat("-Z", "Y").to_euler()
    for o in [o for o in sc.objects if o.get("a8_view_hid")]:
        o.hide_render = False; o.hide_viewport = False; del o["a8_view_hid"]
    for _ in range(12):                                   # что заслоняет героя на луче (дерево, камень) — убрать на этот угол
        dg = bpy.context.evaluated_depsgraph_get(); dg.update()
        hit, _p, _n, _i, o, _m = sc.ray_cast(dg, vc.location, (aimp - vc.location).normalized(), distance=(aimp - vc.location).length)
        if not hit or o.original in mine:
            break
        o = o.original; o.hide_render = True; o.hide_viewport = True; o["a8_view_hid"] = 1
    for f in PICK:
        sc.frame_set(f)
        sc.render.filepath = os.path.join(OUT, f"w{f:05d}_{int(float(a)):03d}.png")
        bpy.ops.render.render(write_still=True)
print("ГОТОВО", OUT)
