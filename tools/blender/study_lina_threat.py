"""Lina: confidence, noticing danger, recoil and retreat. Native editable keys.

An acting study, not a production preset. Uses the preserved face-hold source;
the known broken full blink is deliberately omitted. No audio or finished look.
Blender -b --factory-startup -P this_file -- build|keys|audit|render
"""
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/blender'))
from contact_reaction import _curves
from study_face_hold import coords, head_object

OUT = ROOT / '_game/study/lina_threat/reaction_v2'
SOURCE = ROOT / '_game/study/face_hold/face_hold.blend'
COUNT = 180
# Frame, travel X, rise, torso pitch/yaw, head pitch/yaw, expression.
# Forward is world +X; this is Lina's original hovering stance, not a walk.
POSES = [
    (0, 0, 0, 1, -8, 6, -3, 'smug'),
    (18, .10, .05, 8,-12,3,-3, 'smug'),
    (37, .18,.10, 8,-10,-3,0, 'smug'),
    (55, .18,.10, 4,-6,12,0, 'notice'),
    (63, -.05,.14,-8,-3,24,0, 'alarm'),
    (72,-.30,.18,-16,0,33,0, 'alarm'),
    (86,-.38,.12,-11,0,28,0, 'alarm'),
    (107,-.50,.09,-8,0,20,0, 'worry'),
    (131,-.85,.04,-4,5,0,5, 'worry'),
    (179,-1.65,.02,-4,5,0,5, 'worry'),
]
FACES = {
    'smug': {'lipCornerPuller_L': .27, 'outerBrowRaiser_R': .22, 'squint': .13},
    'notice': {'innerBrowRaiser': .22, 'outerBrowRaiser': .12, 'lipPressor': .12},
    'alarm': {'innerBrowRaiser': .48, 'outerBrowRaiser': .32, 'upperLidRaiser': .28,
              'jawOpen': .24, 'lipStretcher': .13},
    'worry': {'innerBrowRaiser': .43, 'browLowerer': .15, 'lipPressor': .23},
}
# Flex in the source upper-arm/forearm plane; world-X rotation also twisted
# the sleeve and made the old apparent flexion limit misleading.
FOREARMS = {0:(10,0),18:(22,15),37:(30,22),55:(30,22),63:(55,28),
            72:(65,35),86:(60,32),107:(48,25),131:(52,15),179:(45,5)}
ESCAPE = {107:(0,-15),131:(-.45,-65),179:(-1.3,-130)}


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def material(name, color, emission=0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    p = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = .8
    p.inputs['Emission Color'].default_value = (*color, 1)
    p.inputs['Emission Strength'].default_value = emission
    return m


def aimed(obj, target):
    obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    sc = bpy.context.scene; sc.frame_set(0); bpy.context.view_layer.update()
    root = bpy.data.objects['lina_root']; head = head_object()
    arm = next(m.object for m in head.modifiers if m.type == 'ARMATURE')
    members = [root, *root.children_recursive]
    # Preserve the source's native pose and equipment following constraints.
    for ob in members:
        ob.animation_data_clear()
        if ob.type == 'MESH' and ob.data.shape_keys:
            ob.data.shape_keys.animation_data_clear()
            for k in ob.data.shape_keys.key_blocks: k.value = 0
    for ob in list(sc.objects):
        if ob not in members: bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.objects['lina_blob'].hide_render = True
    bpy.context.view_layer.update()
    base = {b.name: arm.matrix_world @ b.matrix for b in arm.pose.bones}
    rest = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
    np.savez_compressed(OUT/'baseline.npz', **{o.name.replace('\\','/'):coords(o) for o in members
                        if o.type=='MESH' and o.name!='lina_blob'})
    inv = arm.matrix_world.inverted()
    def rotate(desired, name, xyz):
        b = arm.pose.bones[name]; p = desired[name].translation
        t = Matrix.Translation(p) @ Euler(tuple(math.radians(v) for v in xyz)).to_matrix().to_4x4() @ Matrix.Translation(-p)
        for child in [b, *b.children_recursive]: desired[child.name] = t @ desired[child.name]
    def flex_elbow(desired, side, degrees):
        from mathutils import Quaternion
        name='elbow_'+side; b=arm.pose.bones[name]
        p=desired[name].translation
        upper=p-desired['bicep_'+side].translation
        fore=desired['wrist_'+side].translation-p
        axis=upper.cross(fore).normalized()
        t=Matrix.Translation(p) @ Quaternion(axis,math.radians(degrees)).to_matrix().to_4x4() @ Matrix.Translation(-p)
        for child in [b,*b.children_recursive]: desired[child.name]=t @ desired[child.name]
    expected = {}; previous_q = {}
    for f, x, z, pitch, yaw, hp, hy, emotion in POSES:
        for b in arm.pose.bones: b.matrix_basis = rest[b.name]
        d = {n: m.copy() for n,m in base.items()}
        y,turn=ESCAPE.get(f,(0,0))
        for m in d.values(): m.translation += Vector((x,y,z))
        rotate(d,'Root_0',(0,-8 if 63<=f<=107 else -3 if f>=131 else 0,0))
        rotate(d,'Spine_0',(0,pitch*.55,yaw*.55))
        rotate(d,'Spine_1',(0,pitch*.45,yaw*.45))
        rotate(d,'Head_0',(0,hp*.6,hy*.6))
        rotate(d,'Head_1',(0,hp*.4,hy*.4))
        # Original airborne legs trail the torso; never claim planted-foot QA.
        lag = -9 if f >= 63 else 0
        for side in ('L','R'): rotate(d,'thigh_'+side,(0,lag,0))
        er,el=FOREARMS[f]
        flex_elbow(d,'R',er)
        flex_elbow(d,'L',el)
        if 63<=f<=107:
            rotate(d,'bicep_R',(-10,-8,10))
            rotate(d,'bicep_L',(5,-5,-5))
        for name in ('hair_L','hair_R','hair_back'):
            rotate(d,name,(0,4 if 63<=f<=86 else 0,0))
        # The decision ends in a turn toward the escape path, not a statue
        # translating backwards forever. Turn the complete posed rig together.
        rotate(d,'Root_0',(0,0,turn))
        for b in arm.pose.bones:
            b.rotation_mode = 'QUATERNION'; b.matrix = inv @ d[b.name]
            bpy.context.view_layer.update()
            if b.name in previous_q and b.rotation_quaternion.dot(previous_q[b.name]) < 0:
                b.rotation_quaternion.negate()
            previous_q[b.name] = b.rotation_quaternion.copy()
        expected[str(f)] = {n: [list(r) for r in arm.matrix_world @ arm.pose.bones[n].matrix]
                            for n in ('Root_0','Head_1','wrist_L','wrist_R')}
        for b in arm.pose.bones:
            for path in ('location','rotation_quaternion','scale'): b.keyframe_insert(path,frame=f)
        kb = head.data.shape_keys.key_blocks
        for k in kb:
            if k.name == 'Basis': continue
            k.value = FACES[emotion].get(k.name,0); k.keyframe_insert('value',frame=f)
    for datablock in (arm, head.data.shape_keys):
        for c in _curves(datablock.animation_data.action):
            for k in c.keyframe_points:
                k.interpolation = 'BEZIER'; k.handle_left_type = k.handle_right_type = 'AUTO_CLAMPED'
    floor_mat = material('warm stone',(.21,.18,.16))
    bpy.ops.mesh.primitive_plane_add(size=200)
    bpy.context.object.name='Study ground'; bpy.context.object.data.materials.append(floor_mat)
    # A rounded theatrical hand silhouette continuing beyond the frame.
    # The game hand's PCA projection read as a detached fist: rejected.
    shape=[(-6,-.8),(0,-.9),(.6,-1.3),(1.2,-2),(1.65,-2.15),(1.4,-1.7),(.85,-.6),
           (2.2,-1.1),(2.9,-1),(2.4,-.7),(1.25,-.12),(2.65,.05),(3.25,.4),(2.6,.4),
           (1.3,.45),(2.35,1.05),(2.6,1.55),(2.15,1.35),(1.0,.95),(1.6,1.9),
           (1.5,2.25),(1.2,1.8),(.3,1.25),(-.2,.9),(-6,.8)]
    curve=bpy.data.curves.new('rounded threat silhouette','CURVE');curve.dimensions='2D';curve.resolution_u=8
    curve.fill_mode='BOTH'
    spl=curve.splines.new('BEZIER');spl.bezier_points.add(len(shape)-1);spl.use_cyclic_u=True
    for point,(a,b) in zip(spl.bezier_points,shape):
        point.co=(-a,b,0);point.handle_left_type=point.handle_right_type='AUTO'
    shadow=bpy.data.objects.new('Looming shadow',curve);sc.collection.objects.link(shadow)
    bpy.context.view_layer.update()
    proof=shadow.to_mesh()
    if not len(proof.polygons): raise ValueError('Threat silhouette has no visible surface')
    shadow.to_mesh_clear()
    curve.materials.append(material('shadow',(.018,.014,.025)))
    for f,x in [(0,11),(37,11),(55,5.3),(72,2.8),(179,2.3)]:
        shadow.location=(x,0,.018); shadow.keyframe_insert('location',frame=f)
    # One visible intention: the fire grows in her open palm, then dies when
    # she notices the approaching hand. Keep the effect subordinate to acting.
    fire=bpy.data.objects.new('Fire in palm',None);sc.collection.objects.link(fire)
    for name,color,size in [('outer',(.95,.055,.006),1)]:
        verts=[]
        for z,r,dx in [(0,.05,0),(.22,.22,0),(.5,.13,.03),(.88,.005,.17)]:
            verts.extend([(size*(dx+r*math.cos(i*math.tau/12)),size*r*math.sin(i*math.tau/12),size*z) for i in range(12)])
        faces=[(j*12+i,j*12+(i+1)%12,(j+1)*12+(i+1)%12,(j+1)*12+i) for j in range(3) for i in range(12)]
        m=bpy.data.meshes.new('flame '+name);m.from_pydata(verts,[],faces)
        ob=bpy.data.objects.new('flame '+name,m);sc.collection.objects.link(ob);ob.parent=fire
        mat=material('fire '+name,color,1.5);m.materials.append(mat)
        nodes=mat.node_tree.nodes;links=mat.node_tree.links
        coord=nodes.new('ShaderNodeTexCoord');xyz=nodes.new('ShaderNodeSeparateXYZ');ramp=nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position=.12;ramp.color_ramp.elements[0].color=(1,.75,.025,1)
        ramp.color_ramp.elements[1].position=.9;ramp.color_ramp.elements[1].color=(.8,.018,.001,1)
        p=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
        links.new(coord.outputs['Generated'],xyz.inputs[0]);links.new(xyz.outputs['Z'],ramp.inputs[0])
        links.new(ramp.outputs[0],p.inputs['Base Color']);links.new(ramp.outputs[0],p.inputs['Emission Color'])
        for poly in m.polygons: poly.use_smooth=True
    flame_levels=[(0,.15),(18,.7),(37,1),(55,.9),(63,.15),(69,0),(179,0)]
    for f in range(COUNT):
        sc.frame_set(f);bpy.context.view_layer.update()
        fire.location=(arm.matrix_world@arm.pose.bones['wrist_L'].matrix).translation+Vector((.06,.21,.24))
        strength=float(np.interp(f,[a for a,b in flame_levels],[b for a,b in flame_levels]))
        fire.scale=(strength*(1+.04*math.sin(f*.7)),strength,strength*(1+.06*math.sin(f*.9)))
        fire.keyframe_insert('location',frame=f);fire.keyframe_insert('scale',frame=f)
    cam=bpy.data.objects.new('story',bpy.data.cameras.new('story'));sc.collection.objects.link(cam)
    cam.location=(15,-7,10);aimed(cam,(-.2,0,2.4));cam.data.type='ORTHO';cam.data.ortho_scale=8.6
    sc.camera=cam
    side=cam.copy();side.data=cam.data.copy();side.name='side_check';sc.collection.objects.link(side)
    side.location=(1,18,7);aimed(side,(-.4,0,2.6));side.data.ortho_scale=7.2
    close=cam.copy();close.data=cam.data.copy();close.name='face_check';sc.collection.objects.link(close)
    close.location=(9,-5,5.8);aimed(close,(-.2,0,4.55));close.data.ortho_scale=2.2
    for name,pos,energy,color,size in [('warm key',(5,-6,10),1700,(1,.77,.56),7),
                                      ('cool rim',(-3,4,8),2200,(.57,.73,1),5),
                                      ('face fill',(8,2,6),700,(1,.92,.84),6)]:
        ob=bpy.data.objects.new(name,bpy.data.lights.new(name,'AREA'));sc.collection.objects.link(ob)
        ob.location=pos;aimed(ob,(0,0,3));ob.data.energy=energy;ob.data.color=color;ob.data.size=size
    sc.world=bpy.data.worlds.new('study world');sc.world.use_nodes=True
    bg=next(n for n in sc.world.node_tree.nodes if n.type=='BACKGROUND');bg.inputs[0].default_value=(.12,.15,.2,1);bg.inputs[1].default_value=.6
    sc.render.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=16
    sc.render.resolution_x=360;sc.render.resolution_y=480;sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGB'
    sc.render.use_compositing=False;sc.render.use_sequencer=False;sc.render.film_transparent=False
    sc.view_settings.view_transform='AgX';sc.view_settings.look='None'
    sc.frame_start=0;sc.frame_end=COUNT-1;sc.render.fps=30
    sc['source_sha256']=source_hash;sc['expected_poses']=json.dumps(expected)
    sc['limits']='Airborne acting proof. No blink, audio, full environment or physical shadow simulation.'
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.region_3d.view_camera_zoom=0
                area.spaces.active.shading.type='SOLID'
    sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'blocking.blend'))
    dump('build.json',dict(source_sha256=source_hash,source_unchanged=hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash,
                           source=str(SOURCE.relative_to(ROOT)),frames=COUNT,poses=POSES,limits=sc['limits']))


def keys():
    from study_head_target import gpu_guard
    gpu_guard();sc=bpy.context.scene
    for camera,frames in [('story',(0,37,55,72,107,131,179)),('side_check',(37,72)),('face_check',(37,55,72))]:
        sc.camera=bpy.data.objects[camera]
        for f in frames:
            sc.frame_set(f);sc.render.filepath=str(OUT/'keys'/f'{camera}_{f:03}.png');bpy.ops.render.render(write_still=True)


def audit():
    sc=bpy.context.scene;head=head_object()
    arm=next(m.object for m in head.modifiers if m.type=='ARMATURE')
    meshes=[o for o in bpy.data.objects['lina_root'].children_recursive if o.type=='MESH' and o.name!='lina_blob']
    baseline=np.load(OUT/'baseline.npz'); topology={}; maxima={}; base_geometry={}
    from study_head_target import contacts
    for o in meshes:
        o.data.calc_loop_triangles()
        tri=np.array([tuple(t.vertices) for t in o.data.loop_triangles],dtype=int)
        edges=np.array(sorted({tuple(sorted(pair)) for a,b,c in tri for pair in ((a,b),(b,c),(c,a))}))
        p=baseline[o.name.replace('\\','/')];e0=np.linalg.norm(p[edges[:,0]]-p[edges[:,1]],axis=1)
        a0=np.linalg.norm(np.cross(p[tri[:,1]]-p[tri[:,0]],p[tri[:,2]]-p[tri[:,0]]),axis=1)
        topology[o.name]=(tri,edges,e0,a0)
        base_geometry[o.name]=dict(points=[Vector(v) for v in p],polygons=[tuple(poly.vertices) for poly in o.data.polygons])
        maxima[o.name]=dict(max_edge_ratio=0.,max_stretched_edges=0,max_contracted_triangles=0,worst_frame=None)
    base_contacts=contacts(base_geometry);new_contacts={}
    expected=json.loads(sc['expected_poses']); replay=0.; angular=0.; travel=0.; low=1e9; previous={}; issues=[]
    from bpy_extras.object_utils import world_to_camera_view
    frame_bounds=[]
    for f in range(COUNT):
        sc.frame_set(f);bpy.context.view_layer.update()
        for b in arm.pose.bones:
            m=arm.matrix_world@b.matrix;q=m.to_quaternion();p=m.translation
            if b.name in previous:
                oq,op=previous[b.name]
                angle=math.degrees(q.rotation_difference(oq).angle) % 360
                angular=max(angular,min(angle,360-angle))
                travel=max(travel,(p-op).length)
            previous[b.name]=(q.copy(),p.copy())
            if str(f) in expected and b.name in expected[str(f)]:
                replay=max(replay,float(np.abs(np.array(m)-np.array(expected[str(f)][b.name])).max()))
        bound=[];geometry={}
        for o in meshes:
            p=coords(o);tri,edges,e0,a0=topology[o.name]
            geometry[o.name]=dict(points=[Vector(v) for v in p],polygons=base_geometry[o.name]['polygons'])
            if not np.isfinite(p).all(): raise ValueError('Nonfinite geometry')
            low=min(low,float(p[:,2].min()))
            e=np.linalg.norm(p[edges[:,0]]-p[edges[:,1]],axis=1);ratio=e/np.maximum(e0,1e-10)
            a=np.linalg.norm(np.cross(p[tri[:,1]]-p[tri[:,0]],p[tri[:,2]]-p[tri[:,0]]),axis=1)
            stretched=int(((ratio>1.8)&(e-e0>.05)).sum())
            contracted=int(((a0>2.5e-8)&(a/np.maximum(a0,1e-10)<.2)).sum())
            row=maxima[o.name]
            if float(ratio.max())>row['max_edge_ratio']:
                row.update(max_edge_ratio=float(ratio.max()),worst_frame=f)
            row['max_stretched_edges']=max(row['max_stretched_edges'],stretched)
            row['max_contracted_triangles']=max(row['max_contracted_triangles'],contracted)
            if stretched or contracted: issues.append(dict(frame=f,mesh=o.name,stretched=stretched,contracted=contracted))
            # Every surface vertex, not only an object origin, must remain in the story frame.
            v=np.array([world_to_camera_view(sc,sc.camera,Vector(x))[:2] for x in p])
            bound.append([float(v[:,0].min()),float(v[:,1].min()),float(v[:,0].max()),float(v[:,1].max())])
        for pair,hits in contacts(geometry).items():
            added=hits-base_contacts[pair]
            if added and len(added)>new_contacts.get(pair,{}).get('count',0):
                new_contacts[pair]=dict(frame=f,count=len(added),polygon_pairs=sorted(added))
        frame_bounds.append([min(b[0] for b in bound),min(b[1] for b in bound),max(b[2] for b in bound),max(b[3] for b in bound)])
    source_ok=hashlib.sha256(SOURCE.read_bytes()).hexdigest()==sc['source_sha256']
    clipped=[f for f,b in enumerate(frame_bounds) if min(b[:2])<0 or max(b[2:])>1]
    report=dict(frames=COUNT,source_unchanged=source_ok,native_key_replay_max_error=replay,
         scene_sha256=hashlib.sha256((OUT/'blocking.blend').read_bytes()).hexdigest(),
         max_joint_rotation_degrees_per_frame=angular,max_joint_travel_per_frame=travel,
         lowest_surface=low,meshes=maxima,geometry_flags=issues,clipped_frames=clipped,
         new_hair_collar_contact_candidates=new_contacts,
         passed=source_ok and replay<1e-4 and not issues and not clipped and low>0 and angular<20,
         limits='Pass covers surface deformation, framing and continuity. Hair/collar BVH contacts are separate candidates needing inspection, not a full self-intersection or artistic quality verdict.')
    dump('audit.json',report)
    print('AUDIT',json.dumps(dict(replay=replay,angular=angular,geometry_flags=len(issues),clipped=len(clipped),lowest=low)),flush=True)
    if not report['passed']: raise ValueError('Core motion audit failed; inspect audit.json before rendering')


if __name__=='__main__':
    mode=sys.argv[sys.argv.index('--')+1]
    if mode=='build': build()
    else:
        bpy.ops.wm.open_mainfile(filepath=str(OUT/'blocking.blend'),use_scripts=False)
        if mode=='keys': keys()
        elif mode=='audit': audit()
        elif mode=='render':
            from study_head_target import gpu_guard
            checked=json.loads((OUT/'audit.json').read_text())
            if not checked['passed'] or checked.get('scene_sha256')!=hashlib.sha256((OUT/'blocking.blend').read_bytes()).hexdigest():
                raise ValueError('Fresh passing core audit of this scene is required before rendering')
            gpu_guard();sc=bpy.context.scene
            sc.render.use_overwrite=True;sc.render.use_placeholder=False
            sc.render.filepath=str(OUT/'frames'/'frame_');started=time.time()
            bpy.ops.render.render(animation=True)
            frames=[OUT/'frames'/f'frame_{f:04}.png' for f in range(COUNT)]
            if not all(p.is_file() and p.stat().st_mtime>=started-1 for p in frames):
                raise ValueError('Render did not refresh every requested frame')
            dump('render_manifest.json',dict(scene_sha256=hashlib.sha256((OUT/'blocking.blend').read_bytes()).hexdigest(),
                 frames={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in frames}))
        else: raise ValueError(mode)
