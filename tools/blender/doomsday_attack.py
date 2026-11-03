"""Authored whole-body attack poses; isolated motion review before film assembly."""
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doomsday_full_scene as film
import doomsday_performance as motion
import doomsday_arm_controls as controls
from doomsday_native_pressure import write_pose, hinge
from doomsday_hand_orientation import required_hand_angles

OUT = film.OUT.parent / 'attack_rebuild'
IMPACT_LOAD = -2.2


def copy_pose(pose):
    return {name: matrix.copy() for name, matrix in pose.items()}


def grip(state, pose, hold=1):
    scene, actors, pressure, bank, manifest, data, control, pole_local, binding, left_binding, fingers = state
    arm = actors['axe']
    pose['axe_1'] = pose['wrist_R'] @ binding
    for name, local in fingers['R'].items():
        pose[name] = pose['wrist_R'] @ local
    write_pose(arm, pose)
    control.matrix_world = controls._space(arm, 'L')
    bpy.context.view_layer.update()
    target = pose['axe_1'] @ left_binding
    target_object=bpy.data.objects[control['target']]
    pole_object=bpy.data.objects[control['pole']]
    properties=('forearm_roll','hand_flex','hand_deviation')
    previous=[float(control.get(name,0)) for name in properties]
    if hold<1:
        shoulder=pose['bicep_L'].translation
        lateral=pose['bicep_L'].translation-pose['bicep_R'].translation
        lateral.z=0;lateral.normalize()
        forward=lateral.cross(Vector((0,0,1))).normalized()
        free=shoulder+lateral*.5+forward*.25+Vector((0,0,-.5))
        free_pole=shoulder+lateral*.65+forward*.1+Vector((0,0,-.28))
        target_object.location=control.matrix_world.inverted()@free
        pole_object.location=control.matrix_world.inverted()@free_pole
        for name in ('forearm_roll','hand_flex','hand_deviation'):control[name]=0.
        controls.apply_controls(control)
        orientation=(arm.matrix_world@arm.pose.bones['wrist_L'].matrix).to_quaternion().slerp(target.to_quaternion(),hold)
        position=free.lerp(target.translation,hold)+(lateral*.32+forward*.12)*math.sin(math.pi*hold)
        reach=sum((control.matrix_world.to_3x3()@(control.data.bones[n].tail_local-control.data.bones[n].head_local)).length for n in ('upper','lower'))
        if (position-shoulder).length>.98*reach:position=shoulder+(position-shoulder).normalized()*(.98*reach)
        target_object.location=control.matrix_world.inverted()@position
        pole_object.location=control.matrix_world.inverted()@free_pole.lerp(control.matrix_world@pole_local,hold)
    else:
        position=target.translation
        orientation=target.to_quaternion()
        target_object.location=control.matrix_world.inverted()@position
        pole_object.location=pole_local
    if hold==0:
        angles,error=dict.fromkeys(properties,0.),0.
    else:
        angles, error = required_hand_angles(control, orientation,initial=previous)
    for name, value in angles.items():
        control[name] = value
    controls.apply_controls(control)
    result = motion.snapshot(arm)
    reach = (result['wrist_L'].translation - position).length
    closed=copy_pose(result)
    closure=film.smooth((hold-.85)/.15)
    reference=bank['axe'][225]
    for name, local in fingers['L'].items():
        result[name]=result['wrist_L']@reference['wrist_L'].inverted()@reference[name]
        closed[name] = result['wrist_L'] @ local
    result=motion.mix(arm,result,closed,closure)
    return result, {'reach_error': reach, 'orientation_error': error,'closure':closure,'hold':hold}


def authored(state, *, drop=0, travel=0, height=0, lean=0, twist=0,
             lift=0, elbow=0, legs=None):
    arm = state[1]['axe']
    stand = motion.shift(state[3]['axe'][195], Vector((2.5, 0, 0)))
    pose = motion.shift(stand, Vector((0, -travel, height - drop)))
    lateral = (stand['bicep_R'].translation - stand['bicep_L'].translation).normalized()
    motion.branch(arm, pose, 'spine1', math.radians(lean), 'X')
    motion.branch(arm, pose, 'spine2', math.radians(twist), 'Z')
    # Reuse only the verified local right-arm articulation/grip. Torso, pelvis
    # and legs remain the independently authored standing-derived action.
    contact = state[2]['axe'][0]
    carry = pose['clavicle_R'] @ contact['clavicle_R'].inverted()
    for bone in [arm.pose.bones['bicep_R'], *arm.pose.bones['bicep_R'].children_recursive]:
        pose[bone.name] = carry @ contact[bone.name]
    upper_axis = (pose['bicep_R'].translation - pose['bicep_L'].translation).normalized()
    motion.branch(arm, pose, 'bicep_R', math.radians(lift), upper_axis)
    motion.branch(arm, pose, 'elbow_R', math.radians(elbow), hinge(pose, ('bicep_R','elbow_R','wrist_R')))
    if legs is None:
        for side in ('L','R'):
            chain = tuple(n+'_'+side for n in ('thigh','knee','ankle'))
            pose, _ = motion.solve(arm, pose, chain, stand['ankle_'+side], Vector((0,-1,0)))
    else:
        for side, (thigh, knee) in legs.items():
            motion.branch(arm, pose, 'thigh_'+side, math.radians(thigh), 'X')
            motion.branch(arm, pose, 'knee_'+side, math.radians(knee), hinge(pose, tuple(n+'_'+side for n in ('thigh','knee','ankle'))))
    return pose


def key_poses(state):
    poses = {
        195: authored(state),
        213: authored(state, drop=.26, lean=12, twist=-12, lift=55,elbow=-20),
        231: authored(state, travel=.25, height=.06, lean=-8, twist=-20, lift=95,
                      legs={'L':(-25,45),'R':(8,5)}),
        246: authored(state, travel=.85, height=.90, lean=-10, twist=-30, lift=95,
                      legs={'L':(-38,65),'R':(26,48)}),
        264: authored(state, travel=1.75, height=1.10, lean=-4, twist=-15, lift=80,
                      legs={'L':(-12,40),'R':(38,65)}),
        279: reaction(state,IMPACT_LOAD,1),
    }
    for frame,angle in ((264,20),):
        motion.branch(state[1]['axe'],poses[frame],'bicep_R',math.radians(angle),'Z')
    return poses


def reaction(state, amount, leg_lag):
    arm = state[1]['axe']
    base = state[2]['axe'][0]
    pose = copy_pose(base)
    motion.branch(arm, pose, 'spine1', math.radians(5*amount), 'X')
    motion.branch(arm, pose, 'elbow_R', math.radians(10*amount),
                  hinge(pose, ('bicep_R','elbow_R','wrist_R')))
    # The shaft stops first. Keep its complete transform while the arm bends
    # and the body's mass continues forward; do not move the defender to meet it.
    position = pose['wrist_R'].translation.copy()
    pose['wrist_R'] = base['wrist_R'].copy()
    pose['wrist_R'].translation = position
    pose = motion.shift(pose, base['wrist_R'].translation-position)
    for side, angle in (('L',10),('R',18)):
        motion.branch(arm, pose, 'thigh_'+side, math.radians(angle*leg_lag), 'X')
        motion.branch(arm, pose, 'knee_'+side, math.radians(5*leg_lag),
                      hinge(pose, tuple(n+'_'+side for n in ('thigh','knee','ankle'))))
    motion.branch(arm, pose, 'head', math.radians(-3*amount), 'X')
    return pose


def root_path(frame, state):
    start = state[3]['axe'][195]['root'].translation + Vector((2.5,0,0))
    end = reaction(state,IMPACT_LOAD,1)['root'].translation
    takeoff = start + Vector((0,-.25,.06))
    duration = (279-231)/30
    speed = (end.y-takeoff.y)/duration
    gravity = 2.5  # Deliberate slowed airborne timing; continuous ballistic arc.
    up_speed = (end.z-takeoff.z+.5*gravity*duration**2)/duration
    if frame <= 219:
        t=film.smooth((frame-195)/24)
        return start+Vector((0,0,-.30*t))
    if frame <= 231:
        t=(frame-219)/12
        p0=start+Vector((0,0,-.30))
        tangent=Vector((0,speed,up_speed))*(12/30)
        return (2*t**3-3*t*t+1)*p0+(-2*t**3+3*t*t)*takeoff+(t**3-t*t)*tangent
    t=(frame-231)/30
    return Vector((start.x+(end.x-start.x)*t/duration,
                   takeoff.y+speed*t,takeoff.z+up_speed*t-.5*gravity*t*t))


def pose_at(state, keys, frame):
    arm=state[1]['axe']
    if frame >= 279:
        amount=IMPACT_LOAD*(1-(frame-279)/6)**2 if frame<285 else motion.curve(frame,((285,0),(299,-.35),(310,-.15)))
        lag=1-film.smooth((frame-279)/12)
        return reaction(state,amount,lag)
    times=sorted(keys)
    left=max(f for f in times if f<=frame)
    right=min(f for f in times if f>frame)
    t=(frame-left)/(right-left)
    pose=motion.mix(arm,keys[left],keys[right],film.smooth(t))
    pose=motion.shift(pose,root_path(frame,state)-pose['root'].translation)
    stand=motion.shift(state[3]['axe'][195],Vector((2.5,0,0)))
    if frame<=231:
        for side in ('L','R'):
            if side=='L' and frame>219:
                continue
            goal=stand['ankle_'+side].copy()
            if side=='R' and frame>219:
                pivot=stand['toeBase_R'].translation
                turn=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(25*film.smooth((frame-219)/12)),4,'X')@Matrix.Translation(-pivot)
                goal=turn@goal
            pose,_=motion.solve(arm,pose,tuple(n+'_'+side for n in ('thigh','knee','ankle')),goal,Vector((0,-1,0)))
    return pose


def defender_at(state,frame):
    return motion.mix(state[1]['rubick'],state[3]['rubick'][195],state[2]['rubick'][0],
                      film.smooth((frame-264)/14))


def setup_camera(scene):
    scene.timeline_markers.clear()
    camera = scene.camera
    camera.animation_data_clear()
    camera.data.animation_data_clear()
    target = Vector((0,-.6,1.8))
    camera.location = target + Vector((10,3,1.7))
    camera.rotation_euler = (target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.type='ORTHO'
    camera.data.ortho_scale=10.8
    scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=960
    scene.render.resolution_y=640
    scene.render.resolution_percentage=100
    scene.display.shading.color_type='OBJECT'
    if not scene.objects.get('AttackReviewFloor'):
        mesh=bpy.data.meshes.new('AttackReviewFloor')
        mesh.from_pydata([(-100,-100,0),(100,-100,0),(100,100,0),(-100,100,0)],[],[(0,1,2,3)])
        floor=bpy.data.objects.new('AttackReviewFloor',mesh)
        scene.collection.objects.link(floor)
        floor.color=(.13,.15,.18,1)


def fit_camera(scene,actors,count):
    """Reserve space using evaluated actor bounds, including the entire blade."""
    from bpy_extras.object_utils import world_to_camera_view
    from contact_metrics import descendants, visible_meshes
    members=set()
    for actor in actors.values():
        members.update(descendants(actor.parent,scene.objects))
    meshes=[o for o in visible_meshes(scene) if o in members and not any(
        word in o.name.lower() for word in ('physics','collision','hitbox','shadow','blob'))]
    scales=[];factors=[]
    for frame in range(count):
        scene.frame_set(frame)
        graph=bpy.context.evaluated_depsgraph_get()
        points=[]
        for obj in meshes:
            evaluated=obj.evaluated_get(graph)
            points.extend(world_to_camera_view(scene,scene.camera,evaluated.matrix_world@Vector(corner))
                          for corner in evaluated.bound_box)
        scales.append(scene.camera.data.ortho_scale)
        factors.append(max([1.]+[abs(p[axis]-.5)/.44 for p in points for axis in (0,1)]))
    for frame in range(count):
        # Expand early enough for the swing; never zoom to fit just one lucky frame.
        factor=max(factors[max(0,frame-6):min(count,frame+7)])
        scene.camera.data.ortho_scale=scales[frame]*factor
        scene.camera.data.keyframe_insert('ortho_scale',frame=frame)
    return {'maximum_expansion':max(factors),'meshes':[o.name for o in meshes]}


def probes():
    state=film.prepare()
    scene,actors=state[:2]
    setup_camera(scene)
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for obj in scene.objects:
        if obj.type=='MESH' and obj.data.shape_keys:
            obj.data.shape_keys.animation_data_clear()
    for frame,pose in key_poses(state).items():
        scene.frame_set(frame)
        final,row=grip(state,pose,film.smooth((frame-215)/16))
        write_pose(actors['axe'],final)
        write_pose(actors['rubick'],defender_at(state,frame))
        for obj in scene.objects:
            if obj.type=='MESH' and obj.data.shape_keys:
                corrective=obj.data.shape_keys.key_blocks.get('Authored left finger separation')
                if corrective:corrective.value=row['closure']
        scene.render.filepath=str(OUT/f'pose_{frame}.png')
        bpy.ops.render.render(write_still=True)
        rows.append({'frame':frame,**row})
    (OUT/'pose_review.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
    print(json.dumps(rows))
    return state


def build():
    state=film.prepare()
    scene,actors,pressure,bank,manifest,data=state[:6]
    setup_camera(scene)
    keys=key_poses(state)
    result={'axe':[],'rubick':[]}
    rows=[]
    # Sample twice as fast at 30 fps: the earlier 1.6-second airborne hold was
    # rejected. The same arc now has effective gravity 10 world units/s².
    source_frames=list(range(195,311,2))
    for frame in source_frames:
        scene.frame_set(frame)
        try:
            pose,row=grip(state,pose_at(state,keys,frame),film.smooth((frame-215)/16))
        except ValueError as error:
            raise ValueError(f'Pose {frame}: {error}') from error
        if row['reach_error']>.002:
            raise ValueError(f'Unreachable left grip at {frame}: {row}')
        result['axe'].append(pose)
        result['rubick'].append(defender_at(state,frame))
        rows.append({'frame':frame,**row,'root':list(pose['root'].translation)})
    for name,actor in actors.items():
        motion.bake(actor,result[name])
    for index,frame in enumerate(source_frames):
        progress=film.smooth((frame-231)/48)
        a,r=result['axe'][index],result['rubick'][index]
        target=a['root'].translation.lerp(r['Root_0'].translation,.5)
        target.y+=.4
        target.z=2.1+.25*progress
        scene.camera.location=target+Vector((10,-1,1))
        scene.camera.rotation_euler=(target-scene.camera.location).to_track_quat('-Z','Y').to_euler()
        scene.camera.data.ortho_scale=10.8-3*progress
        scene.camera.keyframe_insert('location',frame=index)
        scene.camera.keyframe_insert('rotation_euler',frame=index)
        scene.camera.data.keyframe_insert('ortho_scale',frame=index)
    for obj in scene.objects:
        if obj.type=='MESH' and obj.data.shape_keys:
            obj.data.shape_keys.animation_data_clear()
            key=obj.data.shape_keys.key_blocks.get('Authored left finger separation')
            if key:key.value=1
    for frame,source_frame in enumerate(source_frames):
        for channel,value in zip(manifest['facial_channels'],data['facial_values'][source_frame]):
            obj=scene.objects.get(channel['object'])
            if obj and obj.data.shape_keys and channel['shape'] in obj.data.shape_keys.key_blocks:
                key=obj.data.shape_keys.key_blocks[channel['shape']]
                key.value=float(value)
                key.keyframe_insert('value',frame=frame)
        for obj in scene.objects:
            if obj.type=='MESH' and obj.data.shape_keys:
                corrective=obj.data.shape_keys.key_blocks.get('Authored left finger separation')
                if corrective:
                    corrective.value=rows[frame]['closure']
                    corrective.keyframe_insert('value',frame=frame)
    scene.frame_start,scene.frame_end,scene.render.fps=0,len(source_frames)-1,30
    bounds=fit_camera(scene,actors,len(source_frames))
    scene.frame_set(0)
    scene['review_status']='ATTACK REBUILD; WHOLE-ACTION REVIEW PENDING'
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'fast_build_report.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
    (OUT/'camera_fit.json').write_text(json.dumps(bounds,indent=2),encoding='utf8')
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'attack_fast.blend'),compress=True)
    return scene


if __name__=='__main__':
    build() if '--motion' in sys.argv else probes()
