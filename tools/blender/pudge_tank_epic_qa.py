"""Reopen checks and contact views for the cinematic still candidate only."""
import bpy
import json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(bpy.data.filepath).parent
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
arm=max((o for o in hero.children_recursive if o.type=='ARMATURE'),key=lambda o:len(o.pose.bones))
hand_bones={b.name for side in ('R','L') for b in
            (arm.pose.bones['wrist_'+side],*arm.pose.bones['wrist_'+side].children_recursive)}
hits=[]
contact=[]
for ob,bvh in hero_surfaces.items():
    for other,other_bvh in tank_surfaces.items():
        overlap=bvh.overlap(other_bvh)
        if overlap: hits.append(dict(hero=ob.name,tank=other.name,pairs=len(overlap)))
    for other,other_bvh in weapon_surfaces.items():
        overlap=bvh.overlap(other_bvh)
        if overlap:
            ev=ob.evaluated_get(dg); me=ev.to_mesh()
            hand_ids={g.index for g in ob.vertex_groups if g.name in hand_bones}
            non_hand=[]
            for i in {a for a,_ in overlap}:
                weights=[sum(g.weight for g in me.vertices[v].groups if g.group in hand_ids)
                         for v in me.polygons[i].vertices]
                if min(weights)<.8: non_hand.append({'polygon':i,'minimum_hand_weight':min(weights)})
            ev.to_mesh_clear()
            contact.append(dict(hero=ob.name,weapon=other.name,pairs=len(overlap),non_hand_polygons=non_hand))
reference=(arm.matrix_world@arm.pose.bones['weapon_rt_1'].matrix)@Vector(launcher['grip_local_bone'])
actual=launcher.evaluated_get(dg).matrix_world@Vector(launcher['prop_grip'])
report=dict(actor_tank_surface_overlap=hits,weapon_actor_surface_overlap=contact,
            grip_reference_error_m=(actual-reference).length,
            limits='One still; weapon-hand intersections need visual interpretation. No full-map or motion approval.')
if 'support_grip' in launcher:
    support=launcher.evaluated_get(dg).matrix_world@Vector(launcher['support_grip'])
    support_hand=(arm.matrix_world@arm.pose.bones['wrist_L'].matrix)@Vector(launcher['support_local_wrist'])
    report['support_reference_error_m']=(support-support_hand).length
(OUT/'saved_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
if report.get('support_reference_error_m',0)>.001: raise ValueError('Support hand left the foregrip')
if hits: raise ValueError('Actor intersects tank')
if (actual-reference).length>.001: raise ValueError('Saved attachment changed')
cam=sc.camera
cam.data.dof.use_dof=False
cam.data.shift_x=cam.data.shift_y=0
sc.render.resolution_x=sc.render.resolution_y=800
sc.cycles.samples=64
preferences=bpy.context.preferences.addons['cycles'].preferences
preferences.compute_device_type='CUDA'
preferences.get_devices()
for device in preferences.devices: device.use=device.type=='CUDA'
sc.cycles.device='GPU'
views=[('grip_outer',actual,(-3,-2,1)),('grip_inner',actual,(2,-2,.5))]
if 'support_grip' in launcher:
    views += [('support_grip',support,(1,-2,.5)),('both_grips',(actual+support)*.5,(1,-4,1))]
for name,center,delta in views:
    cam.location=center+Vector(delta)
    cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.lens=50
    sc.render.filepath=str(OUT/f'{name}.png')
    bpy.ops.render.render(write_still=True)
