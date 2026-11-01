"""Silent intention study: reach, notice an opening trap, pause, withdraw.

Rigid mannequin and authored kinematics, not a skinned character or dynamics.
Reuse the established geometry and two-link solver; no addons or game assets.
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
from study_throw import LINKS
from study_pointing import point_segment, segment_distance

FPS, COUNT = 30, 150
BLOCK = (0, 35, 54, 68, 80, 100, 135)


def curve(t, keys):
    for (a, x), (b, y) in zip(keys, keys[1:]):
        if t <= b:
            return x+(y-x)*geom.smooth((t-a)/(b-a))
    return keys[-1][1]


def pose(t):
    reach = curve(t, [(0,0),(.5,0),(1.65,1),(2.65,1),(3.45,0),(5,0)])
    recoil = curve(t, [(0,0),(2.65,0),(3.4,1),(3.8,.87),(5,.87)])
    lean = .18*reach-.26*recoil
    pelvis = Vector((0,-.12-.075*recoil,.91-.075*recoil))
    neck = pelvis+Vector((0,.5*math.sin(lean),.5*math.cos(lean)))
    head = neck+Vector((0,-.04*recoil,math.sqrt(.19**2-(.04*recoil)**2)))
    notice = curve(t, [(0,0),(1.95,0),(2.25,1),(5,1)])
    gaze = Vector((0,1,-.25+.17*notice)).normalized()
    p = {'pelvis':pelvis,'neck':neck,'head':head,'Nose':head+gaze*.145}
    for side,sign in [('L',-1),('R',1)]:
        hip=pelvis+Vector((sign*.15,0,0))
        ankle=Vector((sign*.23,-.04,.10))
        shoulder=neck+Vector((sign*.23,0,0))
        hand=Vector((sign*.38,.04,.72))
        if side=='R':hand=hand.lerp(Vector((.25,.63,1.24)),reach)
        defend=curve(t,[(0,0),(2.78 if side=='R' else 2.95,0),(3.5,1),(5,1)])
        hand=hand.lerp(Vector((sign*.32,.26 if side=='R' else .18,1.35)),defend)
        knee=geom.solve(hip,ankle,.46,.46,Vector((0,1,0)))
        elbow=geom.solve(shoulder,hand,.44,.42,Vector((sign*.35,.25,-1)))
        for key,value in [('hip',hip),('ankle',ankle),('knee',knee),('shoulder',shoulder),('elbow',elbow),('hand',hand)]:
            p[side+'_'+key]=value
    return p


def lid_angle(t):
    return -math.radians(75)*geom.smooth((t-1.8)/.35)


def setup():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=32
    sc.render.resolution_x,sc.render.resolution_y=960,540
    sc.render.resolution_percentage=100;sc.render.fps=FPS;sc.frame_start=0;sc.frame_end=COUNT-1
    sc.render.image_settings.file_format='PNG';sc.view_settings.view_transform='AgX'
    sc.world=bpy.data.worlds.new('Studio');sc.world.use_nodes=True
    sc.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.19,.23,.29,1)
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.5
    body=geom.material('Ivory',(.72,.76,.75));dark=geom.material('Joints',(.055,.10,.13))
    shell=geom.material('Trap shell',(.38,.10,.045));inside=geom.material('Inside',(.12,.018,.012))
    gold=geom.material('Lure',(.92,.48,.04),.45)
    geom.cube('Floor',(0,0,-.06),(200,200,.12),geom.material('Floor',(.10,.15,.19)))
    geom.cube('Pedestal',(0,1.08,.43),(.46,.42,.86),dark,.025)
    geom.cube('Trap base',(0,1.08,.89),(.62,.52,.06),shell,.012)
    for sign in (-1,1):
        geom.cube('Side wall '+str(sign),(sign*.29,1.08,.98),(.04,.52,.12),shell,.008)
        geom.cube('End wall '+str(sign),(0,1.08+sign*.24,.98),(.54,.04,.12),shell,.008)
    geom.cube('Mouth',(0,1.08,.925),(.54,.44,.008),inside)
    lure=geom.sphere('Lure',.045,gold);lure.location=(0,1.03,.974)
    hinge=bpy.data.objects.new('Lid hinge',None);sc.collection.objects.link(hinge);hinge.location=(0,1.34,1.06)
    lid=geom.cube('Lid',(0,-.26,.035),(.62,.52,.07),shell,.018);lid.parent=hinge
    lining=geom.cube('Lid inside',(0,-.26,-.005),(.55,.45,.008),inside);lining.parent=hinge
    # Four small blunt teeth make the opened prop read as a hazard.
    for i,x in enumerate((-.23,-.075,.075,.23)):
        bpy.ops.mesh.primitive_cone_add(vertices=4,radius1=.045,radius2=.008,depth=.12)
        ob=bpy.context.object;ob.name='Tooth '+str(i);ob.data.materials.append(body)
        ob.parent=hinge;ob.location=(x,-.46,-.065);ob.rotation_euler.x=math.pi
    for name in pose(0):
        radius=.14 if name=='head' else (.10 if name=='pelvis' else .047)
        if name=='Nose':radius=.035
        ob=geom.sphere(name,radius,body if name in ('head','Nose') else dark);ob['radius']=radius
    for name in LINKS:
        ob=geom.rod(name,geom.radius_for(name),body);ob['radius']=geom.radius_for(name)
    for side,sign in [('L',-1),('R',1)]:
        geom.cube(side+'_foot',(sign*.23,.02,.05),(.18,.34,.10),dark,.02)
    for name,location,energy in [('Key',(2,3,5),1100),('Rim',(-3,-1,4),800)]:
        ob=bpy.data.objects.new(name,bpy.data.lights.new(name,'AREA'));sc.collection.objects.link(ob)
        ob.location=location;ob.data.energy=energy;ob.data.size=4
        ob.rotation_euler=(Vector((0,.5,1))-ob.location).to_track_quat('-Z','Y').to_euler()
    for name,location in [('three_quarter',(5,4,2.6)),('profile',(6,.55,2.0))]:
        cam=bpy.data.objects.new(name,bpy.data.cameras.new(name));sc.collection.objects.link(cam)
        cam.location=location;cam.rotation_euler=(Vector((0,.48,.90))-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type='ORTHO';cam.data.ortho_scale=4.1
    sc.camera=bpy.data.objects['profile']
    for i in range(4*(COUNT-1)+1):
        frame=i/4;p=pose(frame/FPS)
        for name,value in p.items():
            ob=bpy.data.objects[name];ob.location=value;geom.key(ob,['location'],frame)
        for name,(a,b) in LINKS.items():
            ob=bpy.data.objects[name];geom.orient(ob,p[a],p[b]);geom.key(ob,['location','rotation_quaternion','scale'],frame)
        hinge.rotation_euler.x=lid_angle(frame/FPS);geom.key(hinge,['rotation_euler'],frame)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for k in fc.keyframe_points:k.interpolation='LINEAR'
    sc.frame_set(0)
    return sc


def audit():
    sc=bpy.context.scene;worst=joint=length=hold=0.;clearance=margin=10.;previous=None;step=0.
    reference=None;foot0={n:bpy.data.objects[n].matrix_world.copy() for n in ('L_foot','R_foot')}
    drift=0.;hand_front=10.;arm_clearance=10.;foot_ground=0.;floor=10.
    for i in range(8*(COUNT-1)+1):
        f=i/8;t=f/FPS;sc.frame_set(int(f),subframe=f%1);bpy.context.view_layer.update()
        actual={n:bpy.data.objects[n].matrix_world.translation.copy() for n in pose(t)}
        for n,v in pose(t).items():worst=max(worst,(v-actual[n]).length)
        if previous:step=max(step,max((actual[n]-previous[n]).length for n in actual))
        previous=actual
        if t>=3.85:
            reference=reference or actual
            hold=max(hold,max((actual[n]-reference[n]).length for n in actual))
        for n,m in foot0.items():drift=max(drift,max(abs(a-b) for row0,row1 in zip(m,bpy.data.objects[n].matrix_world) for a,b in zip(row0,row1)))
        rods={}
        for n,(a,b) in LINKS.items():
            ob=bpy.data.objects[n];ends=[ob.matrix_world@Vector((0,0,z)) for z in (-.5,.5)]
            rods[n]=ends
            joint=max(joint,(ends[0]-actual[a]).length,(ends[1]-actual[b]).length)
            length=max(length,abs((ends[1]-ends[0]).length-geom.LENGTHS[n.split('_')[-1]]))
            if n.endswith(('upperarm','forearm')):
                clearance=min(clearance,point_segment(actual['head'],*ends)-.14-geom.radius_for(n))
        for n in ('L_upperarm','R_upperarm','L_forearm','R_forearm'):
            for other in ('torso','L_thigh','R_thigh','L_shin','R_shin'):
                arm_clearance=min(arm_clearance,segment_distance(*rods[n],*rods[other])-geom.radius_for(n)-geom.radius_for(other))
        # All trap geometry stays at y >= .78. Character remains outside this plane.
        hand_front=min(hand_front,.78-max(actual[n].y+bpy.data.objects[n]['radius'] for n in actual))
        if i%8==0:
            for ob in sc.objects:
                if ob.type=='MESH' and ob.name!='Floor':
                    bottom=min((ob.matrix_world@Vector(corner)).z for corner in ob.bound_box)
                    floor=min(floor,bottom)
                    if ob.name in foot0:foot_ground=max(foot_ground,abs(bottom))
            for camera in ('profile','three_quarter'):
                for ob in sc.objects:
                    if ob.type=='MESH' and ob.name!='Floor':
                        for corner in ob.bound_box:
                            uv=world_to_camera_view(sc,bpy.data.objects[camera],ob.matrix_world@Vector(corner))
                            margin=min(margin,uv.x,uv.y,1-uv.x,1-uv.y)
    report=dict(samples=8*(COUNT-1)+1,max_playback_error_m=worst,max_joint_error_m=joint,
        max_length_error_m=length,min_arm_head_clearance_m=clearance,min_arm_body_clearance_m=arm_clearance,
        min_frame_margin=margin,max_foot_transform_drift=drift,max_hold_drift_m=hold,
        min_trap_separating_plane_gap_m=hand_front,max_step_m=step,
        minimum_floor_m=floor,max_foot_ground_error_m=foot_ground,
        scope='Rigid mannequin; selected capsule and separating-plane checks, no skin, fingers or physical balance.')
    report['passed']=(worst<.002 and joint<.002 and length<.0001 and clearance>0 and arm_clearance>0
                      and margin>.025 and drift<1e-6 and hold<1e-6 and hand_front>0 and step<.015
                      and floor>-.0001 and foot_ground<.0001)
    return report


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--mode',choices=('build','render','audit'),default='build')
    args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.out.resolve()
    if args.mode=='build':
        out.mkdir(parents=True,exist_ok=False);setup()
        bpy.context.preferences.filepaths.file_preview_type='NONE';bpy.context.preferences.filepaths.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),use_scripts=False)
    report=audit();(out/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not report['passed']:raise ValueError('Scene audit failed')
    sc=bpy.context.scene
    if args.mode=='build':
        for camera in ('profile','three_quarter'):
            sc.camera=bpy.data.objects[camera]
            for frame in BLOCK:
                sc.frame_set(frame);sc.render.filepath=str(out/f'{camera}_{frame:03d}.png');bpy.ops.render.render(write_still=True)
    elif args.mode=='render':
        folder=out/'frames';folder.mkdir(exist_ok=False)
        sc.camera=bpy.data.objects['profile'];sc.render.filepath=str(folder/'frame_');bpy.ops.render.render(animation=True)


if __name__=='__main__':main()
