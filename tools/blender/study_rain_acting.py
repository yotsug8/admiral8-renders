"""Authored acting study on the official Rain rig, with embedded scripts disabled.

Not a general action preset. Default: seven pose cards and a control-continuity report.
--render: 180 frames at 30 fps. External asset and limitations: ACTING_RIG_CANDIDATES.md.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '_game/external/rain_v33/Rain v3.3/rain_v3.2.blend'
ORB=Vector((.68,-.48,1.07))


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--surprise', action='store_true', help='Transfer acting to an animated obstacle and protective step')
    parser.add_argument('--frames', help='Comma-separated diagnostic frames')
    parser.add_argument('--engine', choices=('CYCLES','BLENDER_EEVEE'), default='CYCLES')
    parser.add_argument('--view', choices=('front','side','back'), default='front')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    frames=list(range(180)) if args.render else [0,28,64,80,110,140,179]
    if args.frames:frames=[int(f) for f in args.frames.split(',')]
    if not frames or any(f<0 or f>=180 for f in frames):raise ValueError('Frames must be in 0..179')
    check_frames=list(range(180)) if args.render else sorted({f for x in frames for f in (max(0,x-1),x,min(179,x+1))})
    out = Path(args.out).resolve()
    if not out.is_relative_to((ROOT / '_game/study').resolve()):
        raise ValueError('Study output must stay below _game/study')
    out.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out).free < 128*1024**2:
        raise RuntimeError('Less than 128 MiB free; no render started')
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    scene = bpy.context.scene
    rig = bpy.data.objects['RIG-rain']
    bones = rig.pose.bones
    for key in ('ik_arm_left', 'ik_arm_right', 'ik_fingers_left', 'ik_fingers_right', 'ik_spine'):
        bones['Properties_IKFK'][key] = 0
    if args.surprise:
        for key in ('ik_arm_left','ik_arm_right','ik_leg_left','ik_leg_right'):
            bones['Properties_IKFK'][key]=1
        for key in ('ik_stretch_arms','ik_stretch_legs'):
            bones['Properties_IKFK'][key]=0
    rig.update_tag()
    bpy.context.view_layer.update()
    basis = {b.name: b.matrix_basis.copy() for b in bones}
    authored=('FK-Upperarm.L','FK-Upperarm.R','FK-Forearm.L','FK-Forearm.R',
              'FK-Hand.L','FK-Spine','FK-Chest','FK-Scarf1','FK-Neck','FK-Head',
              'TGT-Eye.L','TGT-Eye.R','MSTR-Eyebrow.L','MSTR-Eyebrow.R')
    if args.surprise:
        authored+=('MSTR-Pelvis','MSTR-Foot.L','MSTR-Foot.R','IK-Hand.L','IK-Hand.R',
                   'IK-Pole-Forearm.L','IK-Pole-Forearm.R','MSTR-Jaw',
                   'ACT-Lips_Corner.L','ACT-Lips_Corner.R')+tuple(f'FK-Hair_Ponytail{i}' for i in range(1,5))
    rest={b.name:b.matrix.copy() for b in bones}

    def update():
        bpy.context.view_layer.update()

    def rotate(name, axis, degrees):
        bone = bones[name]
        matrix = bone.matrix.copy()
        pivot = matrix.translation
        bone.matrix = (Matrix.Translation(pivot)
                       @ Quaternion(Vector(axis), math.radians(degrees)).to_matrix().to_4x4()
                       @ Matrix.Translation(-pivot) @ matrix)
        update()

    def move(name, delta=None, target=None):
        matrix = bones[name].matrix.copy()
        matrix.translation = Vector(target) if target is not None else matrix.translation + Vector(delta)
        bones[name].matrix = matrix
        update()

    def blend(t, start, duration):
        x = max(0., min(1., (t-start)/duration))
        return x*x*x*(10+x*(-15+6*x))

    def obstacle(t):
        wake=blend(t,1.90,.30)
        settle=blend(t,2.30,.60)
        return ORB+Vector((-.10*wake,.04*wake,.26*wake-.09*settle))

    def hand_rotation(side,direction,normal):
        wrist=rest['FK-Hand.'+side].translation
        finger=(rest['FK-Middle3.'+side].translation-wrist).normalized()
        old_normal=(rest['FK-Index1.'+side].translation-wrist).cross(rest['FK-Pinky1.'+side].translation-wrist).normalized()
        if old_normal.z<0:old_normal=-old_normal
        direction=Vector(direction).normalized()
        normal=Vector(normal);normal=(normal-direction*normal.dot(direction)).normalized()
        q=finger.rotation_difference(direction);current=q@old_normal
        angle=math.atan2(direction.dot(current.cross(normal)),current.dot(normal))
        return Quaternion(direction,angle)@q@rest['FK-Hand.'+side].to_quaternion()

    def surprise_pose(t):
        for name in authored:bones[name].matrix_basis=basis[name]
        update()
        notice=blend(t,.20,.55)
        reach=blend(t,.65,1.0)
        recoil=blend(t,2.06,.32)
        arms=blend(t,2.06,.58)
        recover=blend(t,3.05,.85)
        peek=blend(t,4.30,1.05)
        load=blend(t,2.10,.22)*(1-blend(t,2.85,.50))
        stride=blend(t,2.32,.62)
        lift=.075*math.sin(math.pi*stride)
        back=.14*blend(t,2.20,.72)
        lean=8*reach*(1-recoil)-14*recoil+8*recover+8*peek
        move('MSTR-Pelvis',delta=(.055*load,back,-.055-.055*recoil+.018*recover))
        move('MSTR-Foot.L',delta=(.05,-.08,0))
        move('MSTR-Foot.R',delta=(-.05,-.08+.28*stride,lift))
        rotate('FK-Spine',(1,0,0),lean*.45)
        rotate('FK-Chest',(1,0,0),lean*.55)
        rotate('FK-Chest',(0,0,1),10*notice-6*recoil+5*peek)
        rotate('FK-Scarf1',(1,0,0),min(0,-lean*.65))
        rotate('FK-Head',(1,0,0),14*notice+16*recoil-18*recover+3*peek)
        rotate('FK-Head',(0,0,1),32*notice+12*recoil-8*recover+7*peek)
        rotate('MSTR-Jaw',(1,0,0),9*recoil-7*recover)
        move('MSTR-Eyebrow.L',delta=(0,0,.005*notice+.014*recoil-.010*recover+.009*peek))
        move('MSTR-Eyebrow.R',delta=(0,0,.003*notice+.014*recoil-.013*recover))
        for side in ('L','R'):bones['ACT-Lips_Corner.'+side].location.y=-.004*recoil
        update()
        head_delta=bones['FK-Head'].matrix.to_quaternion()@rest['FK-Head'].to_quaternion().inverted()
        for i,droop in enumerate((10,25,20,10),1):
            # One delayed response to the startle, not perpetual decorative wobble.
            drag=6*blend(t,2.12+.04*i,.25)*(1-blend(t,2.65+.04*i,.45))
            rotate(f'FK-Hair_Ponytail{i}',head_delta@Vector((1,0,0)),-droop+drag)
        target=Vector((0,-2,1.4)).lerp(obstacle(t),blend(t,.12,.28))
        for side,sign in (('L',1),('R',-1)):
            relaxed=Vector((sign*.23,-.08+back,.86))
            reaching=Vector((.34,-.26,1.12)) if side=='L' else relaxed
            guarded=Vector((sign*.27,back-.18,1.25 if side=='L' else 1.18))
            final=Vector((.26,back-.18,1.13)) if side=='L' else relaxed
            location=relaxed.lerp(reaching,reach).lerp(guarded,recoil if side=='L' else arms).lerp(final,recover)
            if side=='R':location+=Vector((sign*.08,-.10,0))*math.sin(math.pi*arms)*(1-recover)
            q0=hand_rotation(side,(0,0,-1),(-sign,0,0))
            q1=hand_rotation(side,(.8,-.5,-.1),(0,0,1)) if side=='L' else q0
            q2=hand_rotation(side,(0,0,1),(0,1,0))
            q=q0.slerp(q1,reach).slerp(q2,arms).slerp(q0,recover*(.2 if side=='L' else 1))
            bones['IK-Hand.'+side].matrix=Matrix.LocRotScale(location,q,Vector((1,1,1)))
            update()
            move('IK-Pole-Forearm.'+side,target=(sign*.58,back-.06,.97))
            move('TGT-Eye.'+side,target=target)

    def pose(t):
        if args.surprise:
            surprise_pose(t)
            return
        for name in authored:
            bones[name].matrix_basis = basis[name]
        update()
        notice = blend(t, .35, .6)
        refuse = blend(t, 1.25, .85)
        reconsider = blend(t, 3.05, .95)
        reach = blend(t, 4.0, 1.05)
        refuse *= 1-reconsider
        rotate('FK-Upperarm.L', (0,1,0), 67-60*refuse)
        rotate('FK-Upperarm.R', (0,1,0), -70)
        rotate('FK-Forearm.L', (1,0,0), -15)
        rotate('FK-Forearm.R', (1,0,0), -12)
        rotate('FK-Forearm.L', (0,1,0), -95*refuse)
        rotate('FK-Hand.L', (0,0,1), -55*refuse)
        rotate('FK-Spine', (1,0,0), 5*reach-3*refuse)
        rotate('FK-Chest', (0,0,1), 12*notice-22*refuse+6*reach)
        rotate('FK-Chest', (1,0,0), 5*reach)
        rotate('FK-Scarf1', (1,0,0), -8*reach)
        rotate('FK-Neck', (0,0,1), 8*notice-16*refuse)
        shake = math.sin((t-1.8)*math.tau/0.72)*4 if 1.8<t<2.52 else 0
        # Windowed shake, zero velocity at both ends.
        shake *= blend(t,1.8,.16)*(1-blend(t,2.36,.16))
        rotate('FK-Head', (0,0,1), 36*notice-54*refuse+shake)
        rotate('FK-Head', (1,0,0), 20*notice-26*refuse+4*reach)
        # Gaze changes before the head; the target remains a world-space intention.
        look = blend(t,.22,.25)
        target = Vector((0,-2,1.4)).lerp(ORB,look)
        target = target.lerp(Vector((-.8,-2,1.5)), refuse*.75)
        # The group target has an Armature constraint; writing its matrix would
        # apply the parent-space switch twice. Its two child controls are free.
        for side in ('L','R'):
            move('TGT-Eye.'+side, target=target)
        move('MSTR-Eyebrow.L', delta=(0,0,.009*notice-.011*refuse+.003*reach))
        move('MSTR-Eyebrow.R', delta=(0,0,.004*notice-.004*refuse))
        # Reach is authored through FK controls; no DEF/helper-bone editing.
        if reach:
            shoulder = bones['FK-Upperarm.L'].matrix.translation.copy()
            elbow = bones['FK-Forearm.L'].matrix.translation.copy()
            wrist = bones['FK-Hand.L'].matrix.translation.copy()
            l1, l2 = (elbow-shoulder).length, (wrist-elbow).length
            target = wrist.lerp(Vector((.40,-.33,1.13)),reach)
            direction = target-shoulder
            distance = min(direction.length, (l1+l2)*.995)
            axis = direction.normalized()
            along = (l1*l1-l2*l2+distance*distance)/(2*distance)
            pole = Vector((.6,.4,-1))
            side = (pole-axis*axis.dot(pole)).normalized()
            wanted_elbow = shoulder+axis*along+side*math.sqrt(max(0,l1*l1-along*along))
            for name, end, desired in [('FK-Upperarm.L','FK-Forearm.L',wanted_elbow),('FK-Forearm.L','FK-Hand.L',target)]:
                matrix = bones[name].matrix.copy()
                pivot = matrix.translation
                q = Quaternion().slerp((bones[end].matrix.translation-pivot).rotation_difference(desired-pivot),reach)
                bones[name].matrix = Matrix.Translation(pivot)@q.to_matrix().to_4x4()@Matrix.Translation(-pivot)@matrix
                update()
            hand=bones['FK-Hand.L'];matrix=hand.matrix.copy();pivot=matrix.translation
            finger=bones['FK-Middle3.L'].matrix.translation-pivot
            desired=ORB-pivot
            q=Quaternion().slerp(finger.rotation_difference(desired),reach)
            hand.matrix=Matrix.Translation(pivot)@q.to_matrix().to_4x4()@Matrix.Translation(-pivot)@matrix
            update()

    def aim(ob, target):
        ob.rotation_euler = (Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()

    def material(name, color, metallic=0):
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = (*color,1)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (*color,1)
        bsdf.inputs['Roughness'].default_value = .38
        bsdf.inputs['Metallic'].default_value = metallic
        return mat

    for ob in list(scene.objects):
        if ob.type in ('CAMERA','LIGHT'):
            bpy.data.objects.remove(ob,do_unlink=True)
    bpy.ops.object.camera_add(location={'front':(-2.4,-6,2.2),'side':(6,-.6,2),'back':(-2.4,6,2.2)}[args.view])
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 2.15 if args.surprise else 1.95
    aim(camera,(.28,-.10,.88) if args.surprise else (.28,0,.90))
    scene.camera = camera
    for name,loc,power,size,color in [('Key',(-3,-4,5),550,4,(1,.87,.74)),('Fill',(3,-2,3),300,3,(.7,.83,1)),('Rim',(1,3,4),650,3,(1,.95,.8))]:
        bpy.ops.object.light_add(type='AREA',location=loc)
        light=bpy.context.object
        light.name=name;light.data.energy=power;light.data.size=size;light.data.color=color
        aim(light,(0,0,1))
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,.00115 if args.surprise else -.01))
    bpy.context.object.data.materials.append(material('Slate',(.055,.075,.09)))
    bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.13,depth=.98,location=(ORB.x,ORB.y,.49))
    bpy.context.object.data.materials.append(material('Pedestal',(.06,.10,.14),.35))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=.10,location=ORB)
    bpy.context.object.name='Temptation'
    bpy.context.object.data.materials.append(material('Copper',(.65,.16,.035),.5))
    bpy.ops.object.shade_smooth()
    orb=bpy.context.object
    eyes=[]
    if args.surprise:
        for dx in (-.036,.036):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=1)
            eye=bpy.context.object;eye.data.materials.append(material('Ivory eye',(.8,.85,.7)))
            eyes.append((eye,Vector((dx,-.088,.025)),Vector((.025,.014,.03))))
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=1)
            pupil=bpy.context.object;pupil.data.materials.append(material('Pupil',(.012,.018,.012)))
            eyes.append((pupil,Vector((dx,-.101,.025)),Vector((.009,.004,.014))))

    def prop_pose(t):
        if not args.surprise:return
        orb.location=obstacle(t)
        openness=.08+.92*blend(t,1.90,.16)
        for eye,offset,scale in eyes:
            eye.location=orb.location+offset
            eye.scale=Vector((scale.x,scale.y,scale.z*openness))
    scene.world=bpy.data.worlds.new('StudyWorld');scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.18,.23,.3,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.35
    scene.render.engine=args.engine;scene.cycles.device='CPU';scene.cycles.samples=16;scene.cycles.use_denoising=True
    prefs=bpy.context.preferences.addons['cycles'].preferences
    try:
        if args.engine!='CYCLES':raise RuntimeError('Cycles not requested')
        prefs.compute_device_type='OPTIX'
        prefs.get_devices()
        gpu=[d for d in prefs.devices if d.type=='OPTIX']
        if gpu:
            for device in prefs.devices:device.use=device.type=='OPTIX'
            scene.cycles.device='GPU'
    except (TypeError,RuntimeError):
        pass
    scene.render.resolution_x=640;scene.render.resolution_y=720;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
    scene.view_settings.view_transform='AgX';scene.render.fps=30
    scene.render.threads_mode='FIXED';scene.render.threads=4
    report={'source_sha256':source_hash,'credit':'Rain Rig (CC) Blender Foundation | studio.blender.org',
            'known_invalid_driver':'DEF-Spine3.bbone_easeout targets missing STR-Spine4; not changed',
            'scope':'Authored pose/acting study, not a validated full rig or collision certification', 'samples':[]}
    if args.surprise:
        report['scenario']='Animated obstacle, protective step and reconsideration'
        report['native_ik']={'max_wrist_error_m':0.,'max_ankle_error_m':0.}
        report['support']={'max_sole_error_m':0.,'checked_frames':0}
    # Check continuity before spending time on images; this does not prove skin quality.
    tracked=tuple(dict.fromkeys(authored+('FK-Hand.R',))) if args.surprise else ('FK-Head','FK-Hand.L','FK-Hand.R','FK-Forearm.L')
    continuity_names=('FK-Head','FK-Hand.L','FK-Hand.R','FK-Forearm.L','FK-Forearm.R',
                      'MSTR-Pelvis','MSTR-Foot.L','MSTR-Foot.R') if args.surprise else tracked
    previous=None;max_step={name:0. for name in tracked};max_angle={name:0. for name in tracked}
    cached={};evaluated={};worst_step={};worst_angle={};previous_frame=None
    min_orb_clearance=100.;closest_frame=None
    # Geometry is not needed for controller continuity. Restore exact viewport
    # flags before rendering and verify each evaluated control against the cache.
    viewport_flags={ob.name:ob.hide_viewport for ob in scene.objects if ob.type=='MESH'}
    for name in viewport_flags:bpy.data.objects[name].hide_viewport=True
    update()
    for frame in check_frames:
        pose(frame/30)
        cached[frame]={name:bones[name].matrix_basis.copy() for name in authored}
        current={name:bones[name].matrix.copy() for name in tracked}
        # Conservative capsules around arm and fingers; no contact is intended.
        center=obstacle(frame/30) if args.surprise else ORB
        segments=[]
        for side in (('L','R') if args.surprise else ('L',)):
            segments.extend([(f'FK-Upperarm.{side}',f'FK-Forearm.{side}',.055),(f'FK-Forearm.{side}',f'FK-Hand.{side}',.045)])
            for finger in ('Thumb','Index','Middle','Ring','Pinky'):
                segments.extend([(f'FK-Hand.{side}',f'FK-{finger}1.{side}',.025),
                                 (f'FK-{finger}1.{side}',f'FK-{finger}3.{side}',.02)])
        for start,end,radius in segments:
            a=bones[start].matrix.translation;b=bones[end].matrix.translation
            line=b-a;t=max(0,min(1,(center-a).dot(line)/max(1e-12,line.length_squared)))
            clearance=(center-(a+line*t)).length-.10-radius
            if clearance<min_orb_clearance:min_orb_clearance=clearance;closest_frame=frame
            if clearance<0:raise RuntimeError(f'Arm/prop capsule overlap at {frame}: {start}, {clearance}')
        if args.surprise:
            errors={side:{'wrist':(bones['FK-Hand.'+side].matrix.translation-bones['IK-Hand.'+side].matrix.translation).length,
                          'ankle':(bones['IK-Shin.'+side].tail-bones['IK-Foot.'+side].matrix.translation).length} for side in ('L','R')}
            for joint in ('wrist','ankle'):
                key=f'max_{joint}_error_m';report['native_ik'][key]=max(report['native_ik'][key],*(row[joint] for row in errors.values()))
            if max(v for row in errors.values() for v in row.values())>.002:
                (out/'failed.json').write_text(json.dumps({'frame':frame,'reach_errors':errors},indent=2))
                raise RuntimeError(f'Unreachable limb at {frame}')
        evaluated[frame]=current
        if previous and frame==previous_frame+1:
            for name in tracked:
                step=(current[name].translation-previous[name].translation).length
                angle=math.degrees(current[name].to_quaternion().rotation_difference(previous[name].to_quaternion()).angle)
                angle=min(angle,360-angle)
                if step>max_step[name]:max_step[name]=step;worst_step[name]=frame
                if angle>max_angle[name]:max_angle[name]=angle;worst_angle[name]=frame
        previous=current
        previous_frame=frame
        if frame%30==0:print('PREFLIGHT',frame,flush=True)
    report['continuity']={'samples':len(check_frames),'whole_clip':args.render,'max_step_m':max_step,'max_angle_deg':max_angle,'worst_step_frame':worst_step,'worst_angle_frame':worst_angle,'physical_controls':list(continuity_names)}
    report['arm_prop_capsules']={'minimum_clearance_m':min_orb_clearance,'closest_frame':closest_frame,'scope':'Arm/fingers versus sphere only; not all surface intersections'}
    (out/'preflight.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    # Eye aim points and pole targets are not physical body parts. Their travel
    # is recorded, but only evaluated body controls use the motion thresholds.
    if max(max_step[n] for n in continuity_names)>.06 or max(max_angle[n] for n in continuity_names)>20:
        raise RuntimeError('Control discontinuity; see preflight.json')
    for name,hidden in viewport_flags.items():bpy.data.objects[name].hide_viewport=hidden
    update()
    for frame in frames:
        for name,matrix in cached[frame].items():bones[name].matrix_basis=matrix
        update()
        prop_pose(frame/30)
        if args.surprise:
            dg=bpy.context.evaluated_depsgraph_get();shoe=bpy.data.objects['GEO-rain-shoes'];ev=shoe.evaluated_get(dg);mesh=ev.to_mesh()
            sole={}
            for side in ('L','R'):
                groups={g.index for g in shoe.vertex_groups if g.name.endswith('.'+side)}
                sole[side]=min((ev.matrix_world@v.co).z for v in mesh.vertices if any(g.group in groups and g.weight>.5 for g in v.groups))-.00115
            ev.to_mesh_clear()
            expected=.075*math.sin(math.pi*blend(frame/30,2.32,.62))
            sole_error=max(abs(sole['L']),abs(sole['R']-expected))
            report['support']['max_sole_error_m']=max(report['support']['max_sole_error_m'],sole_error)
            report['support']['checked_frames']+=1
            if sole_error>.002:raise RuntimeError(f'Sole support mismatch at {frame}: {sole}')
        for name in tracked:
            error=max(abs(bones[name].matrix[row][col]-evaluated[frame][name][row][col]) for row in range(4) for col in range(4))
            if error>1e-5:raise RuntimeError(f'Cached pose differs at {frame}: {name}, {error}')
        points={n:list(bones[n].matrix.translation) for n in ('FK-Head','FK-Hand.L','FK-Hand.R')}
        if not all(math.isfinite(x) for point in points.values() for x in point):
            raise RuntimeError(f'Non-finite control at {frame}')
        report['samples'].append({'frame':frame,'controls':points})
        scene.render.filepath=str(out/f'{frame:04d}.png')
        bpy.ops.render.render(write_still=True)
    report['source_unchanged']=hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('RAIN_STUDY_DONE',len(report['samples']))


if __name__=='__main__':
    run()
