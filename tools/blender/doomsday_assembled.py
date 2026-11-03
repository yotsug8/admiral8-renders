"""Fourteen-second assembly around the preserved fast attack and timed voice."""
import json
import hashlib
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
import doomsday_attack as attack
import doomsday_full_scene as film
import doomsday_performance as motion
from doomsday_native_pressure import write_pose

OUT=film.OUT.parent/'assembled'
SHOTS=((0,'Establish'),(45,'Weapon'),(120,'Threat'),(195,'Charge'),
       (237,'Attack'),(281,'Contact'),(295,'Effort'),(330,'Rubick'),(360,'Realization'))


def cached_attack():
    bpy.ops.wm.open_mainfile(filepath=str(attack.OUT/'attack_fast.blend'))
    scene=bpy.context.scene
    actors={n:film.main_rig(scene,n) for n in ('axe','rubick')}
    poses={n:[] for n in actors};camera=[]
    for frame in range(58):
        scene.frame_set(frame)
        for n,actor in actors.items():poses[n].append(motion.snapshot(actor))
        camera.append((scene.camera.matrix_world.copy(),scene.camera.data.ortho_scale))
    return poses,camera


def introduction(state,start,frame):
    arm=state[1]['axe'];pose=attack.copy_pose(start)
    lean=motion.curve(frame,((0,-2),(45,0),(78,4),(110,2),(142,7),(172,3),(195,1),(217,-2),(237,0)))
    turn=motion.curve(frame,((0,-4),(65,0),(105,4),(142,0),(180,-3),(237,0)))
    lift=motion.curve(frame,((0,-22),(35,-22),(85,0),(237,0)))
    shift=Vector((motion.curve(frame,((0,-.06),(80,.04),(140,-.02),(237,0))),0,0))
    pose=motion.shift(pose,shift)
    motion.branch(arm,pose,'spine1',math.radians(lean),'X')
    motion.branch(arm,pose,'spine2',math.radians(turn),'Z')
    lateral=(pose['bicep_R'].translation-pose['bicep_L'].translation).normalized()
    motion.branch(arm,pose,'bicep_R',math.radians(lift),lateral)
    motion.branch(arm,pose,'head',math.radians(-lean*.5),'X')
    for side in ('L','R'):
        pose,_=motion.solve(arm,pose,tuple(n+'_'+side for n in ('thigh','knee','ankle')),
                            start['ankle_'+side],Vector((0,-1,0)))
    return pose


def ending(state,frame):
    # A second failed pull has a complete release/effort/settle, rather than
    # holding the first impact pose for the rest of the film.
    amount=motion.curve(frame,((294,-.155),(310,-1.1),(327,-.10),
                              (351,-.35),(364,-.25),(390,-1.05),(419,-.85)))
    pose=attack.reaction(state,amount,0)
    realization=film.smooth((frame-360)/38)
    motion.branch(state[1]['axe'],pose,'head',math.radians(-6*realization),'X')
    return attack.grip(state,pose)[0]


def face(state,rows):
    scene,actors,pressure,bank,manifest,data=state[:6]
    envelope=json.loads((OUT/'battle_cry_envelope.json').read_text(encoding='utf8'))
    for obj in scene.objects:
        if obj.type=='MESH' and obj.data.shape_keys:obj.data.shape_keys.animation_data_clear()
    for frame in range(420):
        cry_index=frame-envelope['start_frame']
        cry=envelope['env'][cry_index] if 0<=cry_index<len(envelope['env']) else 0
        realization=film.smooth((frame-360)/38)
        overrides={'jawOpen':.04+.62*cry,'browLowerer':.55,'squint':.2,
                   'jawClencher':.22,'lipPressor':.18}
        if frame>=279:
            overrides.update(jawOpen=.12+.06*realization,browLowerer=.65-.45*realization,
                jawClencher=.65-.5*realization,squint=.3*(1-realization),
                innerBrowRaiser=.30*realization,upperLidRaiser=.25*realization,lipPressor=.2*(1-realization))
        for channel,value in zip(manifest['facial_channels'],data['facial_values'][frame]):
            obj=scene.objects.get(channel['object'])
            if not obj or not obj.data.shape_keys:continue
            key=obj.data.shape_keys.key_blocks.get(channel['shape'])
            if not key:continue
            if frame>=195 and 'axe' in channel['object']:
                value=overrides.get(channel['shape'],0)
            key.value=float(value);key.keyframe_insert('value',frame=frame)
        for obj in scene.objects:
            if obj.type=='MESH' and obj.data.shape_keys:
                key=obj.data.shape_keys.key_blocks.get('Authored left finger separation')
                if key:
                    key.value=rows[frame]['closure'];key.keyframe_insert('value',frame=frame)


def weapon_composition(camera):
    basis=camera.rotation_euler.to_matrix()
    camera.location+=basis@Vector((.60,-.35,0))
    camera.data.lens=50
    camera.data.dof.use_dof=True
    camera.data.dof.aperture_fstop=3.5
    camera.data.dof.focus_distance=6.4


def lock_performance_cameras(scene):
    # Following the head cancelled the actor's effort on screen. Hold the
    # camera in world space so the torso can move visibly within the shot.
    for name,start,end in (('Threat',120,194),('Effort',295,329),('Realization',360,419)):
        scene.frame_set(start)
        camera=scene.objects['Assembly '+name]
        camera.animation_data_clear()
        if name=='Effort':
            for frame in range(start,end+1):
                camera.data.lens=48;camera.data.keyframe_insert('lens',frame=frame)


def cameras(scene,poses,cached):
    template=scene.camera
    cams={}
    recipe=json.loads(Path(__file__).with_name('doomsday_contact_pose.json').read_text(encoding='utf8'))
    scene.timeline_markers.clear()
    for start,name in SHOTS:
        cam=bpy.data.objects.new('Assembly '+name,template.data.copy())
        scene.collection.objects.link(cam)
        cam.animation_data_clear();cam.data.animation_data_clear()
        cams[name]=cam
        scene.timeline_markers.new(name,frame=start).camera=cam
    for frame in range(420):
        name=next(n for start,n in reversed(SHOTS) if frame>=start)
        scene.camera=cam=cams[name]
        a,r=poses['axe'][frame],poses['rubick'][frame]
        if name=='Attack':
            matrix,scale=cached[frame-237]
            # Perspective rays originate above the court. The orthographic
            # review camera sent lower rays under the rising foreground terrain.
            progress=film.smooth((frame-255)/24)
            target=a['root'].translation.lerp(r['Root_0'].translation,.5)
            target.y+=.4;target.z=2.1+.25*progress
            direction=Vector((10,-1,2.5)).normalized()
            cam.data.type='PERSP';cam.data.lens=42
            distance=scale*640/540*42/cam.data.sensor_width
            cam.location=target+direction*distance
            cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
            cam.keyframe_insert('location',frame=frame);cam.keyframe_insert('rotation_euler',frame=frame)
        elif name in ('Weapon','Charge'):
            blade=a['axe_1']@Vector(recipe['contact_weapon_local'])
            target=a['head'].translation.lerp(blade,.55 if name=='Weapon' else .15)
            offset=Vector((4,-5,.5)) if name=='Weapon' else Vector((4,3,.4))
            cam.location=target+offset
            cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
            cam.data.type='PERSP';cam.data.lens=45 if name=='Weapon' else 42
            if name=='Weapon':weapon_composition(cam)
            cam.keyframe_insert('location',frame=frame);cam.keyframe_insert('rotation_euler',frame=frame)
        else:
            film.camera(scene,(a,r),frame)
            if name=='Contact':
                target=a['axe_1']@Vector(recipe['contact_weapon_local'])
                cam.location=target+Vector((3,-1.3,1.1))
                cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
                cam.data.lens=55
                cam.keyframe_insert('location',frame=frame);cam.keyframe_insert('rotation_euler',frame=frame)
                cam.data.keyframe_insert('lens',frame=frame)
        if name!='Weapon':cam.data.dof.use_dof=False
    lock_performance_cameras(scene)
    scene.camera=cams['Establish']


def restore_look(scene):
    for obj in scene.objects:
        if obj.type=='MESH' and obj.parent is None and any(w in obj.name.lower() for w in
              ('court','statue','tower','tree','boulder','rock','trunk')):
            obj.hide_render=False;obj.hide_set(False)
        if obj.name in ('Cold key','Warm edge','Reverse fill','Distant daylight'):
            obj.hide_render=False;obj.hide_set(False)
        if obj.name in ('AttackReviewFloor','DraftGround'):
            obj.hide_render=True
    scene.render.engine='CYCLES'
    from doomsday_refine import gpu
    gpu(scene)
    scene.cycles.samples=24
    scene.cycles.use_denoising=True
    scene.render.use_persistent_data=True
    scene.render.use_compositing=False


def finish_look(scene):
    restore_look(scene)
    actors={n:film.main_rig(scene,n) for n in ('axe','rubick')}
    scene.frame_set(279)
    recipe=json.loads(Path(__file__).with_name('doomsday_contact_pose.json').read_text(encoding='utf8'))
    contact=actors['axe'].matrix_world@actors['axe'].pose.bones['axe_1'].matrix@Vector(recipe['contact_weapon_local'])
    from doomsday_performance_fx import apply
    from doomsday_atmosphere import glow
    report=apply(scene,actors['axe'],actors['rubick'],contact)
    glow(scene)
    # Broad low frontal fill reveals the eyes under the brow without flattening
    # the existing key/rim separation or introducing glossy skin highlights.
    light=bpy.data.lights.new('Assembly face fill','AREA')
    light.energy=85;light.shape='DISK';light.size=4
    light.color=(.63,.76,1)
    obj=bpy.data.objects.new('Assembly face fill',light);scene.collection.objects.link(obj)
    obj.location=(3,-2,2.2)
    target=Vector((0,1,2.5));obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()
    for camera in (o for o in scene.objects if o.type=='CAMERA' and o.name.startswith('Assembly ')):
        if any(n in camera.name for n in ('Threat','Effort','Rubick','Realization')):
            camera.data.dof.use_dof=True;camera.data.dof.aperture_fstop=5.6
            for frame in range(420):
                scene.frame_set(frame)
                hero=actors['rubick'] if camera.name.endswith('Rubick') else actors['axe']
                bone='Head_0' if hero==actors['rubick'] else 'head'
                point=hero.matrix_world@hero.pose.bones[bone].head
                camera.data.dof.focus_distance=(point-camera.location).length
                camera.data.keyframe_insert('dof.focus_distance',frame=frame)
    (OUT/'effects_report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    scene.frame_set(0)
    return scene


def build(material=False):
    clips,cam=cached_attack()
    state=film.prepare()
    scene,actors=state[:2]
    attack.setup_camera(scene)
    attack_rows=json.loads((attack.OUT/'fast_build_report.json').read_text(encoding='utf8'))
    poses={'axe':[],'rubick':[]};rows=[]
    for frame in range(420):
        scene.frame_set(frame)
        if frame<237:
            a=introduction(state,clips['axe'][0],frame)
            r=attack.copy_pose(clips['rubick'][0]);closure=0
        elif frame<295:
            a=attack.copy_pose(clips['axe'][frame-237]);r=attack.copy_pose(clips['rubick'][frame-237])
            closure=attack_rows[frame-237]['closure']
        else:
            a=ending(state,frame);r=attack.copy_pose(clips['rubick'][-1]);closure=1
            response=film.smooth((frame-330)/22)
            motion.branch(actors['rubick'],r,'Head_0',math.radians(-5*response),'Z')
        for name,p in (('axe',a),('rubick',r)):poses[name].append(p)
        rows.append({'frame':frame,'closure':closure})
    for name,actor in actors.items():motion.bake(actor,poses[name])
    face(state,rows)
    cameras(scene,poses,cam)
    scene.frame_start,scene.frame_end,scene.render.fps=0,419,30
    scene.render.resolution_x,scene.render.resolution_y=960,540
    scene.render.resolution_percentage=100
    if material:finish_look(scene)
    scene.frame_set(0)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'assembly_timing.json').write_text(json.dumps({'fps':30,'frames':420,'attack_start':237,
         'takeoff':255,'contact':279,'cry_start':246,'shots':SHOTS,'material':material},indent=2),encoding='utf8')
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/('material.blend' if material else 'assembly.blend')),compress=True)
    return scene


def render_scene():
    source=OUT/'material.blend'
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene=bpy.context.scene
    scene.render.engine='BLENDER_EEVEE'
    scene.eevee.taa_render_samples=64
    scene.render.resolution_x,scene.render.resolution_y=1280,720
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.use_motion_blur=False
    frames=OUT/'finished_frames';frames.mkdir(exist_ok=True)
    settings={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'engine':scene.render.engine,'samples':64,'size':[1280,720],
              'fps':30,'frames':420,'motion_blur':False}
    manifest=frames/'settings.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf8'))!=settings:
        raise ValueError('Different render settings: preserve this cache and choose a new output directory')
    manifest.write_text(json.dumps(settings,indent=2),encoding='utf8')
    for frame in range(420):
        path=frames/f'{frame:04d}.png'
        if path.exists():continue
        scene.frame_set(frame);scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)


def patch_weapon():
    """Re-render only the tighter weapon shot; retain the base cache evidence."""
    source=OUT/'material.blend'
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene=bpy.context.scene;camera=scene.objects['Assembly Weapon']
    for frame in range(45,120):
        scene.frame_set(frame)
        weapon_composition(camera)
        camera.keyframe_insert('location',frame=frame)
    scene.render.engine='BLENDER_EEVEE';scene.eevee.taa_render_samples=64
    scene.render.resolution_x,scene.render.resolution_y=1280,720
    scene.render.resolution_percentage=100
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'material_framed.blend'),compress=True)
    folder=OUT/'weapon_patch';folder.mkdir(exist_ok=True)
    for frame in range(45,120):
        scene.frame_set(frame);scene.render.filepath=str(folder/f'{frame:04d}.png')
        bpy.ops.render.render(write_still=True)


def patch_acting_camera():
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'material_framed.blend'))
    scene=bpy.context.scene
    lock_performance_cameras(scene)
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'material_framed.blend'),compress=True)
    folder=OUT/'acting_camera_patch';folder.mkdir(exist_ok=True)
    for frame in [*range(120,195),*range(295,330),*range(360,420)]:
        scene.frame_set(frame);scene.render.filepath=str(folder/f'{frame:04d}.png')
        bpy.ops.render.render(write_still=True)


if __name__=='__main__':
    if '--render' in sys.argv:render_scene()
    elif '--patch-weapon' in sys.argv:patch_weapon()
    elif '--patch-acting-camera' in sys.argv:patch_acting_camera()
    else:build('--material' in sys.argv)
