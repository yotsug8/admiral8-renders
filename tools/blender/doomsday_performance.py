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
from mathutils import Matrix, Vector, Quaternion

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('DOOMSDAY_RUN_DIR',str(ROOT/'_game/skits/doomsday/v7')))
SOURCE=ROOT/'_game/skits/doomsday/v3/scene.blend'
sys.path.insert(0,str(Path(__file__).resolve().parent))
from contact_reaction import _basis, _solve_leg
from doomsday_refine import gpu, smooth
from doomsday_atmosphere import environment, glow, filament

N=420
LIFT=231
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


def solve_arm(arm,pose,side,target):
    """Two-bone solve with an authored elbow plane in front of the chest."""
    chain=tuple(n+'_'+side for n in ('bicep','elbow','wrist'))
    h,k,w=(pose[n].translation.copy() for n in chain)
    upper,lower=(k-h).length,(w-k).length
    axis=target.translation-h;distance=axis.length;direction=axis.normalized()
    if distance>upper+lower or distance<abs(upper-lower):raise ValueError('Unreachable arm target')
    pole=Vector((1,-.8,-.4)) if side=='L' else Vector((-1,-.65,-1.3))
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


def author(scene,axe,rubick):
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
    times=sorted(set(range(N))|{q/8 for q in range(230*8,(N-1)*8+1)})
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


def cameras(scene,axe,rubick,contact):
    cam=scene.camera;cam.animation_data_clear();cam.data.animation_data_clear()
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
        elif f<LIFT:
            target=Vector((-.2,2.2,2.5));pos=Vector((-5,-5,2.1));lens=38
        elif f<273:
            target=ahead+Vector((.20,-.10,.45))
            sweep=smooth((f-262)/10)
            tip=axe.matrix_world@axe.pose.bones['axe_1'].matrix@tip_local
            target=target.lerp(ahead.lerp(tip,.35)+Vector((0,0,.15)),sweep)
            pos=Vector((-4.8,-3.6,3.1));lens=48-4*sweep
        elif f<HIT:
            target=rhead;pos=target+Vector((.6,2.8,.08));lens=60
        elif f<316:
            target=contact+Vector((0,.55,-.15));pos=target+Vector((4.5,-4,.2));lens=32
        elif f<324:
            target=contact;pos=target+Vector((3.5,-.8,.5));lens=65
        elif f<363:
            target=rhead;pos=target+Vector((.6,2.8,.08));lens=60
        else:
            target=face_targets[390]+Vector((0,0,-.13));pos=target+Vector((-2.3,-2.5,.25));lens=48
        cam.location=pos;cam.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler();cam.data.lens=lens
        cam.data.dof.focus_distance=(target-pos).length;cam.data.dof.aperture_fstop=4 if f<45 or 195<=f<316 else 2.5
        for key in ('location','rotation_euler'):cam.keyframe_insert(key,frame=f)
        for key in ('lens','dof.focus_distance','dof.aperture_fstop'):cam.data.keyframe_insert(key,frame=f)
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
            for name,value in {'jawOpen':.10+.45*speak+.20*shock-.15*disbelief,
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
    poses,defender,contact=author(scene,axe,rubick)
    environment(scene);glow(scene);cameras(scene,axe,rubick,contact);face(scene)
    # Pale masonry is too prominent from the new reverse angles; preserve its
    # native maps while toning it down into the surrounding stone palette.
    for ob in scene.objects:
        if ob.type!='MESH' or 'statue' not in ob.name.lower():continue
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
    from doomsday_performance_fx import apply
    fx=apply(scene,axe,rubick,contact)
    (OUT/'fx.json').write_text(json.dumps(fx,indent=2))
    if '--audit' in sys.argv:
        import doomsday_performance_qa as qa
        qa.OUT=OUT
        qa.audit(scene,axe,rubick,contact,poses,defender)
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
        scene.render.engine='BLENDER_WORKBENCH'
        scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL'
        scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True
        scene.render.resolution_x=360;scene.render.resolution_y=640;scene.render.resolution_percentage=100
    else:raise ValueError(mode)
    if '--overview' in sys.argv:
        cam=scene.camera;cam.animation_data_clear();cam.data.animation_data_clear()
        scene.render.resolution_x=640;scene.render.resolution_y=360;scene.render.resolution_percentage=100
        target=Vector((0,-.4,2.0));cam.location=Vector((-8.0,0,3.1))
        cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=24
    if '--frames' in sys.argv:
        selected=[int(f) for f in sys.argv[sys.argv.index('--frames')+1].split(',')]
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
        if '--inspect-arms' in sys.argv:
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
