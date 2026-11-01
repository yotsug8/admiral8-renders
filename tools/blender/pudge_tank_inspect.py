"""Inspect the saved tank and grip geometry without changing source assets."""
import json
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

OUT = Path(__file__).resolve().parents[2] / '_game/skits/pudge_tank/twohand'
scene = bpy.context.scene
dg = bpy.context.evaluated_depsgraph_get()
hero = bpy.data.objects['pudge_root']
tank = bpy.data.objects['detailed_tank']
weapon = bpy.data.objects['heavy_launcher']
def surface(obj):
    ev = obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    points = [ev.matrix_world @ v.co for v in mesh.vertices]
    polygons = [list(p.vertices) for p in mesh.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(points, polygons), points, polygons
guns = [surface(o) for o in weapon.children_recursive if o.type == 'MESH' and not o.hide_render]
overlaps = []
for obj in hero.children_recursive:
    if obj.type != 'MESH' or obj.hide_render or not any(s in obj.name for s in ('.back_model', '.bracer_model', '.head')):
        continue
    bvh, points, polygons = surface(obj)
    for other, _, _ in guns:
        pairs = bvh.overlap(other)
        if pairs:
            samples = {i for i, _ in pairs}
            centers = [sum((points[j] for j in polygons[i]), Vector()) / len(polygons[i]) for i in samples]
            overlaps.append({'object': obj.name, 'pairs': len(pairs), 'centers': [list(c) for c in centers]})
report = {'overlaps': overlaps, 'tank_materials': [], 'tank_meshes': []}
for obj in tank.children_recursive:
    if obj.type != 'MESH':
        continue
    report['tank_meshes'].append({'name': obj.name, 'faces': len(obj.data.polygons), 'hidden': obj.hide_render})
    for slot in obj.material_slots:
        mat = slot.material
        if mat:
            report['tank_materials'].append({'name': mat.name, 'nodes': [(n.type, n.name) for n in mat.node_tree.nodes]})
(OUT / 'geometry_inspection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'overlaps': overlaps, 'tank_meshes': report['tank_meshes']}, indent=2), flush=True)
for root in (hero, weapon):
    for obj in (root, *root.children_recursive):
        obj.hide_render = True
points = [obj.matrix_world @ Vector(corner) for obj in tank.children_recursive if obj.type == 'MESH' for corner in obj.bound_box]
low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
center = (low + high) / 2
camera = scene.camera
camera.location = center + Vector((9, -13, 8))
camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
camera.data.lens = 40
camera.data.shift_x = camera.data.shift_y = 0
camera.data.dof.use_dof = False
scene.render.resolution_x, scene.render.resolution_y = 960, 720
scene.eevee.taa_render_samples = 48
scene.render.filepath = str(OUT / 'tank_inspection.png')
bpy.ops.render.render(write_still=True)
