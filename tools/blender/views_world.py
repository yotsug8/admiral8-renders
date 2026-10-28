# Проверка движения с неподвижных камер: сцена собирается render_scene.py (без его рендера), потом выбранные кадры
# снимаются камерами вокруг героя, стоящими на месте весь ролик (A8_VIEWS в render_scene ведёт камеру за взглядом героя —
# поворот на месте с ней не виден). Углы — от взгляда героя на первом из кадров; кадры подряд → ролик движения.
# blender -b --factory-startup -P tools/blender/views_world.py -- <scene.json> <папка> <кадры 0,2,4…> [half]
#   A8_WVIEWS=pudge:0,90;sniper@200-363:0      герой и углы, ° (несколько героев — через «;», файлы w<кадр>_<герой>_<угол>.png);
#                                              @a-b — снимать героя только в этих кадрах (где он движется)
#   A8_FAST=1   быстрая проверка движения: без карты (ровная земля, загрузка ~30 с вместо 5 мин), 4 прохода света, четверть кадра —
#               ~0,3 с на кадр вместо 2,2; картинка грубая, для показа и цвета — без него
#   A8_JERK=1   без кадров: рывки кистей, головы и оружия (скачок ускорения на кадре — стыки анимаций)
#   A8_CLIP=1   без кадров: на каждом кадре — проходит ли оружие сквозь тело (пересечение сеток, кроме кистей)
import bpy, sys, os, math, json, shutil, re
from mathutils import Matrix, Vector

FAST = bool(os.environ.get("A8_FAST"))
if FAST:
    i = sys.argv.index("--") + 1; scene = os.path.abspath(sys.argv[i])
    D = json.load(open(scene, encoding="utf-8")); D["map"] = None
    fd = os.path.join(os.path.dirname(scene), "_fast"); os.makedirs(fd, exist_ok=True)   # render_scene берёт голоса и деревья
    shutil.copy(os.path.join(os.path.dirname(scene), "voices.json"), fd)                 # из папки сцены — своя папка
    json.dump([], open(os.path.join(fd, "trees.json"), "w"))                             # без карты — без деревьев
    fast = os.path.join(fd, "scene.json"); json.dump(D, open(fast, "w", encoding="utf-8")); sys.argv[i] = fast
    os.environ["A8_SAMPLES"] = "4"

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_scene.py")
code = open(SRC, encoding="utf-8").read().replace("bpy.ops.render.render(", "_noop(")
os.environ.pop("A8_VIEWS", None)
g = {"__file__": SRC, "__name__": "__main__", "_noop": lambda **k: None}
exec(compile(code, SRC, "exec"), g)

R = math.radians
sc, ACTORS, HERO_OBJS, PICK, OUT = g["sc"], g["ACTORS"], g["HERO_OBJS"], g["PICK"], g["OUT"]
if FAST:
    sc.render.resolution_percentage = int(os.environ.get("A8_PCT", 25))
WHEAD = bool(os.environ.get("A8_WHEAD"))                  # крупно голова: камера ведёт голову (мимика), углы — от взгляда на 1-м кадре
def HERO_OBJS_OF(who):
    """Всё, из чего собран герой: его скелет, части одежды и оружия (у них общий корень)."""
    root = ACTORS[who]["root"]; out = set()
    for o in HERO_OBJS:
        p = o
        while p and p != root:
            p = p.parent
        if p:
            out.add(o)
    return out


def clip_check(who, fr):
    """Оружие сквозь тело: на каждом кадре — пересечение сеток оружия (части с weapon/hook/… в имени) с телом героя,
    кроме кистей (там оружие держится). Печатает кадры с пересечением и что во что."""
    from mathutils.bvhtree import BVHTree
    objs = [o for o in HERO_OBJS_OF(who) if o.type == "MESH"]
    WPN = re.compile(r"weapon|hook|sword|blade|axe|staff|gun|bow|cleaver|anchor|hammer|mace|spear|club|dagger|katana", re.I)
    weap = [o for o in objs if WPN.search(o.name)]
    body = [o for o in objs if not WPN.search(o.name) and ".vmdl_c" in o.name and "physics" not in o.name and o.visible_get()]
    arm = ACTORS[who]["arm"]
    hands = [b for b in arm.pose.bones if re.search(r"wrist|hand|finger|thumb", b.name, re.I)]
    hit = {}
    def tree(o, dg, skip=None):
        e = o.evaluated_get(dg); m = e.to_mesh(); M = o.matrix_world
        vs = [M @ v.co for v in m.vertices]
        ps = [list(p.vertices) for p in m.polygons]
        if skip:
            ps = [p for p in ps if not skip(sum((vs[i] for i in p), Vector()) / len(p))]
        e.to_mesh_clear()
        return BVHTree.FromPolygons(vs, ps) if ps else None
    for f in fr:
        sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get()
        hp = [arm.matrix_world @ b.head for b in hands]
        near = lambda c: any((c - h).length < 0.35 for h in hp)
        bt = [(b, tree(b, dg, near)) for b in body]
        for w in weap:
            wt = tree(w, dg)
            for b, t in bt:
                if t and wt:
                    pairs = wt.overlap(t); n = len(pairs)
                    if n and os.environ.get("A8_CLIP") == "2" and f == fr[0]:   # где: ближайшая кость к месту пересечения
                        e = b.evaluated_get(dg); m = e.to_mesh(); M = b.matrix_world
                        near_b = {}
                        for _, pi in pairs[:400]:
                            c = M @ m.polygons[pi].center if pi < len(m.polygons) else None
                            if c:
                                bn = min(arm.pose.bones, key=lambda x: ((arm.matrix_world @ x.head) - c).length).name
                                near_b[bn] = near_b.get(bn, 0) + 1
                        e.to_mesh_clear(); print(f"    {w.name.split(chr(92))[-1][:30]} × {b.name.split('.')[-1]}: у костей {near_b}")
                    if n:
                        hit.setdefault((w.name.split(".vmdl")[0].split("\\")[-1], b.name.split(".")[-1]), []).append((f, n))
    if not hit:
        print(f"  ПЕРЕСЕЧЕНИЙ НЕТ {who}: оружие не проходит сквозь тело ({len(fr)} кадров)")
    for (w, b), fs in hit.items():
        base = min(n for _, n in fs) if len(fs) == len(fr) else 0   # на всех кадрах — касание у кисти, как в игровой стойке:
        fs = [(f, n) for f, n in fs if n > base + max(8, base * 0.3)]   # считать только сверх него
        if not fs:
            print(f"  касание {who}: {w} — {b} на всех кадрах ({base} граней, у кисти — как в игре)"); continue
        rng = []
        for f, n in fs:
            if rng and f - rng[-1][1] <= 2:
                rng[-1][1] = f; rng[-1][2] = max(rng[-1][2], n)
            else:
                rng.append([f, f, n])
        print(f"  ⚠ ПЕРЕСЕЧЕНИЕ {who}: {w} в {b} — кадры " + ", ".join(f"{a}–{b_} (до {n} граней)" for a, b_, n in rng))


def jerk_check(who, fr):
    """Рывки: кисти, голова и оружие относительно корня героя — скачок ускорения (вторая разность) на кадре.
    Печатает кадры, где ускорение в 4 раза выше обычного для этой точки и больше 2 см/кадр² (или 2°)."""
    arm = ACTORS[who]["arm"]; root = ACTORS[who]["root"]
    pts = [b.name for b in arm.pose.bones if re.fullmatch(r"(wrist|hand)_[lr]|head", b.name, re.I)]
    WPN = re.compile(r"weapon|hook|sword|blade|axe|staff|gun|bow|cleaver|anchor|hammer|mace|spear|club|dagger|katana", re.I)
    weap = [o for o in HERO_OBJS_OF(who) if o.type == "MESH" and WPN.search(o.name)]
    track = {n: [] for n in pts + [o.name for o in weap]}
    for f in fr:
        sc.frame_set(f); inv = root.matrix_world.inverted()
        for n in pts:
            track[n].append(inv @ arm.matrix_world @ arm.pose.bones[n].matrix)
        for o in weap:                                    # оружие — по его сетке (кость части): середина и поворот
            dg = bpy.context.evaluated_depsgraph_get(); e = o.evaluated_get(dg); m = e.to_mesh()
            vs = [m.vertices[i].co.copy() for i in range(0, len(m.vertices), max(1, len(m.vertices) // 60))]; e.to_mesh_clear()
            M = inv @ o.matrix_world; track[o.name].append([M @ v for v in vs])
    for n, T in track.items():
        if len(T) < 5:
            continue
        if isinstance(T[0], list):                        # точки сетки: средний сдвиг
            acc = [max((T[i + 1][j] - 2 * T[i][j] + T[i - 1][j]).length for j in range(len(T[i]))) for i in range(1, len(T) - 1)]
        else:
            acc = [(T[i + 1].translation - 2 * T[i].translation + T[i - 1].translation).length +
                   0.01 * math.degrees((T[i].to_quaternion().rotation_difference(T[i + 1].to_quaternion()).angle -
                                        T[i - 1].to_quaternion().rotation_difference(T[i].to_quaternion()).angle).__abs__())
                   for i in range(1, len(T) - 1)]
        med = sorted(acc)[len(acc) // 2]
        bad = [(fr[i + 1], a) for i, a in enumerate(acc) if a > max(4 * med, 0.02)]
        nm = n.split("\\")[-1].split(".vmdl")[0]
        if bad:
            print(f"  ⚠ РЫВОК {who} {nm}: кадры " + ", ".join(f"{f} ({a * 100:.0f})" for f, a in bad[:12]) + f"; обычно {med * 100:.1f}")
        else:
            print(f"  рывков нет {who} {nm}")


vd = bpy.data.cameras.new("wview"); vc = bpy.data.objects.new("wview", vd); sc.collection.objects.link(vc)
vd.angle = R(40); vd.clip_start = 0.05; sc.camera = vc
multi = ";" in os.environ["A8_WVIEWS"]
CLIP = bool(os.environ.get("A8_CLIP"))                    # только проверка пересечений, без кадров
JERK = bool(os.environ.get("A8_JERK"))                    # только проверка рывков, без кадров
for spec in os.environ["A8_WVIEWS"].split(";"):
    who, angs = spec.split(":")
    fr = PICK
    if "@" in who:
        who, rng = who.split("@"); f0, f1 = map(int, rng.split("-")); fr = [f for f in PICK if f0 <= f <= f1]
    arm = ACTORS[who]["arm"]
    if CLIP:
        clip_check(who, fr); continue
    if JERK:
        jerk_check(who, fr); continue
    mine = HERO_OBJS_OF(who)
    for o in HERO_OBJS:                                   # другие герои не заслоняют (камера спереди — между героями);
        o.hide_render = o not in mine and not os.environ.get("A8_WALL")   # A8_WALL=1 — видны все (касания)
    sc.frame_set(fr[0])
    bones = [arm.matrix_world @ b.head for b in arm.pose.bones]
    lo = min(p.z for p in bones); mid = sum(bones, Vector()) / len(bones)
    hb = arm.pose.bones.get(ACTORS[who]["info"].get("head_bone", "head"))   # рост — до макушки, не по всем костям
    hi = (arm.matrix_world @ hb.head).z + 0.25 * ((arm.matrix_world @ hb.head).z - lo) if hb else max(p.z for p in bones)
    fwd = arm.matrix_world.to_3x3() @ Vector((0, -1, 0)); fwd.z = 0; fwd.normalize()   # взгляд на первом кадре
    path = []                                             # весь путь героя в этих кадрах — в кадре целиком
    for f in fr[::5] + [fr[-1]]:
        sc.frame_set(f); path.append(arm.matrix_world.translation.copy())
        if os.environ.get("A8_WALL"):                     # касания: в кадре и собеседники
            path += [A["arm"].matrix_world.translation.copy() for n_, A in ACTORS.items() if n_ != who]
    c = Vector([(min(p[i] for p in path) + max(p[i] for p in path)) / 2 for i in range(3)])   # середина пути, не среднее
    span = max((p - q).length for p in path for q in path)
    mid = Vector((c.x, c.y, mid.z))
    hfov = 2 * math.atan(math.tan(R(20)) * 9 / 16)       # кадр вертикальный: по ширине угол меньше
    d = max(((hi - lo) * 1.6 + 0.6) / 2 / math.tan(R(20)) * 1.4, (span + 1.3 * (hi - lo) + 1) / 2 / math.tan(hfov / 2))   # + ширина героя с оружием (Пудж ~3 м) и поля
    aimp = Vector((mid.x, mid.y, (lo + hi) / 2))
    print(f"  вид {who}: путь {span:.1f} м, рост {hi - lo:.1f} м, камера в {d:.1f} м")
    mine = mine | {arm} | set(arm.children_recursive)
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
        for f in fr:
            sc.frame_set(f)
            if WHEAD:
                hb = arm.pose.bones.get(ACTORS[who]["info"].get("head_bone", "head")) or arm.pose.bones[0]
                hw = ACTORS[who]["info"].get("head_w", 0.9)
                H = arm.matrix_world @ hb.head + Vector((0, 0, 0.25 * hw))
                vc.location = H + (Matrix.Rotation(R(float(a)), 3, "Z") @ fwd) * (hw * 0.75 / math.tan(hfov / 2)) + Vector((0, 0, 0.1 * hw))
                vc.rotation_euler = (H - vc.location).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = os.path.join(OUT, f"w{f:05d}_{who + '_' if multi else ''}{int(float(a)):03d}.png")
            bpy.ops.render.render(write_still=True)
print("ГОТОВО", OUT)
