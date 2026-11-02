"""Fourteen-second staging with a compact two-handed authored leap.

Blender --background --python-exit-code 1 --python this.py -- probe|motion|draft
Uses the accepted material sources, not the native culling-blade jump.
"""
import hashlib
import json
import math
import os
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector, Quaternion

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('DOOMSDAY_RUN_DIR',str(ROOT/'_game/skits/doomsday/v11')))
SOURCE=ROOT/'_game/skits/doomsday/v3/scene.blend'
sys.path.insert(0,str(Path(__file__).resolve().parent))
from contact_reaction import _basis, _solve_leg
from doomsday_refine import gpu, smooth
from doomsday_atmosphere import environment, glow, filament

N=420
LIFT=252
HIT=279


def snapshot(arm):
    return {b.name:arm.matrix_world@b.matrix for b in arm.pose.bones}


def shift(pose,delta):
    t=Matrix.Translation(delta)
    return {n:t@m for n,m in pose.items()}


def mix(arm,a,b,t):
    result={}
    def visit(bone):
        n=bone.name
        if n in result:return result[n]
        m,m1=a[n],b[n]
        if bone.parent:
            m=a[bone.parent.name].inverted()@m
            m1=b[bone.parent.name].inverted()@m1
        p,q,s=m.decompose();p1,q1,s1=m1.decompose()
        position=p.lerp(p1,t)
        if n in ('knee_L','knee_R','ankle_L','ankle_R') and position.length>1e-8:
            position=position.normalized()*p.length
        local=Matrix.LocRotScale(position,q.slerp(q1,t),s.lerp(s1,t))
        result[n]=visit(bone.parent)@local if bone.parent else local
        return result[n]
    for bone in arm.pose.bones:visit(bone)
    return result


def branch(arm,pose,name,angle,axis='X'):
    pivot=pose[name].translation
    t=Matrix.Translation(pivot)@Matrix.Rotation(angle,4,axis)@Matrix.Translation(-pivot)
    for bone in [arm.pose.bones[name],*arm.pose.bones[name].children_recursive]:pose[bone.name]=t@pose[bone.name]


def curve(frame, keys):
    """Authored continuous phrases; internal poses do not stop every channel."""
    if frame<=keys[0][0]:return keys[0][1]
    if frame>=keys[-1][0]:return keys[-1][1]
    for i,((a,va),(b,vb)) in enumerate(zip(keys,keys[1:])):
        if frame<=b:
            t=(frame-a)/(b-a)
            ma=0 if i==0 else (vb-keys[i-1][1])/(b-keys[i-1][0])
            mb=0 if i+2==len(keys) else (keys[i+2][1]-va)/(keys[i+2][0]-a)
            return (2*t**3-3*t*t+1)*va+(t**3-2*t*t+t)*(b-a)*ma+(-2*t**3+3*t*t)*vb+(t**3-t*t)*(b-a)*mb


def around(matrix, pivot, angle, axis='X'):
    return Matrix.Translation(pivot)@Matrix.Rotation(math.radians(angle),4,axis)@Matrix.Translation(-pivot)@matrix


def solve(arm,pose,chain,target,pole):
    result={n:m.copy() for n,m in pose.items()}
    pole=_solve_leg(pose,result,chain,Vector(),pole,Vector((0,-1,0)),target)
    delta=target@pose[chain[-1]].inverted()
    for bone in arm.pose.bones[chain[-1]].children_recursive:result[bone.name]=delta@pose[bone.name]
    # Off-chain helpers (including Axe's shoulder armour) must inherit their
    # solved ancestor; leaving their world pose unchanged detaches the silhouette.
    for bone in arm.pose.bones[chain[0]].children_recursive:
        if bone.name in chain:continue
        ancestor=next((p for p in bone.parent_recursive if p.name in chain),None)
        if ancestor:result[bone.name]=result[ancestor.name]@pose[ancestor.name].inverted()@pose[bone.name]
    return result,pole


def solve_arm(arm,pose,side,target,elbow_pole=None):
    """Two-bone solve with an authored elbow plane in front of the chest."""
    chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
    h,k,w=(pose[n].translation.copy() for n in chain)
    upper,lower=(k-h).length,(w-k).length
    axis=target.translation-h;distance=axis.length;direction=axis.normalized()
    if distance>upper+lower or distance<abs(upper-lower):raise ValueError('Unreachable arm target')
    pole=Vector(elbow_pole) if elbow_pole is not None else Vector((1,-.8,-.4)) if side=='L' else Vector((-1,-.65,-1.3))
    pole-=direction*pole.dot(direction);pole.normalize()
    along=(upper*upper-lower*lower+distance*distance)/(2*distance)
    joint=h+direction*along+pole*math.sqrt(max(0,upper*upper-along*along))
    result={n:m.copy() for n,m in pose.items()}
    q=(k-h).rotation_difference(joint-h)
    result[chain[0]]=q.to_matrix().to_4x4()@pose[chain[0]];result[chain[0]].translation=h
    lower_rotation=(q@(w-k)).rotation_difference(target.translation-joint)
    result[chain[1]]=lower_rotation.to_matrix().to_4x4()@q.to_matrix().to_4x4()@pose[chain[1]]
    result[chain[1]].translation=joint;result[chain[2]]=target.copy()
    for bone in arm.pose.bones[chain[0]].children_recursive:
        if bone.name in chain:continue
        ancestor=next(p for p in bone.parent_recursive if p.name in chain)
        result[bone.name]=result[ancestor.name]@pose[ancestor.name].inverted()@pose[bone.name]
    return result


def bake(arm,poses,extra=None):
    arm.animation_data_clear()
    inverse=arm.matrix_world.inverted();previous={}
    times=dict(enumerate(poses));times.update(extra or {})
    for f,pose in sorted(times.items()):
        for bone in arm.pose.bones:
            m=_basis(bone,inverse@pose[bone.name],inverse@pose[bone.parent.name] if bone.parent else None)
            p,q,s=m.decompose()
            if bone.name in previous and q.dot(previous[bone.name])<0:q.negate()
            previous[bone.name]=q.copy()
            bone.location=p;bone.rotation_mode='QUATERNION';bone.rotation_quaternion=q;bone.scale=s
            for key in ('location','rotation_quaternion','scale'):bone.keyframe_insert(key,frame=f)
    for layer in arm.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:key.interpolation='LINEAR'


def author_legacy_v7(scene,axe,rubick,dense=True):
    scene.frame_set(0);bpy.context.view_layer.update();base=snapshot(axe);idle=snapshot(rubick)
    scene.frame_set(60);bpy.context.view_layer.update();grip=snapshot(axe)
    weapon=next(o for o in scene.objects if o.type=='MESH' and 'axe_weapon' in o.name)
    ev=weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
    weapon_local=[grip['axe_1'].inverted()@ev.matrix_world@v.co for v in ev.data.vertices]
    scene.frame_set(44);bpy.context.view_layer.update();cast=snapshot(rubick)
    point=Vector(json.loads((SOURCE.parent.parent/'v2/staging.json').read_text())['contact'])
    direction=(point-grip['wrist_R'].translation).normalized()
    left=grip['wrist_L'].copy();left.translation+=direction*.12
    left_relative=grip['wrist_R'].inverted()@left
    weapon_relative=grip['wrist_R'].inverted()@grip['axe_1']
    weapon_relative.translation*=.8
    weapon_relative=weapon_relative@Matrix.Diagonal((.8,.8,.8,1))
    poses=[];extra={};root0=base['root'].translation.copy();end=Vector((-.25,-.30,root0.z))
    poles={'L':Vector((1,0,-1)),'R':Vector((-1,0,-1))};held=None;contact=None
    times=sorted(set(range(N))|({q/8 for q in range(230*8,(N-1)*8+1)} if dense else set()))
    for f in times:
        u=max(0,min(1,(f-LIFT)/(HIT-LIFT)))
        if f<LIFT:
            root=root0+Vector((curve(f,((0,0),(42,.08),(100,-.055),(172,.035),(195,0),(216,.05),(231,0))),
                curve(f,((0,0),(60,.07),(128,-.045),(182,0),(216,.13),(231,-.10))),
                curve(f,((0,0),(80,-.025),(150,-.045),(195,-.01),(216,-.34),(231,0)))))
        elif f<=HIT:
            root=(root0+Vector((0,-.10,0))).lerp(end,.8*u+.2*u*u)
            root.z+=.85*math.sin(math.pi*.72*u)
        else:
            # Impact -> recoil -> second pressure -> let the effort go. The
            # suspended pelvis changes direction; it does not simply sink.
            root=end+Vector((curve(f,((279,0),(289,-.06),(303,.05),(317,-.035),(350,.08),(398,.06),(419,.06))),
                curve(f,((279,0),(286,-.16),(299,.08),(313,-.12),(334,.03),(375,-.02),(405,-.03),(419,-.03))),
                .85*math.sin(math.pi*.72)+curve(f,((279,0),(289,-.045),(302,.025),(316,-.025),(352,-.10),(395,-.12),(419,-.12)))))
        pose=shift(base,root-root0)
        lean=curve(f,((0,0),(75,4),(120,1),(153,7),(180,2),(195,0),(216,28),(231,10),
                      (250,31),(268,22),(279,14),(287,26),(300,7),(314,25),(336,14),(370,10),(402,12),(419,12)))
        twist=curve(f,((0,0),(60,-4),(125,3),(180,0),(216,-9),(249,-5),(279,0),
                       (289,5),(304,-4),(317,3),(360,0),(402,-3),(419,-3)))
        branch(axe,pose,'spine1',math.radians(lean))
        branch(axe,pose,'spine2',math.radians(twist),'Z')
        nod=curve(f,((0,0),(70,-3),(115,0),(132,-8),(147,2),(164,-5),(190,0),(216,-10),
                     (247,-12),(279,0),(285,-10),(300,4),(316,-8),(350,-4),(374,-12),(396,7),(405,7),(419,7)))
        branch(axe,pose,'head',math.radians(nod))
        branch(axe,pose,'head',math.radians(curve(f,((0,0),(150,0),(178,3),(211,0),
                     (360,0),(378,-12),(401,10),(405,10),(419,10)))),'Z')
        # Feet stay planted during compression. In flight the knees fold behind
        # the body; the arrest leaves the attacker briefly held by magic.
        for side in ('L','R'):
            chain=tuple(n+'_'+side for n in ('thigh','knee','ankle'))
            foot=base[chain[-1]].copy()
            if f>=LIFT:
                foot.translation+=root-root0
                fold=curve(f,((231,0),(245,.8),(258,1),(279,.6),(291,.23),(305,.62),
                               (319,.46),(355,.28),(398,.2),(419,.2)))
                foot.translation+=Vector(((-.30 if side=='L' else .30)*fold,
                                          (-.15 if side=='L' else .60)*fold,
                                          (.40 if side=='L' else .25)*fold))
                if f>HIT:
                    follow=curve(f,((279,0),(291,-.22),(307,.15),(327,-.10),(359,.05),(402,0),(419,0)))
                    foot.translation.y+=follow*(1 if side=='L' else .65)
                pivot=foot.translation.copy()
                foot=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(18)*fold,4,'X')@Matrix.Translation(-pivot)@foot
            pose,_=solve(axe,pose,chain,foot,None)
        lift=smooth((f-180)/(LIFT-180))
        swing=smooth((u-.68)/.32) if f>=LIFT else 0
        rest=pose['spine3'].translation+Vector((.00,-.38,-.32))
        raised=pose['head'].translation+Vector((.25,.05,-.15))
        stop=pose['spine3'].translation+Vector((-.10,-.47,-.30))
        wrist_position=rest.lerp(raised,lift).lerp(stop,swing)
        up=Vector((.5,-.12,.858)).lerp(Vector((.5,.20,.843)),lift).normalized()
        axis=up.lerp(Vector((0,-.97,.243)),swing).normalized()
        rotation=direction.rotation_difference(axis).to_matrix().to_4x4()
        right=rotation@grip['wrist_R'];right.translation=wrist_position
        if f<LIFT:
            accent=curve(f,((0,0),(44,0),(65,10),(92,3),(119,0),(155,-5),(180,0),(231,0)))
            right=around(right,pose['spine3'].translation,accent)
        if f==HIT:
            held=right.copy()
            contact=min((right@weapon_relative@p for p in weapon_local),key=lambda p:p.y)
        if f>HIT:
            recoil=curve(f,((279,0),(286,-7),(300,3),(314,-3),(337,1.5),(363,0),(403,0),(419,0)))
            right=around(held,contact,recoil)
        left=right@left_relative
        for side,target in (('R',right),('L',left)):
            chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
            try:
                if side=='R':pose=solve_arm(axe,pose,side,target)
                else:pose,poles[side]=solve(axe,pose,chain,target,poles[side])
            except ValueError as exc:raise ValueError(f'Grip unreachable at {f}/{side}: {exc}') from exc
            hand_delta=target@grip['wrist_'+side].inverted()
            for bone in axe.pose.bones['wrist_'+side].children_recursive:
                pose[bone.name]=hand_delta@grip[bone.name]
        pose['axe_1']=right@weapon_relative
        if f==int(f):poses.append(pose)
        else:extra[f]=pose
    bake(axe,poses,extra)
    scene.frame_set(HIT);bpy.context.view_layer.update()
    weapon=next(o for o in scene.objects if o.type=='MESH' and 'axe_weapon' in o.name)
    ev=weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
    points=[ev.matrix_world@v.co for v in ev.data.vertices]
    evaluated_contact=min(points,key=lambda p:p.y)
    if (contact-evaluated_contact).length>.0001:
        raise ValueError('Rigid weapon contact prediction differs from evaluated mesh')
    delta=contact-cast['index_1_R'].translation
    offset=Vector((delta.x,delta.y,0))
    cast=shift(cast,offset);idle=shift(idle,offset)
    target=cast['wrist_R'].copy();target.translation.z+=delta.z
    cast,_=solve(rubick,cast,('bicep_R','elbow_R','wrist_R'),target,None)
    defender=[]
    for f in range(N):
        pose=mix(rubick,idle,cast,smooth((f-(HIT-25))/25))
        head=curve(f,((0,0),(75,-4),(150,1),(230,-3),(264,0),(283,-6),(301,0),(330,4),(348,-5),(376,-2),(409,0),(419,0)))
        branch(rubick,pose,'Head_0',math.radians(head),'Z')
        if f>=HIT:
            # Quiet defender: absorbs a little load through his shoulder, then
            # deliberately releases it while the index contact remains planted.
            spine=next((n for n in ('spine3','spine2','Spine2') if n in pose),None)
            if spine:
                branch(rubick,pose,spine,math.radians(curve(f,((279,0),(288,-4),(310,1),(350,0),(419,0)))))
                pose,_=solve(rubick,pose,('bicep_R','elbow_R','wrist_R'),cast['wrist_R'],None)
        defender.append(pose)
    bake(rubick,defender)
    (OUT/'staging.json').write_text(json.dumps({'frames':N,'fps':30,'hit':HIT,'takeoff':LIFT,
        'contact':list(contact),'weapon_scale':.8,'two_hand_separation':(left_relative.translation).length,
        'held_by_magic':True,'landing':None},indent=2))
    return poses,defender,contact


def native_attack(scene, arm):
    """Take full articulated poses as a starting point, discarding native travel."""
    objects=set(bpy.data.objects);actions=set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/models/render/models_heroes_axe_axe.glb'),bone_heuristic='BLENDER')
    imported=set(bpy.data.objects)-objects
    source=next(o for o in imported if o.type=='ARMATURE')
    action=next(a for a in set(bpy.data.actions)-actions if a.name.split('.')[0]=='attack_alt_anim')
    source.animation_data.action=action;source.animation_data.action_slot=action.slots[0]
    poses=[]
    for f in range(15):
        scene.frame_set(f);bpy.context.view_layer.update()
        poses.append({b.name:arm.matrix_world@b.matrix for b in source.pose.bones if b.name in arm.pose.bones})
    for ob in imported:bpy.data.objects.remove(ob,do_unlink=True)
    return poses


def stage_arrest(arm,pose,contact,weight):
    """Pose correction checked in the live scene from front, side and rear.

    Lower the two-handed grip as a whole while preserving the blade contact;
    changing elbow poles alone forced a forearm through the handle.
    """
    if weight<=0:return pose
    result=shift(pose,Vector((0,-.20*weight-.08*math.sin(math.pi*weight),0)))
    weapon=around(pose['axe_1'],contact,-10*weight,'X')
    for side,final_pole in (('R',Vector((-1,-.5,-1))),('L',Vector((1,0,-.6)))):
        binding=pose['axe_1'].inverted()@pose['wrist_'+side]
        pole=(pose['elbow_'+side].translation-pose['bicep_'+side].translation).normalized()
        pole= pole.lerp(final_pole.normalized(),weight)
        result=solve_arm(arm,result,side,weapon@binding,pole)
    result['axe_1']=weapon
    return result


def pressure_phrase(arm,pose,frame):
    """A deliberate second effort, followed by looking from weapon to defender."""
    weight=curve(frame,((0,0),(300,0),(325,1),(338,.75),(358,0),(419,0)))
    weight=max(0,weight)
    result=shift(pose,Vector((0,-.20*weight,.08*weight)))
    branch(arm,result,'spine1',math.radians(16*weight),'X')
    branch(arm,result,'spine2',math.radians(-10*weight),'Z')
    branch(arm,result,'head',math.radians(-10*weight),'X')
    if weight>0:
        left_pole=Vector((1,0,-.6)).lerp(Vector((1,0,1)),weight)
        for side,pole in (('R',Vector((-1,-.5,-1))),('L',left_pole)):
            result=solve_arm(arm,result,side,pose['wrist_'+side],pole)
        result['axe_1']=pose['axe_1'].copy()
    if frame>=358:
        branch(arm,result,'head',math.radians(curve(frame,((358,0),(374,-12),(400,7),(419,5)))),'Z')
        branch(arm,result,'head',math.radians(curve(frame,((358,0),(373,-7),(398,5),(419,3)))),'X')
    return result


def author(scene,axe,rubick,dense=True):
    scene.frame_set(0);bpy.context.view_layer.update();base=snapshot(axe);idle=snapshot(rubick)
    scene.frame_set(60);bpy.context.view_layer.update();grip=snapshot(axe)
    weapon=next(o for o in scene.objects if o.type=='MESH' and 'axe_weapon' in o.name)
    ev=weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
    weapon_local=[grip['axe_1'].inverted()@ev.matrix_world@v.co for v in ev.data.vertices]
    binds={s:grip['axe_1'].inverted()@grip['wrist_'+s] for s in ('L','R')}
    _,axes=np.linalg.eigh(np.cov(np.asarray([tuple(p) for p in weapon_local]).T))
    shaft_axis=Vector(axes[:,-1].tolist())
    center=sum(weapon_local,Vector())/len(weapon_local)
    if shaft_axis.dot(center-binds['R'].translation)<0:shaft_axis.negate()
    binds['L'].translation+=shaft_axis*(.38/(grip['axe_1'].to_3x3()@shaft_axis).length)
    # Live-pose calibration: turn the support palm around the actual handle,
    # not merely the elbow around a fixed wrist. The latter crossed the shaft.
    binds['L']=around(binds['L'],Vector((-.0742359,-.0201558,-.0856006)),-95,shaft_axis)
    scene.frame_set(44);bpy.context.view_layer.update();cast=snapshot(rubick)
    bank=native_attack(scene,axe)
    root0=base['root'].translation.copy();end=Vector((-.25,-.30,root0.z))
    stance=shift(bank[0],root0-bank[0]['root'].translation)
    poses=[];extra={};held=None;contact=None;poles={'L':None,'R':None}
    times=sorted(set(range(N))|({q/8 for q in range(250*8,(N-1)*8+1)} if dense else set()))
    for f in times:
        t=curve(f,((0,0),(195,0),(210,4),(228,8),(238,9.3),(250,9.6),(262,10),(270,10.5),(279,11.6),(419,11.6)))
        t=max(0,min(12,t));i=int(t);part=t-i
        native=mix(axe,bank[i],bank[min(14,i+1)],part)
        u=max(0,min(1,(f-LIFT)/(HIT-LIFT)))
        if f<LIFT:
            root=root0+Vector((curve(f,((0,0),(200,.07),(233,.13),(252,0))),
                curve(f,((0,0),(205,.08),(237,.14),(252,-.18))),
                curve(f,((0,0),(215,-.06),(244,-.43),(252,0)))))
        elif f<=HIT:
            root=(root0+Vector((0,-.18,0))).lerp(end,u)
            root.z+=.85*math.sin(math.pi*.72*u)
        else:
            # The arrested weapon suspends the attacker. Momentum carries his
            # torso forward, then one deliberate pressure attempt fails.
            root=end+Vector((curve(f,((279,0),(288,.04),(306,-.03),(337,.04),(365,0),(419,-.02))),
                curve(f,((279,0),(286,-.18),(303,-.06),(329,-.16),(350,-.14),(379,-.08),(419,-.09))),
                .85*math.sin(math.pi*.72)+curve(f,((279,0),(290,-.10),(309,-.05),(340,-.08),(380,-.13),(419,-.14)))))
        pose=shift(native,root-native['root'].translation)
        if f<195:
            branch(axe,pose,'head',math.radians(curve(f,((0,-3),(74,-3),(112,3),(145,-7),(170,0),(195,-2)))),'X')
        if 195<f<=HIT:
            branch(axe,pose,'spine1',math.radians(curve(f,((195,0),(226,-7),(242,-10),(258,5),(279,0)))))
            branch(axe,pose,'spine2',math.radians(curve(f,((195,0),(228,-9),(246,-6),(268,5),(279,0)))),'Z')
        if f>HIT:
            branch(axe,pose,'spine1',math.radians(curve(f,((279,0),(286,8),(304,-3),(331,6),(350,5),(382,1),(419,2)))))
            branch(axe,pose,'spine2',math.radians(curve(f,((279,0),(293,5),(312,-3),(342,4),(377,0),(419,1)))),'Z')
            branch(axe,pose,'head',math.radians(curve(f,((279,0),(285,-9),(307,-3),(339,-6),(366,2),(395,7),(419,6)))))
        for side in ('L','R'):
            chain=tuple(n+'_'+side for n in ('thigh','knee','ankle'))
            foot=stance[chain[-1]].copy()
            if f>=LIFT:
                fold=curve(f,((252,0),(269,.9),(279,.7),(294,.45),(322,.62),(354,.52),(391,.38),(419,.40)))
                foot.translation+=root-(root0+Vector((0,-.18,0)))+Vector(((-.15 if side=='L' else .12)*fold,
                    (-.25 if side=='L' else .50)*fold,(.32 if side=='L' else .46)*fold))
                if f>HIT:foot.translation.y+=.12*math.sin(math.pi*max(0,min(1,(f-HIT)/45)))
                h,k,w=(pose[n].translation for n in chain)
                axis=foot.translation-h;reach=.99*((k-h).length+(w-k).length)
                if axis.length>reach:foot.translation=h+axis.normalized()*reach
            try:pose,_=solve(axe,pose,chain,foot,None)
            except ValueError as exc:raise ValueError(f'Leg unreachable at {f}/{side}: {exc}') from exc
        weapon_pose=pose['axe_1'].copy()
        weapon_pose.translation+=pose['wrist_R'].translation-(weapon_pose@binds['R']).translation
        join=smooth((f-230)/18)
        frame_binds={side:binds[side].copy() for side in ('L','R')}
        free_left=pose['wrist_L'].copy()
        free_weight=smooth((f-195)/12)
        outside=pose['bicep_L'].translation-pose['spine3'].translation
        outside.z=0;outside.normalize()
        free_left.translation=free_left.translation.lerp(
            pose['bicep_L'].translation+outside*.48+Vector((0,-.25,-.35)),free_weight)
        lh,lk,lw=(pose[n+'_L'].translation for n in ('bicep','elbow','wrist'))
        free_axis=free_left.translation-lh;free_reach=.90*((lk-lh).length+(lw-lk).length)
        if free_axis.length>free_reach:free_left.translation=lh+free_axis.normalized()*free_reach
        reach_arc=(outside*.25+Vector((0,-.50,.15)))*math.sin(math.pi*join)
        if 230<f<=HIT:
            # Restage the one-handed source near the chest/head for a genuine
            # two-handed strike. Move the prop, never stretch either arm.
            for _ in range(24):
                correction=Vector()
                for side in ('R','L'):
                    h,k,w=(pose[n+'_'+side].translation for n in ('bicep','elbow','wrist'))
                    target=(weapon_pose@binds[side]).translation
                    if side=='L':target=free_left.translation.lerp(target,join)+reach_arc
                    axis=target-h;radius=(1-.08*join)*((k-h).length+(w-k).length)
                    if axis.length>radius:
                        correction-=axis.normalized()*min(.08,(axis.length-radius)/(join if side=='L' else 1))
                weapon_pose.translation+=correction
                if correction.length<1e-6:break
        if f==HIT:
            held=weapon_pose.copy();contact=min((held@p for p in weapon_local),key=lambda p:p.y)
        if f>HIT:
            weapon_pose=around(held,contact,-2.5*smooth((f-HIT)/10))
        # The left hand joins the shaft before the actual swing. During the
        # preparatory reach it retains the source action's free-arm gesture.
        for side in ('R','L'):
            target=weapon_pose@frame_binds[side]
            if side=='L':
                target=free_left.lerp(target,join);target.translation+=reach_arc
            chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
            try:
                if side=='L' and free_weight>0:
                    h,k,w=(pose[n].translation for n in chain)
                    source_pole=(k-h).normalized().lerp((outside+Vector((0,-.6,-.9))).normalized(),free_weight)
                    pole=source_pole.lerp(Vector((1,0,-.6)).normalized(),join)
                    pose=solve_arm(axe,pose,side,target,pole)
                else:pose,poles[side]=solve(axe,pose,chain,target,poles[side])
            except ValueError as exc:raise ValueError(f'Native staging unreachable at {f}/{side}: {exc}') from exc
            if side=='R' or join>0:
                delta=target@grip['wrist_'+side].inverted()
                closed={n:m.copy() for n,m in pose.items()}
                for bone in axe.pose.bones['wrist_'+side].children_recursive:closed[bone.name]=delta@grip[bone.name]
                pose=mix(axe,pose,closed,1 if side=='R' else join)
        pose['axe_1']=weapon_pose
        if f==int(f):poses.append(pose)
        else:extra[f]=pose
    tip=held.inverted()@contact
    from doomsday_cinematography import flight_legs
    for f,pose in list(enumerate(poses))+list(extra.items()):
        corrected=stage_arrest(axe,pose,pose['axe_1']@tip,smooth((f-260)/19))
        corrected=pressure_phrase(axe,corrected,f)
        corrected=flight_legs(axe,corrected,f,branch,curve)
        if f==int(f):poses[int(f)]=corrected
        else:extra[f]=corrected
    bake(axe,poses,extra)
    delta=contact-cast['index_1_R'].translation
    (OUT/'contact_probe.json').write_text(json.dumps({'contact':list(contact),'cast_finger':list(cast['index_1_R'].translation),'delta':list(delta)},indent=2))
    cast=shift(cast,Vector((delta.x,delta.y,0)));idle=shift(idle,Vector((delta.x,delta.y,0)))
    target=cast['wrist_R'].copy();target.translation.z+=delta.z
    cast,_=solve(rubick,cast,('bicep_R','elbow_R','wrist_R'),target,None)
    defender=[]
    for f in range(N):
        pose=mix(rubick,idle,cast,smooth((f-263)/16))
        branch(rubick,pose,'Head_0',math.radians(curve(f,((0,0),(279,0),(294,-2),(328,0),(354,-6),(382,-4),(419,-4)))),'Z')
        defender.append(pose)
    bake(rubick,defender)
    (OUT/'staging.json').write_text(json.dumps({'frames':N,'fps':30,'hit':HIT,'takeoff':LIFT,
        'contact':list(contact),'source_upper_body':'attack_alt_anim, restaged timing and hands',
        'held_by_magic':True,'release':None,'landing':None,
        'phrase':'gather, attack, arrest, inertia, pressure, realization'},indent=2))
    return poses,defender,contact


def cameras(scene,axe,rubick,contact):
    from doomsday_cinematography import apply
    return apply(scene,axe,rubick,contact,N)


def cameras_legacy_v10(scene,axe,rubick,contact):
    cam=scene.camera;cam.animation_data_clear();cam.data.animation_data_clear()
    cam.data.sensor_fit='HORIZONTAL'
    face_targets={}
    for frame in (145,390):
        scene.frame_set(frame);bpy.context.view_layer.update()
        face_targets[frame]=axe.matrix_world@axe.pose.bones['head'].head
    scene.frame_set(HIT);bpy.context.view_layer.update()
    tip_local=(axe.matrix_world@axe.pose.bones['axe_1'].matrix).inverted()@contact
    for f in range(N):
        scene.frame_set(f);bpy.context.view_layer.update()
        ahead=axe.matrix_world@axe.pose.bones['head'].head
        rhead=rubick.matrix_world@rubick.pose.bones['Head_0'].head
        if f<45:
            pos=Vector((-6,-8,2.3));target=Vector((-.5,-.1,2.0));lens=33
        elif f<120:
            center=axe.matrix_world@axe.pose.bones['axe_1'].head
            target=center+Vector((0,0,.7));pos=target+Vector((-1.5,-2.8,.25));lens=45
        elif f<195:
            target=face_targets[145]+Vector((0,0,-.08));pos=target+Vector((-1.8,-3.2,.15));lens=56
        elif f<225:
            target=Vector((-.2,1.2,2.3));pos=Vector((-9,-2.0,3.0));lens=32
        elif f<273:
            target=Vector((-.2,1.0,3.0));pos=Vector((-8.5,-3.0,3.5));lens=34
        elif f<330:
            target=contact.lerp(ahead,.5)+Vector((0,0,-.35));pos=target+Vector((-7.0,-.7,.35));lens=38
        elif f<360:
            target=rhead.lerp(contact,.28);pos=target+Vector((-3.0,2.5,.15));lens=48
        else:
            target=face_targets[390]+Vector((0,0,-.13));pos=target+Vector((-2.3,-2.5,.25));lens=48
        cam.location=pos;cam.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler();cam.data.lens=lens
        cam.data.dof.focus_distance=(target-pos).length;cam.data.dof.aperture_fstop=4 if f<45 or 195<=f<316 else 2.5
        for key in ('location','rotation_euler'):cam.keyframe_insert(key,frame=f)
        for key in ('lens','dof.focus_distance','dof.aperture_fstop'):cam.data.keyframe_insert(key,frame=f)
    # Fit each uninterrupted action shot once over its complete motion. Never
    # crop the backswing or make a tracking camera cancel the actor's travel.
    actors=[o for root in ('axe_root','rubick_root')
            for o in scene.objects[root].children_recursive if o.type=='MESH']
    for start,stop in ((195,225),(225,273),(273,330)):
        scene.frame_set(start)
        rotation=cam.rotation_euler.to_quaternion();inverse=rotation.inverted()
        points=[]
        for frame in range(start,stop,3):
            scene.frame_set(frame);graph=bpy.context.evaluated_depsgraph_get()
            for ob in actors:
                if start==273 and 'axe_weapon' not in ob.name:continue
                ev=ob.evaluated_get(graph)
                points.extend(inverse@(ev.matrix_world@Vector(p)) for p in ev.bound_box)
            if start==273:
                for arm,names in ((axe,('head','spine1','bicep_L','bicep_R','elbow_L','elbow_R','wrist_L','wrist_R')),
                                  (rubick,('Head_0','bicep_R','elbow_R','wrist_R'))):
                    for name in names:
                        center=arm.matrix_world@arm.pose.bones[name].head
                        points.extend(inverse@(center+Vector((x,y,z)))
                                      for x in (-.35,.35) for y in (-.35,.35) for z in (-.35,.35))
        lo=Vector(tuple(min(p[i] for p in points) for i in range(3)))
        hi=Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center=(lo+hi)*.5
        # Blender uses horizontal sensor fit here; vertical portrait field is
        # expanded accordingly. Reserve room around all actual actor geometry.
        lens=32;tanx=cam.data.sensor_width/(2*lens)
        tany=tanx*(360/640 if 'blocking' in sys.argv else 640/360)
        distance=max(max(abs(p.x-center.x)/(.85*tanx),
                         abs(p.y-center.y)/(.88*tany))+p.z-center.z for p in points)
        location=rotation@(center+Vector((0,0,distance)))
        for frame in range(start,stop):
            cam.location=location;cam.rotation_euler=rotation.to_euler();cam.data.lens=lens
            cam.data.dof.focus_distance=distance
            for key in ('location','rotation_euler'):cam.keyframe_insert(key,frame=frame)
            for key in ('lens','dof.focus_distance'):cam.data.keyframe_insert(key,frame=frame)
    for owner in (cam,cam.data):
        for layer in owner.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:key.interpolation='CONSTANT'


def face(scene):
    audio_source=ROOT/'_game/skits/doomsday/v6'
    data=audio_source/'voice/voices.json'
    native=audio_source/'audio/native_dialogue_envelope.json'
    battle=audio_source/'audio/battle_cry_envelope.json'
    env=json.loads(data.read_text())['threat']['env'] if data.exists() else json.loads(native.read_text())['env'] if native.exists() else []
    cry=json.loads(battle.read_text())['env'] if battle.exists() else []
    for ob in scene.objects:
        if ob.type!='MESH' or not ob.data.shape_keys or 'axe_model' not in ob.data.name:continue
        keys=ob.data.shape_keys;keys.animation_data_clear()
        for f in range(N):
            index=math.floor(f-74.4)
            speak=env[index] if 0<=index<len(env) else 0
            if 0<=f-225<len(cry):speak=max(speak,cry[f-225])
            shock=smooth((f-HIT)/8)
            disbelief=smooth((f-363)/34)
            effort=max(0,curve(f,((0,0),(300,0),(325,1),(338,.75),(358,0),(419,0))))
            for name,value in {'jawOpen':max(0,.08+.45*speak+.14*shock+.22*effort-.20*disbelief),
                               'browLowerer':.6*(1-shock)+.25*disbelief,
                               'innerBrowRaiser':.45*shock+.2*disbelief,'upperLidRaiser':.5*shock-.2*disbelief,
                               'eyeClosed':.9*max(0,1-abs(f-385)/2)}.items():
                if name in keys.key_blocks:
                    keys.key_blocks[name].value=value;keys.key_blocks[name].keyframe_insert('value',frame=f)


def main():
    mode=sys.argv[sys.argv.index('--')+1]
    OUT.mkdir(exist_ok=True,parents=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE));scene=bpy.context.scene;gpu(scene)
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='OPTIX';prefs.get_devices()
    for device in prefs.devices:device.use=device.type=='OPTIX'
    scene.cycles.device='GPU'
    scene.frame_start=0;scene.frame_end=N-1
    axe=next(o for o in scene.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='axe_root')
    rubick=next(o for o in scene.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='rubick_root')
    for ob in list(scene.objects):
        if ob.name.startswith(('Charge ','Contact spark ')) or ob.name in ('Weapon charge light','Arrest light'):
            bpy.data.objects.remove(ob,do_unlink=True)
    scene.render.resolution_x=640 if mode=='blocking' else int(os.environ.get('DOOMSDAY_WIDTH','1280'))
    scene.render.resolution_y=360 if mode=='blocking' else int(os.environ.get('DOOMSDAY_HEIGHT','720'))
    scene.render.resolution_percentage=100
    poses,defender,contact=author(scene,axe,rubick,dense=mode!='blocking')
    cameras(scene,axe,rubick,contact);face(scene)
    if mode!='blocking':environment(scene);glow(scene)
    # Pale masonry is too prominent from the new reverse angles; preserve its
    # native maps while toning it down into the surrounding stone palette.
    for ob in scene.objects:
        if mode=='blocking' or ob.type!='MESH' or 'statue' not in ob.name.lower():continue
        for slot in ob.material_slots:
            if not slot.material or not slot.material.use_nodes:continue
            slot.material=slot.material.copy();nt=slot.material.node_tree
            p=next((n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'),None)
            if not p:continue
            color=p.inputs['Base Color'];h=nt.nodes.new('ShaderNodeHueSaturation')
            h.inputs['Value'].default_value=.25;h.inputs['Saturation'].default_value=.45
            if color.is_linked:nt.links.new(color.links[0].from_socket,h.inputs['Color'])
            else:h.inputs['Color'].default_value=color.default_value
            nt.links.new(h.outputs[0],color)
    if mode!='blocking':
        from doomsday_performance_fx import apply
        fx=apply(scene,axe,rubick,contact)
        (OUT/'fx.json').write_text(json.dumps(fx,indent=2))
    if '--audit' in sys.argv:
        import doomsday_performance_qa as qa
        qa.OUT=OUT;qa.LIFT=LIFT
        qa.audit(scene,axe,rubick,contact,poses,defender)
    if '--weapon-check' in sys.argv:
        from doomsday_weapon_clearance import audit as weapon_clearance, audit_forearms
        checked=[int(f) for f in sys.argv[sys.argv.index('--frames')+1].split(',')] if '--frames' in sys.argv else range(180,N)
        weapon_clearance(scene,axe,frames=checked,output=OUT/'weapon_clearance.json')
        audit_forearms(scene,axe,checked,OUT/'forearm_clearance.json')
    if '--no-render' in sys.argv:return
    scene.render.use_persistent_data=True
    scene.render.use_motion_blur=False
    if mode=='probe':
        selected=[0,60,120,220,247,270,279,310,340,380];folder=OUT/'probe';scene.cycles.samples=32
    elif mode in ('motion','patch'):
        selected=list(range(0,N,2));folder=OUT/'motion';scene.cycles.samples=24
        if mode=='patch':selected=[f for f in selected if 232<=f<=272 or 280<=f<=302 or f>=364]
        if mode=='patch' and '--arm-update' in sys.argv:
            selected=[f for f in range(0,N,2) if not (274<=f<=278 or 324<=f<=362)]
    elif mode=='draft':
        selected=list(range(N));folder=OUT/'frames';scene.cycles.samples=48
    elif mode=='blocking':
        selected=list(range(N));folder=OUT/'blocking'
        for ob in scene.objects:
            ancestry=[];parent=ob
            while parent:ancestry.append(parent.name);parent=parent.parent
            actor=next((name for name in ('axe_root','rubick_root') if name in ancestry),None)
            if not actor:
                if ob.type!='CAMERA':ob.hide_render=True
                continue
            if ob.type=='MESH':
                ob.color=(.48,.12,.07,1) if actor=='axe_root' else (.14,.24,.19,1)
                if any(word in ob.name for word in ('weapon','armor','staff','shoulder')):ob.color=(.25,.29,.34,1)
                if 'belt' in ob.name:ob.color=(.20,.15,.10,1)
        bpy.ops.mesh.primitive_plane_add(size=80)
        ground=bpy.context.object;ground.name='Movement review ground';ground.color=(.20,.22,.24,1)
        scene.use_nodes=False;scene.render.film_transparent=False
        scene.render.engine='BLENDER_WORKBENCH'
        scene.display.shading.light='STUDIO';scene.display.shading.color_type='OBJECT'
        scene.display.shading.background_type='WORLD';scene.world.color=(.06,.07,.08)
        scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True
        scene.render.resolution_x=640;scene.render.resolution_y=360;scene.render.resolution_percentage=100
    else:raise ValueError(mode)
    if '--overview' in sys.argv:
        cam=scene.camera;cam.animation_data_clear();cam.data.animation_data_clear()
        scene.render.resolution_x=640;scene.render.resolution_y=360;scene.render.resolution_percentage=100
        target=Vector((0,.35,2.3));cam.location=Vector((-8.5,-4.55,3.7))
        cam.data.type='ORTHO';cam.data.ortho_scale=10.8
        cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=23
    if '--frames' in sys.argv:
        selected=[int(f) for f in sys.argv[sys.argv.index('--frames')+1].split(',')]
    if '--overview' in sys.argv:
        from bpy_extras.object_utils import world_to_camera_view
        actors=[o for root_name in ('axe_root','rubick_root')
                for o in scene.objects[root_name].children_recursive
                if o.type=='MESH' and not o.hide_render]
        bounds=[float('inf'),-float('inf'),float('inf'),-float('inf')]
        for f in selected:
            scene.frame_set(f);graph=bpy.context.evaluated_depsgraph_get()
            for ob in actors:
                ev=ob.evaluated_get(graph)
                for corner in ev.bound_box:
                    point=world_to_camera_view(scene,cam,ev.matrix_world@Vector(corner))
                    bounds[0]=min(bounds[0],point.x);bounds[1]=max(bounds[1],point.x)
                    bounds[2]=min(bounds[2],point.y);bounds[3]=max(bounds[3],point.y)
        width=cam.data.ortho_scale;height=width*scene.render.resolution_y/scene.render.resolution_x
        orientation=cam.rotation_euler.to_quaternion()
        cam.location+=orientation@Vector((((bounds[0]+bounds[1])*.5-.5)*width,
                                         ((bounds[2]+bounds[3])*.5-.5)*height,0))
        cam.data.ortho_scale*=max((bounds[1]-bounds[0])/.90,(bounds[3]-bounds[2])/.86)
        (OUT/'overview_fit.json').write_text(json.dumps({'sampled_frames':len(selected),
            'before':bounds,'margin':[.05,.07],'ortho_scale':cam.data.ortho_scale},indent=2))
    if os.environ.get('DOOMSDAY_FRAME_DIR'):folder=Path(os.environ['DOOMSDAY_FRAME_DIR'])
    folder.mkdir(exist_ok=True,parents=True);manifest=folder/'manifest.json'
    baseline=None
    if mode=='patch':
        baseline=json.loads(manifest.read_text())
        if baseline['source_frames']!=list(range(0,N,2)):raise ValueError('Patch requires complete motion manifest')
        for f,digest in zip(baseline['source_frames'],baseline['frame_sha256']):
            if f not in selected and hashlib.sha256((folder/f'{f:04d}.png').read_bytes()).hexdigest()!=digest:
                raise ValueError(f'Untouched frame changed: {f}')
        receipt=OUT/'motion_before_patch.json'
        if not receipt.exists():receipt.write_text(json.dumps(baseline,indent=2))
    else:manifest.unlink(missing_ok=True)
    hashes=[]
    for f in selected:
        scene.frame_set(f);scene.render.filepath=str(folder/f'{f:04d}.png')
        bpy.ops.render.render(write_still=True)
        hashes.append(hashlib.sha256(Path(scene.render.filepath).read_bytes()).hexdigest())
        inspect_frames=([int(n) for n in sys.argv[sys.argv.index('--inspect-frames')+1].split(',')]
                        if '--inspect-frames' in sys.argv else selected)
        if '--inspect-arms' in sys.argv and f in inspect_frames:
            original=scene.camera;cam=original.copy();cam.data=original.data.copy()
            cam.animation_data_clear();cam.data.animation_data_clear()
            scene.collection.objects.link(cam);scene.camera=cam
            target=axe.matrix_world@axe.pose.bones['spine3'].head
            for label,offset in (('left',Vector((-4.3,0,.3))),('right',Vector((4.3,0,.3)))):
                cam.location=target+offset;cam.rotation_euler=(-offset).to_track_quat('-Z','Y').to_euler()
                cam.data.lens=44;cam.data.dof.focus_distance=offset.length
                scene.render.filepath=str(folder/f'{f:04d}_{label}.png');bpy.ops.render.render(write_still=True)
            scene.camera=original;bpy.data.objects.remove(cam,do_unlink=True)
    result={'source_frames':selected,'fps':15 if mode in ('motion','patch') else 30,
        'frame_sha256':hashes,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if baseline:
        merged=dict(zip(baseline['source_frames'],baseline['frame_sha256']))
        merged.update(zip(selected,hashes))
        result.update(source_frames=baseline['source_frames'],frame_sha256=[merged[f] for f in baseline['source_frames']],
                      patch_frames=selected,baseline_script_sha256=baseline['script_sha256'],
                      patch_kind='arm_update' if '--arm-update' in sys.argv else 'motion_update')
    manifest.write_text(json.dumps(result,indent=2))
    if '--cycles-probes' in sys.argv:
        scene.render.engine='CYCLES';scene.cycles.samples=32
        scene.render.resolution_x=540;scene.render.resolution_y=960;scene.render.resolution_percentage=100
        cameras(scene,axe,rubick,contact)
        probe=OUT/'probe';probe.mkdir(exist_ok=True)
        for f in (120,216,250,279,287,300,314,375,405):
            scene.frame_set(f);scene.render.filepath=str(probe/f'{f:04d}.png')
            bpy.ops.render.render(write_still=True)


if __name__=='__main__':main()
