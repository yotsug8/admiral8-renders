# Полная проверка сцены 006 по всей анимации: blender -b scene006.blend -P qa_scene.py
# Пересечения Пуджей между собой и с картой, обрезка кадром и зоны заголовка/интерфейса, головы пловцов над водой,
# рывки поз и носителей, лица, закрытые картой. Печатает QA-строки и итог QA_OK / QA_FAIL.
import bpy, bmesh, math
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view
sc = bpy.context.scene; cam = sc.camera
WATER_Z = 1.6
STEP = 2
arms = [o for o in sc.objects if o.type == "ARMATURE" and not o.hide_render and o.parent]
NAME = {a: a.parent.name.replace("Mover_", "") for a in arms}
MESH = {a: [c for c in a.children if c.type == "MESH" and not c.hide_render] for a in arms}
DIVE = {"BOB": (95, 186)}
FAST_OK = {"P7": (0, 200), "BOB": (170, 192), "SPIN": (40, 130)}   # быстрые движения по замыслу: денежный танец, выпрыгивание из воды                          # нарочно под водой
LYING = {"SWIM", "FLOAT"}
problems = {}
def bad(kind, who, f, info=""):
    problems.setdefault((kind, who), []).append((f, info))

# карта рядом с Пуджами, выше дна: статичный BVH
dg = bpy.context.evaluated_depsgraph_get()
ctr = sum((a.parent.matrix_world.translation for a in arms), Vector()) / len(arms)
bm = bmesh.new(); mapnames = []
for o in sc.objects:
    if o.type != "MESH" or o.hide_render or o.name == "WATER" or o in sum(MESH.values(), []): continue
    if o.parent in arms: continue
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    if min(v.z for v in bb) > 12 or max(v.z for v in bb) < WATER_Z - 0.6: continue
    if min((Vector((v.x, v.y, 0)) - Vector((ctr.x, ctr.y, 0))).length for v in bb) > 40 and \
       not (min(v.x for v in bb) < ctr.x < max(v.x for v in bb) and min(v.y for v in bb) < ctr.y < max(v.y for v in bb)): continue
    ev = o.evaluated_get(dg); me = ev.to_mesh(); me.transform(ev.matrix_world)
    n0 = len(bm.faces); bm.from_mesh(me); ev.to_mesh_clear()
    mapnames += [o.name] * (len(bm.faces) - n0)
bm.faces.ensure_lookup_table()
# только то, что выше дна: дно реки и так под Пуджами
geom_del = [f for f in bm.faces if max(v.co.z for v in f.verts) < WATER_Z + 0.1]
keep_names = [n for f, n in zip(bm.faces, mapnames) if max(v.co.z for v in f.verts) >= WATER_Z + 0.1]
bmesh.ops.delete(bm, geom=geom_del, context="FACES")
MAP = BVHTree.FromBMesh(bm); bm.faces.ensure_lookup_table()
print("QA карта рядом:", len(keep_names), "граней")

prev = {}
for f in range(1, sc.frame_end + 1, STEP):
    sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get()
    trees, verts = {}, {}
    for a in arms:
        b = bmesh.new()
        for m in MESH[a]:
            ev = m.evaluated_get(dg); me = ev.to_mesh(); me.transform(ev.matrix_world); b.from_mesh(me); ev.to_mesh_clear()
        verts[a] = [v.co.copy() for i_, v in enumerate(b.verts) if i_ % 7 == 0]
        trees[a] = BVHTree.FromBMesh(b); b.free()
    # 1. Пудж с Пуджем
    for i, a in enumerate(arms):
        for c in arms[i + 1:]:
            n = len(trees[a].overlap(trees[c]))
            if n: bad("пересечение", f"{NAME[a]}+{NAME[c]}", f, n)
    for a in arms:
        nm = NAME[a]
        # 2. Пудж с картой (берег, камни, деревья) выше дна
        ov = trees[a].overlap(MAP)
        if ov:
            hits = {keep_names[j] for _, j in ov if j < len(keep_names)}
            bad("в карте", nm, f, ",".join(sorted(h.split(".")[0] for h in hits))[:80])
        head = a.matrix_world @ a.pose.bones["head"].head
        # 3. Кадр: голова в безопасной зоне, тело не обрезано больше чем на 25%
        hv = world_to_camera_view(sc, cam, head)
        if not (0.05 < hv.x < 0.95 and 0.19 < hv.y < 0.74) and hv.z > 0:
            bad("голова вне зоны", nm, f, f"x={hv.x:.2f} y={hv.y:.2f}")
        above = [v for v in verts[a] if v.z > WATER_Z]
        if above:
            pr = [world_to_camera_view(sc, cam, v) for v in above]
            out = sum(1 for p in pr if not (0 <= p.x <= 1 and 0 <= p.y <= 1)) / len(pr)
            if out > 0.25: bad("обрезан кадром", nm, f, f"{out:.0%}")
        # 4. Голова над водой (кроме нарочного нырка)
        d = DIVE.get(nm)
        if head.z < WATER_Z + 0.15 and not (d and d[0] <= f <= d[1]):
            bad("голова под водой", nm, f, f"z={head.z:.2f}")
        # 5. Рывки: скачок точек тела между соседними проверками
        pts = [a.matrix_world @ a.pose.bones[b].head for b in ("root", "spine3", "head", "wrist_L", "wrist_R")]
        if a in prev:
            jump = max((p - q).length for p, q in zip(pts, prev[a])) / STEP
            ok_ = FAST_OK.get(nm)
            if jump > 0.7 and not (ok_ and ok_[0] <= f <= ok_[1]): bad("рывок", nm, f, f"{jump:.2f} м/кадр")
        prev[a] = pts
        # 6. Лицо закрыто картой со стороны камеры
        cp = cam.matrix_world.translation; dvec = head - cp
        hit = MAP.ray_cast(cp, dvec.normalized(), dvec.length - 0.6)
        if hit[0] is not None and not (d and d[0] <= f <= d[1]) and hv.z > 0 and 0 < hv.x < 1 and 0 < hv.y < 1:
            bad("лицо закрыто картой", nm, f, keep_names[hit[2]].split(".")[0] if hit[2] < len(keep_names) else "")

ok = True
for (kind, who), v in sorted(problems.items()):
    fr = [x for x, _ in v]
    print(f"QA {kind:20s} {who:12s} кадров {len(fr):3d}  {fr[0]}–{fr[-1]}  пример: кадр {v[0][0]} {v[0][1]}")
    ok = False
print("QA_OK" if ok else "QA_FAIL")
