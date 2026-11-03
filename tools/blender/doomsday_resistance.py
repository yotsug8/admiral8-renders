"""Continue a stopped strike with an asymmetric, sustained whole-body effort.

Uses the saved revision_alive assembly and its contact constraints as input.
Constraint stability is not a surface-grasp or artistic acceptance test.
The grounded trial is rejected; only the airborne pose family is retained.
Review the 286..419 continuation before any beauty render or voice replacement.
"""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import doomsday_performance as motion
import doomsday_attack as attack
import doomsday_arm_controls as controls
from doomsday_native_pressure import hinge,write_pose
from doomsday_hand_orientation import required_hand_angles
from doomsday_pressure_study import main_rig
from doomsday_alive import phrase

SOURCE=ROOT/'_game/skits/doomsday/v12/revision_alive/assembly.blend'
OUT=ROOT/'_game/skits/doomsday/v12/resistance'


def state_from_scene(scene):
    actors={n:main_rig(scene,n) for n in ('axe','rubick')}
    scene.frame_set(0)
    standing=motion.snapshot(actors['axe'])
    scene.frame_set(286)
    base=motion.snapshot(actors['axe'])
    control=bpy.data.objects['DoomsdayArmControls_L']
    control.matrix_world=controls._space(actors['axe'],'L')
    recipe=json.loads(Path(__file__).with_name('doomsday_contact_pose.json').read_text(encoding='utf8'))
    fingers={side:{b.name:base['wrist_'+side].inverted()@base[b.name]
                  for b in actors['axe'].pose.bones['wrist_'+side].children_recursive
                  if b.name!='axe_1' and not b.name.startswith('chain_')}
             for side in ('L','R')}
    weapon=next(o for o in scene.objects if o.type=='MESH' and 'axe_weapon' in o.name)
    evaluated=weapon.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
    tree=BVHTree.FromPolygons([evaluated.matrix_world@v.co for v in mesh.vertices],[tuple(p.vertices) for p in mesh.polygons])
    point,normal,_,_=tree.find_nearest(base['wrist_L'].translation)
    direction=(base['wrist_L'].translation-point).normalized()
    evaluated.to_mesh_clear()
    return (scene,actors,{'axe':[base]}, {'axe':{225:base}},{'standing':standing,'withdraw':direction},None,
            control,Vector(recipe['pole_local']),base['wrist_R'].inverted()@base['axe_1'],
            base['axe_1'].inverted()@base['wrist_L'],fingers)


def pose_at(state,frame):
    arm=state[1]['axe'];base=state[2]['axe'][0]
    pose=attack.copy_pose(base)
    action_frame=min(419,286+(frame-286)*133/93)
    def curve(*keys):return phrase(action_frame,keys)
    # One change of leverage: torso coils, the right knee comes forward,
    # then chest opens into the pull. No periodic pelvis or knee oscillation.
    motion.branch(arm,pose,'spine1',math.radians(curve((286,0),(309,9),(346,3),(419,1))),'X')
    motion.branch(arm,pose,'spine2',math.radians(curve((286,0),(314,-10),(346,-12),(419,-6))),'Z')
    motion.branch(arm,pose,'elbow_R',math.radians(curve((286,0),(303,-5),(331,-22),(419,-25))),
                  hinge(pose,('bicep_R','elbow_R','wrist_R')))
    wrist_position=pose['wrist_R'].translation.copy()
    pose['wrist_R']=base['wrist_R'].copy();pose['wrist_R'].translation=wrist_position
    pose=motion.shift(pose,base['wrist_R'].translation-wrist_position)
    for side,thigh,knee in (
        ('R',curve((286,0),(318,-32),(370,-15),(419,-12)),curve((286,0),(302,-12),(332,18),(419,9))),
        ('L',curve((286,0),(310,12),(352,18),(419,15)),curve((286,0),(317,-22),(380,-12),(419,-10)))):
        motion.branch(arm,pose,'thigh_'+side,math.radians(thigh),'X')
        motion.branch(arm,pose,'knee_'+side,math.radians(knee),hinge(pose,tuple(n+'_'+side for n in ('thigh','knee','ankle'))))
    motion.branch(arm,pose,'head',math.radians(curve((286,0),(309,7),(341,-5),(368,-9),(419,-11))),'X')
    motion.branch(arm,pose,'head',math.radians(curve((286,0),(322,0),(351,9),(379,9),(419,3))),'Z')
    result,grip=attack.grip(state,pose)
    if grip['reach_error']>.002 or grip['orientation_error']>.5:
        raise ValueError(f'Unverified grasp at frame {frame}: {grip}')
    # The failed pull ends with a deliberate release of the upper hand.
    # Fingers open first, then the whole arm returns beside the torso while
    # the right hand continues to hold the stopped weapon.
    standing=state[4]['standing']
    opening=phrase(frame,((345,0),(356,1),(419,1)))
    opened=attack.copy_pose(result)
    for bone in arm.pose.bones['wrist_L'].children_recursive:
        opened[bone.name]=result['wrist_L']@arm.data.bones['wrist_L'].matrix_local.inverted()@bone.bone.matrix_local
    result=motion.mix(arm,result,opened,opening)
    release=phrase(frame,((356,0),(365,1),(419,1)))
    lower=phrase(frame,((365,0),(410,1),(419,1)))
    if frame>356:
        carry=result['clavicle_L']@standing['clavicle_L'].inverted()
        rest_hand=carry@standing['wrist_L'];rest_elbow=carry@standing['elbow_L']
        hand=result['wrist_L'].copy();direction=state[4]['withdraw']
        waypoint=hand.translation+direction*.22
        hand.translation=hand.translation.lerp(waypoint,release).lerp(rest_hand.translation,lower)
        hand.translation+=direction*.18*math.sin(math.pi*lower)
        orientation=result['wrist_L'].to_quaternion().slerp(rest_hand.to_quaternion(),lower)
        control=state[6];write_pose(arm,result);control.matrix_world=controls._space(arm,'L')
        bpy.context.view_layer.update()
        bpy.data.objects[control['target']].location=control.matrix_world.inverted()@hand.translation
        current_pole=control.matrix_world@state[7]
        bpy.data.objects[control['pole']].location=control.matrix_world.inverted()@current_pole.lerp(rest_elbow.translation,lower)
        angles,error=required_hand_angles(control,orientation)
        for name,value in angles.items():control[name]=value
        controls.apply_controls(control);result=motion.snapshot(arm)
        error_position=(result['wrist_L'].translation-hand.translation).length
        if error_position>.002:raise ValueError(f'Release target unreachable at {frame}: {error_position}')
        relaxed=attack.copy_pose(result)
        for bone in arm.pose.bones['wrist_L'].children_recursive:
            relaxed[bone.name]=result['wrist_L']@standing['wrist_L'].inverted()@standing[bone.name]
        result=motion.mix(arm,result,relaxed,lower)
    grip['left_hold']=1-release
    return result,grip


def isolate(scene):
    for ob in scene.objects:
        visible=ob.type=='MESH' and ('models\\heroes\\' in ob.name or ob.name=='AttackReviewFloor')
        if ob.type not in ('CAMERA',):
            ob.hide_render=not visible
            ob.hide_set(not visible)
    scene.render.engine='BLENDER_WORKBENCH'
    scene.display.shading.color_type='TEXTURE'
    for material in bpy.data.materials:
        if not material.use_nodes:continue
        tree=material.node_tree
        shader=next((n for n in tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if shader is None:continue
        queue=[link.from_node for link in shader.inputs['Base Color'].links];seen=set()
        while queue:
            node=queue.pop(0)
            if node in seen:continue
            seen.add(node)
            if node.type=='TEX_IMAGE' and node.image:
                tree.nodes.active=node;break
            queue.extend(link.from_node for socket in node.inputs for link in socket.links)
    scene.display.shading.light='STUDIO'
    scene.display.shading.show_shadows=True
    scene.render.resolution_x,scene.render.resolution_y=960,540
    scene.render.resolution_percentage=100
    scene.render.use_compositing=False


def fit_review_camera(scene,camera):
    rotation=camera.rotation_euler.to_matrix();inverse=rotation.transposed();points=[]
    for frame in range(237,420):
        scene.frame_set(frame);graph=bpy.context.evaluated_depsgraph_get()
        for ob in scene.objects:
            if ob.type!='MESH' or 'models\\heroes\\' not in ob.name:continue
            evaluated=ob.evaluated_get(graph)
            points.extend(inverse@(evaluated.matrix_world@Vector(p)) for p in evaluated.bound_box)
    low=[min(p[i] for p in points) for i in (0,1)];high=[max(p[i] for p in points) for i in (0,1)]
    center=inverse@camera.location;center.x=(low[0]+high[0])*.5;center.y=(low[1]+high[1])*.5
    camera.location=rotation@center
    camera.data.ortho_scale=max(high[0]-low[0],(high[1]-low[1])*16/9)*1.10


def build():
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    scene=bpy.context.scene
    arm=main_rig(scene,'axe')
    original=[]
    for frame in range(420):
        scene.frame_set(frame);original.append(motion.snapshot(arm))
    state=state_from_scene(scene)
    arm.animation_data_clear()
    poses=original[:286];reports=[]
    for frame in range(286,420):
        scene.frame_set(frame)
        pose,grip=pose_at(state,frame)
        poses.append(pose)
        reports.append({'frame':frame,**grip,'root':list(pose['root'].translation),
                        'head':list(pose['head'].translation),
                        'weapon_matrix_error':max(abs(pose['axe_1'][i][j]-original[286]['axe_1'][i][j]) for i in range(4) for j in range(4))})
    motion.bake(arm,poses)
    isolate(scene)
    # The fixed review shot reveals legs and body through the complete action.
    cam=bpy.data.objects.new('Resistance overview',bpy.data.cameras.new('Resistance overview'))
    scene.collection.objects.link(cam)
    target=Vector((0,-1.7,1.75))
    cam.location=target+Vector((8,-6,1.3))
    cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.type='ORTHO';cam.data.ortho_scale=7.8
    scene.timeline_markers.clear();scene.camera=cam
    fit_review_camera(scene,cam)
    scene.frame_start,scene.frame_end=237,419
    scene.frame_set(331)
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'airborne_release_v2.blend'),compress=True)
    (OUT/'airborne_release_v2_report.json').write_text(json.dumps({'frames':reports,
        'intent':'Blocked airborne attack, asymmetric continued effort, then upper hand opens and releases after the failed pull',
        'left_finger_opening':[345,356],'left_arm_release':[356,410],
        'camera_fit':'All evaluated hero bounding boxes across 183 frames, 10 percent margin',
        'review':'Pose probe only; full motion and skin review pending'},indent=2),encoding='utf8')
    return scene


def render(timing=False):
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'airborne_release_v2.blend'))
    scene=bpy.context.scene
    scene.view_settings.exposure=.6
    folder=OUT/('airborne_timing_frames' if timing else 'airborne_release_v2_frames')
    folder.mkdir(exist_ok=True)
    # Keep takeoff and interception at their original speed. The continued
    # effort has one attempt and one release, not a four-second tableau.
    samples=(list(range(237,286))+[286+i*133/59 for i in range(60)]
             if timing else list(range(237,420)))
    for index,frame in enumerate(samples):
        scene.frame_set(math.floor(frame),subframe=frame-math.floor(frame))
        number=index if timing else int(frame)
        scene.render.filepath=str(folder/f'{number:04d}.png')
        bpy.ops.render.render(write_still=True)
    if timing:
        (OUT/'airborne_timing_map.json').write_text(json.dumps({
            'fps':30,'source_frames':samples,'contact_output_frame':49,
            'scope':'Timing comparison only; no change to the source poses'},indent=2),encoding='utf8')


if __name__=='__main__':
    if '--render' in sys.argv:render('--timing-test' in sys.argv)
    else:build()
