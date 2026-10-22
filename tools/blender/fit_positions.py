# Автоподбор позиций Пуджей без касаний: blender -b scene006.blend -P fit_positions.py -- P1,BOB,SPIN
# Для каждого по очереди пробует сдвиги (вдоль/поперёк реки) от малого к большому; годится сдвиг, при котором по всей
# анимации нет пересечений с другими Пуджами и с картой выше воды, а голова в безопасной зоне кадра. Печатает FIT имя dal dlat.
import bpy, bmesh, sys, math
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view
WHO = sys.argv[sys.argv.index("--") + 1].split(",")
sc = bpy.context.scene; cam = sc.camera; WATER_Z = 1.6; STEP = 2
DIR = Vector((0.52, 0.85, 0)).normalized(); PERP = Vector((DIR.y, -DIR.x, 0))
arms = {o.parent.name.replace("Mover_", ""): o for o in sc.objects if o.type == "ARMATURE" and not o.hide_render and o.parent}
MESH = {n: [c for c in a.children if c.type == "MESH" and not c.hide_render] for n, a in arms.items()}
# карта выше воды (как в qa_scene)
dg = bpy.context.evaluated_depsgraph_get()
ctr = sum((a.parent.matrix_world.translation for a in arms.values()), Vector()) / len(arms)
bm = bmesh.new()
for o in sc.objects:
    if o.type != "MESH" or o.hide_render or o.name == "WATER" or (o.parent and o.parent.type == "ARMATURE"): continue
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    if max(v.z for v in bb) < WATER_Z + 0.1 or min(v.z for v in bb) > 12: continue
    if min((Vector((v.x - ctr.x, v.y - ctr.y, 0))).length for v in bb) > 45 and not (min(v.x for v in bb) < ctr.x < max(v.x for v in bb) and min(v.y for v in bb) < ctr.y < max(v.y for v in bb)): continue
    ev = o.evaluated_get(dg); me = ev.to_mesh(); me.transform(ev.matrix_world); bm.from_mesh(me); ev.to_mesh_clear()
bmesh.ops.delete(bm, geom=[f for f in bm.faces if max(v.co.z for v in f.verts) < WATER_Z + 0.1], context="FACES")
MAP = BVHTree.FromBMesh(bm)
# кэш геометрии всех Пуджей по кадрам
frames = list(range(1, sc.frame_end + 1, STEP))
geo = {n: [] for n in arms}; heads = {n: [] for n in arms}
for f in frames:
    sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get()
    for n, a in arms.items():
        vs, ps = [], []
        for m in MESH[n]:
            ev = m.evaluated_get(dg); me = ev.to_mesh(); me.transform(ev.matrix_world)
            o0 = len(vs); vs += [v.co.copy() for v in me.vertices]; ps += [[o0 + i for i in p.vertices] for p in me.polygons]
            ev.to_mesh_clear()
        geo[n].append((vs, ps)); heads[n].append(a.matrix_world @ a.pose.bones["head"].head)
print("FIT кэш готов")
off = {n: Vector() for n in arms}
def tree(n, i, extra=Vector()):
    vs, ps = geo[n][i]; d = off[n] + extra
    return BVHTree.FromPolygons([v + d for v in vs], ps)
def clean(n, extra):
    for i, f in enumerate(frames):
        t = tree(n, i, extra)
        if t.overlap(MAP): return False, f"карта@{f}"
        for m in arms:
            if m != n and t.overlap(tree(m, i)): return False, f"{m}@{f}"
        hv = world_to_camera_view(sc, cam, heads[n][i] + off[n] + extra)
        if hv.z > 0 and heads[n][i].z > WATER_Z and not (0.06 < hv.x < 0.94 and 0.19 < hv.y < 0.74): return False, f"кадр@{f}"
    return True, ""
cands = sorted({(da, dl) for da in [x * 0.5 for x in range(-8, 9)] for dl in [x * 0.3 for x in range(-10, 11)]}, key=lambda c: math.hypot(*c))
for n in WHO:
    for da, dl in cands:
        ok, why = clean(n, DIR * da + PERP * dl)
        if ok:
            off[n] = off[n] + DIR * da + PERP * dl
            print(f"FIT {n} {da:+.1f} {dl:+.1f}", flush=True); break
    else:
        print(f"FIT {n} НЕ НАЙДЕНО", flush=True)
    print("FIT причина на месте:", n, clean(n, Vector())[1], flush=True)
