# Свои анимации героя (скрипт Blender, например tools/blender/kunkka_race.py) → DMX для движка доты.
# blender -b --factory-startup -P tools/dota_engine/anim_to_dmx.py -- <папка исходников модели в content> <модель .glb> <префикс> <скрипт>
#   префикс — как у файлов разобранной модели (kunkka → kunkka_idle.dmx); скрипт задаёт CUSTOM {имя: действие} и LOOPING
# Образец — настоящая стойка <префикс>_idle.dmx: по ней находится переход «Blender → движок» (масштаб и оси одним преобразованием M
# и поправка C_b для каждой кости), потом каждая поза своей анимации переводится и записывается каналами, как у Valve.
import bpy, sys, os, math
from mathutils import Matrix, Vector, Quaternion
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import datamodel
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT, GLB, PREFIX, SCRIPT = sys.argv[sys.argv.index("--") + 1:][:4]
SRC_IDLE = os.path.join(OUT, f"{PREFIX}_idle.dmx")
FPS = 30; SPEED = FPS / 24.0
def log(*a): print("[dmx]", *a, flush=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=GLB, bone_heuristic="BLENDER")
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
ACTS = {a.name: a for a in bpy.data.actions}

# --- свои анимации: скрипт ставит их на скелет (arm, sc, ACTS, FPS) и задаёт CUSTOM
exec(compile(open(SCRIPT, encoding="utf-8").read(), SCRIPT, "exec"))

# --- позы Blender (пространство скелета) по кадрам
def bl_mats(action, frames, src_fps):
    ad = arm.animation_data or arm.animation_data_create(); ad.action = action
    try: ad.action_slot = action.slots[0]
    except Exception: pass
    out = []
    for k in frames:
        t = k * src_fps / FPS
        sc.frame_set(int(t), subframe=t - int(t))
        out.append({pb.name: pb.matrix.copy() for pb in arm.pose.bones})
    return out

# --- DMX: образец
dm = datamodel.load(SRC_IDLE)
clip = dm.root["animationList"]["animations"][0]
chans = clip["channels"]
joints = {}
def walk(j, parent):
    if j.type == "DmeJoint":
        joints[j.name] = (j, parent); parent = j.name
    for c in j.get("children", []) or []: walk(c, parent)
for c in dm.root["skeleton"]["children"]: walk(c, None)
order = list(joints.keys())
by_tr = {}
for ch in chans:
    el = ch["toElement"]; by_tr.setdefault(el.name, {})[ch["toAttribute"]] = ch
def q2m(q): return Quaternion((q[3], q[0], q[1], q[2])).to_matrix().to_4x4()
def local(name, k):
    c = by_tr.get(name, {})
    if "position" in c:
        v = c["position"]["log"]["layers"][0]["values"]; p = v[min(k, len(v) - 1)]
    else:
        p = joints[name][0]["transform"]["position"]
    if "orientation" in c:
        v = c["orientation"]["log"]["layers"][0]["values"]; q = v[min(k, len(v) - 1)]
    else:
        q = joints[name][0]["transform"]["orientation"]
    return Matrix.Translation(Vector((p[0], p[1], p[2]))) @ q2m(q)
NI = len(chans[0]["log"]["layers"][0]["times"])
def dmx_world(k, loc=local):
    W = {}
    for n in order:
        par = joints[n][1]
        W[n] = (W[par] if par else Matrix.Identity(4)) @ loc(n, k)
    return W
idle_dmx = [dmx_world(k) for k in range(NI)]
idle_bl = bl_mats(ACTS["idle"], range(NI), 24)
common = [n for n in order if n in idle_bl[0]]
log("кадров стойки", NI, "костей DMX", len(order), "общих", len(common))

# --- M: подобие (масштаб+поворот+сдвиг) по положениям общих костей во всех кадрах (Умеяма)
import numpy as np
P = np.array([list(idle_bl[k][n].translation) for k in range(NI) for n in common])
Q = np.array([list(idle_dmx[k][n].translation) for k in range(NI) for n in common])
mp, mq = P.mean(0), Q.mean(0); X, Y = P - mp, Q - mq
U, S, Vt = np.linalg.svd(Y.T @ X / len(P)); D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(U @ Vt))
Rm = U @ D @ Vt; s = (S * np.diag(D)).sum() / (X ** 2).sum() * len(P); t = mq - s * Rm @ mp
M = Matrix(((*(s * Rm[0]), t[0]), (*(s * Rm[1]), t[1]), (*(s * Rm[2]), t[2]), (0, 0, 0, 1)))
err = np.abs((s * (Rm @ X.T)).T - Y).max()
log("масштаб", round(s, 3), "ошибка положений, дюймов", round(float(err), 3))
# --- поправки C_b и проверка: стойка, переведённая обратно, должна совпасть с образцом
Cb = {n: (M @ idle_bl[0][n]).inverted() @ idle_dmx[0][n] for n in common}
worst = 0.0
for k in range(0, NI, 5):
    for n in common:
        A_ = M @ idle_bl[k][n] @ Cb[n]; B_ = idle_dmx[k][n]
        worst = max(worst, (A_.translation - B_.translation).length, (A_.to_quaternion().rotation_difference(B_.to_quaternion()).angle) * 10)
log("проверка переноса стойки (дюймы / 0.1 рад):", round(worst, 3))

def write(name, action, nframes, loop_src_idle=True):
    frames = list(range(nframes + 1))
    bl = bl_mats(action, frames, FPS)
    dm2 = datamodel.load(SRC_IDLE)
    clip2 = dm2.root["animationList"]["animations"][0]; clip2.name = name
    tf = clip2["timeFrame"]; tf["duration"] = datamodel.Time(nframes / FPS)   # тип «время», иначе движок считает длительность нулевой
    W = {}; L = {}
    for k in frames:
        Wk = {}
        for n in order:
            par = joints[n][1]
            if n in common: Wk[n] = M @ bl[k][n] @ Cb[n]
            else: Wk[n] = (Wk[par] if par else Matrix.Identity(4)) @ local(n, k % (NI - 1))
        for n in order:
            par = joints[n][1]
            L.setdefault(n, []).append((Wk[par].inverted() if par else Matrix.Identity(4)) @ Wk[n])
    times = [k / FPS for k in frames]
    for ch in clip2["channels"]:
        n = ch["toElement"].name; attr = ch["toAttribute"]
        if n not in L: continue
        lay = ch["log"]["layers"][0]
        if attr == "position":
            lay["values"] = datamodel.make_array([datamodel.Vector3(list(m.translation)) for m in L[n]], datamodel.Vector3)
        else:
            vals = []; prev = None
            for m in L[n]:
                q = m.to_quaternion().normalized()
                if prev is not None and prev.dot(q) < 0: q.negate()
                prev = q; vals.append(datamodel.Quaternion([q.x, q.y, q.z, q.w]))
            lay["values"] = datamodel.make_array(vals, datamodel.Quaternion)
        lay["times"] = datamodel.make_array([datamodel.Time(x) for x in times], datamodel.Time) if hasattr(datamodel, "Time") else times
        if "curvetypes" in lay and lay["curvetypes"]: lay["curvetypes"] = datamodel.make_array([lay["curvetypes"][0]] * len(times), int)
    path = os.path.join(OUT, f"{PREFIX}_{name}.dmx")
    dm2.write(path, "binary", 9)
    log("записано", path, "кадров", len(frames))
for name, act in CUSTOM.items():
    write(name, act, int(act.frame_range[1]))
log("готово")
