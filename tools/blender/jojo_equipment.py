"""Revision 3: canonical Dota equipment, neck topology and safer framing."""
import ast
import bpy
import json
import math
import bmesh
from pathlib import Path
from mathutils import Matrix, Vector, Quaternion

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'out/dota-jojo/v3';OUT.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;s.frame_set(1)


def actor(name):
    root=bpy.data.objects[name]
    obs=list(root.children_recursive)
    arm=max((o for o in obs if o.type=='ARMATURE'),key=lambda o:len(o.pose.bones))
    head=next(o for o in obs if o.type=='MESH' and o.data.shape_keys and 'jawOpen' in o.data.shape_keys.key_blocks)
    return dict(root=root,obs=obs,arm=arm,head=head)


p=actor('PUDGE_DOPPIO');a=actor('PUDGE_MUSCULAR')
# Join the actual rear boundary of the head to the posed torso surface.
# Pudge's opening is almost vertical, not a horizontal neck ring.
def fitted_neck(act):
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    arm=act['arm'];head=act['head']
    torso=next(o for o in act['obs'] if o.type=='MESH' and 'upper_body' in o.name)
    dg=bpy.context.evaluated_depsgraph_get()
    hm=bpy.data.meshes.new_from_object(head.evaluated_get(dg),depsgraph=dg)
    bm=bmesh.new();bm.from_mesh(hm)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.0003)
    used=set();loops=[]
    for edge in [e for e in bm.edges if e.is_boundary]:
        if edge in used:continue
        ring=[edge.verts[0]];used.add(edge);v=edge.verts[1]
        while v!=ring[0]:
            ring.append(v)
            nxt=next((e for e in v.link_edges if e.is_boundary and e not in used),None)
            if nxt is None:break
            used.add(nxt);v=nxt.other_vert(v)
        if len(ring)>5:loops.append(ring)
    ring=min(loops,key=lambda r:sum(v.co.z for v in r)/len(r))
    top=[head.matrix_world@v.co for v in ring];bm.free();bpy.data.meshes.remove(hm)
    tm=bpy.data.meshes.new_from_object(torso.evaluated_get(dg),preserve_all_data_layers=True,depsgraph=dg)
    world=[torso.matrix_world@v.co for v in tm.vertices]
    bodybm=bmesh.new();bodybm.from_mesh(tm);bmesh.ops.remove_doubles(bodybm,verts=list(bodybm.verts),dist=.0003)
    used=set();rings=[]
    for edge in [e for e in bodybm.edges if e.is_boundary]:
        if edge in used:continue
        ring=[edge.verts[0]];used.add(edge);v=edge.verts[1]
        while v!=ring[0]:
            ring.append(v);nxt=next((e for e in v.link_edges if e.is_boundary and e not in used),None)
            if nxt is None:break
            used.add(nxt);v=nxt.other_vert(v)
        if len(ring)>5:rings.append([torso.matrix_world@v.co for v in ring])
    center=sum(top,Vector())/len(top)
    boundary=min(rings,key=lambda r:(sum(r,Vector())/len(r)-center).length_squared)
    bodybm.free()
    # Use the actual opening edge, not the closest unrelated torso face.
    from mathutils.geometry import intersect_point_line
    bottom=[];tex=[]
    for point in top:
        options=[]
        for p0,p1 in zip(boundary,boundary[1:]+boundary[:1]):
            _,factor=intersect_point_line(point,p0,p1)
            options.append(p0.lerp(p1,max(0,min(1,factor))))
        co=min(options,key=lambda q:(q-point).length_squared)
        bottom.append(co+(co-center)*.025)
        vi=min(range(len(world)),key=lambda i:(world[i]-co).length_squared)
        li=next(loop.index for loop in tm.loops if loop.vertex_index==vi)
        tex.append(tm.uv_layers.active.data[li].uv.copy())
    n=len(top);vertices=[];weights=[];faces=[]
    for row in range(5):
        t=row/4;w=1.0
        deform=(arm.pose.bones['spine3'].matrix@arm.data.bones['spine3'].matrix_local.inverted())*(1-w)+(arm.pose.bones['head'].matrix@arm.data.bones['head'].matrix_local.inverted())*w
        for lo,hi in zip(bottom,top):
            point=lo.lerp(hi,t)
            vertices.append(deform.inverted()@(arm.matrix_world.inverted()@point));weights.append(w)
    for row in range(4):
        for i in range(n):
            j=(i+1)%n;faces.append((row*n+i,row*n+j,(row+1)*n+j,(row+1)*n+i))
    mesh=bpy.data.meshes.new('Fitted head torso join');mesh.from_pydata(vertices,[],faces);mesh.update()
    obj=bpy.data.objects.new('ANATOMY / fitted neck / '+act['root'].name,mesh);s.collection.objects.link(obj)
    obj.parent=arm;obj.matrix_world=arm.matrix_world.copy()
    for name in ['head','spine3']:obj.vertex_groups.new(name=name)
    for i,w in enumerate(weights):
        obj.vertex_groups['head'].add([i],w,'REPLACE');obj.vertex_groups['spine3'].add([i],1-w,'REPLACE')
    modifier=obj.modifiers.new('Neck skinning','ARMATURE');modifier.object=arm
    mesh.materials.append(torso.data.materials[0]);layer=mesh.uv_layers.new()
    for poly in mesh.polygons:
        poly.use_smooth=True
        for i in poly.loop_indices:layer.data[i].uv=tex[mesh.loops[i].vertex_index%n]
    bpy.data.meshes.remove(tm)
    for f in range(1,505):
        obj.hide_render=not(f<155 if act is p else f>=155);obj.keyframe_insert('hide_render',frame=f)
    print('FITTED_NECK',act['root'].name,n,flush=True)

fitted_neck(p);fitted_neck(a)
# The source head texture bakes a nearly black underside into the throat.
# Restore skin there and illuminate the repaired join from below eye level.
def throat_surface(act):
    from mathutils.kdtree import KDTree
    head=act['head'];body=next(o for o in act['obs'] if o.type=='MESH' and 'upper_body' in o.name)
    material=bpy.data.materials.new('Restored throat skin / '+act['root'].name);material.use_nodes=True
    nodes=material.node_tree.nodes;links=material.node_tree.links;bs=nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value=(.36,.225,.19,1);bs.inputs['Roughness'].default_value=.7
    noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=34;noise.inputs['Detail'].default_value=2
    bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.012
    links.new(noise.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs['Normal'],bs.inputs['Normal'])
    ramp=nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.25;ramp.color_ramp.elements[0].color=(.25,.12,.1,1)
    ramp.color_ramp.elements[1].position=.75;ramp.color_ramp.elements[1].color=(.45,.25,.20,1)
    mottling=nodes.new('ShaderNodeTexNoise');mottling.inputs['Scale'].default_value=6;mottling.inputs['Detail'].default_value=3
    links.new(mottling.outputs['Fac'],ramp.inputs[0]);links.new(ramp.outputs[0],bs.inputs['Base Color'])
    # Blend the repaired throat into the original face, not a hard material band.
    attr=head.data.color_attributes.new(name='throat_blend',type='FLOAT_COLOR',domain='POINT')
    low=min(v.co.z for v in head.data.vertices);high=max(v.co.z for v in head.data.vertices)
    for v in head.data.vertices:
        t=(v.co.z-low)/(high-low);w=max(0,min(1,(.38-t)/.18));w=w*w*(3-2*w)
        attr.data[v.index].color=(w,w,w,1)
    original=head.data.materials[0].copy();head.data.materials[0]=original
    nt=original.node_tree;principled=next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
    old=principled.inputs['Base Color'].links[0].from_socket if principled.inputs['Base Color'].links else None
    mix=nt.nodes.new('ShaderNodeMixRGB');mix.inputs[2].default_value=(.35,.19,.15,1)
    if old:nt.links.new(old,mix.inputs[1])
    # Project the real chest skin texture onto the lower head, with a smooth
    # blend into the original face. Avoid a flat, separately colored patch.
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform
    dg=bpy.context.evaluated_depsgraph_get()
    tm=bpy.data.meshes.new_from_object(body.evaluated_get(dg),preserve_all_data_layers=True,depsgraph=dg);tm.calc_loop_triangles()
    points=[body.matrix_world@v.co for v in tm.vertices];triangles=list(tm.loop_triangles)
    tree=BVHTree.FromPolygons(points,[list(t.vertices)for t in triangles],all_triangles=True)
    hm=head.evaluated_get(dg).to_mesh();layer=head.data.uv_layers.new(name='neck_skin_uv')
    mapped={}
    for v in hm.vertices:
        probe=head.matrix_world@v.co+Vector((0,0,-.18));co,normal,index,_=tree.find_nearest(probe);tri=triangles[index]
        uv=[Vector((*tm.uv_layers.active.data[i].uv,0))for i in tri.loops]
        result=barycentric_transform(co,*[points[i]for i in tri.vertices],*uv);mapped[v.index]=result.xy
    for loop in head.data.loops:layer.data[loop.index].uv=mapped[loop.vertex_index]
    source=next(n.image for n in body.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'color' in n.image.name.lower())
    sample=nt.nodes.new('ShaderNodeTexImage');sample.image=source;uvnode=nt.nodes.new('ShaderNodeUVMap');uvnode.uv_map=layer.name
    nt.links.new(uvnode.outputs[0],sample.inputs[0]);nt.links.new(sample.outputs['Color'],mix.inputs[2])
    bpy.data.meshes.remove(tm);head.evaluated_get(dg).to_mesh_clear()
    attribute=nt.nodes.new('ShaderNodeVertexColor');attribute.layer_name='throat_blend'

    nt.links.new(attribute.outputs['Color'],mix.inputs[0]);nt.links.new(mix.outputs[0],principled.inputs['Base Color'])
    bridge=bpy.data.objects['ANATOMY / fitted neck / '+act['root'].name]
    bridge.data.materials.clear();bridge.data.materials.append(material)
    data=bpy.data.lights.new('Neck soft fill','AREA');data.energy=40;data.shape='DISK';data.size=2.5
    obj=bpy.data.objects.new('Neck soft fill / '+act['root'].name,data);s.collection.objects.link(obj);obj.parent=act['root']
    obj.location=(.1,-3.2,1.5);obj.rotation_euler=(Vector((.1,-.4,2.3))-obj.location).to_track_quat('-Z','Y').to_euler()
    for f in range(1,505):
        obj.hide_render=not(f<155 if act is p else f>=155);obj.keyframe_insert('hide_render',frame=f)

throat_surface(p);throat_surface(a)



def pos(act,name):
    return (act['arm'].matrix_world@act['arm'].pose.bones[name].matrix).translation.copy()


def rotate(act,name,q):
    arm=act['arm'];bone=arm.pose.bones[name];m=arm.matrix_world@bone.matrix;c=m.translation
    bone.matrix=arm.matrix_world.inverted()@Matrix.Translation(c)@q.to_matrix().to_4x4()@Matrix.Translation(-c)@m
    bpy.context.view_layer.update()


def hand(act,side,target):
    upper,middle,end=['bicep_'+side,'elbow_'+side,'wrist_'+side]
    shoulder,elbow,wrist=[pos(act,b) for b in (upper,middle,end)]
    u,v=elbow-shoulder,wrist-elbow
    forward=(target-shoulder).normalized();d=min((target-shoulder).length,(u.length+v.length)*.97)
    pole=Vector((1 if side=='L' else -1,.15,-.25));pole=(pole-forward*pole.dot(forward)).normalized()
    x=(u.length_squared-v.length_squared+d*d)/(2*d)
    desired=shoulder+forward*x+pole*math.sqrt(max(0,u.length_squared-x*x))
    rotate(act,upper,u.rotation_difference(desired-shoulder))
    rotate(act,middle,(pos(act,end)-pos(act,middle)).rotation_difference(target-pos(act,middle)))


def grip_axis(act,side):
    # Native hook/cleaver handles both run along -Y of their weapon socket.
    # This was checked against the actual game meshes, not inferred from a
    # generic wrist axis. It keeps the new shaft inside the existing fist.
    socket='weapon_rt_1' if side=='R' else 'weapon_lf_2'
    axis=-(act['arm'].matrix_world@act['arm'].pose.bones[socket].matrix).to_3x3().col[1]
    axis.normalize()
    return axis if axis.z>=0 else -axis


def settle_forearm(act,side,up=None):
    axis=(pos(act,'wrist_'+side)-pos(act,'elbow_'+side)).normalized()
    grip=grip_axis(act,side);up=up if up is not None else Vector((0,0,1))
    v=(grip-axis*grip.dot(axis)).normalized();w=(up-axis*up.dot(axis)).normalized()
    angle=math.atan2(axis.dot(v.cross(w)),v.dot(w))
    rotate(act,'elbow_'+side,Quaternion(axis,angle*.8))
    rotate(act,'wrist_'+side,Quaternion(axis,angle*.2))


def import_prop(name,pivot,scale,turn=None):
    before=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/'out/dota-jojo/assets'/f'{name}.glb'),bone_heuristic='BLENDER')
    obs=list(set(bpy.data.objects)-before)
    root=bpy.data.objects.new('ITEM / '+name,None);s.collection.objects.link(root)
    result=[]
    dg=bpy.context.evaluated_depsgraph_get()
    for obj in obs:
        if obj.type!='MESH' or obj.name.startswith('Icosphere') or 'physics' in obj.name:continue
        mesh=bpy.data.meshes.new_from_object(obj.evaluated_get(dg),preserve_all_data_layers=True,depsgraph=dg)
        if name=='madness':
            # This Drow cosmetic includes a hood in separate UV islands.
            # Keep the mask and its white fangs; remove the unrelated cloth.
            bm=bmesh.new();bm.from_mesh(mesh);uv=bm.loops.layers.uv.active
            remove=[]
            for face in bm.faces:
                coords=[loop[uv].uv for loop in face.loops]
                x=sum(co.x for co in coords)/len(coords)*256
                y=(1-sum(co.y for co in coords)/len(coords))*256
                if y<64 or (x<130 and y>108):remove.append(face)
            bmesh.ops.delete(bm,geom=remove,context='FACES');bm.to_mesh(mesh);bm.free()
        for v in mesh.vertices:
            co=obj.matrix_world@v.co-Vector(pivot)
            if turn:co=turn@co
            v.co=co*scale
        baked=bpy.data.objects.new('ITEM mesh / '+name,mesh);s.collection.objects.link(baked);baked.parent=root
        result.append(baked)
        for slot in baked.material_slots:
            mat=slot.material
            if not mat or not mat.use_nodes:continue
            for n in mat.node_tree.nodes:
                if n.type=='BSDF_PRINCIPLED':
                    for attr,value in [('Alpha',1),('Metallic',.15),('Roughness',.52),('Emission Strength',0)]:
                        for link in list(n.inputs[attr].links):mat.node_tree.links.remove(link)
                        n.inputs[attr].default_value=value
    for obj in obs:bpy.data.objects.remove(obj,do_unlink=True)
    return root,result


observer=import_prop('observer',(-.55,-.04499,.69492),.41,Quaternion((0,1,0),-math.pi/2))
sentry=import_prop('sentry',(-.55,-.04499,.69492),.41,Quaternion((0,1,0),-math.pi/2))
dagon=import_prop('dagon',(2.74289,-.02243,2.7),.37)
mask=import_prop('madness',(0,-.05,3.57),1.35)


def matrix(act,bone):
    return act['arm'].matrix_world@act['arm'].pose.bones[bone].matrix


# Snapshot existing animation first: no accumulation of IK corrections.
cache={}
for act in [p,a]:
    arm=act['arm'];cache[arm.name]={}
    for f in range(1,505):
        s.frame_set(f)
        cache[arm.name][f]={b.name:b.matrix_basis.copy() for b in arm.pose.bones}
    arm.animation_data_clear()

offsets={}
report=[]
for f in range(1,505):
    s.frame_set(f)
    for act in [p,a]:
        for b in act['arm'].pose.bones:b.matrix_basis=cache[act['arm'].name][f][b.name]
    bpy.context.view_layer.update()
    for side in 'LR':
        shoulder=pos(p,'bicep_'+side)
        hand(p,side,shoulder+Vector((.20 if side=='L' else -.20,-.65,-.5)))
        settle_forearm(p,side)
    hand(a,'L',pos(a,'bicep_L')+Vector((.20,-.65,-.5)))
    settle_forearm(a,'L',Vector((.55,0,1)).normalized())
    for act in [p,a]:
        for b in act['arm'].pose.bones:
            b.rotation_mode='QUATERNION'
            for prop in ['location','rotation_quaternion','scale']:b.keyframe_insert(prop,frame=f)
    for item,act,side,start,end in [(observer,p,'R',1,154),(sentry,p,'L',1,154),(dagon,a,'L',155,504)]:
        root,meshes=item
        bone='wrist_'+side
        wrist=matrix(act,bone)
        socket=pos(act,'weapon_rt_1' if side=='R' else 'weapon_lf_2')
        if root.name not in offsets:
            m=Vector((0,0,1)).rotation_difference(grip_axis(act,side)).to_matrix().to_4x4();m.translation=socket
            offsets[root.name]=wrist.inverted()@m
        root.matrix_world=wrist@offsets[root.name]
        root.rotation_mode='QUATERNION'
        for prop in ['location','rotation_quaternion']:root.keyframe_insert(prop,frame=f)
        for o in meshes:o.hide_render=not start<=f<=end;o.keyframe_insert('hide_render',frame=f)
        if f in [1,154,155,345,380,417,475]:report.append({'frame':f,'item':root.name,'wrist':list(wrist.translation),'socket':list(socket),'pivot':list(root.location)})
    head=matrix(a,'head')
    if 'mask' not in offsets:
        m=Quaternion((1,0,0),math.radians(-70)).to_matrix().to_4x4();m.translation=Vector((a['root'].location.x+.15,-.20,2.88))
        offsets['mask']=head.inverted()@m
    mask[0].matrix_world=head@offsets['mask'];mask[0].rotation_mode='QUATERNION'
    for prop in ['location','rotation_quaternion']:mask[0].keyframe_insert(prop,frame=f)
    for o in mask[1]:o.hide_render=f<155;o.keyframe_insert('hide_render',frame=f)


def camera(name,first,last,target0,target1,lens,start,end):
    obj=bpy.data.objects[name];obj.animation_data_clear();obj.data.animation_data_clear();obj.data.lens=lens
    for f,loc,target in [(start,first,target0),(end,last,target1)]:
        obj.location=loc;obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
        obj.keyframe_insert('location',frame=f);obj.keyframe_insert('rotation_euler',frame=f)


camera('01_Shadow_identity',(-1.8,-7.6,2.6),(-1.6,-7.1,2.6),(-1.8,-.4,1.85),(-1.8,-.4,1.85),46,1,90)
camera('02_Time_erasure',(0,-11.6,5),(0,-11.2,4.9),(.2,-.5,2.6),(.2,-.5,2.6),32,91,222)
camera('03_Diavolo_glimpse',(2.6,-4.6,2.9),(2.6,-4.6,2.9),(2.85,-.4,2.35),(2.85,-.4,2.35),34,223,244)
camera('05_Column_reveal',(-1.1,-8.5,3.3),(3,-9.8,3.7),(2.25,0,1.8),(2.25,-3.1,2.15),40,316,407)
camera('06_Diavolo_eye',(2.5,-7.4,3.3),(2.5,-7.4,3.3),(2.25,-3.8,2.9),(2.25,-3.8,2.9),48,408,452)
camera('07_Diavolo_portrait',(2.7,-8.5,3.1),(2.5,-8.1,3.0),(2.85,-3.7,2.65),(2.85,-3.7,2.65),38,453,504)
s.frame_set(1)
s.render.filepath=str(OUT/'frames/frame_')
s.frame_start=1;s.frame_end=504
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'jojo-v3.blend'))
(OUT/'equipment-audit.json').write_text(json.dumps(report,indent=2))
print('EQUIPMENT_REVISION_READY',flush=True)
