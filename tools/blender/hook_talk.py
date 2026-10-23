# Анимации разговора для сценки «Крюк» (исполняется внутри anim_to_dmx.py: есть arm, sc, ACTS, FPS).
# Герой — переменная окружения A8_WHO (pudge | sniper). Поза — игровая анимация, поверх неё повороты суставов в мире:
#   рот Пуджа — челюсть jaw0_0 открывается по громкости его реплики (_game/hook/voices.json), кивки на ударениях;
#   Снайпер (рта под усами нет) опускает голову к винтовке и покачивает ею, пока говорит.
# Тайминги совпадают со сценой tools/dota_engine/scene_hook.py: анимация начинается на склейке, голос — через OFF с.
import json, math, os
import bpy
from mathutils import Matrix, Vector

R = math.radians
MW = arm.matrix_world
X = Vector((1, 0, 0)); Z = Vector((0, 0, 1))
VOICES = json.load(open(os.environ.get("A8_VOICES", r"%USERPROFILE%\Desktop\ClaudeCode\admiral8-renders\_game\hook\voices.json"), encoding="utf-8"))
WHO = os.environ.get("A8_WHO", "pudge")


def sm(a, b, t):
    t = min(1.0, max(0.0, (t - a) / (b - a))); return t * t * (3 - 2 * t)


def world(name):
    return MW @ arm.pose.bones[name].matrix


def turn(name, axis, ang):
    M = world(name); p = M.translation.copy()
    arm.pose.bones[name].matrix = MW.inverted() @ (Matrix.Translation(p) @ Matrix.Rotation(ang, 4, axis) @ Matrix.Translation(-p) @ M)
    bpy.context.view_layer.update()


def base_pose(action, t):
    ad = arm.animation_data or arm.animation_data_create(); ad.action = ACTS[action]
    try: ad.action_slot = ACTS[action].slots[0]
    except Exception: pass
    n = ACTS[action].frame_range[1]; f = (t * 24.0) % n
    sc.frame_set(int(f), subframe=f - int(f))


def voice(name, off):
    """Громкость реплики в момент t сцены анимации (0…1), сглаженная: рот открывается быстро, закрывается мягче."""
    env = VOICES[name]["env"]; out = []; v = 0.0
    def at(t):
        i = int((t - off) * 30)
        return env[i] if 0 <= i < len(env) else 0.0
    return at


def smooth_series(fn, n, up=0.6, down=0.25):
    vals, v = [], 0.0
    for k in range(n + 1):
        x = fn(k / FPS); v += (x - v) * (up if x > v else down); vals.append(v)
    return vals


def bake(name, dur, pose):
    n = int(dur * FPS); keyed = []
    for k in range(n + 1):
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        pose(k / FPS, k)
        keyed.append({pb.name: pb.matrix.copy() for pb in arm.pose.bones})
    act = bpy.data.actions.new(name); ad = arm.animation_data; ad.action = act
    try: ad.action_slot = act.slots.new(id_type="OBJECT", name=arm.name)
    except Exception: pass
    for k, P in enumerate(keyed):
        sc.frame_set(k)
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        for pb in sorted(arm.pose.bones, key=lambda b: len(b.parent_recursive)):
            pb.matrix = P[pb.name]; bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            for path in ("location", "rotation_quaternion", "scale"):
                pb.keyframe_insert(path, frame=k)
    act.frame_range = (0, n)
    return act


def talker(base, line, off, dur, jaw_max=22, nod=5, grin=0.0):
    """Пудж говорит: челюсть по громкости, кивок на нарастании громкости; grin — рот чуть приоткрыт после реплики."""
    loud = smooth_series(voice(line, off), int(dur * FPS))
    end = off + VOICES[line]["dur"]

    def pose(t, k):
        base_pose(base, t)
        v = loud[k]; dv = loud[k] - loud[max(0, k - 3)]
        turn("head", X, R(nod * max(0.0, dv) * 3 + 2 * v))
        turn("jaw0_0", X, R(jaw_max * v + grin * sm(end, end + 0.4, t)))
    return pose


if WHO == "pudge":
    CUSTOM = {"a8_p1": bake("a8_p1", 4.9, talker("portrait", "p1", 0.1, 4.9)),
              "a8_p2": bake("a8_p2", 2.4, talker("pudge_idle", "p2", 0.5, 2.4, jaw_max=26, nod=7, grin=7))}
else:
    def look_gun(t, k, loud=smooth_series(voice("s2", 0.3), int(3.2 * FPS))):
        base_pose("sniper_idle", t)
        d = sm(0.15, 0.7, t)                                   # опустил голову к винтовке
        v = loud[k]
        turn("neck_1", X, R(14 * d))
        turn("head", X, R(26 * d + 6 * v * math.sin(t * 9)))   # пока говорит — покачивает головой
        turn("head", Z, R(5 * v * math.sin(t * 6)))
    CUSTOM = {"a8_s2": bake("a8_s2", 3.2, look_gun)}
LOOPING = {k: False for k in CUSTOM}
