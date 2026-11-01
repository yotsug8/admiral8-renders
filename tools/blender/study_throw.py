"""A/B throwing study: preparation and follow-through on a rigid mannequin.

Not a game rig or physical balance simulation. Identical ball flight in both
versions isolates the authored body performance. No sound, captions or addons.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_lift as geom
from study_pointing import point_segment

FPS, COUNT, RELEASE, RADIUS = 30, 120, 1.4, .08
START = Vector((.40, .34, 1.12))
WIND = Vector((.49, -.34, 1.38))
LAUNCH = Vector((.38, .64, 1.55))
VELOCITY = Vector((0, 2.4, 1.5))
LINKS = {'torso': ('pelvis', 'neck'), 'shoulder': ('L_shoulder', 'R_shoulder')}
for side in ('L', 'R'):
    for name, a, b in [('thigh','hip','knee'), ('shin','knee','ankle'),
                       ('upperarm','shoulder','elbow'), ('forearm','elbow','hand')]:
        LINKS[side+'_'+name] = (side+'_'+a, side+'_'+b)


def hermite(t, a, b, p, q, v=None, w=None):
    u = max(0., min(1., (t-a)/(b-a)))
    v, w = v or Vector(), w or Vector()
    return ((2*u**3-3*u*u+1)*p + (u**3-2*u*u+u)*(b-a)*v
            + (-2*u**3+3*u*u)*q + (u**3-u*u)*(b-a)*w)


def held(case, t):
    if case == 'mechanical':
        return hermite(t, 1.05, RELEASE, START, LAUNCH, w=VELOCITY)
    if t <= .9:
        return hermite(t, .30, .9, START, WIND)
    u=max(0.,min(1.,(t-.9)/(RELEASE-.9)))
    # Arc clears the shoulder; zero endpoint derivatives retain release speed.
    return hermite(t, .9, RELEASE, WIND, LAUNCH, w=VELOCITY)+Vector((0,0,.33*16*u*u*(1-u)**2))


def flight(t):
    """Analytic ballistic segments with explicitly authored restitution/friction."""
    remain = max(0., t-RELEASE)
    p, velocity = LAUNCH.copy(), VELOCITY.copy()
    for bounce in range(4):
        impact = (velocity.z + math.sqrt(velocity.z**2 + 2*9.81*(p.z-RADIUS))) / 9.81
        if remain <= impact:
            return p+velocity*remain+Vector((0, 0, -4.905*remain**2))
        p += velocity*impact+Vector((0, 0, -4.905*impact**2))
        p.z = RADIUS
        remain -= impact
        velocity = Vector((velocity.x*.65, velocity.y*.65, (9.81*impact-velocity.z)*.35))
    # Once bounce height is negligible, friction stops the ball on the ground.
    speed = velocity.length
    travel = min(remain, speed/3)
    if speed:
        p += Vector((velocity.x, velocity.y, 0)).normalized()*(speed*travel-1.5*travel**2)
    return p


def impact_times():
    t, z, speed = RELEASE, LAUNCH.z, VELOCITY.z
    times = []
    for _ in range(4):
        dt = (speed+math.sqrt(speed**2+2*9.81*(z-RADIUS)))/9.81
        t += dt;times.append(t);speed = (9.81*dt-speed)*.35;z = RADIUS
    return times


def pose(case, t):
    effort = 0.
    if case == 'staged':
        keys = [(0,0.),(.3,0.),(.9,-.12),(1.4,.20),(1.65,.25),(2.65,0.),(4.,0.)]
        for (a,x),(b,y) in zip(keys,keys[1:]):
            if t <= b:
                effort = x+(y-x)*geom.smooth((t-a)/(b-a));break
    pelvis = Vector((0, -.08-.10*max(effort,0), .91-.05*abs(effort)))
    neck = pelvis+Vector((0, .50*math.sin(effort), .50*math.cos(effort)))
    head = neck+Vector((0, .19*math.sin(effort*.6), .19*math.cos(effort*.6)))
    p = {'pelvis':pelvis,'neck':neck,'head':head,'Nose':head+Vector((0,.145,.015))}
    ball = held(case,t) if t < RELEASE else flight(t)
    grip_offset = Vector((0,.10,0))
    if t <= RELEASE:
        right_hand = held(case,t)-grip_offset
    elif case == 'mechanical':
        right_hand = LAUNCH-grip_offset
    elif t <= 1.72:
        right_hand = hermite(t, RELEASE, 1.72, LAUNCH-grip_offset,
                             Vector((.45,.70,1.10)), v=VELOCITY)
    else:
        right_hand = hermite(t,1.72,2.65,Vector((.45,.70,1.10)),START-grip_offset)
    for side,sign in [('L',-1),('R',1)]:
        hip=pelvis+Vector((sign*.15,0,0))
        ankle=Vector((sign*.23, .12 if side=='L' else -.12, .10))
        shoulder=neck+Vector((sign*.23,0,0))
        hand=right_hand if side=='R' else Vector((-.43,.14-.45*effort,.89))
        knee=geom.solve(hip,ankle,.46,.46,Vector((0,1,0)))
        elbow=geom.solve(shoulder,hand,.44,.42,Vector((sign,-.2,.1)))
        for n,value in [('hip',hip),('ankle',ankle),('knee',knee),('shoulder',shoulder),('elbow',elbow),('hand',hand)]:
            p[side+'_'+n]=value
    return p,ball


def setup(case):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=32
    sc.render.resolution_x,sc.render.resolution_y=960,540
    sc.render.resolution_percentage=100;sc.render.fps=FPS;sc.frame_start=0;sc.frame_end=COUNT-1
    sc.render.image_settings.file_format='PNG';sc.view_settings.view_transform='AgX'
    sc.world=bpy.data.worlds.new('Studio');sc.world.use_nodes=True
    sc.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.19,.23,.29,1)
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.5
    body=geom.material('Ivory',(.72,.76,.75));dark=geom.material('Joints',(.055,.10,.13))
    accent=geom.material('Warm',(.85,.23,.045));floor=geom.material('Floor',(.10,.15,.19))
    geom.cube('Floor',(0,0,-.06),(200,200,.12),floor)
    target=geom.material('Target',(.22,.38,.39))
    geom.cube('Landing patch',(.38,2.42,0),(.8,.8,.0002),target)
    p,_=pose(case,0)
    for name in p:
        radius=.14 if name=='head' else (.10 if name=='pelvis' else .047)
        if name=='Nose':radius=.035
        ob=geom.sphere(name,radius,body if name in ('head','Nose') else dark)
        ob['radius']=radius
    for name in LINKS:
        ob=geom.rod(name,geom.radius_for(name),body);ob['radius']=geom.radius_for(name)
    geom.sphere('Ball',RADIUS,accent)
    for side,sign in [('L',-1),('R',1)]:
        geom.cube(side+'_foot',(sign*.23,(.12 if side=='L' else -.12)+.06,.05),(.18,.34,.10),dark,.02)
    for name,location,energy in [('Key',(2,3,5),1100),('Rim',(-3,-1,4),800)]:
        light=bpy.data.objects.new(name,bpy.data.lights.new(name,'AREA'));sc.collection.objects.link(light)
        light.location=location;light.data.energy=energy;light.data.size=4
        light.rotation_euler=(Vector((0,1,1))-light.location).to_track_quat('-Z','Y').to_euler()
    for name,location in [('three_quarter',(5,5,3.0)),('profile',(6,.6,2.2))]:
        cam=bpy.data.objects.new(name,bpy.data.cameras.new(name));sc.collection.objects.link(cam)
        cam.location=location;cam.rotation_euler=(Vector((0,1.1,.85))-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type='ORTHO';cam.data.ortho_scale=5.1
    sc.camera=bpy.data.objects['profile']
    key_frames = {i/4 for i in range(4*(COUNT-1)+1)}
    key_frames.update(t*FPS for t in impact_times() if t*FPS < COUNT)
    for frame in sorted(key_frames):
        p,ball=pose(case,frame/FPS)
        for name,value in {**p,'Ball':ball}.items():
            ob=bpy.data.objects[name];ob.location=value;geom.key(ob,['location'],frame)
        for name,(a,b) in LINKS.items():
            ob=bpy.data.objects[name];geom.orient(ob,p[a],p[b]);geom.key(ob,['location','rotation_quaternion','scale'],frame)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:key.interpolation='LINEAR'
    sc.frame_set(0)
    return sc


def audit(case):
    sc=bpy.context.scene;worst=0.;min_height=10.;frame_margin=1.;grip_error=0.;body_clearance=10.
    worst_sample = None
    limb_error=0.;length_error=0.;arm_head_clearance=10.
    for i in range(8*(COUNT-1)+1):
        frame=i/8;t=frame/FPS;sc.frame_set(int(frame),subframe=frame%1);bpy.context.view_layer.update()
        p,ball=pose(case,t)
        for name,value in {**p,'Ball':ball}.items():
            error=(bpy.data.objects[name].matrix_world.translation-value).length
            if error>worst:worst=error;worst_sample={'frame':frame,'object':name}
        actual=bpy.data.objects['Ball'].matrix_world.translation
        for name,(a,b) in LINKS.items():
            ob=bpy.data.objects[name]
            ends=[ob.matrix_world@Vector((0,0,z)) for z in (-.5,.5)]
            limb_error=max(limb_error,(ends[0]-bpy.data.objects[a].matrix_world.translation).length,
                           (ends[1]-bpy.data.objects[b].matrix_world.translation).length)
            expected=geom.LENGTHS[name.split('_')[-1]]
            length_error=max(length_error,abs((ends[1]-ends[0]).length-expected))
            if name.endswith(('upperarm','forearm')):
                arm_head_clearance=min(arm_head_clearance,point_segment(p['head'],*ends)-.14-geom.radius_for(name))
        min_height=min(min_height,actual.z-RADIUS)
        for name in ('torso','L_thigh','R_thigh','L_shin','R_shin'):
            a,b=LINKS[name]
            body_clearance=min(body_clearance,point_segment(actual,p[a],p[b])-RADIUS-geom.radius_for(name))
        body_clearance=min(body_clearance,(actual-p['head']).length-RADIUS-.14)
        if t<RELEASE:
            grip_error=max(grip_error,abs((actual-bpy.data.objects['R_hand'].matrix_world.translation).length-.10))
        for cam in ('three_quarter','profile'):
            for name in p.keys()|{'Ball'}:
                ob=bpy.data.objects[name];radius=RADIUS if name=='Ball' else ob['radius']
                for axis in (Vector((radius,0,0)),Vector((0,radius,0)),Vector((0,0,radius))):
                    for sign in (-1,1):
                        uv=world_to_camera_view(sc,bpy.data.objects[cam],ob.matrix_world.translation+axis*sign)
                        frame_margin=min(frame_margin,uv.x,1-uv.x,uv.y,1-uv.y)
    report={'samples':8*(COUNT-1)+1,'max_playback_error_m':worst,'minimum_ball_ground_clearance_m':min_height,
            'worst_playback_sample':worst_sample,
            'max_grip_distance_error_m':grip_error,'minimum_frame_margin':frame_margin,
            'minimum_ball_body_clearance_m':body_clearance,
            'max_limb_endpoint_error_m':limb_error,'max_segment_length_error_m':length_error,
            'minimum_arm_head_clearance_m':arm_head_clearance,
            'limits':'Rigid mannequin, fixed feet. No fingers, skin or measured center of mass. Ball flight matches across cases.'}
    report['passed']=(worst<.002 and min_height>-.001 and grip_error<.001 and frame_margin>.025
                      and body_clearance>0 and limb_error<.002 and length_error<.0001 and arm_head_clearance>0)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--case',choices=('mechanical','staged'),required=True)
    p.add_argument('--mode',choices=('build','render','audit'),default='build')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.out.resolve()
    if args.mode=='build':
        out.mkdir(parents=True,exist_ok=False);sc=setup(args.case)
        bpy.context.preferences.filepaths.file_preview_type='NONE';bpy.context.preferences.filepaths.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),use_scripts=False)
        report=audit(args.case);(out/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if not report['passed']:raise ValueError(report)
        sc=bpy.context.scene
        for camera in ('three_quarter','profile'):
            sc.camera=bpy.data.objects[camera]
            for frame in (0,27,42,50,65,100):
                sc.frame_set(frame);sc.render.filepath=str(out/f'{camera}_{frame:03}.png');bpy.ops.render.render(write_still=True)
    elif args.mode=='audit':
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),use_scripts=False)
        report=audit(args.case);(out/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
        if not report['passed']:raise ValueError('Audit failed')
    else:
        if not json.loads((out/'audit.json').read_text())['passed']:raise ValueError('Audit required')
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),use_scripts=False);sc=bpy.context.scene
        frames=out/'frames';frames.mkdir(exist_ok=False)
        sc.camera=bpy.data.objects['profile'];sc.render.filepath=str(frames/'frame_')
        bpy.ops.render.render(animation=True)


if __name__=='__main__':main()
