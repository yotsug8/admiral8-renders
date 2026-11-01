"""A separate cinematic look candidate, loaded from the rejected native still.

Physical lighting, restored PBR materials, rounded hero silhouettes, and a
larger licensed launcher. A still candidate only; approval is visual.
"""
import bpy
import json
import math
import numpy as np
from pathlib import Path
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'_game/skits/pudge_tank/epic'
OUT.mkdir(parents=True, exist_ok=True)
sc = bpy.context.scene
bpy.context.preferences.filepaths.save_version = 0
sc.frame_set(0)
hero = bpy.data.objects['pudge_root']
tank = bpy.data.objects['detailed_tank']
old_launcher = bpy.data.objects['held_launcher']
arm = max((o for o in hero.children_recursive if o.type=='ARMATURE'), key=lambda o:len(o.pose.bones))
for bone_name,degrees in [('bicep_R',30),('bicep_L',35)]:
    bone=arm.pose.bones[bone_name]
    pivot=(arm.matrix_world@bone.matrix).translation
    rotate=Matrix.Rotation(math.radians(degrees),4,'Y')
    bone.matrix=arm.matrix_world.inverted() @ Matrix.Translation(pivot) @ rotate @ Matrix.Translation(-pivot) @ arm.matrix_world @ bone.matrix
    bpy.context.view_layer.update()
dg=bpy.context.evaluated_depsgraph_get()
carry_axis=(old_launcher.evaluated_get(dg).matrix_world.to_3x3() @ Vector((0,-1,0))).normalized()
upright=carry_axis.rotation_difference(Vector((0,0,1))).to_matrix().to_4x4()
elbow=arm.pose.bones['elbow_R']
pivot=(arm.matrix_world@elbow.matrix).translation
elbow.matrix=arm.matrix_world.inverted() @ Matrix.Translation(pivot) @ upright @ Matrix.Translation(-pivot) @ arm.matrix_world @ elbow.matrix
bpy.context.view_layer.update()
hand = arm.matrix_world @ arm.pose.bones['weapon_rt_1'].matrix
dg = bpy.context.evaluated_depsgraph_get()
grip = old_launcher.evaluated_get(dg).matrix_world @ Vector((0,-.075,.182))
grip_axis = (old_launcher.evaluated_get(dg).matrix_world.to_3x3() @ Vector((0,-1,0))).normalized()
for ob in [old_launcher,*old_launcher.children_recursive]: ob.hide_render=True

# Restore the tank's original textured PBR inputs, not the flat paint shader.
with bpy.data.libraries.load(str(ROOT/'_game/skits/pudge_tank/revision/look_v2.blend'), link=False) as (src,dst):
    names = list(src.materials)
    dst.materials = names[:]
original_materials = dict(zip(names,dst.materials))
for ob in tank.children_recursive:
    if ob.type!='MESH': continue
    for slot in ob.material_slots:
        key=slot.material.name.removeprefix('production paint ')
        if key in original_materials: slot.material=original_materials[key]

before=set(sc.objects)
bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/external/pudge_tank/heavy_launcher.glb'), merge_vertices=True)
weapon_objects=set(sc.objects)-before
launcher=bpy.data.objects.new('heavy_launcher',None)
sc.collection.objects.link(launcher)
for ob in weapon_objects:
    if not ob.parent: ob.parent=launcher
bpy.context.view_layer.update()
local_grip=Vector((.285,0,-.19))
forward=Vector((-.1,-.995,.05))
forward=(forward-grip_axis*forward.dot(grip_axis)).normalized()
x=-forward
z=grip_axis
y=z.cross(x).normalized()
orientation=Matrix((x,y,z)).transposed().to_4x4()
launcher.matrix_world=Matrix.Translation(grip) @ orientation @ Matrix.Scale(2.9,4) @ Matrix.Translation(-local_grip)
c=launcher.constraints.new('CHILD_OF')
c.target,c.subtarget=arm,'weapon_rt_1'
c.inverse_matrix=hand.inverted()
launcher['grip_local_bone']=list(hand.inverted()@grip)
launcher['prop_grip']=list(local_grip)

hero_meshes=[o for o in hero.children_recursive if o.type=='MESH' and not o.hide_render
             and not any(t in o.name.lower() for t in ('hitbox','physics','blob'))]
for ob in hero_meshes:
    # Weld glTF seams before subdividing, preserving UV loops and bone weights.
    weld=ob.modifiers.new('close render seams','WELD')
    weld.merge_threshold=.0001
    sub=ob.modifiers.new('smooth close-up silhouette','SUBSURF')
    sub.levels=sub.render_levels=2
for ob in weapon_objects:
    if ob.type!='MESH': continue
    for poly in ob.data.polygons: poly.use_smooth=True
    weld=ob.modifiers.new('join imported seams','WELD')
    weld.merge_threshold=.00001
    sub=ob.modifiers.new('rounded weapon surfaces','SUBSURF')
    sub.levels=sub.render_levels=1

# Physical BSDFs respond to the same key, fill and rim lights throughout.
hero_mats={s.material for o in hero_meshes for s in o.material_slots if s.material}
weapon_mats={s.material for o in weapon_objects if o.type=='MESH' for s in o.material_slots if s.material}
scene_mats={s.material for o in sc.objects if o.type=='MESH' and not o.hide_render for s in o.material_slots if s.material}
for mat in scene_mats:
    nt=mat.node_tree if mat.use_nodes else None
    if not nt: continue
    p=next((n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'),None)
    out=next((n for n in nt.nodes if n.type=='OUTPUT_MATERIAL'),None)
    if not p or not out: continue
    nt.links.new(p.outputs['BSDF'],out.inputs['Surface'])
    # The game-lighting helper parks albedo outside the BSDF and sets its base
    # to black. Reconnect the original color image before removing emission.
    if not p.inputs['Base Color'].is_linked:
        tex=next((n for n in nt.nodes if n.type=='TEX_IMAGE' and n.image and
                  n.image.colorspace_settings.name=='sRGB' and
                  not any(s in n.image.name.lower() for s in ('normal','mask','rough'))),None)
        if tex: nt.links.new(tex.outputs['Color'],p.inputs['Base Color'])
    if p.inputs['Emission Color'].is_linked:
        for link in list(p.inputs['Emission Color'].links): nt.links.remove(link)
    p.inputs['Emission Color'].default_value=(0,0,0,1)
    p.inputs['Emission Strength'].default_value=0
    if p.inputs['Base Color'].is_linked:
        color=p.inputs['Base Color'].links[0].from_socket
        hs=nt.nodes.new('ShaderNodeHueSaturation')
        hs.inputs['Saturation'].default_value=1.2 if mat in hero_mats else 1.15
        hs.inputs['Value'].default_value=1.05
        nt.links.new(color,hs.inputs['Color'])
        nt.links.new(hs.outputs[0],p.inputs['Base Color'])
    if mat in hero_mats:
        for link in list(p.inputs['Metallic'].links): nt.links.remove(link)
        p.inputs['Metallic'].default_value=0
        p.inputs['Roughness'].default_value=.58
        p.inputs['Specular IOR Level'].default_value=.3
        p.inputs['Subsurface Weight'].default_value=.035
    elif mat in weapon_mats:
        p.inputs['Metallic'].default_value=.55
        p.inputs['Roughness'].default_value=.34

# Preserve the native set, but use a deliberately lit foreground.
for ob in list(sc.objects):
    if ob.type=='LIGHT': bpy.data.objects.remove(ob,do_unlink=True)
origin=Vector((-83,78.5,3.251190185546875))
world=bpy.data.worlds.new('cool ambient sky')
world.use_nodes=True
bg=next(n for n in world.node_tree.nodes if n.type=='BACKGROUND')
bg.inputs['Color'].default_value=(.24,.42,.7,1)
bg.inputs['Strength'].default_value=.35
sc.world=world

def light(name,kind,local,energy,color,target,size):
    data=bpy.data.lights.new(name,kind)
    data.energy,data.color=energy,color
    if kind=='AREA': data.shape='DISK'; data.size=size
    if kind=='SUN': data.angle=math.radians(size)
    ob=bpy.data.objects.new(name,data); sc.collection.objects.link(ob)
    ob.location=origin+Vector(local)
    ob.rotation_euler=(origin+Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
    return ob
light('golden sunlight','SUN',(-8,-5,16),3.0,(1,.75,.42),(0,3,0),12)
light('soft face key','AREA',(-7,-7,9),2400,(1,.84,.68),(-2,0,2.6),6)
light('blue sky fill','AREA',(5,-4,6),1700,(.38,.65,1),(-2,0,2.5),7)
light('warm separation','AREA',(-1,7,10),4500,(1,.5,.18),(-2,0,3),5)

cam=sc.camera
cam.data.dof.use_dof=True
cam.data.dof.aperture_fstop=3.5
cam.data.lens=34
target=origin+Vector((-2,0,3.1))
cam.location=origin+Vector((-6,-15,3.1))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
sc.render.resolution_x,sc.render.resolution_y=720,1280
sc.render.resolution_percentage=100
sc.render.engine='CYCLES'
sc.cycles.samples=96
sc.cycles.use_denoising=True
preferences=bpy.context.preferences.addons['cycles'].preferences
preferences.compute_device_type='CUDA'
preferences.get_devices()
for device in preferences.devices: device.use=device.type=='CUDA'
sc.cycles.device='GPU'
sc.view_settings.view_transform='AgX'
try: sc.view_settings.look='AgX - Medium High Contrast'
except TypeError: pass
sc.view_settings.exposure=.6
sc.render.image_settings.file_format='PNG'
sc.render.filepath=str(OUT/'candidate.png')
bpy.context.view_layer.update()
dg=bpy.context.evaluated_depsgraph_get()
points=[]
for ob in [*hero_meshes,*[o for o in weapon_objects if o.type=='MESH']]:
    ev=ob.evaluated_get(dg)
    me=ev.to_mesh()
    co=np.empty(len(me.vertices)*3,dtype=np.float32)
    me.vertices.foreach_get('co',co)
    co=co.reshape(-1,3)
    world=np.asarray(ev.matrix_world)
    points.append(co@world[:3,:3].T+world[:3,3])
    ev.to_mesh_clear()
points=np.concatenate(points)
points=np.column_stack((points,np.ones(len(points))))

def projected():
    bpy.context.view_layer.update()
    matrix=np.asarray(cam.calc_matrix_camera(dg,x=720,y=1280) @ cam.matrix_world.inverted())
    clip=points@matrix.T
    return clip[:,:2]/clip[:,3:4]*.5+.5

# Fit the visible meshes, not collider objects or oversized local bounding boxes.
for _ in range(3):
    uv=projected()
    width,height=np.ptp(uv,axis=0)
    factor=max(width/.82,height/.73,1)
    if factor>1: cam.location=target+(cam.location-target)*factor*1.005
    for axis,attr in enumerate(('shift_x','shift_y')):
        uv=projected()
        center=(uv.min(axis=0)+uv.max(axis=0))/2
        old=getattr(cam.data,attr)
        setattr(cam.data,attr,old+.01)
        derivative=(projected()[0,axis]-uv[0,axis])/.01
        setattr(cam.data,attr,old+(.49-center[axis])/derivative)
uv=projected()
cam.data.dof.focus_distance=(target-cam.location).length
report={'stage':'Unapproved cinematic still candidate','weapon_scale':2.9,
        'grip_world':list(grip),'weapon_axis':list(forward),'hero_meshes':[o.name for o in hero_meshes]}
report['framing']={'min':uv.min(axis=0).tolist(),'max':uv.max(axis=0).tolist(),'camera':list(cam.location)}
report['weapon_bounds']={o.name:[list(o.matrix_world@Vector(v)) for v in o.bound_box] for o in weapon_objects if o.type=='MESH'}
(OUT/'candidate_setup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'candidate.blend'),compress=True)
bpy.ops.render.render(write_still=True)
