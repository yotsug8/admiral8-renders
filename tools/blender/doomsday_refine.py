"""Reference-led staging pass over the verified v2 cache; no hero reimport.

Blender --python tools/blender/doomsday_refine.py -- build|probe|draft
The v2 action/contacts remain the source; this pass improves readable framing,
native prop materials, depth and the visible response. It does not certify acting.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'_game/skits/doomsday/v2'
OUT=ROOT/'_game/skits/doomsday/v3'
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(Path(__file__).resolve().parent))
from contact_reaction import _basis, _solve_leg


def smooth(t):
    t=max(0,min(1,t));return t*t*(3-2*t)


def ground(x,y):
    from mathutils import noise
    fade=smooth((math.hypot(x,y+1)-10)/18)
    return fade*(3.5+3*noise.noise(Vector((x*.035,y*.035,0)))+math.sin(x*.08+y*.06))


def gpu(scene):
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='CUDA';prefs.get_devices()
    for device in prefs.devices:device.use=device.type=='CUDA'
    scene.cycles.device='GPU' if any(d.type=='CUDA' for d in prefs.devices) else 'CPU'


def surface(mat):
    """Relocated dry props use their native albedo, without the exported dark tint."""
    if not mat or not mat.use_nodes:return
    nt=mat.node_tree
    p=next((n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'),None)
    tex=next((n for n in nt.nodes if n.type=='TEX_IMAGE' and n.image and 'color' in n.image.name.lower()),None)
    if not p or not tex:return
    nt.links.new(tex.outputs['Color'],p.inputs['Base Color'])
    tex.image.alpha_mode='CHANNEL_PACKED'
    for key,value in (('Metallic',0),('Roughness',.78),('Alpha',1),('Emission Strength',0)):
        for link in list(p.inputs[key].links):nt.links.remove(link)
        p.inputs[key].default_value=value


def place_prop(ob,position,height):
    matrix=ob.matrix_world.copy();ob.parent=None;ob.data=ob.data.copy()
    ob.data.transform(matrix);ob.matrix_world=Matrix.Identity(4)
    lo=Vector(tuple(min(v.co[i] for v in ob.data.vertices) for i in range(3)))
    hi=Vector(tuple(max(v.co[i] for v in ob.data.vertices) for i in range(3)))
    center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z))
    factor=height/max(.01,hi.z-lo.z)
    for v in ob.data.vertices:v.co=(v.co-center)*factor
    x,y=position;ob.location=(x,y,ground(x,y))
    for mat in ob.data.materials:surface(mat)


def landmarks(scene):
    # Reuse the installed game's complete trees and cliffs, not loose polygons.
    before=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/maps/dire_tank_base_v2.glb'),bone_heuristic='BLENDER')
    imported=list(set(bpy.data.objects)-before)
    trees=sorted([o for o in imported if o.type=='MESH' and o.data.name.startswith(('dire_tree004.','dire_tree007.')) and '_model' in o.data.name],key=lambda o:o.name)
    cliffs=sorted([o for o in imported if o.type=='MESH' and 'cliff_wall' in o.name],key=lambda o:o.name)
    selected=trees[:2]
    if len(trees)<2:raise ValueError('Missing complete environment templates')
    matrices={o:o.matrix_world.copy() for o in selected}
    for ob in selected:ob.parent=None;ob.matrix_world=matrices[ob]
    for ob in imported:
        if ob not in selected:bpy.data.objects.remove(ob,do_unlink=True)
    layouts=[((-7,8),6.2),((7,11),7.5),((-10,-14),5.5),((8,-12),6.8),((-13,16),8),((14,18),9)]
    for i,(xy,height) in enumerate(layouts):
        template=trees[i%2]
        ob=template.copy();ob.data=template.data;scene.collection.objects.link(ob)
        place_prop(ob,xy,height);ob.rotation_euler.z=.8*i
    for ob in selected:bpy.data.objects.remove(ob,do_unlink=True)


def boulders(scene):
    folder=OUT/'external/boulder_01';manifest=json.loads((folder/'manifest.json').read_text())
    for item in manifest['files']:
        if hashlib.sha256((folder/item['file']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Boulder source changed')
    before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(folder/'boulder_01_8k.gltf'))
    imported=set(bpy.data.objects)-before;template=next(o for o in imported if o.type=='MESH')
    place_prop(template,(0,0),1)
    positions=[]
    for ob in list(scene.objects):
        if ob.type=='MESH' and 'ground_rock001' in ob.name:
            positions.append(((ob.location.x,ob.location.y),.18+min(.2,max(ob.dimensions)*.06)))
            bpy.data.objects.remove(ob,do_unlink=True)
    positions.extend([((-5,9),2.6),((5,12),3.4),((-8,-12),2.8),((8,-14),3.5)])
    for i,(xy,height) in enumerate(positions):
        ob=template.copy();ob.data=template.data;scene.collection.objects.link(ob)
        ob.location=(*xy,ground(*xy)-height*.12);ob.scale=(height,)*3;ob.rotation_euler.z=i*2.39996
    for ob in imported:bpy.data.objects.remove(ob,do_unlink=True)


def protected(arm,scene):
    samples=[]
    names=('root','wrist_L','wrist_R','ankle_L','ankle_R','axe_1')
    for i in range(scene.frame_end*2+1):
        scene.frame_set(i//2,subframe=(i%2)/2);bpy.context.view_layer.update()
        samples.append({n:arm.matrix_world@arm.pose.bones[n].matrix for n in names})
    return samples


def acting(arm,scene):
    # The rejected head recoil exposed the shoulder/neck seam. Keep the source
    # head path while independently checking the revised shoulder articulation.
    for ob in scene.objects:
        if ob.type!='MESH' or not ob.data.shape_keys or 'axe_model' not in ob.data.name:continue
        keys=ob.data.shape_keys.key_blocks
        for f in range(108):
            startled=smooth((f-93)/7)
            blink=max(0,1-abs(f-93)/2)
            values={'browLowerer':.7*(1-startled),'innerBrowRaiser':.65*startled,
                    'upperLidRaiser':.62*startled,'jawOpen':.18+.4*startled,
                    'eyeClosed':blink,'lipCornerDepressor':.25*startled}
            for name,value in values.items():
                if name in keys:keys[name].value=value;keys[name].keyframe_insert('value',frame=f)


def workshop_materials():
    folder=OUT/'source_audit/workshop'
    manifest=json.loads((folder/'textures.json').read_text())
    for name,entry in manifest['materials'].items():
        mat=bpy.data.materials.get(name)
        if not mat:continue
        nt=mat.node_tree;p=next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
        for kind in ('color','normal'):
            info=entry[kind];path=folder/info['file']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Workshop texture provenance changed')
            tex=nt.nodes.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(path),check_existing=True)
            tex.image.colorspace_settings.name='sRGB' if kind=='color' else 'Non-Color';tex.image.alpha_mode='CHANNEL_PACKED'
            if kind=='color':nt.links.new(tex.outputs['Color'],p.inputs['Base Color'])
            else:
                normal=nt.nodes.new('ShaderNodeNormalMap');nt.links.new(tex.outputs['Color'],normal.inputs['Color']);nt.links.new(normal.outputs[0],p.inputs['Normal'])
        metal=.5 if 'weapon' in name else .2 if any(t in name for t in ('armor','shoulder')) else 0
        for key,value in (('Metallic',metal),('Roughness',.48 if metal else .75),('Specular IOR Level',.12),('Alpha',1)):
            for link in list(p.inputs[key].links):nt.links.remove(link)
            p.inputs[key].default_value=value


def restore_clavicles(arm,scene):
    """Let raised attack shoulders return with the chest, retaining both grips."""
    before=set(bpy.data.objects);actions=set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/models/render/models_heroes_axe_axe.glb'),bone_heuristic='BLENDER')
    imported=set(bpy.data.objects)-before
    source=next(o for o in imported if o.type=='ARMATURE')
    clip=next(a for a in set(bpy.data.actions)-actions if a.name.startswith('culling_blade'))
    source.animation_data.action=clip;source.animation_data.action_slot=clip.slots[0]
    scene.frame_set(0);bpy.context.view_layer.update()
    rest={side:source.pose.bones['clavicle_'+side].matrix_basis.copy() for side in ('L','R')}
    for ob in imported:bpy.data.objects.remove(ob,do_unlink=True)
    times=[44+i/8 for i in range((107-44)*8+1)];records=[];inv=arm.matrix_world.inverted();previous=None;poles={};initial_poles={}
    changed={b.name for side in ('L','R') for b in [arm.pose.bones['clavicle_'+side],*arm.pose.bones['clavicle_'+side].children_recursive]}
    for f in times:
        scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
        original={b.name:arm.matrix_world@b.matrix for b in arm.pose.bones};pose={n:m.copy() for n,m in original.items()}
        if f==44:
            for side in ('L','R'):
                shoulder,elbow,wrist=(original[n+'_'+side].translation for n in ('bicep','elbow','wrist'))
                direction=(wrist-shoulder).normalized();pole=elbow-shoulder
                poles[side]=(pole-direction*pole.dot(direction)).normalized()
                initial_poles[side]=poles[side].copy()
            previous=original;records.append((f,original));continue
        for side in ('L','R'):
            bone=arm.pose.bones['clavicle_'+side]
            basis=_basis(bone,inv@pose[bone.name],inv@pose[bone.parent.name])
            loc,q,scale=basis.decompose();rl,rq,rs=rest[side].decompose();t=smooth((f-44)/16)
            basis=Matrix.LocRotScale(loc.lerp(rl,t),q.slerp(rq,t),scale.lerp(rs,t))
            target=arm.matrix_world@bone.bone.convert_local_to_pose(basis,bone.bone.matrix_local,parent_matrix=inv@pose[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
            delta=target@pose[bone.name].inverted()
            for b in [bone,*bone.children_recursive]:pose[b.name]=delta@pose[b.name]
        desired={n:m.copy() for n,m in pose.items()}
        for side in ('L','R'):
            chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
            poles[side]=_solve_leg(pose,desired,chain,Vector(),poles[side],Vector((0,-1,0)),original['wrist_'+side])
            # Explicit staging of the elbow plane: settle below the held shaft.
            # Rotate the solved triangle around its shoulder-to-wrist axis;
            # lengths and the fixed wrist are unchanged by this operation.
            shoulder=desired[chain[0]].translation;wrist=desired[chain[2]].translation
            axis=(wrist-shoulder).normalized();vector=desired[chain[1]].translation-shoulder
            current_plane=vector-axis*vector.dot(axis)
            start=initial_poles[side]-axis*initial_poles[side].dot(axis)
            down=Vector((0,0,-1));down-=axis*down.dot(axis)
            bend=start.normalized().lerp(down.normalized(),smooth((f-44)/16)).normalized()
            if current_plane.length>1e-6:
                rotation=current_plane.rotation_difference(bend).to_matrix().to_4x4()
                transform=Matrix.Translation(shoulder)@rotation@Matrix.Translation(-shoulder)
                for name in chain[:2]:desired[name]=transform@desired[name]
            poles[side]=bend
            for b in arm.pose.bones['wrist_'+side].children_recursive:desired[b.name]=original[b.name]
            if previous:
                for bone,child in ((chain[0],chain[1]),(chain[1],chain[2])):
                    a=previous[child].translation-previous[bone].translation;b=desired[child].translation-desired[bone].translation
                    matrix=a.rotation_difference(b).to_matrix().to_4x4()@previous[bone];matrix.translation=desired[bone].translation;desired[bone]=matrix
        previous=desired;records.append((f,desired))
    scene.frame_set(43);bpy.context.view_layer.update()
    previous_q={name:arm.pose.bones[name].rotation_quaternion.copy() for name in changed}
    for f,pose in records:
        for name in changed:
            bone=arm.pose.bones[name];matrix=_basis(bone,inv@pose[name],inv@pose[bone.parent.name])
            loc,q,scale=matrix.decompose()
            if name in previous_q and q.dot(previous_q[name])<0:q.negate()
            previous_q[name]=q.copy();bone.location=loc;bone.rotation_mode='QUATERNION';bone.rotation_quaternion=q;bone.scale=scale
            for key in ('location','rotation_quaternion','scale'):bone.keyframe_insert(key,frame=f)


def cameras(scene,axe,rubick):
    cam=scene.camera;cam.animation_data_clear();cam.data.animation_data_clear()
    contact=Vector(json.loads((SOURCE/'staging.json').read_text())['contact'])
    for f in range(108):
        scene.frame_set(f);bpy.context.view_layer.update()
        ahead=axe.matrix_world@axe.pose.bones['head'].head
        rhead=rubick.matrix_world@rubick.pose.bones['Head_0'].head
        if f<19:
            target=ahead+Vector((0,0,-.3));pos=target+Vector((1.0,-3.5,.3));lens=52
        elif f<39:
            pos=Vector((3,-3.8,1.3));target=Vector((0,2,2.25));lens=48
        elif f<68:
            pos=Vector((3.2,-6.8,1.3));target=Vector((-.3,-1.2,1.95));lens=40
        elif f<76:
            target=contact+Vector((0,.1,0));pos=target+Vector((1.5,-2.8,.35));lens=62
        elif f<90:
            target=rhead;pos=target+Vector((.6,2.8,.08));lens=60
        else:
            target=ahead+Vector((0,0,-.04));pos=target+Vector((.35,-1.8,1));lens=42
        cam.location=pos;cam.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler();cam.data.lens=lens
        cam.data.dof.focus_distance=(target-pos).length;cam.data.dof.aperture_fstop=7 if 19<=f<68 else 4
        for key in ('location','rotation_euler'):cam.keyframe_insert(key,frame=f)
        for key in ('lens','dof.focus_distance','dof.aperture_fstop'):cam.data.keyframe_insert(key,frame=f)
    for owner in (cam,cam.data):
        for layer in owner.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:key.interpolation='CONSTANT'


def build():
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE/'effects.blend'));scene=bpy.context.scene;gpu(scene)
    axe=next(o for o in scene.objects if o.type=='ARMATURE' and 'head' in o.pose.bones and 'axe_1' in o.pose.bones)
    rubick=next(o for o in scene.objects if o.type=='ARMATURE' and 'Head_0' in o.pose.bones and 'index_1_R' in o.pose.bones)
    original=protected(axe,scene)
    for ob in scene.objects:
        if ob.type=='MESH' and any(s in ob.name for s in ('tower','statue','rock001')):
            for mat in ob.data.materials:surface(mat)
            if 'tower' in ob.name:
                ob.scale=(.72,)*3;ob.location.y=13 if ob.location.y>0 else -15
                ob.location.z=ground(ob.location.x,ob.location.y)
    landmarks(scene);boulders(scene)
    # Preserve photographic ground detail while reducing the unrelated orange cast.
    mat=bpy.data.materials['Rocky ground'];nt=mat.node_tree;p=nt.nodes.get('Principled BSDF')
    source=p.inputs['Base Color'].links[0].from_socket
    hue=nt.nodes.new('ShaderNodeHueSaturation');hue.inputs['Saturation'].default_value=.55;hue.inputs['Value'].default_value=.7
    nt.links.new(source,hue.inputs['Color']);nt.links.new(hue.outputs[0],p.inputs['Base Color'])
    rock=mat.copy();rock.name='Weathered stone photo material'
    for ob in scene.objects:
        if ob.type=='MESH' and any(token in ob.name for token in ('cliff_wall','ground_rock001')):
            ob.data.materials.clear();ob.data.materials.append(rock)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.3
    wn=scene.world.node_tree;bg=wn.nodes['Background'];env=bg.inputs[0].links[0].from_socket
    sky=wn.nodes.new('ShaderNodeHueSaturation');sky.inputs['Value'].default_value=.4;sky.inputs['Saturation'].default_value=.65
    wn.links.new(env,sky.inputs['Color'])
    lightpath=wn.nodes.new('ShaderNodeLightPath');mix=wn.nodes.new('ShaderNodeMixRGB')
    wn.links.new(lightpath.outputs['Is Camera Ray'],mix.inputs[0]);wn.links.new(env,mix.inputs[1]);wn.links.new(sky.outputs[0],mix.inputs[2]);wn.links.new(mix.outputs[0],bg.inputs[0])
    # Clear air around the actors; haze belongs to the distant landscape.
    mist=bpy.data.materials['Thin aerial perspective'].node_tree
    volume=next(n for n in mist.nodes if n.type=='PRINCIPLED_VOLUME')
    geometry=mist.nodes.new('ShaderNodeNewGeometry');xy=mist.nodes.new('ShaderNodeVectorMath');xy.operation='MULTIPLY';xy.inputs[1].default_value=(1,1,0)
    distance=mist.nodes.new('ShaderNodeVectorMath');distance.operation='LENGTH'
    density=mist.nodes.new('ShaderNodeMapRange');density.inputs['From Min'].default_value=8;density.inputs['From Max'].default_value=28
    density.inputs['To Min'].default_value=0;density.inputs['To Max'].default_value=.018
    mist.links.new(geometry.outputs['Position'],xy.inputs[0]);mist.links.new(xy.outputs[0],distance.inputs[0]);mist.links.new(distance.outputs['Value'],density.inputs['Value']);mist.links.new(density.outputs[0],volume.inputs['Density'])
    for ob in scene.objects:
        if ob.type!='LIGHT':continue
        if ob.name=='Cold key':ob.data.energy=2500;ob.data.size=5;ob.data.color=(.78,.87,1)
        if ob.name=='Warm edge':ob.data.energy=1700;ob.data.size=3;ob.data.color=(1,.5,.19)
        if ob.name=='Reverse fill':ob.data.energy=1200;ob.data.size=5
    workshop_materials();restore_clavicles(axe,scene);acting(axe,scene);cameras(scene,axe,rubick)
    after=protected(axe,scene)
    worst=max((abs(a[n][i][j]-b[n][i][j]),k/2,n,i,j) for k,(a,b) in enumerate(zip(original,after)) for n in a for i in range(4) for j in range(4))
    error=worst[0]
    print('PROTECTED_WORST',worst,flush=True)
    if error>1e-5:raise ValueError(f'Protected action changed: {error}')
    scene.cycles.samples=48
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
    (OUT/'build_report.json').write_text(json.dumps({'protected_samples':len(after),'max_protected_matrix_error':error,
        'source_blend_sha256':hashlib.sha256((SOURCE/'effects.blend').read_bytes()).hexdigest(),
        'scope':'Root, ankles, wrists and weapon preserved; face and framing need visual review.'},indent=2))
    print('REFINE_BUILD_OK',error,flush=True)


def render(draft=False):
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'));scene=bpy.context.scene;gpu(scene)
    selected=json.loads((SOURCE/'delivery/report.json').read_text())['source_frames'] if draft else [0,32,44,72,84,100]
    folder=OUT/('frames' if draft else 'probe');folder.mkdir(exist_ok=True)
    manifest=folder/'manifest.json'
    if draft:manifest.unlink(missing_ok=True)
    hashes=[]
    for f in selected:
        scene.frame_set(f);path=folder/f'{f:04d}.png';scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True);hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    if draft:manifest.write_text(json.dumps({'source_frames':selected,'fps':30,'frame_sha256':hashes,
        'blend_sha256':hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':
    mode=sys.argv[sys.argv.index('--')+1]
    if mode=='build':build()
    elif mode=='probe':render()
    elif mode=='draft':render(True)
    else:raise ValueError(mode)
