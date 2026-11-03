"""Fleet of Kunkkas against a giant Pudge. All sources stay under _game.

Blender -b --factory-startup -P tools/blender/fleet_battle.py -- assets|build|probe|render
Final frames stream to FFmpeg to avoid a multi-gigabyte PNG intermediate.
"""
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys

import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/blender'))
from kunkka_ghostship import helpers, aim, light, surface, linear_keys

OUT=ROOT/'_game/skits/fleet_battle'
MODELS=ROOT/'_game/models/render'
FPS=30
COUNT=540


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
    obj=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(obj)
    obj.location=position;aim(obj,target);return obj


def build():
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'assets.blend'),use_scripts=False)
    bpy.context.preferences.filepaths.save_version=0
    sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.render.fps=FPS
    sc.frame_start=0;sc.frame_end=COUNT-1
    sc.render.resolution_x=1080;sc.render.resolution_y=1920;sc.render.resolution_percentage=100
    sc.eevee.taa_render_samples=48;sc.render.film_transparent=False
    sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGB'
    sc.view_settings.view_transform='AgX'
    report=json.loads((OUT/'assets.json').read_text())
    from workshop_materials import apply_verified
    textures=apply_verified(ROOT/'_game/models/workshop',['kunkka2','pudge2'])
    # Geometry is linked between troops; every skeleton, constraint and action strip is independent.
    actors=[clone_actor(report['kunkka'],f'Captain{i:02d}') for i in range(14)]
    giant=clone_actor(report['pudge'],'Giant')
    native=lambda who,name:bpy.data.actions[report[who]['actions'][name]['name']]
    run,speed=inplace_run(bpy.data.objects[report['kunkka']['arm']],native('kunkka','run'))
    boats=[];boat_offsets=[(-18,-9),(-9,-4),(0,0),(9,-4),(18,-9),(-27,-15),(27,-15)]
    for i,(x,dy) in enumerate(boat_offsets):
        root=bpy.data.objects.new(f'FleetShip{i:02d}',None);sc.collection.objects.link(root)
        mapping=clone_objects(report['ship']['objects'],f'Ship{i:02d}')
        for obj in mapping.values():
            if obj.parent is None:obj.parent=root
        root.scale=(1.4,)*3
        for f in range(COUNT):
            y=-58+min(f,150)*.30+dy
            key_transform(root,f,(x,y,-.55+.07*math.sin(f*.065+i)),(.012*math.sin(f*.05+i),.015*math.sin(f*.07+i),math.pi))
        linear_keys(root.animation_data.action);boats.append(root)
    ashore={4:(-2.47,8.66),5:(3.5,7.4),2:(-6.88,10.7),3:(-8,4),6:(7.72,8.62),7:(7,3)}
    routes={}
    for i,A in enumerate(actors):
        root=A['root'];root.scale=(.62,)*3
        strip(A,native('kunkka','idle'),0,COUNT,blend=0,repeat=True,phase=(i*3)%25)
        boat=i//2;x,dy=boat_offsets[boat];localx=(-.9 if i%2==0 else .9)
        deck_y=1.2 if i%2==0 else .15;deck_z=2.02 if i%2==0 else 1.75
        start=Vector((x+localx,-13+dy+deck_y,deck_z))
        landing=Vector((x+localx,-5.7,0.04))
        finish=Vector((*ashore.get(i,(x,4)),.04))
        if i in ashore:
            strip(A,native('kunkka','flail'),165,186,blend=3)
            running=strip(A,run,184,239,blend=4,repeat=True)
            distance=(finish-landing).length
            running.scale=(speed*.62)/(distance/(55/FPS));running.repeat=(55/(22*running.scale))
            running.frame_start=184;running.frame_end=239
            if i in (2,4,5,6):
                t=241+(i%3)*5;strip(A,native('kunkka','attack1'),t,t+38,blend=5)
            retreat_run=strip(A,run,285,326,blend=5,repeat=True)
            retreat_run.scale=(speed*.62)/(math.sqrt(20)/(40/FPS))
            retreat_run.repeat=41/(22*retreat_run.scale)
            retreat_run.frame_start=285;retreat_run.frame_end=326
            strip(A,native('kunkka','ghostship'),347+(i%3)*4,386+(i%3)*4,blend=5)
            routes[str(i)]=dict(start=list(start),landing=list(landing),fight=list(finish),run_speed=distance/(55/FPS))
        previous_yaw=math.pi
        for f in range(COUNT):
            if f<165 or i not in ashore:
                pos=Vector((x+localx,-58+min(f,150)*.3+dy+deck_y,deck_z+.07*math.sin(f*.065+boat)))
                yaw=math.pi
            elif f<184:
                u=(f-165)/19;pos=start.lerp(landing,u);pos.z+=1.45*math.sin(math.pi*u);yaw=math.pi
            elif f<239:
                u=(f-184)/55;pos=landing.lerp(finish,u);direction=finish-landing
                run_yaw=math.atan2(direction.x,-direction.y)
                yaw=turn_between(math.pi,run_yaw,f,181,191)
                look=Vector((0,12,0))-finish
                yaw=turn_between(yaw,math.atan2(look.x,-look.y),f,232,239)
            else:
                pos=finish.copy();direction=Vector((0,12,0))-pos;yaw=math.atan2(direction.x,-direction.y)
                # Withdraw from the giant's counterattack, then cast from clear flanks.
                if i in ashore and f>=278:
                    sign=-1 if pos.x<0 else 1
                    away=math.atan2(sign*4,2)
                    yaw=turn_between(yaw,away,f,278,292)
                if f>=285:
                    retreat=min(1,(f-285)/40);sign=-1 if pos.x<0 else 1;pos.x+=sign*retreat*4
                    pos.y-=retreat*2
                    if f>=326:
                        direction=Vector((0,12,0))-pos;yaw=math.atan2(direction.x,-direction.y)
                        yaw=turn_between(away,yaw,f,326,341)
            # Euler wrapping must not introduce a full revolution between adjacent keys.
            yaw=previous_yaw+math.atan2(math.sin(yaw-previous_yaw),math.cos(yaw-previous_yaw))
            previous_yaw=yaw
            key_transform(root,f,pos,(0,0,yaw))
        linear_keys(root.animation_data.action)
    giant['root'].location=(0,12,.03);giant['root'].scale=(2.8,)*3
    strip(giant,native('pudge','pudge_idle'),0,COUNT,blend=0,repeat=True)
    strip(giant,native('pudge','pudge_meathook_start'),108,159,blend=7)
    strip(giant,native('pudge','pudge_attack1'),290,338,blend=6)
    strip(giant,native('pudge','pudge_flail'),430,468,blend=5)
    death=strip(giant,native('pudge','pudge_death'),465,535,blend=5);death.blend_out=0;death.extrapolation='HOLD_FORWARD'
    ghost_ships=[]
    for i,x in enumerate((-3.5,3.5,0)):
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
                    nt.links.new(mix.outputs[0],b.inputs['Base Color']);nt.links.new(mix.outputs[0],b.inputs['Emission Color']);b.inputs['Emission Strength'].default_value=1.4
                    visibility=nt.nodes.new('ShaderNodeValue');visibility.name='Impact dissolve'
                    for frame,value in ((0,0),(385+i*7,0),(393+i*7,1),(429+i*7,1),(441+i*7,0),(539,0)):
                        visibility.outputs[0].default_value=value;visibility.outputs[0].keyframe_insert('default_value',frame=frame)
                    alpha=b.inputs['Alpha'].links[0].from_socket if b.inputs['Alpha'].links else None
                    multiply=nt.nodes.new('ShaderNodeMath');multiply.operation='MULTIPLY'
                    multiply.inputs[0].default_value=b.inputs['Alpha'].default_value
                    if alpha:nt.links.new(alpha,multiply.inputs[0])
                    nt.links.new(visibility.outputs[0],multiply.inputs[1]);nt.links.new(multiply.outputs[0],b.inputs['Alpha'])
        for f in range(COUNT):
            t=f-(385+i*7);u=max(0,min(44/50,t/50))
            # Keep physical size at impact: fade magic away, never shrink a ship into a toy.
            key_transform(root,f,(x,-38+u*48,-1.3),(0,0,math.pi),(2,)*3)
        linear_keys(root.animation_data.action);ghost_ships.append(root)
    cams=[]
    c=camera('01_Fleet_leader',(7,-37,11),(0,-56,3),38)
    for f in (0,60):
        y=-58+f*.30;c.location=(5,y+10,13);aim(c,(0,y+.6,3));c.keyframe_insert('location',frame=f);c.keyframe_insert('rotation_euler',frame=f)
    linear_keys(c.animation_data.action);cams.append((0,c))
    cams.append((60,camera('02_Fleet_and_giant',(40,-55,40),(0,-18,3),24)))
    cams.append((105,camera('03_Giant_threat',(15,-11,6),(0,12,6),43)))
    cams.append((165,camera('04_Landing',(24,-22,12),(-1,-4,2.5),28)))
    cams.append((240,camera('05_Battle',(-18,-6,6),(0,11,4.2),35)))
    cams.append((345,camera('06_Command',(0,-5,3),(-6.5,6.3,2.4),38)))
    cams.append((390,camera('07_Barrage',(25,-24,17),(0,6,5),38)))
    cams.append((465,camera('08_Fall',(-22,-10,8),(0,10,4),40)))
    cams.append((510,camera('09_Aftermath',(19,-14,10),(0,10,2.5),40)))
    sc.timeline_markers.clear()
    for f,c in cams:sc.timeline_markers.new(c.name,frame=f).camera=c
    sc.camera=cams[0][1]
    environment()
    effects(boats)
    # Existing, verified Blender 5 compositor: emission-only local bloom.
    from doomsday_atmosphere import glow
    glow(sc)
    sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
    dump('staging.json',dict(count=COUNT,fps=FPS,resolution=[1080,1920],troops=14,ships=7,giant_scale=2.8,native_run_speed=speed,routes=routes,
         cameras=[dict(frame=f,name=c.name) for f,c in cams],textures=textures,
         actors=[dict(root=A['root'].name,arm=A['arm'].name) for A in actors],giant=dict(root=giant['root'].name,arm=giant['arm'].name)))
    print('BATTLE_BUILT')


def environment():
    sc=bpy.context.scene;rng=random.Random(71)
    sea=surface('Deep moving sea',(.012,.045,.065),.24,.32)
    nt=sea.node_tree;b=nt.nodes['Principled BSDF']
    tex=nt.nodes.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=1.3;tex.inputs['Detail'].default_value=4
    coord=nt.nodes.new('ShaderNodeTexCoord');mapping=nt.nodes.new('ShaderNodeMapping')
    nt.links.new(coord.outputs['Object'],mapping.inputs[0]);nt.links.new(mapping.outputs[0],tex.inputs[0])
    for f,x in ((0,0),(COUNT-1,6)):
        mapping.inputs['Location'].default_value=(x,0,0);mapping.inputs['Location'].keyframe_insert('default_value',frame=f)
    bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.42;bump.inputs['Distance'].default_value=.16
    nt.links.new(tex.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs[0],b.inputs['Normal'])
    verts=[];faces=[];n=160
    for j in range(n+1):
        for i in range(n+1):
            x=-190+i*2.4;y=-250+j*2.4
            verts.append((x,y,-.7+.12*math.sin(x*.52+y*.19)+.08*math.sin(y*.7)))
    for j in range(n):
        for i in range(n):
            a=j*(n+1)+i;faces.append((a,a+1,a+n+2,a+n+1))
    mesh=bpy.data.meshes.new('Ocean');mesh.from_pydata(verts,[],faces);mesh.update()
    water=bpy.data.objects.new('Ocean',mesh);sc.collection.objects.link(water);water.data.materials.append(sea)
    for p in mesh.polygons:p.use_smooth=True
    beach=surface('Wet shore',(.11,.105,.075),.72)
    nt=beach.node_tree;b=nt.nodes['Principled BSDF'];tex=nt.nodes.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=3.2
    ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.045,.043,.03,1);ramp.color_ramp.elements[1].color=(.24,.21,.14,1)
    coord=nt.nodes.new('ShaderNodeTexCoord');nt.links.new(coord.outputs['Object'],tex.inputs[0]);nt.links.new(tex.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs[0],b.inputs['Base Color'])
    bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Distance'].default_value=.065;nt.links.new(tex.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs[0],b.inputs['Normal'])
    verts=[];faces=[];width=90;depth=85
    for j in range(depth+1):
        for i in range(width+1):
            x=-90+i*2;y=-8+j*1.8;z=-.65 if j==0 else 0 if j<20 else .03*(j-20)**1.35
            verts.append((x,y,z))
    for j in range(depth):
        for i in range(width):
            a=j*(width+1)+i;faces.append((a,a+1,a+width+2,a+width+1))
    mesh=bpy.data.meshes.new('Shore');mesh.from_pydata(verts,[],faces);mesh.update()
    shore=bpy.data.objects.new('Shore',mesh);sc.collection.objects.link(shore);shore.data.materials.append(beach)
    for p in mesh.polygons:p.use_smooth=True
    imp,fix=helpers();rocks,_=imp(str(MODELS/'models_props_rock_riveredge_rock_wall001a.glb'));fix(rocks)
    rock=next(o for o in rocks if o.type=='MESH');box=mesh_bounds([rock]);size=Vector(box['max'])-Vector(box['min']);mid=(Vector(box['max'])+Vector(box['min']))*.5
    rock.data.transform(rock.matrix_world);rock.parent=None;rock.matrix_world.identity()
    for v in rock.data.vertices:v.co-=mid
    rock.hide_render=True
    for i in range(24):
        obj=rock.copy();sc.collection.objects.link(obj);obj.hide_render=False;obj.name=f'Cliff{i}'
        obj.location=(-100+i*9,63+rng.uniform(-9,18),9)
        obj.scale=tuple(a/b for a,b in zip((rng.uniform(13,22),rng.uniform(10,20),rng.uniform(14,28)),size))
        obj.rotation_euler.z=rng.uniform(-.6,.6)
    world=bpy.data.worlds.new('Storm dusk');world.use_nodes=True;sc.world=world
    nt=world.node_tree;nt.nodes.clear();out=nt.nodes.new('ShaderNodeOutputWorld');bg=nt.nodes.new('ShaderNodeBackground');bg.inputs['Strength'].default_value=.32
    tex=nt.nodes.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=3.8;tex.inputs['Detail'].default_value=3
    coord=nt.nodes.new('ShaderNodeTexCoord');ramp=nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color=(.018,.035,.07,1);ramp.color_ramp.elements[1].color=(.28,.37,.46,1)
    nt.links.new(coord.outputs['Normal'],tex.inputs[0]);nt.links.new(tex.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs[0],bg.inputs[0]);nt.links.new(bg.outputs[0],out.inputs['Surface'])
    sun_data=bpy.data.lights.new('Low warm sun','SUN');sun_data.energy=2.7;sun_data.angle=.17;sun_data.color=(1,.73,.43)
    sun=bpy.data.objects.new('Low warm sun',sun_data);sc.collection.objects.link(sun);sun.rotation_euler=(.5,-.7,-.8)
    light('Coastal sky',(0,-15,35),16000,(.35,.65,1),35,(0,10,3))
    light('Battle rim',(-10,38,20),16000,(1,.42,.14),20,(0,12,5))
    light('Fleet fill',(0,-45,19),9000,(.4,.65,1),28,(0,-30,3))
    bpy.ops.mesh.primitive_cube_add(size=1,location=(0,68,15));mist=bpy.context.object;mist.name='Distant haze';mist.scale=(250,85,35)
    mat=bpy.data.materials.new('Horizon mist');mat.use_nodes=True;nt=mat.node_tree;nt.nodes.clear()
    v=nt.nodes.new('ShaderNodeVolumePrincipled');v.inputs['Density'].default_value=.016;v.inputs['Color'].default_value=(.38,.47,.58,1)
    out=nt.nodes.new('ShaderNodeOutputMaterial');nt.links.new(v.outputs[0],out.inputs['Volume']);mist.data.materials.append(mat)


def effects(boats):
    """Event-linked wakes, landing dust and impact spray; no whole-screen flash."""
    sc=bpy.context.scene;rng=random.Random(914)
    foam=surface('Broken sea foam',(.62,.82,.88),.6)
    nt=foam.node_tree;b=nt.nodes['Principled BSDF'];noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=7;noise.inputs['Detail'].default_value=3
    ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.43;ramp.color_ramp.elements[1].position=.65
    coord=nt.nodes.new('ShaderNodeTexCoord');nt.links.new(coord.outputs['Object'],noise.inputs[0]);nt.links.new(noise.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs[0],b.inputs['Alpha'])
    for boat in boats:
        for sign in (-1,1):
            verts=[];faces=[]
            for j in range(20):
                y=4+j*.7;x=sign*(1.35+j*.12)
                verts.extend([(x-.25,y,.05),(x+.25+j*.025,y,.05)])
                if j:faces.append((2*j-2,2*j-1,2*j+1,2*j))
            mesh=bpy.data.meshes.new('Foam ribbon');mesh.from_pydata(verts,[],faces)
            o=bpy.data.objects.new('Ship wake',mesh);sc.collection.objects.link(o);o.parent=boat;o.data.materials.append(foam)
    spray=surface('Sea spray',(.48,.82,.93),.3)
    dust=surface('Impact stone',(.20,.16,.10),.8)
    spark=surface('Steel contact',(1,.40,.045),.4);b=spark.node_tree.nodes['Principled BSDF'];b.inputs['Emission Color'].default_value=(1,.2,.015,1);b.inputs['Emission Strength'].default_value=5
    # Coordinates are revised with the contact probes, not inferred from a sound cue.
    events=[(184,(-.6,-5.8,.15),dust,20,2),(259,(.14,10.25,3.1),spark,14,1.5),
            (264,(2.8,10.18,2.61),spark,14,1.5),(320,(1,5,.2),dust,34,4),
            (429,(-2,9,1.3),spray,60,7),(443,(3,9,1.6),spray,60,7),
            (510,(0,10,.2),dust,70,7)]
    for event,(start,origin,material,count,force) in enumerate(events):
        for i in range(count):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=1)
            obj=bpy.context.object;obj.name=f'Impact_{event}_{i}';obj.data.materials.append(material)
            velocity=Vector((rng.uniform(-1,1),rng.uniform(-1,1),rng.uniform(.5,1.4)))*force
            lifetime=rng.randint(15,33);radius=rng.uniform(.035,.12)*(2 if material==dust else 1)
            for frame in sorted({0,start-1,*range(start,start+lifetime+1),COUNT-1}):
                age=max(0,min(lifetime,frame-start))/FPS
                pos=Vector(origin)+velocity*age+Vector((0,0,-4.9*age*age))
                # Actual ballistic arcs; keep strength until the end instead of shrinking all flight.
                fade=max(0,min(1,(start+lifetime-frame)/5))
                scale=radius*fade if start<=frame<start+lifetime else .00001
                key_transform(obj,frame,pos,None,(scale,scale,scale*(2.6 if material==spray else 1)))
            linear_keys(obj.animation_data.action)
    dump('events.json',dict(fps=FPS,events=[dict(frame=f,name='landing' if n==0 else 'sword' if n in (1,2) else 'giant_swing' if n==3 else 'ship_impact' if n in (4,5) else 'giant_fall',position=list(p)) for n,(f,p,*_) in enumerate(events)]))


def preview():
    import shutil
    if shutil.disk_usage(OUT).free<150_000_000:
        raise RuntimeError('Need 150 MB reserve before the 13-still probe (under 20 MB output)')
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False)
    sc=bpy.context.scene;sc.render.resolution_percentage=40;sc.eevee.taa_render_samples=16
    from study_head_target import gpu_guard
    gpu_guard()
    (OUT/'probes').mkdir(exist_ok=True)
    for frame in (20,80,126,177,214,263,300,322,368,420,449,487,525):
        sc.frame_set(frame);sc.render.filepath=str(OUT/'probes'/f'frame_{frame:04d}.png');bpy.ops.render.render(write_still=True)


def render(percent=100):
    """Color-managed PNG stream, one temporary frame; preserves frame-rate and no upscaling."""
    import shutil
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False)
    sc=bpy.context.scene
    sc.render.resolution_percentage=percent
    if percent<100:sc.eevee.taa_render_samples=12
    from study_head_target import gpu_guard
    gpu_guard()
    if shutil.disk_usage(OUT).free<250_000_000:raise RuntimeError('Need 250 MB for final movie and QA stills')
    runtime=OUT/'runtime.json'
    ffmpeg=os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    if not ffmpeg and runtime.is_file():ffmpeg=json.loads(runtime.read_text())['ffmpeg']
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise RuntimeError('Set FFMPEG to an installed executable, or configure local runtime.json')
    label='motion' if percent<100 else 'fleet_battle_silent'
    output=OUT/(label+'.mp4');log=(OUT/(label+'_encode.log')).open('wb')
    proc=subprocess.Popen([ffmpeg,'-y','-v','error','-f','image2pipe','-framerate',str(FPS),'-vcodec','png','-i','-',
         '-an','-c:v','libx264','-crf','18','-preset','medium','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],stdin=subprocess.PIPE,stderr=log)
    qa=OUT/('motion_qa' if percent<100 else 'qa_frames');qa.mkdir(exist_ok=True);temp=OUT/'frame_current.png'
    try:
        for frame in range(COUNT):
            sc.frame_set(frame);bpy.ops.render.render()
            bpy.data.images['Render Result'].save_render(str(temp),scene=sc)
            proc.stdin.write(temp.read_bytes())
            if frame%15==0 or frame in (64,65,104,105,164,165,239,240,344,345,389,390,464,465,509,510,539):
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
    elif mode=='motion':render(30)
    else:raise ValueError(mode)
