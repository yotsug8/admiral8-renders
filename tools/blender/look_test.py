# Проба «киношного» вида в Blender: герой со всеми частями, свет (тёплый основной + контровой), лес фоном с размытием,
# широкий объектив вплотную. Один кадр.
# blender -b --factory-startup -P tools/blender/look_test.py -- <герой> <анимация> <кадр анимации> <выход.png>
import bpy, sys, os, math, json
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
HERO, ANIM, FRAME, OUT = args[0], args[1], float(args[2]), args[3]
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INFO = json.load(open(os.path.join(REPO, "_game", "data", "troupe.json"), encoding="utf-8"))[HERO]
M2U = 39.37

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene


def imp(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path, bone_heuristic="BLENDER")
    return [o for o in bpy.data.objects if o not in before]


RND = os.path.join(REPO, "_game", "models", "render")
body = imp(os.path.join(RND, os.path.basename(INFO["glb"])))   # с текстурами (для анимаций выгрузка без них)
arm = next(o for o in body if o.type == "ARMATURE")
for o in body:
    if o.type == "MESH" and o.name.startswith("Icosphere"):
        bpy.data.objects.remove(o)
# части (одежда, оружие): их сетки привязать к скелету тела — кости у частей те же
for p in INFO["parts"]:
    g = os.path.join(RND, p.replace("/", "_").replace(".vmdl", ".glb"))
    if not os.path.exists(g):
        continue
    objs = imp(g)
    arms = [o for o in objs if o.type == "ARMATURE"]
    for o in [o for o in objs if o.type == "MESH"]:
        if o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o); continue
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.object = arm
        o.parent = arm
    for o in arms:
        bpy.data.objects.remove(o)

act = bpy.data.actions.get(ANIM)
ad = arm.animation_data or arm.animation_data_create(); ad.action = act
try: ad.action_slot = act.slots[0]
except Exception: pass
sc.frame_set(int(FRAME * 24))
if INFO.get("jaw"):                                   # рот приоткрыт — как на слове
    pb = arm.pose.bones[INFO["jaw"]]; pb.rotation_mode = "XYZ"; pb.rotation_euler.x += math.radians(14)

head = arm.matrix_world @ arm.pose.bones[INFO["head_bone"]].head
# ---- земля, лес фоном
bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0))
g = bpy.context.object; mat = bpy.data.materials.new("ground"); mat.use_nodes = True
nt = mat.node_tree; bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 3.0
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.10, 0.16, 0.05, 1); ramp.color_ramp.elements[1].color = (0.28, 0.36, 0.12, 1)
nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.9; g.data.materials.append(mat)
world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
wn = world.node_tree; env = wn.nodes.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load(os.path.join(os.path.dirname(bpy.app.binary_path), f"{bpy.app.version[0]}.{bpy.app.version[1]}",
                                              "datafiles", "studiolights", "world", "forest.exr"))
bg = next(n for n in wn.nodes if n.type == "BACKGROUND"); bg.inputs["Strength"].default_value = 0.9
wn.links.new(env.outputs["Color"], bg.inputs["Color"])
# ---- свет: тёплый основной спереди-слева, холодный контровой сзади-справа, мягкий заполняющий
def light(kind, loc, rot, energy, color, size=1.0):
    d = bpy.data.lights.new(kind, kind); d.energy = energy; d.color = color
    if kind == "AREA": d.size = size
    o = bpy.data.objects.new(kind, d); sc.collection.objects.link(o); o.location = loc; o.rotation_euler = [math.radians(a) for a in rot]
light("SUN", (0, 0, 10), (50, 0, -35), 3.2, (1.0, 0.86, 0.68))
light("AREA", (head.x + 2.5, head.y + 3.0, head.z + 1.5), (60, 0, 140), 1800, (0.6, 0.75, 1.0), 2.0)
light("AREA", (head.x - 3.0, head.y - 3.0, head.z), (80, 0, -45), 500, (1.0, 0.95, 0.9), 4.0)
# ---- камера: 32 мм вплотную, чуть снизу, резкость на глазах
cam_d = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_d); sc.collection.objects.link(cam); sc.camera = cam
cam_d.lens = 32; cam_d.dof.use_dof = True; cam_d.dof.aperture_fstop = 1.8
eye = head + Vector((0, -0.35, 0.15))
cam.location = eye + Vector((1.2, -3.2, -0.12))
cam.rotation_euler = (eye + Vector((0, 0, -0.25)) - cam.location).to_track_quat("-Z", "Y").to_euler()
cam_d.dof.focus_distance = (eye - cam.location).length
# ---- рендер
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        sc.render.engine = eng; break
    except TypeError:
        pass
sc.render.resolution_x, sc.render.resolution_y = 1080, 1920
try:
    sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("ПРОБА", OUT)
