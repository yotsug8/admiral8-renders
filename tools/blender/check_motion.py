# Замирания и оружие сквозь тело: blender -b scene006.blend -P check_motion.py
import bpy, bmesh
from mathutils.bvhtree import BVHTree
sc = bpy.context.scene
arms = [o for o in sc.objects if o.type == "ARMATURE" and not o.hide_render and o.parent]
NAME = {a: a.parent.name.replace("Mover_", "") for a in arms}
WEAP = ("righthook", "weapon", "leftweapon")
prev = {}; still = {a: [] for a in arms}; cut = {}
for f in range(1, sc.frame_end + 1):
    sc.frame_set(f)
    for a in arms:
        pts = [a.matrix_world @ pb.head for pb in a.pose.bones]
        if a in prev:
            mv = max((p - q).length for p, q in zip(pts, prev[a]))
            still[a].append((f, mv))
        prev[a] = pts
    if f % 3: continue
    dg = bpy.context.evaluated_depsgraph_get()
    for a in arms:
        body, weap = bmesh.new(), {}
        for m in a.children:
            if m.type != "MESH" or m.hide_render: continue
            ev = m.evaluated_get(dg); me = ev.to_mesh(); me.transform(ev.matrix_world)
            w = next((k for k in WEAP if f"\\{k}." in m.name or m.name.split("\\")[-1].startswith(k + ".")), None)
            if w:
                b = bmesh.new(); b.from_mesh(me); weap[w] = BVHTree.FromBMesh(b); b.free()
            elif not any(k in m.name for k in ("belt", "bracer", "back", "hair")):
                body.from_mesh(me)
            ev.to_mesh_clear()
        bt = BVHTree.FromBMesh(body); body.free()
        for w, t in weap.items():
            n = len(t.overlap(bt))
            if n > 105: cut.setdefault((NAME[a], w), []).append((f, n))
for a in arms:
    run = []; out = []
    for f, mv in still[a]:
        if mv < 0.004: run.append(f)
        else:
            if len(run) >= 12: out.append((run[0], run[-1]))
            run = []
    if len(run) >= 12: out.append((run[0], run[-1]))
    print("FROZEN", NAME[a], out)
for k, v in sorted(cut.items()):
    print("CUT", k, "кадров", len(v), "с", v[0][0], "по", v[-1][0], "макс", max(n for _, n in v), [f for f, _ in v][:30])
print("MOTION_DONE")
