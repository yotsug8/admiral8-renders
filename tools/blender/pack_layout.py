# Расстановка Пуджей упаковкой по кадрам с учётом высоты: blender -b scene006.blend -P pack_layout.py -- <подвижные>
# Клетка 0.25 м хранит интервал высот, который в этом кадре занимает Пудж (с крюком и тесаком), с запасом 1 клетка и 0.15 м.
# Касание Пуджей — пересечение интервалов в одной клетке в один кадр; касание карты — Пудж ниже верха карты в клетке.
# Перебор с откатом сдвигов (вдоль/поперёк реки) ближе к исходным; голова — в безопасной зоне кадра. PACK имя dal dlat.
import bpy, sys, math
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
MOV = sys.argv[sys.argv.index("--") + 1].split(",")
sc = bpy.context.scene; cam = sc.camera; WZ = 1.6; CELL = 0.25; STEP = 2; MZ = 0.15
DIR = Vector((0.52, 0.85, 0)).normalized(); PERP = Vector((DIR.y, -DIR.x, 0))
arms = {o.parent.name.replace("Mover_", ""): o for o in sc.objects if o.type == "ARMATURE" and not o.hide_render and o.parent}
MESH = {n: [c for c in a.children if c.type == "MESH" and not c.hide_render] for n, a in arms.items()}
BW = np.array([[u, v] for u in np.linspace(0, 1, 5) for v in np.linspace(0, 1, 5) if u + v <= 1])
ctr = sum((a.parent.matrix_world.translation for a in arms.values()), Vector()) / len(arms)
R = 44.0; X0, Y0 = ctr.x - R, ctr.y - R; N = int(2 * R / CELL)
INF = np.float32(1e9)

def raster(tris, zmin):
    lo = np.full((N, N), INF, np.float32); hi = np.full((N, N), -INF, np.float32)
    t = tris[tris[:, :, 2].max(axis=1) > zmin]
    if not len(t): return lo, hi
    p = t[:, 0, None, :] + BW[None, :, 0, None] * (t[:, 1, None, :] - t[:, 0, None, :]) + BW[None, :, 1, None] * (t[:, 2, None, :] - t[:, 0, None, :])
    p = p.reshape(-1, 3); p = p[p[:, 2] > zmin]
    i = np.floor((p[:, 1] - Y0) / CELL).astype(int); j = np.floor((p[:, 0] - X0) / CELL).astype(int)
    k = (i >= 0) & (i < N) & (j >= 0) & (j < N)
    np.minimum.at(lo, (i[k], j[k]), p[k, 2]); np.maximum.at(hi, (i[k], j[k]), p[k, 2])
    return lo, hi

def grow(lo, hi, r=1):
    l2, h2 = lo.copy(), hi.copy()
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            l2 = np.minimum(l2, np.roll(np.roll(lo, di, 0), dj, 1)); h2 = np.maximum(h2, np.roll(np.roll(hi, di, 0), dj, 1))
    return l2 - MZ, h2 + MZ

def tris_of(objs, dg):
    acc = []
    for m in objs:
        ev = m.evaluated_get(dg); me = ev.to_mesh(); me.transform(ev.matrix_world); me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        lt = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get("vertices", lt)
        acc.append(co[lt.reshape(-1, 3)]); ev.to_mesh_clear()
    return np.concatenate(acc) if acc else np.zeros((0, 3, 3), np.float32)

frames = list(range(1, sc.frame_end + 1, STEP))
LO = {n: [] for n in arms}; HI = {n: [] for n in arms}; heads = {n: [] for n in arms}
for f in frames:
    sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get()
    for n, a in arms.items():
        lo, hi = grow(*raster(tris_of(MESH[n], dg), WZ - 0.3))
        LO[n].append(lo); HI[n].append(hi)
        heads[n].append(a.matrix_world @ a.pose.bones["head"].head)
box = {}
for n in arms:
    lo = np.array(LO[n]); hi = np.array(HI[n]); occ_ = (hi > -INF / 2).any(axis=0); ii, jj = np.nonzero(occ_)
    i0, i1, j0, j1 = ii.min(), ii.max() + 1, jj.min(), jj.max() + 1
    box[n] = (i0, j0, lo[:, i0:i1, j0:j1], hi[:, i0:i1, j0:j1])
    del LO[n], HI[n]
print("PACK кадров", len(frames), flush=True)
dg = bpy.context.evaluated_depsgraph_get(); mobj = []
for o in sc.objects:
    if o.type != "MESH" or o.hide_render or o.name == "WATER" or (o.parent and o.parent.type == "ARMATURE"): continue
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    if max(v.z for v in bb) < WZ + 0.1 or min(v.z for v in bb) > 12: continue
    if max(v.x for v in bb) < X0 or min(v.x for v in bb) > X0 + 2 * R or max(v.y for v in bb) < Y0 or min(v.y for v in bb) > Y0 + 2 * R: continue
    mobj.append(o)
_, MAPHI = raster(tris_of(mobj, dg), WZ + 0.1)
_, MAPHI = grow(np.full_like(MAPHI, INF), MAPHI, 1)
occ_lo = np.full((len(frames), N, N), INF, np.float32); occ_hi = np.full((len(frames), N, N), -INF, np.float32)
def place(n, di, dj):
    i0, j0, lo, hi = box[n]; a, b = i0 + di, j0 + dj; sl = (slice(None), slice(a, a + lo.shape[1]), slice(b, b + lo.shape[2]))
    prev = (occ_lo[sl].copy(), occ_hi[sl].copy())
    np.minimum(occ_lo[sl], lo, out=occ_lo[sl]); np.maximum(occ_hi[sl], hi, out=occ_hi[sl])
    return sl, prev
for n in arms:
    if n not in MOV: place(n, 0, 0)

def fits(n, di, dj):
    i0, j0, lo, hi = box[n]; a, b = i0 + di, j0 + dj
    if a < 0 or b < 0 or a + lo.shape[1] > N or b + lo.shape[2] > N: return "край"
    lmin = lo.min(axis=0)
    if (lmin < MAPHI[a:a + lo.shape[1], b:b + lo.shape[2]]).any(): return "карта"
    ol, oh = occ_lo[:, a:a + lo.shape[1], b:b + lo.shape[2]], occ_hi[:, a:a + lo.shape[1], b:b + lo.shape[2]]
    if ((lo <= oh) & (ol <= hi)).any(): return "Пудж"
    return ""
def in_frame(n, d):
    for h in heads[n][::4]:
        if h.z < WZ: continue
        v = world_to_camera_view(sc, cam, h + d)
        if not (0.07 < v.x < 0.93 and 0.2 < v.y < 0.73): return False
    return True
cands = sorted({(da * 0.5, dl * 0.5) for da in range(-16, 17) for dl in range(-14, 15)}, key=lambda c: math.hypot(*c))
def cell(d): return int(round(d.y / CELL)), int(round(d.x / CELL))
from collections import Counter
for n in MOV:
    why = Counter()
    for da, dl in cands:
        d = DIR * da + PERP * dl; r = fits(n, *cell(d)) or ("" if in_frame(n, d) else "кадр")
        why[r or "OK"] += 1
    print("PACK причины", n, dict(why), flush=True)
import random, time
random.seed(7); t_end = time.time() + 420
base_lo, base_hi = occ_lo.copy(), occ_hi.copy()
best = None; runs = 0
while time.time() < t_end:
    runs += 1
    occ_lo[:] = base_lo; occ_hi[:] = base_hi
    order = MOV[:] if runs == 1 else random.sample(MOV, len(MOV))
    sol = {}
    for n in order:
        cs = cands if runs == 1 else sorted(cands, key=lambda c: math.hypot(*c) + random.uniform(0, 2.5))
        for da, dl in cs:
            d = DIR * da + PERP * dl; di, dj = cell(d)
            if fits(n, di, dj) or not in_frame(n, d): continue
            place(n, di, dj); sol[n] = (da, dl); break
        else:
            break
    if len(sol) == len(MOV):
        cost = sum(math.hypot(*v) for v in sol.values())
        if best is None or cost < best[0]:
            best = (cost, dict(sol)); print(f"PACK найдено (попытка {runs}), суммарный сдвиг {cost:.1f}", flush=True)
        if runs > 40 and best: break
print("PACK попыток", runs)
if best:
    for n in MOV: print(f"PACK {n} {best[1][n][0]:+.1f} {best[1][n][1]:+.1f}")
    print("PACK_OK")
else:
    print("PACK_FAIL")
