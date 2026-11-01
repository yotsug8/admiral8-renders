"""Audit grip constraints, framing, boarding intersections and terrain heights."""
import json
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view

OUT = Path(bpy.data.filepath).parent
scene = bpy.context.scene
hero, tank, weapon = [bpy.data.objects[n] for n in ('pudge_root','detailed_tank','heavy_launcher')]
arm=max((o for o in hero.children_recursive if o.type=='ARMATURE'),key=lambda o:len(o.pose.bones))
head=next(o for o in hero.children_recursive if o.type=='MESH' and o.data.shape_keys)
grips, framing, contacts, weapon_contacts = [], [], [], []

def surface(obj, dg):
    ev=obj.evaluated_get(dg); mesh=ev.to_mesh()
    points=[ev.matrix_world@v.co for v in mesh.vertices]
    faces=[list(p.vertices) for p in mesh.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(points,faces), points

scene.frame_set(0)
terrain=[]
for obj in scene.objects:
    if obj.type!='MESH' or obj.hide_render:
        continue
    if any(s.material and s.material.get('vmat',{}).get('ShaderName')=='multiblend.vfx' for s in obj.material_slots):
        bvh,_=surface(obj,bpy.context.evaluated_depsgraph_get())
        terrain.append((obj.name,bvh))
ground=[]
for y in range(74,93):
    row={'y':y,'samples':[]}
    for x in (-85.4,-83.3,-81.2,-79.):
        hits=[(hit[0].z,name) for name,bvh in terrain
              if (hit:=bvh.ray_cast(Vector((x,y,30)),Vector((0,0,-1)),60))[0] is not None]
        row['samples'].append({'x':x,'hit':max(hits) if hits else None})
    ground.append(row)

for frame in range(300):
    scene.frame_set(frame)
    dg=bpy.context.evaluated_depsgraph_get()
    actual=weapon.evaluated_get(dg).matrix_world@Vector(weapon['prop_grip'])
    right=(arm.matrix_world@arm.pose.bones['weapon_rt_1'].matrix)@Vector(weapon['grip_local_bone'])
    left=(arm.matrix_world@arm.pose.bones['wrist_L'].matrix)@Vector(weapon['support_local_wrist'])
    front=weapon.evaluated_get(dg).matrix_world@Vector(weapon['support_grip'])
    grips.append({'frame':frame,'right_error':(right-actual).length,'left_error':(left-front).length})
    if (frame%6==0 or 108<=frame<=140) and (frame<180 or frame>=270):
        ev=head.evaluated_get(dg)
        uv=[world_to_camera_view(scene,scene.camera,ev.matrix_world@Vector(c)) for c in ev.bound_box]
        framing.append({'frame':frame,'head_min':[min(p[i] for p in uv) for i in (0,1)],
                        'head_max':[max(p[i] for p in uv) for i in (0,1)]})
    if frame in (0,16,24,39,50,54,57,60,63,66,69,72,75,78,81,84,90,108,135,150,179,199,270,285,299):
        actor_surfaces=[(o,*surface(o,dg)) for o in hero.children_recursive
                        if o.type=='MESH' and not o.hide_render and not any(s in o.name.lower() for s in ('blob','hitbox','physics'))]
        tank_surfaces=[(o,*surface(o,dg)) for o in tank.children_recursive if o.type=='MESH' and not o.hide_render]
        weapon_surfaces=[(o,*surface(o,dg)) for o in weapon.children_recursive if o.type=='MESH' and not o.hide_render]
        for a,abvh,_ in actor_surfaces:
            if any(token in a.name.lower() for token in ('back_model','bracer_model','.head')):
                for b,bbvh,_ in weapon_surfaces:
                    pairs=abvh.overlap(bbvh)
                    if pairs:
                        weapon_contacts.append({'frame':frame,'hero':a.name,'weapon':b.name,'pairs':len(pairs)})
            for b,bbvh,_ in tank_surfaces:
                pairs=abvh.overlap(bbvh)
                if pairs:
                    contacts.append({'frame':frame,'hero':a.name,'tank':b.name,'pairs':len(pairs)})
report={'max_right_grip_error':max(r['right_error'] for r in grips),
        'max_left_grip_error':max(r['left_error'] for r in grips),
        'terrain_objects':[n for n,_ in terrain],'ground':ground,
        'framing':framing,'boarding_contacts':contacts,'weapon_rigid_contacts':weapon_contacts,
        'lights':[{'name':o.name,'energy':o.data.energy,'shadow':o.data.use_shadow} for o in scene.objects if o.type=='LIGHT'],
        'limitations':'Boarding surface overlap is sampled; it is not a continuous collision certificate.'}
(OUT/'motion_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('ground','framing','boarding_contacts','terrain_objects')}),flush=True)
print('CONTACTS',len(contacts),flush=True)
