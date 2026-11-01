"""Reopen checks and contact views for the cinematic still candidate only."""
import bpy
import json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/pudge_tank/epic'
sc=bpy.context.scene
sc.frame_set(0)
hero=bpy.data.objects['pudge_root']
tank=bpy.data.objects['detailed_tank']
launcher=bpy.data.objects['heavy_launcher']
dg=bpy.context.evaluated_depsgraph_get()

def meshes(root):
    return [o for o in root.children_recursive if o.type=='MESH' and not o.hide_render
            and not any(t in o.name.lower() for t in ('blob','physics','hitbox'))]

def surface(ob):
    ev=ob.evaluated_get(dg)
    me=ev.to_mesh()
    points=[ev.matrix_world@v.co for v in me.vertices]
    polygons=[list(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(points,polygons)

hero_surfaces={o:surface(o) for o in meshes(hero)}
tank_surfaces={o:surface(o) for o in meshes(tank)}
weapon_surfaces={o:surface(o) for o in meshes(launcher)}
hits=[]
contact=[]
for ob,bvh in hero_surfaces.items():
    for other,other_bvh in tank_surfaces.items():
        overlap=bvh.overlap(other_bvh)
        if overlap: hits.append(dict(hero=ob.name,tank=other.name,pairs=len(overlap)))
    for other,other_bvh in weapon_surfaces.items():
        overlap=bvh.overlap(other_bvh)
        if overlap: contact.append(dict(hero=ob.name,weapon=other.name,pairs=len(overlap)))
arm=max((o for o in hero.children_recursive if o.type=='ARMATURE'),key=lambda o:len(o.pose.bones))
reference=(arm.matrix_world@arm.pose.bones['weapon_rt_1'].matrix)@Vector(launcher['grip_local_bone'])
actual=launcher.evaluated_get(dg).matrix_world@Vector(launcher['prop_grip'])
report=dict(actor_tank_surface_overlap=hits,weapon_actor_surface_overlap=contact,
            grip_reference_error_m=(actual-reference).length,
            limits='One still; weapon-hand intersections need visual interpretation. No full-map or motion approval.')
(OUT/'saved_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
if hits: raise ValueError('Actor intersects tank')
if (actual-reference).length>.001: raise ValueError('Saved attachment changed')
cam=sc.camera
cam.data.dof.use_dof=False
cam.data.shift_x=cam.data.shift_y=0
sc.render.resolution_x=sc.render.resolution_y=800
sc.cycles.samples=64
for name,delta in [('grip_outer',(-3,-2,1)),('grip_inner',(2,-2,.5))]:
    cam.location=actual+Vector(delta)
    cam.rotation_euler=(actual-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.lens=50
    sc.render.filepath=str(OUT/f'{name}.png')
    bpy.ops.render.render(write_still=True)
