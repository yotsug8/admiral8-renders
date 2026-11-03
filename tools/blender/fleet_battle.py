"""Fleet of Kunkkas against a giant Pudge. All sources stay under _game.

Blender -b --factory-startup -P tools/blender/fleet_battle.py -- assets|build|probe|render
Final frames stream to FFmpeg to avoid a multi-gigabyte PNG intermediate.
"""
import json
import hashlib
import math
import os
from pathlib import Path
import random
import subprocess
import sys

import bpy
from mathutils import Vector, Matrix, Euler

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/blender'))
from kunkka_ghostship import helpers, aim, light, surface, linear_keys

BASE=ROOT/'_game/skits/fleet_battle'
OUT=ROOT/os.environ.get('FLEET_OUTPUT','_game/skits/fleet_battle/v2')
MODELS=ROOT/'_game/models/render'
FPS=30
COUNT=540
BOAT_OFFSETS=[(-18,-9),(-9,-4),(0,0),(9,-4),(18,-9),(-27,-15),(27,-15)]


def boat_pose(index, frame):
    x,dy=BOAT_OFFSETS[index]
    if frame<105:
        y=-58+frame*.38+dy
    else:
        u=max(0,min(1,(frame-105)/70))
        start=-58+105*.38+dy
        end=-9 if index in (1,2,3) else -9+dy
        y=(2*u**3-3*u*u+1)*start+(u**3-2*u*u+u)*70*.38+(-2*u**3+3*u*u)*end
    return (x,y,-.55+.045*math.sin(frame*.065+index)), (.008*math.sin(frame*.05+index),.010*math.sin(frame*.07+index),math.pi)


def deck_point(index, frame, point):
    location,rotation=boat_pose(index,frame)
    return Matrix.LocRotScale(Vector(location),Euler(rotation).to_quaternion(),Vector((1.4,)*3))@point


def dump(name,data):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def mesh_bounds(objects):
    deps=bpy.context.evaluated_depsgraph_get()
    points=[]
    for obj in objects:
        if obj.type!='MESH':continue
        ev=obj.evaluated_get(deps)
        points.extend(ev.matrix_world@Vector(p) for p in ev.bound_box)
    return dict(min=[min(p[i] for p in points) for i in range(3)],max=[max(p[i] for p in points) for i in range(3)])


def make_actor(who):
    imp,fix=helpers()
    info=json.loads((ROOT/'_game/data/troupe.json').read_text(encoding='utf-8'))[who]
    objects,actions=imp(str(MODELS/Path(info['glb']).name));fix(objects)
    arm=next(o for o in objects if o.type=='ARMATURE');arm.name=who+'_rig'
    root=bpy.data.objects.new(who+'_placement',None);bpy.context.scene.collection.objects.link(root)
    for obj in objects:
        if obj.parent is None:obj.parent=root
    for rel in info['parts']:
        part,_=imp(str(MODELS/(rel.replace('/','_').replace('.vmdl','.glb'))));fix(part)
        for obj in part:
            if obj.type=='ARMATURE':
                obj.animation_data_clear();obj.parent=root;obj.matrix_world=arm.matrix_world.copy()
                for bone in obj.pose.bones:
                    if bone.name in arm.pose.bones:
                        c=bone.constraints.new('COPY_TRANSFORMS');c.target=arm;c.subtarget=bone.name
        objects+=part
    for obj in objects:
        if obj.type=='MESH' and obj.data.shape_keys:
            obj.data.shape_keys.animation_data_clear()
            for key in obj.data.shape_keys.key_blocks:key.value=0
    amap={a.name:a for a in actions}
    arm.animation_data_clear()
    return dict(root=root,arm=arm,objects=objects,actions=amap)


def active(actor,action,frame):
    arm=actor['arm'];a=actor['actions'][action]
    arm.animation_data_create();arm.animation_data.action=a;arm.animation_data.action_slot=a.slots[0]
    bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update()


def assets():
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version=0
    sc=bpy.context.scene;sc.render.fps=30
    actors={who:make_actor(who) for who in ('kunkka','pudge')}
    report={}
    needed={'kunkka':['idle','run','attack1','attack2','ghostship','flail'],
            'pudge':['pudge_idle','pudge_attack1','pudge_attack2','pudge_meathook_start','pudge_flail','pudge_stun','pudge_death']}
    for who,actor in actors.items():
        report[who]=dict(root=actor['root'].name,arm=actor['arm'].name,objects=[o.name for o in actor['objects']],actions={})
        for name in needed[who]:
            action=actor['actions'][name];action.use_fake_user=True
            samples=[]
            for u in (0,.25,.5,.75,1):
                f=action.frame_range[0]+u*(action.frame_range[1]-action.frame_range[0]);active(actor,name,f)
                samples.append(dict(phase=u,bounds=mesh_bounds(actor['objects']),
                    joints={b.name:list(actor['arm'].matrix_world@b.matrix.translation) for b in actor['arm'].pose.bones if any(t in b.name.lower() for t in ('wrist','ankle','head','weapon'))}))
            report[who]['actions'][name]=dict(name=action.name,frames=list(action.frame_range),samples=samples)
        active(actor,needed[who][0],0)
        actor['arm'].animation_data_clear()
        actor['root'].hide_render=True
        for obj in actor['objects']:obj.hide_render=True
    imp,fix=helpers();ship,_=imp(str(MODELS/'models_heroes_kunkka_ghostship.glb'));fix(ship)
    for obj in ship:obj.hide_render=True
    report['ship']=dict(objects=[o.name for o in ship],bounds=mesh_bounds(ship))
    dump('assets.json',report)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'assets.blend'))
    print('ASSETS_READY')


def clone_objects(names,label):
    originals=[bpy.data.objects[n] for n in names]
    mapping={o:o.copy() for o in originals}
    for old,new in mapping.items():
        new.name=label+'_'+old.name;new.hide_render=False
        bpy.context.scene.collection.objects.link(new)
        if old.parent in mapping:new.parent=mapping[old.parent]
        elif old.parent:new.parent=None
        new.animation_data_clear()
        for mod in new.modifiers:
            if mod.type=='ARMATURE' and mod.object in mapping:mod.object=mapping[mod.object]
        for pb in new.pose.bones if new.type=='ARMATURE' else []:
            for c in pb.constraints:
                if hasattr(c,'target') and c.target in mapping:c.target=mapping[c.target]
    return mapping


def clone_actor(meta,label):
    mapping=clone_objects([meta['root'],*meta['objects']],label)
    return dict(root=mapping[bpy.data.objects[meta['root']]],arm=mapping[bpy.data.objects[meta['arm']]],objects=list(mapping.values()))


def strip(actor,action,start,end,blend=5,repeat=False,phase=0):
    ad=actor['arm'].animation_data_create();ad.action=None
    track=ad.nla_tracks.new();track.name=action.name
    s=track.strips.new(action.name,int(start),action);s.action_slot=action.slots[0]
    s.action_frame_start=action.frame_range[0]+phase;s.action_frame_end=action.frame_range[1]
    length=s.action_frame_end-s.action_frame_start
    if repeat:s.scale=1;s.repeat=max(1,(end-start)/length)
    else:s.scale=(end-start)/length
    s.frame_start=start;s.frame_end=end;s.extrapolation='NOTHING'
    s.blend_type='REPLACE';s.blend_in=blend;s.blend_out=blend
    return s


def inplace_run(arm,action):
    """Keep native vertical bounce, remove only world XY travel before staging a route."""
    sc=bpy.context.scene;poses=[];origin=None
    arm.animation_data_create();arm.animation_data.action=action;arm.animation_data.action_slot=action.slots[0]
    end=int(action.frame_range[1])
    for f in range(end+1):
        sc.frame_set(f);bpy.context.view_layer.update()
        root=arm.pose.bones['root'];world=arm.matrix_world@root.matrix
        if origin is None:origin=world.translation.copy()
        travel=world.translation-origin
        world.translation.x=origin.x;world.translation.y=origin.y
        root.matrix=arm.matrix_world.inverted()@world
        poses.append({b.name:b.matrix_basis.copy() for b in arm.pose.bones})
    speed=math.hypot(travel.x,travel.y)/(end/FPS)
    arm.animation_data_clear()
    for f,pose in enumerate(poses):
        for b in arm.pose.bones:
            b.matrix_basis=pose[b.name];b.rotation_mode='QUATERNION'
            for prop in ('location','rotation_quaternion','scale'):b.keyframe_insert(prop,frame=f)
    out=arm.animation_data.action;out.name='Fleet_run_in_place';out.use_fake_user=True
    linear_keys(out);arm.animation_data_clear()
    return out,speed


def key_transform(obj,frame,location=None,rotation=None,scale=None):
    if location is not None:obj.location=location;obj.keyframe_insert('location',frame=frame)
    if rotation is not None:obj.rotation_euler=rotation;obj.keyframe_insert('rotation_euler',frame=frame)
    if scale is not None:obj.scale=scale;obj.keyframe_insert('scale',frame=frame)


def turn_between(a,b,frame,start,end):
    u=max(0,min(1,(frame-start)/(end-start)))
    u=u*u*(3-2*u)
    return a+math.atan2(math.sin(b-a),math.cos(b-a))*u


def camera(name,position,target,lens=42):
    data=bpy.data.cameras.new(name);data.lens=lens;data.clip_end=700
    data.dof.use_dof=True;data.dof.focus_distance=(Vector(target)-Vector(position)).length
    data.dof.aperture_fstop=4.5 if name.startswith(('05b','06_')) else 7
    obj=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(obj)
    obj.location=position;aim(obj,target);return obj


def material_response():
    # These source materials have no roughness/metallic maps: preserve linked maps if supplied later.
    presets={'ghostship_cannons':(.34,.8),'ghostship_base':(.72,0),
             'kunkka2_tidebringer':(.28,.85),'pudge2_chopper':(.34,.8),'pudge2_hook':(.4,.72),
             'kunkka2_hair':(.82,0),'pudge2_hair':(.85,0),'pudge2_apron':(.8,0),
             'kunkka2_body':(.72,0),'kunkka2_boots':(.6,0),'kunkka2_hands':(.55,0),
             'pudge2_body':(.52,0),'pudge2_armleft':(.52,0)}
    for name,(roughness,metallic) in presets.items():
        mat=bpy.data.materials.get(name)
        if not mat or not mat.use_nodes:continue
        b=mat.node_tree.nodes.get('Principled BSDF')
        if not b:continue
        for key,value in (('Roughness',roughness),('Metallic',metallic)):
            if not b.inputs[key].is_linked:b.inputs[key].default_value=value


def grounded_fall(actor, scene):
    """Authored landing correction: torso/neck support, relaxed arms and soft belly contact.

    The unmodified game death sinks head and belly through the floor. Correct
    the pose, retaining feet and attached weapons; never hide the geometry.
    """
    from contact_reaction import _action, _basis
    from mathutils import Quaternion
    arm=actor['arm'];root=actor['root']
    bones=list(arm.pose.bones)
    fall_start=429
    smooth=lambda v:(lambda u:u*u*(3-2*u))(max(0,min(1,v)))
    for f in range(COUNT):
        root.location.z=.03+.46*smooth((f-450)/30);root.keyframe_insert('location',frame=f)
    linear_keys(root.animation_data.action)
    sampled={}
    for f in range(fall_start,COUNT):
        scene.frame_set(f);ev=arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
        sampled[f]=(ev.matrix_world.copy(),{b.name:b.matrix_basis.copy() for b in ev.pose.bones})
    frames=[]
    for f in range(fall_start,COUNT):
        mw,source=sampled[f];inverse=mw.inverted()
        if f>=480:
            # The native post-impact jiggle re-enters the ground. Settle between
            # two whole-body poses instead of replaying that incompatible tail.
            u=smooth((f-480)/23);source={}
            for bone in bones:
                la,qa,sa=sampled[480][1][bone.name].decompose()
                lb,qb,sb=sampled[COUNT-1][1][bone.name].decompose()
                source[bone.name]=Matrix.LocRotScale(la.lerp(lb,u),qa.slerp(qb,u),sa.lerp(sb,u))
        desired={};local={}
        for bone in bones:
            kwargs={}
            if bone.parent:kwargs=dict(parent_matrix=local[bone.parent.name],parent_matrix_local=bone.parent.bone.matrix_local)
            local[bone.name]=bone.bone.convert_local_to_pose(source[bone.name],bone.bone.matrix_local,**kwargs)
            desired[bone.name]=mw@local[bone.name]
        weight=smooth((f-450)/30);contact=smooth((f-470)/15)
        for name,degrees in (('spine1',-20),('neck1',-10),('bicep_R',7.2),('bicep_L',-7.5)):
            pivot=desired[name].translation.copy()
            transform=Matrix.Translation(pivot)@Quaternion(Vector((1,0,0)),math.radians(degrees)*weight).to_matrix().to_4x4()@Matrix.Translation(-pivot)
            for child in (arm.pose.bones[name],*arm.pose.bones[name].children_recursive):desired[child.name]=transform@desired[child.name]
        for name,lift in (('stomach1_0',2.2),('booby_lf',1.4),('booby_rt',1.4)):
            for child in (arm.pose.bones[name],*arm.pose.bones[name].children_recursive):desired[child.name].translation.z+=lift*contact
        basis={}
        for bone in bones:
            parent=inverse@desired[bone.parent.name] if bone.parent else None
            basis[bone.name]=_basis(bone,inverse@desired[bone.name],parent)
        frames.append(dict(frame=f,basis=basis))
    action=_action(arm,bones,frames,'Fleet_grounded_fall',scene)
    ad=arm.animation_data_create();track=ad.nla_tracks.new();track.name='Grounded fall pose'
    s=track.strips.new(action.name,fall_start,action);s.action_slot=action.slots[0]
    s.action_frame_start=fall_start;s.action_frame_end=COUNT-1;s.frame_start=fall_start;s.frame_end=COUNT-1
    s.blend_type='REPLACE';s.blend_in=0;s.blend_out=0;s.extrapolation='HOLD_FORWARD'
    # Ground contact constrains placement after the complete pose is resolved.
    meshes=[o for o in actor['objects'] if o.type=='MESH' and 'hitbox' not in o.name and not any(p in o.name for p in ('leftweapon_model','righthook_model'))]
    needed=[]
    for f in range(fall_start,COUNT):
        scene.frame_set(f);deps=bpy.context.evaluated_depsgraph_get();low=math.inf
        for obj in meshes:
            ev=obj.evaluated_get(deps);mesh=ev.to_mesh()
            low=min(low,min((ev.matrix_world@v.co).z for v in mesh.vertices));ev.to_mesh_clear()
        needed.append(max(0,.025-low) if low<.025 else 0)
    # A three-frame support envelope avoids popping between changing contact vertices.
    support=[max(needed[max(0,i-1):min(len(needed),i+2)]) for i in range(len(needed))]
    for i,f in enumerate(range(fall_start,COUNT)):
        root.location.z=.03+.46*smooth((f-450)/30)+support[i];root.keyframe_insert('location',frame=f)
    linear_keys(root.animation_data.action)
    dump('fall_support.json',dict(frames=list(range(fall_start,COUNT)),additional_height=support,
         scope='Whole-pose floor support. Must also be visually checked for floating and changes in fall speed.'))


def release_weapons(actor,scene):
    """The first ram breaks the grip; weapons land separately rather than lifting the corpse."""
    import numpy as np
    from mathutils import Quaternion
    scene.frame_set(429);deps=bpy.context.evaluated_depsgraph_get();contacts=[]
    for part,sign in (('righthook_model',-1),('leftweapon_model',1)):
        source=next(o for o in actor['objects'] if o.type=='MESH' and part in o.name)
        ev=source.evaluated_get(deps);mesh=bpy.data.meshes.new_from_object(ev,depsgraph=deps)
        points=[ev.matrix_world@v.co for v in mesh.vertices];center=sum(points,Vector())/len(points)
        mesh.transform(Matrix.Translation(-center)@ev.matrix_world)
        points=[v.co.copy() for v in mesh.vertices]
        _,axes=np.linalg.eigh(np.cov(np.array([tuple(p) for p in points]),rowvar=False))
        normal=Vector(axes[:,0]);normal=normal if normal.z>=0 else -normal
        end_rotation=normal.rotation_difference(Vector((0,0,1)))
        obj=bpy.data.objects.new('Dropped_'+part,mesh);scene.collection.objects.link(obj);obj.rotation_mode='QUATERNION'
        for f,hidden in ((0,False),(428,False),(429,True),(COUNT-1,True)):
            source.hide_render=hidden;source.keyframe_insert('hide_render',frame=f)
        for f,hidden in ((0,True),(428,True),(429,False),(COUNT-1,False)):
            obj.hide_render=hidden;obj.keyframe_insert('hide_render',frame=f)
        contact=None
        for f in range(429,COUNT):
            t=(f-429)/FPS;u=min(1,t/1.15);u=u*u*(3-2*u)
            q=Quaternion().slerp(end_rotation,u)
            low=min((q@p).z for p in points)
            travel=.9*(1-math.exp(-t/.9))
            position=center+Vector((sign*4*travel,4*travel,t-4.9*t*t))
            if position.z<.025-low:
                position.z=.025-low
                if contact is None:contact=f
            obj.location=position;obj.rotation_quaternion=q
            obj.keyframe_insert('location',frame=f);obj.keyframe_insert('rotation_quaternion',frame=f)
        linear_keys(obj.animation_data.action)
        contacts.append(dict(object=obj.name,release=429,ground_contact=contact))
    dump('weapon_drops.json',contacts)


def build():
    library=OUT if (OUT/'assets.blend').is_file() else BASE
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(library/'assets.blend'),use_scripts=False)
    bpy.context.preferences.filepaths.save_version=0
    sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.render.fps=FPS
    sc.frame_start=0;sc.frame_end=COUNT-1
    sc.render.resolution_x=1080;sc.render.resolution_y=1920;sc.render.resolution_percentage=100
    sc.eevee.taa_render_samples=48;sc.render.film_transparent=False
    sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGB'
    sc.view_settings.view_transform='AgX'
    sc.view_settings.look='AgX - Medium High Contrast'
    sc.render.use_motion_blur=True;sc.render.motion_blur_shutter=.2
    report=json.loads((library/'assets.json').read_text())
    from workshop_materials import apply_verified
    textures=apply_verified(ROOT/'_game/models/workshop',['kunkka2','pudge2'])
    material_response()
    # Geometry is linked between troops; every skeleton, constraint and action strip is independent.
    actors=[clone_actor(report['kunkka'],f'Captain{i:02d}') for i in range(14)]
    giant=clone_actor(report['pudge'],'Giant')
    # The source split head contains three neck-boundary vertices weighted only
    # to head, while the coincident torso uses spine/neck. Restore the junction.
    from skin_seams import match_skin_seam
    head=next(o for o in giant['objects'] if o.type=='MESH' and o.name.endswith('.head'))
    body=next(o for o in giant['objects'] if o.type=='MESH' and o.name.endswith('.upper_body'))
    neck_seam=match_skin_seam(head,body)
    native=lambda who,name:bpy.data.actions[report[who]['actions'][name]['name']]
    run,speed=inplace_run(bpy.data.objects[report['kunkka']['arm']],native('kunkka','run'))
    boats=[];boat_offsets=BOAT_OFFSETS
    for i,(x,dy) in enumerate(boat_offsets):
        root=bpy.data.objects.new(f'FleetShip{i:02d}',None);sc.collection.objects.link(root)
        mapping=clone_objects(report['ship']['objects'],f'Ship{i:02d}')
        for obj in mapping.values():
            if obj.parent is None:obj.parent=root
        root.scale=(1.4,)*3
        for f in range(COUNT):
            position,rotation=boat_pose(i,f)
            key_transform(root,f,position,rotation)
        linear_keys(root.animation_data.action);boats.append(root)
    ashore={4:(-3.55,8.4),5:(3.5,7.4),2:(-6.88,10.7),3:(-8,4),6:(7.72,8.62),7:(7,3)}
    routes={}
    departures={4:161,5:170,2:174,3:181,6:168,7:177}
    arrivals={4:236,5:244,2:250,3:254,6:241,7:255}
    retreats={4:282,6:287,2:292,5:296,3:289,7:294}
    for i,A in enumerate(actors):
        root=A['root'];root.scale=(.62,)*3
        strip(A,native('kunkka','idle'),0,COUNT,blend=0,repeat=True,phase=(i*3)%25)
        boat=i//2;x,dy=boat_offsets[boat];localx=(-.9 if i%2==0 else .9)
        deck_y=1.2 if i%2==0 else .15;deck_z=2.02 if i%2==0 else 1.75
        jump=departures.get(i,165);land=jump+21;arrive=arrivals.get(i,239)
        retreat_start=retreats.get(i,285);retreat_end=retreat_start+40
        # Mount passengers on the actual rolling deck, including pitch/roll.
        deck=Vector((-localx/1.4,-deck_y/1.4,(deck_z+.55)/1.4))
        start=deck_point(boat,jump,deck)
        landing=Vector((x+localx,-4.9,0.04))
        finish=Vector((*ashore.get(i,(x,4)),.04))
        if i in ashore:
            strip(A,native('kunkka','flail'),jump,land+2,blend=3)
            running=strip(A,run,land,arrive,blend=4,repeat=True)
            distance=(finish-landing).length
            length=arrive-land
            running.scale=(speed*.62)/(distance/(length/FPS));running.repeat=(length/(22*running.scale))
            running.frame_start=land;running.frame_end=arrive
            if i in (2,4,6):
                t={4:246,6:252,2:258}[i];strip(A,native('kunkka','attack1'),t,t+38,blend=5)
            retreat_run=strip(A,run,retreat_start,retreat_end,blend=5,repeat=True)
            retreat_run.scale=(speed*.62)/(math.sqrt(20)/(40/FPS))
            retreat_run.repeat=40/(22*retreat_run.scale)
            retreat_run.frame_start=retreat_start;retreat_run.frame_end=retreat_end
            # One commander signals. Others cover him instead of copying the same pose.
            if i==4:strip(A,native('kunkka','ghostship'),347,386,blend=5)
            routes[str(i)]=dict(start=list(start),landing=list(landing),fight=list(finish),
                               departure=jump,landing_frame=land,arrival=arrive,run_speed=distance/(length/FPS))
        previous_yaw=math.pi
        for f in range(COUNT):
            if f<jump or i not in ashore:
                pos=deck_point(boat,f,deck)
                yaw=math.pi
            elif f<land:
                u=(f-jump)/21;pos=start.lerp(landing,u);pos.z+=1.15*math.sin(math.pi*u);yaw=math.pi
            elif f<arrive:
                u=(f-land)/(arrive-land);pos=landing.lerp(finish,u);direction=finish-landing
                run_yaw=math.atan2(direction.x,-direction.y)
                yaw=turn_between(math.pi,run_yaw,f,land-3,land+7)
                look=Vector((-3.55 if i==4 else 0,12,0))-finish
                yaw=turn_between(yaw,math.atan2(look.x,-look.y),f,arrive-7,arrive)
            else:
                pos=finish.copy();direction=Vector((-3.55 if i==4 else 0,12,0))-pos;yaw=math.atan2(direction.x,-direction.y)
                # Withdraw from the giant's counterattack, then cast from clear flanks.
                if i in ashore and f>=retreat_start-7:
                    sign=-1 if pos.x<0 else 1
                    away=math.atan2(sign*4,2)
                    yaw=turn_between(yaw,away,f,retreat_start-7,retreat_start+5)
                if f>=retreat_start:
                    retreat=min(1,(f-retreat_start)/40);sign=-1 if pos.x<0 else 1;pos.x+=sign*retreat*4
                    pos.y-=retreat*2
                    if f>=retreat_end:
                        direction=Vector((0,12,0))-pos;yaw=math.atan2(direction.x,-direction.y)
                        yaw=turn_between(away,yaw,f,retreat_end,retreat_end+15)
            # Euler wrapping must not introduce a full revolution between adjacent keys.
            yaw=previous_yaw+math.atan2(math.sin(yaw-previous_yaw),math.cos(yaw-previous_yaw))
            previous_yaw=yaw
            key_transform(root,f,pos,(0,0,yaw))
        linear_keys(root.animation_data.action)
    giant['root'].location=(0,12,.03);giant['root'].scale=(2.8,)*3
    strip(giant,native('pudge','pudge_idle'),0,COUNT,blend=0,repeat=True)
    strip(giant,native('pudge','pudge_meathook_start'),108,159,blend=7)
    hurt=strip(giant,native('pudge','pudge_stun'),264,295,blend=5)
    hurt.action_frame_end=20;hurt.scale=31/20;hurt.frame_start=264;hurt.frame_end=295
    # A full game stun rolls the head too far for this close-up. A brief,
    # eased recoil preserves the neck surface and the response to a small hit.
    hurt.use_animated_influence=True
    for frame,weight in ((264,0),(270,.4),(279,.4),(295,0)):
        hurt.influence=weight;hurt.keyframe_insert('influence',frame=frame)
    for curve in hurt.fcurves:
        if curve.data_path=='influence':
            for key in curve.keyframe_points:
                key.interpolation='BEZIER';key.handle_left_type='AUTO_CLAMPED';key.handle_right_type='AUTO_CLAMPED'
    slam=strip(giant,native('pudge','pudge_attack1'),290,353,blend=6)
    slam.use_animated_time=True
    # The game swing crosses the ground at source phase 14.93. Pose to pose:
    # raise, accelerate into contact, resist briefly, lift and recover; no underground arc.
    for frame,phase in ((290,0),(299,8),(309,14),(315,14.7),(320,14.925),(324,14.925),(337,14.3),(345,8),(353,0)):
        slam.strip_time=phase;slam.keyframe_insert('strip_time',frame=frame)
    for fc in slam.fcurves:
        for k in fc.keyframe_points:k.interpolation='LINEAR'
    # Impact flows directly into a losing-balance pose; never blend through idle or flail.
    death=strip(giant,native('pudge','pudge_death'),429,520,blend=3)
    death.action_frame_start=12;death.scale=91/(54-12);death.frame_start=429;death.frame_end=520
    death.blend_out=0;death.extrapolation='HOLD_FORWARD'
    death.use_animated_time=True
    for frame,phase in ((429,12),(440,17),(449,22),(458,24),(469,26),(480,28),(487,30),(498,36),(520,54)):
        death.strip_time=phase;death.keyframe_insert('strip_time',frame=frame)
    for fc in death.fcurves:
        for k in fc.keyframe_points:k.interpolation='LINEAR'
    from look_motion import apply_looks
    attention=apply_looks(dict(frames=COUNT,fps=FPS,looks=[
        dict(who='giant',start=0,end=264/FPS,yaw_deg=0,pitch_deg=-15,attack=.5,release=.3),
        dict(who='giant',start=353/FPS,end=425/FPS,yaw_deg=0,pitch_deg=-12,attack=.4,release=.3),
    ]),{'giant':giant},sc,FPS)
    release_weapons(giant,sc)
    grounded_fall(giant,sc)
    ghost_ships=[]
    for i,x in enumerate((-4.5,4.5,0)):
        root=bpy.data.objects.new(f'Barrage{i}',None);sc.collection.objects.link(root)
        mapping=clone_objects(report['ship']['objects'],f'Ghost{i}')
        for obj in mapping.values():
            if obj.parent is None:obj.parent=root
            if obj.type=='MESH':
                obj.data=obj.data.copy()
                for slot in obj.material_slots:
                    if not slot.material:continue
                    slot.material=slot.material.copy();nt=slot.material.node_tree;b=nt.nodes.get('Principled BSDF')
                    if not b:continue
                    source=b.inputs['Base Color'].links[0].from_socket if b.inputs['Base Color'].links else None
                    mix=nt.nodes.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[2].default_value=(.16,.7,.85,1)
                    if source:
                        mono=nt.nodes.new('ShaderNodeRGBToBW');nt.links.new(source,mono.inputs[0]);nt.links.new(mono.outputs[0],mix.inputs[1])
                    mix.inputs[2].default_value=(.035,.25,.38,1)
                    nt.links.new(mix.outputs[0],b.inputs['Base Color'])
                    b.inputs['Emission Color'].default_value=(.06,.60,1,1)
                    edge=nt.nodes.new('ShaderNodeLayerWeight');edge.inputs['Blend'].default_value=.35
                    emission=nt.nodes.new('ShaderNodeMath');emission.operation='MULTIPLY_ADD'
                    emission.inputs[1].default_value=1.5;emission.inputs[2].default_value=.25
                    nt.links.new(edge.outputs['Fresnel'],emission.inputs[0]);nt.links.new(emission.outputs[0],b.inputs['Emission Strength'])
                    visibility=nt.nodes.new('ShaderNodeValue');visibility.name='Impact dissolve'
                    for frame,value in ((0,0),(385+i*14,0),(393+i*14,1),(429+i*14,1),(440+i*14,0),(539,0)):
                        visibility.outputs[0].default_value=value;visibility.outputs[0].keyframe_insert('default_value',frame=frame)
                    alpha=b.inputs['Alpha'].links[0].from_socket if b.inputs['Alpha'].links else None
                    multiply=nt.nodes.new('ShaderNodeMath');multiply.operation='MULTIPLY'
                    multiply.inputs[0].default_value=b.inputs['Alpha'].default_value
                    if alpha:nt.links.new(alpha,multiply.inputs[0])
                    opacity=nt.nodes.new('ShaderNodeMath');opacity.operation='MULTIPLY_ADD'
                    opacity.inputs[1].default_value=.30;opacity.inputs[2].default_value=.58
                    nt.links.new(edge.outputs['Fresnel'],opacity.inputs[0])
                    final=nt.nodes.new('ShaderNodeMath');final.operation='MULTIPLY'
                    nt.links.new(visibility.outputs[0],multiply.inputs[1]);nt.links.new(multiply.outputs[0],final.inputs[0]);nt.links.new(opacity.outputs[0],final.inputs[1]);nt.links.new(final.outputs[0],b.inputs['Alpha'])
        for f in range(COUNT):
            t=f-(385+i*14);u=max(0,min(44/50,t/50))
            # Keep physical size at impact: fade magic away, never shrink a ship into a toy.
            key_transform(root,f,(x,-38+u*48,-1.3),(0,0,math.pi),(2,)*3)
        linear_keys(root.animation_data.action);ghost_ships.append(root)
    cams=[]
    c=camera('01_Fleet_leader',(7,-37,11),(0,-56,3),38)
    for f in (0,60):
        y=boat_pose(2,f)[0][1];c.location=(5,y+10,13);aim(c,(0,y+.6,3));c.keyframe_insert('location',frame=f);c.keyframe_insert('rotation_euler',frame=f)
    linear_keys(c.animation_data.action);cams.append((0,c))
    cams.append((60,camera('02_Fleet_and_giant',(29,-49,19),(0,-13,3.5),28)))
    cams.append((105,camera('03_Giant_threat',(8,-7,2.6),(0,12,5.2),34)))
    cams.append((165,camera('04_Landing',(7,-.5,4.8),(-.9,-6,1.7),32)))
    cams.append((205,camera('04b_Charge',(-10,-5,3),(0,9,3.5),28)))
    cams.append((240,camera('05_Leg_strike',(1,4,3.4),(-3.1,10.1,2.3),30)))
    cams.append((267,camera('05b_Hit_reaction',(8,5,13),(.5,11.8,9.5),40)))
    cams.append((290,camera('05c_Counterattack',(-13,-6,4.2),(1.5,7,3.2),24)))
    cams.append((345,camera('06_Command',(-3,0,2.5),(-7.55,6.4,2.1),44)))
    c=camera('07_Ghost_leader',(-12,-28,8),(-4.5,-38,2.2),32)
    for f in (390,426):
        y=-38+min(44/50,(f-385)/50)*48
        c.location=(-12,y+10,8);aim(c,(-4.5,y,2.2));c.keyframe_insert('location',frame=f);c.keyframe_insert('rotation_euler',frame=f)
    linear_keys(c.animation_data.action);cams.append((390,c))
    cams.append((426,camera('07b_Impact',(-17,-1,5),(1,10,5),27)))
    cams.append((453,camera('08_Fall',(-18,-8,6),(0,5.5,3),27)))
    cams.append((496,camera('09_Aftermath',(15,-6,8),(0,7,2),28)))
    sc.timeline_markers.clear()
    for f,c in cams:sc.timeline_markers.new(c.name,frame=f).camera=c
    sc.camera=cams[0][1]
    from fleet_coast import environment as coast_environment
    coast_environment()
    effects(boats)
    # Existing, verified Blender 5 compositor: emission-only local bloom.
    from doomsday_atmosphere import glow
    glow(sc)
    sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
    dump('staging.json',dict(count=COUNT,fps=FPS,resolution=[1080,1920],troops=14,ships=7,giant_scale=2.8,native_run_speed=speed,routes=routes,
         cameras=[dict(frame=f,name=c.name) for f,c in cams],textures=textures,attention=attention,neck_seam=neck_seam,
         actors=[dict(root=A['root'].name,arm=A['arm'].name) for A in actors],giant=dict(root=giant['root'].name,arm=giant['arm'].name)))
    print('BATTLE_BUILT')


def effects(boats):
    """Event-linked wakes, landing dust and impact spray; no whole-screen flash."""
    sc=bpy.context.scene;rng=random.Random(914)
    foam=surface('Broken sea foam',(.62,.82,.88),.6)
    nt=foam.node_tree;b=nt.nodes['Principled BSDF'];noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=7;noise.inputs['Detail'].default_value=3
    ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.43;ramp.color_ramp.elements[1].position=.65
    coord=nt.nodes.new('ShaderNodeTexCoord');nt.links.new(coord.outputs['Object'],noise.inputs[0]);nt.links.new(noise.outputs['Fac'],ramp.inputs[0])
    feather=nt.nodes.new('ShaderNodeAttribute');feather.attribute_name='wake_feather'
    mul=nt.nodes.new('ShaderNodeMath');mul.operation='MULTIPLY'
    nt.links.new(ramp.outputs[0],mul.inputs[0]);nt.links.new(feather.outputs['Fac'],mul.inputs[1])
    strength=nt.nodes.new('ShaderNodeValue')
    for f,v in ((0,.75),(105,.75),(155,.25),(195,0),(539,0)):
        strength.outputs[0].default_value=v;strength.outputs[0].keyframe_insert('default_value',frame=f)
    opacity=nt.nodes.new('ShaderNodeMath');opacity.operation='MULTIPLY'
    nt.links.new(mul.outputs[0],opacity.inputs[0]);nt.links.new(strength.outputs[0],opacity.inputs[1]);nt.links.new(opacity.outputs[0],b.inputs['Alpha'])
    for boat_index,boat in enumerate(boats):
        for sign in (-1,1):
            verts=[];faces=[];feathers=[]
            for j in range(29):
                v=j/28;y=2+v*13;x=sign*(1.5+v*2.7)
                for k in range(7):
                    u=k/6;verts.append((x+(u-.5)*(.45+v*1.7),y,.025*math.sin(y*.6)))
                    feathers.append(math.sin(math.pi*u)**1.5*min(1,v*8)*(1-v)**1.3)
                    if j and k:
                        a=j*7+k;faces.append((a-8,a-7,a,a-1))
            mesh=bpy.data.meshes.new('Foam ribbon');mesh.from_pydata(verts,[],faces)
            mesh.attributes.new('wake_feather','FLOAT','POINT').data.foreach_set('value',feathers)
            o=bpy.data.objects.new('Ship wake',mesh);sc.collection.objects.link(o);o.data.materials.append(foam)
            # Wake stays on water; attaching it to a rolling deck makes the surface levitate.
            for f in range(196):
                p,_=boat_pose(boat_index,f);key_transform(o,f,(p[0],p[1],-.635),(0,0,math.pi),(1.4,1.4,1))
            linear_keys(o.animation_data.action)
    spray=surface('Sea spray',(.48,.82,.93),.3)
    dust=surface('Impact stone',(.20,.16,.10),.8)
    spark=surface('Steel contact',(1,.40,.045),.4);b=spark.node_tree.nodes['Principled BSDF'];b.inputs['Emission Color'].default_value=(1,.2,.015,1);b.inputs['Emission Strength'].default_value=5
    # Coordinates are revised with the contact probes, not inferred from a sound cue.
    events=[(182,(-.9,-4.9,.15),dust,6,1),(259,(-2.44,10.99,2.42),spark,10,1.5),
            (274,(4.7,9.8,.3),spark,10,1.5),(320,(3.59,2.57,.1),dust,10,3),
            (429,(-2,9,1.3),spray,60,7),(443,(3,9,1.6),spray,60,7),
            (483,(0,2,.2),dust,16,4)]
    for event,(start,origin,material,count,force) in enumerate(events):
        for i in range(count):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=1)
            obj=bpy.context.object;obj.name=f'Impact_{event}_{i}';obj.data.materials.append(material)
            velocity=Vector((rng.uniform(-1,1),rng.uniform(-1,1),rng.uniform(.5,1.4)))*force
            lifetime=rng.randint(15,33);radius=rng.uniform(.025,.065)
            for frame in sorted({0,start-1,*range(start,start+lifetime+1),COUNT-1}):
                age=max(0,min(lifetime,frame-start))/FPS
                pos=Vector(origin)+velocity*age+Vector((0,0,-4.9*age*age))
                # Actual ballistic arcs; keep strength until the end instead of shrinking all flight.
                fade=max(0,min(1,(start+lifetime-frame)/5))
                scale=radius*fade if start<=frame<start+lifetime else .00001
                key_transform(obj,frame,pos,None,(scale,scale,scale*(2.6 if material==spray else 1)))
            linear_keys(obj.animation_data.action)
    dump('events.json',dict(fps=FPS,events=[dict(frame=f,name='landing' if n==0 else 'sword' if n in (1,2) else 'giant_swing' if n==3 else 'ship_impact' if n in (4,5) else 'giant_fall',position=list(p)) for n,(f,p,*_) in enumerate(events)]))
    # Low dust rolling out from the actual ground hit, not a cloud of floating stones.
    for start,origin,size in ((182,(-.9,-4.9,.05),.6),(320,(3.59,2.57,.1),1.8),(483,(0,2,.1),2.7)):
        for i in range(4):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1)
            o=bpy.context.object;o.name=f'Ground powder {start}-{i}'
            m=bpy.data.materials.new(o.name);m.use_nodes=True;nt=m.node_tree;nt.nodes.clear()
            out=nt.nodes.new('ShaderNodeOutputMaterial');vol=nt.nodes.new('ShaderNodeVolumePrincipled')
            vol.inputs['Color'].default_value=(.26,.23,.18,1)
            tex=nt.nodes.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=3.5
            density=nt.nodes.new('ShaderNodeMath');density.operation='MULTIPLY'
            nt.links.new(tex.outputs['Fac'],density.inputs[0]);nt.links.new(density.outputs[0],vol.inputs['Density']);nt.links.new(vol.outputs[0],out.inputs['Volume'])
            o.data.materials.append(m);direction=Vector((math.cos(i*math.pi/2),math.sin(i*math.pi/2),.08))
            for f,scale,alpha,offset in ((0,.0001,0,0),(start-1,.0001,0,0),(start+3,.3,.6,.3),(start+17,1,.3,1),(start+38,1.3,0,1.7),(539,1.3,0,1.7)):
                key_transform(o,f,Vector(origin)+direction*offset*size,None,(size*scale,size*scale,.32*size*scale))
                density.inputs[1].default_value=alpha;density.inputs[1].keyframe_insert('default_value',frame=f)
            linear_keys(o.animation_data.action)


def preview():
    import shutil
    if shutil.disk_usage(OUT).free<150_000_000:
        raise RuntimeError('Need 150 MB reserve before the 13-still probe (under 20 MB output)')
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False)
    sc=bpy.context.scene;sc.render.resolution_percentage=40;sc.eevee.taa_render_samples=16;sc.render.use_motion_blur=False
    from study_head_target import gpu_guard
    gpu_guard()
    (OUT/'probes').mkdir(exist_ok=True)
    for frame in (20,80,126,177,214,259,270,300,322,368,420,449,487,525):
        sc.frame_set(frame);sc.render.filepath=str(OUT/'probes'/f'frame_{frame:04d}.png');bpy.ops.render.render(write_still=True)


def render(percent=100, frame_range=None):
    """Color-managed PNG stream, one temporary frame; preserves frame-rate and no upscaling."""
    import shutil
    if frame_range is not None:
        if percent == 100 or len(frame_range) != 2 or not 0 <= frame_range[0] <= frame_range[1] < COUNT:
            raise ValueError('A motion patch needs two inclusive frame bounds within the scene')
    if percent==100:
        review_path=OUT/'quality_review.json'
        if not review_path.is_file():
            raise RuntimeError('Full render blocked: review the entire motion.mp4 and save quality_review.json first')
        review=json.loads(review_path.read_text(encoding='utf-8'))
        expected={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ('scene.blend','motion.mp4')}
        if review.get('status')!='ready' or review.get('blockers')!=[] or review.get('sha256')!=expected or not review.get('observations'):
            raise RuntimeError('Full render blocked: unresolved, missing or stale artistic review; technical checks alone cannot pass this gate')
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False)
    sc=bpy.context.scene
    sc.render.resolution_percentage=percent
    if percent<100:
        sc.eevee.taa_render_samples=12;sc.render.use_motion_blur=False
    from study_head_target import gpu_guard
    gpu_guard()
    if shutil.disk_usage(OUT).free<250_000_000:raise RuntimeError('Need 250 MB for final movie and QA stills')
    runtime=OUT/'runtime.json'
    ffmpeg=os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    if not runtime.is_file():runtime=BASE/'runtime.json'
    if not ffmpeg and runtime.is_file():ffmpeg=json.loads(runtime.read_text())['ffmpeg']
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise RuntimeError('Set FFMPEG to an installed executable, or configure local runtime.json')
    label='motion' if percent<100 else 'fleet_battle_silent'
    if frame_range is not None:label+=f'_{frame_range[0]:04d}_{frame_range[1]:04d}'
    output=OUT/(label+'.mp4');log=(OUT/(label+'_encode.log')).open('wb')
    proc=subprocess.Popen([ffmpeg,'-y','-v','error','-f','image2pipe','-framerate',str(FPS),'-vcodec','png','-i','-',
         '-an','-c:v','libx264','-crf','18','-preset','medium','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],stdin=subprocess.PIPE,stderr=log)
    qa=OUT/('motion_qa' if percent<100 else 'qa_frames');qa.mkdir(exist_ok=True);temp=OUT/'frame_current.png'
    try:
        for frame in (range(frame_range[0],frame_range[1]+1) if frame_range is not None else range(COUNT)):
            sc.frame_set(frame);bpy.ops.render.render()
            bpy.data.images['Render Result'].save_render(str(temp),scene=sc)
            proc.stdin.write(temp.read_bytes())
            cuts={m.frame for m in sc.timeline_markers if m.camera}
            if frame%15==0 or frame in cuts or frame+1 in cuts or frame==COUNT-1 or (percent<100 and 240<=frame<=353 and frame%3==0):
                sc.render.image_settings.file_format='JPEG';sc.render.image_settings.quality=94
                bpy.data.images['Render Result'].save_render(str(qa/f'frame_{frame:04d}.jpg'),scene=sc)
                sc.render.image_settings.file_format='PNG'
            print('FINAL_FRAME',frame,flush=True)
        proc.stdin.close()
        if proc.wait()!=0:raise RuntimeError('FFmpeg encoding failed; see encode.log')
    except BaseException:
        proc.kill();proc.wait();raise
    finally:log.close()
    temp.unlink(missing_ok=True)
    print('FINAL_RENDER_COMPLETE',output,flush=True)


if __name__=='__main__':
    mode=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'assets'
    if mode=='assets':assets()
    elif mode=='build':build()
    elif mode=='probe':preview()
    elif mode=='render':render()
    elif mode=='motion':
        bounds=sys.argv[sys.argv.index('--')+2:]
        render(30,tuple(map(int,bounds)) if bounds else None)
    else:raise ValueError(mode)
