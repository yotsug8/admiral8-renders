"""Stage the replacement props on the project's prepared native forest set.

Load the preserved lively_fix scene with -b. No source scene is overwritten.
Only still probes are rendered; no animation or final-video claim.
"""
import bpy
import ast
import json
import math
from pathlib import Path
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'_game/skits/pudge_tank/revision'
sc = bpy.context.scene
bpy.context.preferences.filepaths.save_version = 0
sc.frame_set(180)
for who in ('pudge', 'sniper', 'kunkka', 'hoodwink'):
    root = bpy.data.objects.get(who+'_root')
    if root:
        for ob in list(root.children_recursive)[::-1]: bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.objects.remove(root, do_unlink=True)
for ob in list(sc.objects):
    if ob.type == 'CAMERA':
        bpy.data.objects.remove(ob, do_unlink=True)
        continue
    # Snapshot the prepared environment's visibility and light directions.
    ob.animation_data_clear()
sc.animation_data_clear()
sc.frame_start, sc.frame_end = 0, 89
sc.frame_set(0)
with bpy.data.libraries.load(str(OUT/'look_v2.blend'), link=False) as (src, dst):
    dst.objects = src.objects
loaded = {o.name:o for o in dst.objects if o}
roots = [loaded[n] for n in ('pudge_root', 'detailed_tank', 'held_launcher')]
members = set(roots)
for ob in roots: members.update(ob.children_recursive)
for ob in members:
    sc.collection.objects.link(ob)
origin = Vector((-83, 78.5, 3.251190185546875))
hero, tank, launcher = roots
# A tube carry still needs the actual pistol grip and trigger assembly: these
# distinguish an RPG from a spear in the wide shot. Restore the imported meshes.
before_import = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/external/pudge_tank/launcher.glb'))
restored = set(bpy.data.objects)-before_import
for name in ('launcher-body', 'trigger-mesh'):
    original = next(o for o in restored if o.type=='MESH' and o.name.startswith(name))
    ob = loaded[name]
    materials = list(ob.data.materials)
    ob.data = original.data.copy()
    ob.data.materials.clear()
    for material in materials: ob.data.materials.append(material)
    local = launcher.matrix_world.inverted() @ ob.matrix_world
    for polygon in ob.data.polygons:
        co = local @ polygon.center
        polygon.material_index = 1 if co.z<.13 or .10<co.y<.43 else 0
        polygon.use_smooth = True
    ob.hide_render = False
for ob in restored: bpy.data.objects.remove(ob, do_unlink=True)
hero.location += origin
tank.location += origin
tank.location.x -= 3.5
# The launcher follows its native hand constraint; translating its base too
# would apply the set displacement twice.
bpy.context.view_layer.update()
# Keep the prop's native grip fixed while lifting the entire forearm. Rotating
# only the prop or wrist makes a readable silhouette at the cost of a bad hold.
arm = max((o for o in hero.children_recursive if o.type=='ARMATURE'), key=lambda o:len(o.pose.bones))
hand = arm.matrix_world @ arm.pose.bones['weapon_rt_1'].matrix
actual_grip = launcher.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world @ Vector((0,-.075,.182))
launcher['grip_local_bone'] = list(hand.inverted() @ actual_grip)
arm.animation_data_clear()
elbow = arm.pose.bones['elbow_R']
pivot = (arm.matrix_world @ elbow.matrix).translation
turn = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(50),4,'Y') @ Matrix.Translation(-pivot)
elbow.matrix = arm.matrix_world.inverted() @ turn @ arm.matrix_world @ elbow.matrix
bpy.context.view_layer.update()
# Match the project's camera-relative game lighting for the carried prop and
# armor paint. Pure PBR reflections hid the dark launcher and washed the tank.
source = ROOT/'tools/blender/render_scene.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('dota_shade','blob_shadow')]
nodes += [n for n in tree.body if isinstance(n, ast.Assign) and
          any(isinstance(t, ast.Name) and t.id=='DOTA' for t in n.targets)]
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), globals())
DOTA.update(gain=1.15, amb=.95, key=.3, spec=.25, rim=.04)

def paint_prop(old, carried=False):
    """Explicit paint shader, preserving the actual base-color image and UVs."""
    name = old.name.lower()
    image = next((n.image for n in old.node_tree.nodes if n.type=='TEX_IMAGE' and n.image
                  and 'basecolor' in n.image.name.lower()), None) if old.use_nodes else None
    color = (.22, .3, .08) if 'olive warhead' in name else (.08, .032, .015) if 'dark wood' in name else (.12, .14, .11)
    material = bpy.data.materials.new('production paint '+old.name)
    material.use_nodes = True
    nt = material.node_tree
    b = nt.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (0, 0, 0, 1)
    b.inputs['Roughness'].default_value = .65
    b.inputs['Specular IOR Level'].default_value = 0
    if image and not carried:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = image
        albedo = tex.outputs['Color']
        if 'mainmetal' in name:
            tint = nt.nodes.new('ShaderNodeMixRGB')
            tint.blend_type = 'MULTIPLY'
            tint.inputs[0].default_value = 1
            tint.inputs[2].default_value = (.95, .95, .9, 1)
            nt.links.new(albedo, tint.inputs[1])
            albedo = tint.outputs[0]
    else:
        rgb = nt.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (*color, 1)
        albedo = rgb.outputs[0]
    geometry = nt.nodes.new('ShaderNodeNewGeometry')
    normal = nt.nodes.new('ShaderNodeVectorTransform')
    normal.vector_type, normal.convert_from, normal.convert_to = 'NORMAL', 'WORLD', 'CAMERA'
    nt.links.new(geometry.outputs['Normal'], normal.inputs['Vector'])
    dot = nt.nodes.new('ShaderNodeVectorMath')
    dot.operation = 'DOT_PRODUCT'
    dot.inputs[1].default_value = Vector((-.4, .5, .7)).normalized()
    normalized = nt.nodes.new('ShaderNodeVectorMath')
    normalized.operation = 'NORMALIZE'
    nt.links.new(normal.outputs[0], normalized.inputs[0])
    nt.links.new(normalized.outputs[0], dot.inputs[0])
    shade = nt.nodes.new('ShaderNodeMath')
    shade.operation = 'MULTIPLY_ADD'
    shade.inputs[1].default_value = .35
    shade.inputs[2].default_value = .65
    shade.use_clamp = True
    nt.links.new(dot.outputs['Value'], shade.inputs[0])
    mix = nt.nodes.new('ShaderNodeMixRGB')
    mix.blend_type = 'MULTIPLY'
    mix.inputs[0].default_value = 1
    nt.links.new(albedo, mix.inputs[1])
    nt.links.new(shade.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], b.inputs['Emission Color'])
    b.inputs['Emission Strength'].default_value = 1.6 if carried else 3
    return material

painted = {}
for root, carried in ((tank, False), (launcher, True)):
    for ob in root.children_recursive:
        if ob.type != 'MESH': continue
        for slot in ob.material_slots:
            if not slot.material: continue
            key = (slot.material, carried)
            if key not in painted: painted[key] = paint_prop(*key)
            slot.material = painted[key]
ACTORS = {'pudge':dict(root=hero, info=dict(radius=104))}
S = 1/39.37
HERO_OBJS = set()
DOTA['blob'] = .45
blob_shadow('pudge')
cam = bpy.data.objects.new('production_look_camera', bpy.data.cameras.new('production_look_camera'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.sensor_fit = 'VERTICAL'
cam.data.clip_start, cam.data.clip_end = .1, 350
cam.data.lens = 32
cam.data.dof.use_dof = True
cam.data.dof.aperture_fstop = 1.8
target = origin+Vector((-1.8, 1, 2.5))
cam.location = origin+Vector((-3, -12, 8.5))
cam.rotation_euler = (target-cam.location).to_track_quat('-Z', 'Y').to_euler()
sc.render.engine = 'BLENDER_EEVEE'
sc.eevee.taa_render_samples = 64
sc.render.resolution_x, sc.render.resolution_y = 540, 960
sc.render.resolution_percentage = 100
sc.render.use_sequencer = False
sc.render.use_simplify = False
sc.render.image_settings.file_format = 'PNG'
dg = bpy.context.evaluated_depsgraph_get()
actor_meshes = [o for o in [*hero.children_recursive, *launcher.children_recursive]
               if o.type=='MESH' and not o.hide_render and
               not any(t in o.name.lower() for t in ('hitbox', 'physics', 'blob'))]
points = [o.evaluated_get(dg).matrix_world@Vector(v) for o in actor_meshes
          for v in o.evaluated_get(dg).bound_box]
for _ in range(50):
    bpy.context.view_layer.update()
    uv = [world_to_camera_view(sc, cam, p) for p in points]
    if all(.06<=p.x<=.94 and .1<=p.y<=.88 and p.z>0 for p in uv): break
    cam.location = target+(cam.location-target)*1.025
else: raise ValueError('Cannot fit complete hero and launcher')
cam.data.dof.focus_distance = (target-cam.location).length
sc.render.filepath = str(OUT/'native_set.png')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'native_set.blend'), compress=True)
bpy.ops.render.render(write_still=True)
(OUT/'native_set_qa.json').write_text(json.dumps(dict(
    camera=list(cam.location), target=list(target),
    actor_bounds_uv=dict(min=[min(p[i] for p in uv) for i in range(2)], max=[max(p[i] for p in uv) for i in range(2)]),
    limits='Still probe. Surface collisions with the native map and camera occlusion need review.'), indent=2), encoding='utf-8')
