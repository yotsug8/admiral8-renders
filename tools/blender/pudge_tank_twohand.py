"""Repose the cinematic candidate with two supported grips and painted armor.

Load epic/candidate.blend. Uses the existing bounded two-segment solver, with
native grip geometry as a starting reference, followed by close-view review.
"""
import bpy
import json
import math
import os
import sys
import numpy as np
from pathlib import Path
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/pudge_tank/twohand'
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools/blender'))
from contact_reaction import _solve_leg, _basis

sc=bpy.context.scene
sc.frame_set(0)
bpy.context.preferences.filepaths.save_version=0
hero=bpy.data.objects['pudge_root']
tank=bpy.data.objects['detailed_tank']
weapon=bpy.data.objects['heavy_launcher']
arm=max((o for o in hero.children_recursive if o.type=='ARMATURE'),key=lambda o:len(o.pose.bones))
world=arm.matrix_world.copy()
for name,angle in [('clavicle_R',45),('clavicle_L',-35)]:
    bone=arm.pose.bones[name]
    pivot=(world@bone.matrix).translation
    turn=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(angle),4,'Z')@Matrix.Translation(-pivot)
    bone.matrix=world.inverted()@turn@world@bone.matrix
    bpy.context.view_layer.update()
base_pose={b.name:b.matrix.copy() for b in arm.pose.bones}
base={n:world@m for n,m in base_pose.items()}
dg=bpy.context.evaluated_depsgraph_get()
old_weapon=weapon.evaluated_get(dg).matrix_world.copy()
native_rear=Vector(weapon['prop_grip'])
rear=Vector((.285,0,-.278))
front=Vector((-.27,0,-.315))
right_local=base['wrist_R'].inverted() @ (old_weapon@native_rear)
left_center=base['weapon_lf_2'].translation
left_local=base['wrist_L'].inverted()@left_center

# Adapt only the lower grip/guard region to the hero's large gauntlets. The
# short original handles left the rigid cuff touching the launcher housing.
for ob in weapon.children_recursive:
    if ob.type!='MESH': continue
    local=old_weapon.inverted()@ob.matrix_world
    inv=local.inverted()
    ob.data=ob.data.copy()
    for v in ob.data.vertices:
        p=local@v.co
        if -.38<p.x<.45 and p.z<-.08:
            # Lengthen the neck of each grip, preserving the lower handle's
            # length. Uniform stretching pushed its butt into the apron.
            amount=min(1.0,(-.08-p.z)/.1)
            amount=amount*amount*(3-2*amount)
            p.z-=.088*amount
            v.co=inv@p
    ob.data.update()

# The native cleaver handle supplies an independent left-palm axis.
before=set(sc.objects)
bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/models/render/models_heroes_pudge_leftweapon.glb'))
reference_objects=set(sc.objects)-before
for ob in reference_objects:
    if ob.type!='ARMATURE': continue
    ob.animation_data_clear()
    ob.matrix_world=world.copy()
    for bone in ob.pose.bones:
        if bone.name in arm.pose.bones:
            c=bone.constraints.new('COPY_TRANSFORMS')
            c.target,c.subtarget=arm,bone.name
bpy.context.view_layer.update()
dg=bpy.context.evaluated_depsgraph_get()
near=[]
for ob in reference_objects:
    if ob.type!='MESH': continue
    ev=ob.evaluated_get(dg)
    me=ev.to_mesh()
    near += [ev.matrix_world@v.co for v in me.vertices if (ev.matrix_world@v.co-left_center).length<.6]
    ev.to_mesh_clear()
if len(near)<6: raise ValueError('Insufficient native left handle geometry')
cloud=np.asarray([tuple(p-left_center) for p in near])
_,singular,axes=np.linalg.svd(cloud-cloud.mean(axis=0),full_matrices=False)
left_axis=Vector(axes[0])
if left_axis.z<0: left_axis=-left_axis
for ob in reference_objects: bpy.data.objects.remove(ob,do_unlink=True)

forward=Vector((.98,-.2,0)).normalized()
z=Quaternion(forward,math.radians(45))@Vector((0,0,1)); x=-forward; y=z.cross(x)
orientation=Matrix((x,y,z)).transposed().to_4x4()
grip_target=Vector((-85.5,76.13,5.6))
desired_weapon=Matrix.Translation(grip_target) @ orientation @ Matrix.Diagonal((2.6,1.65,1.5,1)) @ Matrix.Translation(-rear)
turn=orientation @ old_weapon.to_quaternion().to_matrix().transposed().to_4x4()
right_target=turn @ base['wrist_R']
right_target.translation=grip_target-right_target.to_3x3()@right_local
left_rotation=left_axis.rotation_difference(z).to_matrix().to_4x4()
left_target=left_rotation@base['wrist_L']
left_target.translation=(desired_weapon@front)-left_target.to_3x3()@left_local

# Roll around the vertical handles so each wrist approaches from its shoulder,
# rather than preserving an arbitrary old wrist azimuth and overreaching.
for side,target,local,center in [('R',right_target,right_local,grip_target),
                                 ('L',left_target,left_local,desired_weapon@front)]:
    offset=-(target.to_3x3()@local)
    toward=base[f'bicep_{side}'].translation-center
    offset-=z*offset.dot(z)
    toward-=z*toward.dot(z)
    angle=math.atan2(z.dot(offset.cross(toward)),offset.dot(toward))+math.radians(-15)
    rotated=Matrix.Rotation(angle,4,z)@target
    for row in range(4): target[row]=rotated[row]
    target.translation=center-target.to_3x3()@local

report=dict(native_left_axis=list(left_axis),native_left_samples=len(near),
            native_left_singular=singular.tolist(),arms={})
for side,target in [('R',right_target),('L',left_target)]:
    names=tuple(f'{part}_{side}' for part in ('bicep','elbow','wrist'))
    reach=(target.translation-base[names[0]].translation).length
    lengths=[(base[a].translation-base[b].translation).length for a,b in zip(names,names[1:])]
    report['arms'][side]=dict(target=list(target.translation),reach=reach,lengths=lengths)
    (OUT/'pose_setup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    desired={}
    _solve_leg(base,desired,names,Vector((0,0,0)),None,Vector((0,-1,-1)),target)
    for name in names:
        bone=arm.pose.bones[name]
        pose=world.inverted()@desired[name]
        parent=world.inverted()@desired[bone.parent.name] if bone.parent.name in desired else base_pose[bone.parent.name]
        bone.matrix_basis=_basis(bone,pose,parent)
    bpy.context.view_layer.update()

# Bind only after both independent arm targets have been placed.
for c in list(weapon.constraints): weapon.constraints.remove(c)
weapon.matrix_world=desired_weapon
hand=world@arm.pose.bones['weapon_rt_1'].matrix
c=weapon.constraints.new('CHILD_OF')
c.target,c.subtarget=arm,'weapon_rt_1'
c.inverse_matrix=hand.inverted()
weapon['grip_local_bone']=list(hand.inverted()@grip_target)
weapon['prop_grip']=list(rear)
weapon['support_grip']=list(front)
weapon['support_local_wrist']=list(left_local)
bpy.context.view_layer.update()

armor=[]
for mat in {s.material for o in tank.children_recursive if o.type=='MESH' for s in o.material_slots if s.material}:
    p=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if not p: continue
    nt=mat.node_tree
    for key,value in [('Alpha',1),('Transmission Weight',0),('Coat Weight',0)]:
        for link in list(p.inputs[key].links): nt.links.remove(link)
        p.inputs[key].default_value=value
    if 'mainmetal' in mat.name.lower():
        for link in list(p.inputs['Metallic'].links): nt.links.remove(link)
        p.inputs['Metallic'].default_value=.12
        p.inputs['Specular IOR Level'].default_value=.28
        rough=p.inputs['Roughness']
        if rough.is_linked:
            source=rough.links[0].from_socket
            mapped=nt.nodes.new('ShaderNodeMath'); mapped.operation='MULTIPLY_ADD'
            mapped.inputs[1].default_value=.3; mapped.inputs[2].default_value=.55
            nt.links.new(source,mapped.inputs[0]); nt.links.new(mapped.outputs[0],rough)
        else: rough.default_value=.72
        armor.append(mat.name)
report['painted_armor']=armor

# A fresh opaque paint graph avoids imported clear-coat/render state entirely.
# Painted armor is dielectric; preserve the camouflage and tangent normal map.
repainted={}
for ob in tank.children_recursive:
    if ob.type!='MESH': continue
    for slot in ob.material_slots:
        old=slot.material
        if not old or 'mainmetal' not in old.name.lower(): continue
        if old not in repainted:
            m=bpy.data.materials.new('tank matte paint '+old.name); m.use_nodes=True
            nt=m.node_tree; nt.nodes.clear()
            out=nt.nodes.new('ShaderNodeOutputMaterial')
            diffuse=nt.nodes.new('ShaderNodeBsdfDiffuse')
            diffuse.inputs['Color'].default_value=(.1,.14,.07,1)
            diffuse.inputs['Roughness'].default_value=.65
            nt.links.new(diffuse.outputs[0],out.inputs['Surface'])
            color=next((n.image for n in old.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'basecolor' in n.image.name.lower()),None)
            if color:
                tex=nt.nodes.new('ShaderNodeTexImage'); tex.image=color
                nt.links.new(tex.outputs['Color'],diffuse.inputs['Color'])
            normal=next((n.image for n in old.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'normal' in n.image.name.lower()),None)
            if normal:
                tex=nt.nodes.new('ShaderNodeTexImage'); tex.image=normal
                n=nt.nodes.new('ShaderNodeNormalMap'); n.inputs['Strength'].default_value=.7
                nt.links.new(tex.outputs['Color'],n.inputs['Color']); nt.links.new(n.outputs[0],diffuse.inputs['Normal'])
            repainted[old]=m
        slot.material=repainted[old]

# Restore the established Dota hero look instead of polishing everything into
# soft physical plastic. Original geometry, masks and material boundaries stay.
with bpy.data.libraries.load(str(ROOT/'_game/skits/pudge_tank/revision/native_set.blend'),link=False) as (src,dst):
    material_names=list(src.materials)
    dst.materials=material_names[:]
    dst.worlds=['w']
    dst.objects=['SUN2.5','SUN1.0']
original_mats=dict(zip(material_names,dst.materials))
sc.world=dst.worlds[0]
for ob in list(sc.objects):
    if ob.type=='LIGHT': bpy.data.objects.remove(ob,do_unlink=True)
for ob in dst.objects:
    if ob: sc.collection.objects.link(ob)
fill_data=bpy.data.lights.new('soft production fill','SUN')
fill_data.energy=1.3
fill_data.color=(.85,.93,1)
fill_data.angle=math.radians(25)
fill=bpy.data.objects.new('soft production fill',fill_data)
sc.collection.objects.link(fill)
fill.location=(-87,65,15)
fill.rotation_euler=(Vector((-85,78,5))-fill.location).to_track_quat('-Z','Y').to_euler()
excluded={*tank.children_recursive,*weapon.children_recursive}
for ob in sc.objects:
    if ob.type!='MESH' or ob in excluded: continue
    for slot in ob.material_slots:
        if slot.material and slot.material.name in original_mats: slot.material=original_mats[slot.material.name]
for ob in hero.children_recursive:
    if ob.type!='MESH': continue
    for mod in list(ob.modifiers):
        if mod.name in ('close render seams','smooth close-up silhouette'): ob.modifiers.remove(mod)
    for slot in ob.material_slots:
        if slot.material and slot.material.name in original_mats: slot.material=original_mats[slot.material.name]
for ob in weapon.children_recursive:
    if ob.type!='MESH': continue
    for mod in list(ob.modifiers):
        if mod.name=='rounded weapon surfaces': ob.modifiers.remove(mod)
    for slot in ob.material_slots:
        if not slot.material: continue
        p=next((n for n in slot.material.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if p:
            p.inputs['Coat Weight'].default_value=0
            for link in list(p.inputs['Metallic'].links): slot.material.node_tree.links.remove(link)
            p.inputs['Metallic'].default_value=.3
            for link in list(p.inputs['Roughness'].links): slot.material.node_tree.links.remove(link)
            p.inputs['Roughness'].default_value=.64
sc.view_settings.view_transform='Khronos PBR Neutral'
sc.view_settings.look='None'
sc.view_settings.exposure=-.3
sc.render.engine='BLENDER_EEVEE'
sc.eevee.taa_render_samples=96

# Keep both hands fixed, varying only the right elbow bend plane to clear the
# rigid cuff. This reuses the same fixed-length solver; no mesh is hidden.
def surface(ob):
    ev=ob.evaluated_get(bpy.context.evaluated_depsgraph_get()); me=ev.to_mesh()
    vertices=[ev.matrix_world@v.co for v in me.vertices]
    faces=[list(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(vertices,faces)

weapon_surface=[surface(o) for o in weapon.children_recursive if o.type=='MESH' and not o.hide_render]
hard_parts=[o for o in hero.children_recursive if o.type=='MESH' and
            ('.bracer_model' in o.name or '.back_model' in o.name or o.name.endswith('.head'))]
names=('bicep_R','elbow_R','wrist_R')
pose_now={b.name:b.matrix.copy() for b in arm.pose.bones}
base_now={n:world@m for n,m in pose_now.items()}
chain_basis={n:arm.pose.bones[n].matrix_basis.copy() for n in names}
shoulder=base_now[names[0]].translation
axis=(base_now[names[2]].translation-shoulder).normalized()
trials=[]
for degrees in (0,-15,15,-30,30):
    for n in names: arm.pose.bones[n].matrix_basis=chain_basis[n]
    spin=Matrix.Translation(shoulder)@Matrix.Rotation(math.radians(degrees),4,axis)@Matrix.Translation(-shoulder)
    sample=base_now.copy()
    for n in names: sample[n]=spin@base_now[n]
    desired={}
    _solve_leg(sample,desired,names,Vector(),None,Vector((0,-1,-1)),base_now['wrist_R'])
    for n in names:
        b=arm.pose.bones[n]
        parent=world.inverted()@desired[b.parent.name] if b.parent.name in desired else pose_now[b.parent.name]
        b.matrix_basis=_basis(b,world.inverted()@desired[n],parent)
    bpy.context.view_layer.update()
    intersections={o.name:sum(len(surface(o).overlap(w)) for w in weapon_surface) for o in hard_parts}
    trials.append(dict(elbow_plane_deg=degrees,intersections=intersections))
    if not any(intersections.values()): break
else:
    (OUT/'rejected_cuff_trials.json').write_text(json.dumps(trials,indent=2),encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'rejected_pose.blend'),compress=True)
    raise ValueError('No tested pose clears all rigid equipment and the head')
report['elbow_clearance_trials']=trials

# Reframe real deformed vertices, preserving the low camera angle.
cam=sc.camera
cam.location.z=7.8
cam.rotation_euler=(Vector((-85,78.5,6.35))-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.shift_x=cam.data.shift_y=0
points=[]
for root in (hero,weapon):
    for ob in root.children_recursive:
        if ob.type!='MESH' or ob.hide_render or any(t in ob.name.lower() for t in ('physics','hitbox','blob')): continue
        ev=ob.evaluated_get(dg); me=ev.to_mesh()
        co=np.empty(len(me.vertices)*3,dtype=np.float32); me.vertices.foreach_get('co',co)
        m=np.asarray(ev.matrix_world)
        points.append(co.reshape(-1,3)@m[:3,:3].T+m[:3,3]); ev.to_mesh_clear()
points=np.concatenate(points); points=np.column_stack((points,np.ones(len(points))))
def project():
    bpy.context.view_layer.update()
    m=np.asarray(cam.calc_matrix_camera(dg,x=720,y=1280)@cam.matrix_world.inverted())
    clip=points@m.T
    return clip[:,:2]/clip[:,3:4]*.5+.5
target=Vector((-85,78.5,6.35))
for _ in range(3):
    uv=project(); w,h=np.ptp(uv,axis=0)
    factor=max(w/.82,h/.73,1)
    if factor>1: cam.location=target+(cam.location-target)*factor*1.005
    for axis,attr in enumerate(('shift_x','shift_y')):
        uv=project(); center=(uv.min(axis=0)+uv.max(axis=0))/2
        old=getattr(cam.data,attr); setattr(cam.data,attr,old+.01)
        derivative=(project()[0,axis]-uv[0,axis])/.01
        setattr(cam.data,attr,old+(.49-center[axis])/derivative)
report['framing']={'min':project().min(axis=0).tolist(),'max':project().max(axis=0).tolist()}
cam.data.dof.focus_distance=(target-cam.location).length
sc.render.filepath=str(OUT/'candidate.png')
preferences=bpy.context.preferences.addons['cycles'].preferences
preferences.compute_device_type='CUDA'
preferences.get_devices()
for device in preferences.devices: device.use=device.type=='CUDA'
sc.cycles.device='GPU'
(OUT/'pose_setup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'candidate.blend'),compress=True)
if not os.environ.get('PT_NO_RENDER'):
    bpy.ops.render.render(write_still=True)
