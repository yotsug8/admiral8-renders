"""Authored shot sizes and asymmetric airborne follow-through for Doomsday."""
import math
import bpy
from mathutils import Vector


def flight_legs(arm, pose, frame, branch, curve):
    if frame <= 252:
        return pose
    result = {name: matrix.copy() for name, matrix in pose.items()}
    phrases = {
        'thigh_R': ((252,0),(268,-22),(287,7),(310,-5),(345,0),(419,0)),
        'knee_R': ((252,0),(274,24),(292,8),(318,14),(350,4),(419,4)),
        'ankle_R': ((252,0),(269,12),(294,-4),(335,4),(419,4)),
        'thigh_L': ((252,0),(261,13),(284,-13),(307,5),(345,-3),(419,-3)),
        'knee_L': ((252,0),(264,5),(283,20),(306,6),(342,10),(419,10)),
        'ankle_L': ((252,0),(275,9),(302,-3),(340,3),(419,3)),
    }
    for bone, keys in phrases.items():
        branch(arm, result, bone, math.radians(curve(frame, keys)), 'X')
    return result


def apply(scene, axe, rubick, contact, frames=420):
    cam = scene.camera
    cam.animation_data_clear(); cam.data.animation_data_clear()
    cam.data.type = 'PERSP'; cam.data.sensor_fit = 'HORIZONTAL'
    aspect = scene.render.resolution_y / scene.render.resolution_x
    weapon = next(o for o in scene.objects if o.type == 'MESH' and 'axe_weapon' in o.name)
    samples = {}
    for f in range(frames):
        scene.frame_set(f); bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        ev = weapon.evaluated_get(graph)
        samples[f] = {
            'a': {n: axe.matrix_world @ axe.pose.bones[n].head for n in
                  ('head','spine1','spine3','bicep_L','bicep_R','elbow_L','elbow_R','wrist_L','wrist_R')},
            'r': {n: rubick.matrix_world @ rubick.pose.bones[n].head for n in
                  ('Head_0','wrist_R')},
            'weapon': [ev.matrix_world @ v.co for v in ev.data.vertices],
        }

    def landmarks(f, kind):
        data=samples[f]; points=[]
        names = ('head','spine1','bicep_L','bicep_R','elbow_L','elbow_R','wrist_L','wrist_R')
        if kind == 'detail':
            points.extend(data['weapon'])
            names=('wrist_R',)
        elif kind == 'contact':
            names=('head','spine3','bicep_L','bicep_R','elbow_L','elbow_R','wrist_L','wrist_R')
            points.extend(data['weapon'])
            for n in ('Head_0','wrist_R'):
                p=data['r'][n]
                points.extend(p+Vector((x,y,z)) for x in (-.2,.2) for y in (-.2,.2) for z in (-.25,.25))
        else: points.extend(data['weapon'])
        for n in names:
            p=data['a'][n]; radius=.25 if n=='head' else .15
            points.extend(p+Vector((x,y,z)) for x in (-radius,radius) for y in (-radius,radius) for z in (-radius,radius))
        return points

    plans={}
    # Each shot fits its purposeful landmarks, not both complete characters.
    # A partial track leaves visible screen travel during the flight.
    for start, stop, kind, direction, tracking, lens in (
        (45,120,'detail',(-1,-1.7,.30),0,55),
        (195,243,'attack',(-1,-.28,.08),0,42),
        (243,277,'attack',(-1,-.27,.02),.65,48),
        (277,330,'contact',(-1,-.10,.06),0,32),
    ):
        rotation=(-Vector(direction)).to_track_quat('-Z','Y'); inverse=rotation.inverted()
        reference=samples[start]['a']['head']
        points=[]
        for f in range(start,stop):
            track=(samples[f]['a']['head']-reference)*tracking
            points.extend(inverse@(p-track) for p in landmarks(f,kind))
        lo=Vector(tuple(min(p[i] for p in points) for i in range(3)))
        hi=Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center=(lo+hi)*.5
        tanx=cam.data.sensor_width/(2*lens); tany=tanx*aspect
        distance=max(max(abs(p.x-center.x)/(.91*tanx),abs(p.y-center.y)/(.89*tany))+p.z-center.z for p in points)
        for f in range(start,stop):
            track=(samples[f]['a']['head']-reference)*tracking
            target=rotation@center+track
            location=rotation@(center+Vector((0,0,distance)))+track
            plans[f]=(location,target,lens)

    for f in range(frames):
        data=samples[f]
        if f<45:
            target=Vector((-.7,-.1,1.95));pos=Vector((-8.4,-7.8,3.25));lens=35
        elif f<120 or 195<=f<330:
            pos,target,lens=plans[f]
        elif f<195:
            target=samples[145]['a']['head']+Vector((0,0,-.04))
            pos=target+Vector((-1.6,-3.05,.08));lens=65
        elif f<360:
            target=data['r']['Head_0'].lerp(contact,.24)+Vector((0,0,.06))
            pos=target+Vector((-3.0,2.5,.10));lens=52
        else:
            target=samples[390]['a']['head']+Vector((0,0,-.07))
            pos=target+Vector((-2.9,-1.8,.18));lens=64
        cam.location=pos;cam.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler()
        cam.data.lens=lens;cam.data.dof.focus_distance=(target-pos).length
        cam.data.dof.aperture_fstop=5.6 if 195<=f<330 else 3.2
        for key in ('location','rotation_euler'):cam.keyframe_insert(key,frame=f)
        for key in ('lens','dof.focus_distance','dof.aperture_fstop'):cam.data.keyframe_insert(key,frame=f)
    for owner in (cam,cam.data):
        for layer in owner.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for channel in bag.fcurves:
                        for key in channel.keyframe_points:key.interpolation='CONSTANT'
