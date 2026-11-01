"""Reopen-time checks of the current Pudge/tank still, not animation approval."""
import bpy
import json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'_game/skits/pudge_tank/revision'
sc = bpy.context.scene
sc.frame_set(0)
dg = bpy.context.evaluated_depsgraph_get()
hero = bpy.data.objects['pudge_root']
tank = bpy.data.objects['detailed_tank']
launcher = bpy.data.objects['held_launcher']

def meshes(root):
    return [o for o in root.children_recursive if o.type=='MESH' and not o.hide_render
            and not any(t in o.name.lower() for t in ('hitbox', 'physics', 'blob'))]

def geometry(ob):
    ev = ob.evaluated_get(dg)
    mesh = ev.to_mesh()
    vertices = [ev.matrix_world@v.co for v in mesh.vertices]
    polygons = [list(p.vertices) for p in mesh.polygons]
    ev.to_mesh_clear()
    return vertices, polygons

def bounds(vertices):
    return [Vector(tuple(f(p[i] for p in vertices) for i in range(3))) for f in (min,max)]

def touches(a, b):
    return all(a[0][i]<=b[1][i] and b[0][i]<=a[1][i] for i in range(3))

hero_geometry = {o:geometry(o) for o in meshes(hero)}
tank_geometry = {o:geometry(o) for o in meshes(tank)}
tank_bvh = {o:BVHTree.FromPolygons(*geo, all_triangles=False) for o,geo in tank_geometry.items()}
actor_hits = []
for ob, geo in hero_geometry.items():
    bvh = BVHTree.FromPolygons(*geo, all_triangles=False)
    for other, other_bvh in tank_bvh.items():
        hits = bvh.overlap(other_bvh)
        if hits: actor_hits.append(dict(actor=ob.name, tank=other.name, pairs=len(hits)))
tank_bounds = bounds([p for geo in tank_geometry.values() for p in geo[0]])
tree_hits = []
tree_candidates = 0
for ob in sc.objects:
    if ob.type!='MESH' or ob.hide_render or 'tree_' not in ob.name.lower(): continue
    ev = ob.evaluated_get(dg)
    if not touches(tank_bounds, bounds([ev.matrix_world@Vector(v) for v in ev.bound_box])): continue
    tree_candidates += 1
    tree_bvh = BVHTree.FromPolygons(*geometry(ob), all_triangles=False)
    for other, other_bvh in tank_bvh.items():
        hits = tree_bvh.overlap(other_bvh)
        if hits: tree_hits.append(dict(tree=ob.name, tank=other.name, pairs=len(hits)))
uv = [world_to_camera_view(sc, sc.camera, p) for ob in [*meshes(hero), *meshes(launcher)]
      for p in geometry(ob)[0]]
arm = max((o for o in hero.children_recursive if o.type=='ARMATURE'), key=lambda o:len(o.pose.bones))
reference = (arm.matrix_world@arm.pose.bones['weapon_rt_1'].matrix) @ Vector(launcher['grip_local_bone'])
actual = launcher.evaluated_get(dg).matrix_world@Vector((0,-.075,.182))
report = dict(actor_tank_surface_overlap=actor_hits, tank_tree_surface_overlap=tree_hits,
    nearby_tree_meshes=tree_candidates, grip_reference_error_m=(actual-reference).length,
    projection=dict(min=[min(p[i] for p in uv) for i in range(2)], max=[max(p[i] for p in uv) for i in range(2)]),
    limits='One saved still. No whole-animation, full-map, containment, self-intersection or physical-grasp certification.')
(OUT/'saved_still_qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
if actor_hits or tree_hits: raise ValueError('Static surface overlap detected')
if (actual-reference).length>.001: raise ValueError('Saved grip reference changed')
if not all(.055<=p.x<=.945 and .09<=p.y<=.89 and p.z>0 for p in uv):
    raise ValueError('Actor or launcher leaves the reviewed framing region')

cam = sc.camera
saved = cam.matrix_world.copy()
cam.data.dof.use_dof = False
sc.render.resolution_x = sc.render.resolution_y = 700
for name, delta in [('native_grip_front',(-1.6,-2.4,.7)), ('native_grip_side',(-2.7,.2,.6))]:
    cam.location = actual+Vector(delta)
    cam.rotation_euler = (actual-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.lens = 54
    sc.render.filepath = str(OUT/f'{name}.png')
    bpy.ops.render.render(write_still=True)

# Inspect the posed elbow and glove together, beyond the grip alignment check.
elbow = (arm.matrix_world @ arm.pose.bones['elbow_R'].matrix).translation
target = (actual+elbow)*.5
cam.location = target+Vector((-3.5,-4.5,1.5))
cam.rotation_euler = (target-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.lens = 44
sc.render.filepath = str(OUT/'native_arm.png')
bpy.ops.render.render(write_still=True)
