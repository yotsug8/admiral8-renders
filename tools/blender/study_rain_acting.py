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
    rig.update_tag()
    bpy.context.view_layer.update()
    basis = {b.name: b.matrix_basis.copy() for b in bones}
    authored=('FK-Upperarm.L','FK-Upperarm.R','FK-Forearm.L','FK-Forearm.R',
              'FK-Hand.L','FK-Spine','FK-Chest','FK-Scarf1','FK-Neck','FK-Head',
              'TGT-Eye.L','TGT-Eye.R','MSTR-Eyebrow.L','MSTR-Eyebrow.R')

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

    def pose(t):
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
    camera.data.ortho_scale = 1.95
    aim(camera,(.28,0,.90))
    scene.camera = camera
    for name,loc,power,size,color in [('Key',(-3,-4,5),550,4,(1,.87,.74)),('Fill',(3,-2,3),300,3,(.7,.83,1)),('Rim',(1,3,4),650,3,(1,.95,.8))]:
        bpy.ops.object.light_add(type='AREA',location=loc)
        light=bpy.context.object
        light.name=name;light.data.energy=power;light.data.size=size;light.data.color=color
        aim(light,(0,0,1))
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.01))
    bpy.context.object.data.materials.append(material('Slate',(.055,.075,.09)))
    bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.13,depth=.98,location=(ORB.x,ORB.y,.49))
    bpy.context.object.data.materials.append(material('Pedestal',(.06,.10,.14),.35))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=.10,location=ORB)
    bpy.context.object.name='Temptation'
    bpy.context.object.data.materials.append(material('Copper',(.65,.16,.035),.5))
    bpy.ops.object.shade_smooth()
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
    # Check continuity before spending time on images; this does not prove skin quality.
    tracked=('FK-Head','FK-Hand.L','FK-Hand.R','FK-Forearm.L')
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
        segments=[('FK-Upperarm.L','FK-Forearm.L',.055),('FK-Forearm.L','FK-Hand.L',.045)]
        for finger in ('Thumb','Index','Middle','Ring','Pinky'):
            segments.extend([('FK-Hand.L',f'FK-{finger}1.L',.025),
                             (f'FK-{finger}1.L',f'FK-{finger}3.L',.02)])
        for start,end,radius in segments:
            a=bones[start].matrix.translation;b=bones[end].matrix.translation
            line=b-a;t=max(0,min(1,(ORB-a).dot(line)/max(1e-12,line.length_squared)))
            clearance=(ORB-(a+line*t)).length-.10-radius
            if clearance<min_orb_clearance:min_orb_clearance=clearance;closest_frame=frame
            if clearance<0:raise RuntimeError(f'Arm/prop capsule overlap at {frame}: {start}, {clearance}')
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
    report['continuity']={'samples':len(check_frames),'whole_clip':args.render,'max_step_m':max_step,'max_angle_deg':max_angle,'worst_step_frame':worst_step,'worst_angle_frame':worst_angle}
    report['arm_prop_capsules']={'minimum_clearance_m':min_orb_clearance,'closest_frame':closest_frame,'scope':'Arm/fingers versus sphere only; not all surface intersections'}
    (out/'preflight.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if max(max_step.values())>.06 or max(max_angle.values())>20:
        raise RuntimeError('Control discontinuity; see preflight.json')
    for name,hidden in viewport_flags.items():bpy.data.objects[name].hide_viewport=hidden
    update()
    for frame in frames:
        for name,matrix in cached[frame].items():bones[name].matrix_basis=matrix
        update()
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
