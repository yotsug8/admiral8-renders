# Ширина свободной воды вдоль русла: лучи от точек на воде поперёк реки до берега/камней/деревьев (всё выше воды).
import bpy, bmesh, math
from mathutils import Vector
from mathutils.bvhtree import BVHTree
sc = bpy.context.scene; WZ = 0.4
dg = bpy.context.evaluated_depsgraph_get()
bm = bmesh.new()
for o in sc.objects:
    if o.type != "MESH" or o.hide_render or o.name == "WATER" or (o.parent and o.parent.type == "ARMATURE"): continue
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    if max(v.z for v in bb) < WZ + 0.1: continue
    ev = o.evaluated_get(dg); me = ev.to_mesh(); me.transform(ev.matrix_world); bm.from_mesh(me); ev.to_mesh_clear()
bmesh.ops.delete(bm, geom=[f for f in bm.faces if max(v.co.z for v in f.verts) < WZ + 0.1], context="FACES")
T = BVHTree.FromBMesh(bm)
def free(p, d, h=1.2, lim=30):
    hit = T.ray_cast(Vector((p.x, p.y, WZ + h)), d, lim)
    return hit[3] if hit[0] else lim
def wet(p):     # над точкой нет ничего выше воды до 0.6 м
    return T.ray_cast(Vector((p.x, p.y, WZ + 0.6)), Vector((0, 0, -1)), 0.5)[0] is None and T.ray_cast(Vector((p.x, p.y, WZ + 0.05)), Vector((0, 0, 1)), 0.6)[0] is None
best = []
for ang in range(20, 80, 5):
    DIR = Vector((math.cos(math.radians(ang)), math.sin(math.radians(ang)), 0)); PERP = Vector((DIR.y, -DIR.x, 0))
    for x in range(-90, 50, 3):
        for y in range(-90, 70, 3):
            c = Vector((x, y, 0))
            if not wet(c): continue
            # минимальная ширина на отрезке 24 м вдоль направления
            ws = []
            for al in range(-4, 21, 3):
                p = c + DIR * al
                if not wet(p): ws = []; break
                ws.append(free(p, PERP) + free(p, -PERP))
            if ws: best.append((min(ws), ang, x, y))
best.sort(reverse=True)
seen = []
for w, ang, x, y in best:
    if any(abs(x - a) < 15 and abs(y - b) < 15 for a, b in seen): continue
    seen.append((x, y)); print(f"WIDTH {w:5.1f} м  угол {ang}  центр ({x},{y})")
    if len(seen) >= 10: break
# для текущего брода
C = Vector((-20.0, -1.0, 0)); DIR = Vector((0.52, 0.85, 0)).normalized(); PERP = Vector((DIR.y, -DIR.x, 0))
print("WIDTH сейчас:", [round(free(C + DIR * al, PERP) + free(C + DIR * al, -PERP), 1) for al in range(-4, 21, 3)])
