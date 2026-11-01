"""Two-direction attention/pointing study, run inside Blender 5.2.
--out NEW_DIR --mode block|render; --mode review reopens saved scenes.
Uses the existing rigid mannequin; no dynamics, skin or game-rig claim.
"""
import argparse, hashlib, json, math, re, subprocess, sys, time
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study_lift as lift

FPS, COUNT = 30, 105

def envelope(t,start,end):
    return lift.smooth((t-start)/(end-start))*(1-lift.smooth((t-2.2)/.95))

def target(sign):
    return Vector((sign*1.12,.55,1.30))

def pose(sign,t):
    p,links,_ = lift.pose('light',0)
    yaw = -sign*.22*envelope(t,.5,1.15)
    rotation = Matrix.Rotation(yaw,3,'Z')
    pivot = p['pelvis']
    for name in ['neck','head','L_shoulder','R_shoulder','L_hand','R_hand']:
        p[name] = pivot+rotation@(p[name]-pivot)
    active = 'R' if sign==1 else 'L'
    amount = envelope(t,.7,1.4)
    hand_goal = Vector((sign*.83,.43,1.29))
    p[active+'_hand'] = p[active+'_hand'].lerp(hand_goal,amount)
    for side,s in [('L',-1),('R',1)]:
        a,b = p[side+'_shoulder'],p[side+'_hand']
        p[side+'_elbow'] = lift.solve(a,b,.44,.42,rotation@Vector((s,-.15,.12)))
        links[side+'_upperarm'] = (a,p[side+'_elbow'])
        links[side+'_forearm'] = (p[side+'_elbow'],b)
    links['shoulder'] = (p['L_shoulder'],p['R_shoulder'])
    links['torso'] = (p['pelvis'],p['neck'])
    forward = Vector((0,1,0))
    face = forward.lerp((target(sign)-p['head']).normalized(),envelope(t,.2,.7)).normalized()
    finger = Vector((0,0,-1)).lerp((target(sign)-p[active+'_hand']).normalized(),amount).normalized()
    return p,links,p['head']+face*.145,p[active+'_hand']+finger*.09

def setup(sign,engine='cycles'):
    sc=lift.setup('light')
    if engine=='cycles':
        sc.render.engine='CYCLES';sc.cycles.device='CPU';sc.cycles.samples=16
        sc.cycles.use_denoising=True;sc.cycles.seed=0;sc.cycles.use_animated_seed=False
    box=bpy.data.objects['Box']
    for obj in list(box.children)+[box]: bpy.data.objects.remove(obj,do_unlink=True)
    for obj in sc.objects: obj.animation_data_clear()
    for action in list(bpy.data.actions):
        if action.users==0: bpy.data.actions.remove(action)
    gold=lift.material('Attention target',(.72,.35,.06))
    obj=lift.sphere('Target',.085,gold);obj.location=target(sign)
    post=lift.rod('Target post',.018,gold)
    lift.orient(post,Vector((sign*1.12,.55,.02)),target(sign))
    finger=lift.rod('Index cue',.018,bpy.data.materials['Ivory mannequin'])
    # Mirror only the camera for the right gesture; keep every authored pose.
    sc.camera.location=(-sign*2.6,6.5,2.6)
    sc.camera.rotation_euler=(Vector((0,.2,.86))-sc.camera.location).to_track_quat('-Z','Y').to_euler()
    sc.camera.data.ortho_scale=4.4
    sc.frame_end=COUNT-1
    active='R' if sign==1 else 'L'
    for i in range((COUNT-1)*8+1):
        f=i/8;p,links,nose,tip=pose(sign,f/FPS)
        for name,pos in {**p,'Nose':nose}.items():
            obj=bpy.data.objects[name];obj.location=pos;lift.key(obj,['location'],f)
        for name,(a,b) in {**links,'Index cue':(p[active+'_hand'],tip)}.items():
            obj=bpy.data.objects[name];lift.orient(obj,a,b);lift.key(obj,['location','rotation_quaternion'],f)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for k in curve.keyframe_points:k.interpolation='LINEAR'
    sc['pointing_sign']=sign
    return sc

def point_segment(p,a,b):
    v=b-a
    return (p-(a+v*max(0.,min(1.,(p-a).dot(v)/v.length_squared)))).length

def segment_distance(a,b,c,d):
    u,v,w=b-a,d-c,a-c
    aa,bb,cc,dd,ee=u.dot(u),u.dot(v),v.dot(v),u.dot(w),v.dot(w)
    best=min(point_segment(a,c,d),point_segment(b,c,d),point_segment(c,a,b),point_segment(d,a,b))
    den=aa*cc-bb*bb
    if den>1e-10:
        s,t=(bb*ee-cc*dd)/den,(aa*ee-bb*dd)/den
        if 0<=s<=1 and 0<=t<=1:best=min(best,(a+u*s-c-v*t).length)
    return best

def validate(sign):
    sc=bpy.context.scene
    active='R' if sign==1 else 'L';quiet='L' if sign==1 else 'R'
    names=list(pose(sign,0)[0]);baseline=pose(sign,0)[0]
    max_foot=max_len=max_joint=max_step=max_return=max_quiet=0.
    min_clear=min_floor=min_margin=min_aim=min_face=1.
    min_forearm_px=min_pointer_px=min_target_gap=1e9;max_forearm_slope=0.
    previous=None
    onset={}
    neutral_nose=pose(sign,0)[2]
    for i in range((COUNT-1)*16+1):
        f=i/16;t=f/FPS;sc.frame_set(int(f),subframe=f%1);bpy.context.view_layer.update()
        p={n:bpy.data.objects[n].matrix_world.translation.copy() for n in names}
        observed_nose=bpy.data.objects['Nose'].matrix_world.translation.copy()
        for label,distance,threshold in [('head',(observed_nose-neutral_nose).length,.002),
                ('body',(p[active+'_shoulder']-baseline[active+'_shoulder']).length,.002),
                ('hand',(p[active+'_hand']-baseline[active+'_hand']).length,.02)]:
            if distance>threshold and label not in onset:onset[label]=t
        rods={}
        for name,obj in [(n,bpy.data.objects[n]) for n in pose(sign,0)[1]]:
            a=obj.matrix_world@Vector((0,0,-.5));b=obj.matrix_world@Vector((0,0,.5))
            rods[name]=(a,b,obj['radius'])
            max_len=max(max_len,abs((b-a).length-obj['length']))
            min_floor=min(min_floor,a.z-obj['radius'],b.z-obj['radius'])
        pairs={'torso':('pelvis','neck'),'shoulder':('L_shoulder','R_shoulder')}
        for side in ('L','R'):
            for part,a,b in [('thigh','hip','knee'),('shin','knee','ankle'),('upperarm','shoulder','elbow'),('forearm','elbow','hand')]:
                pairs[side+'_'+part]=(side+'_'+a,side+'_'+b)
            max_foot=max(max_foot,(p[side+'_ankle']-baseline[side+'_ankle']).length,
                (bpy.data.objects[side+'_foot'].matrix_world.translation-Vector(((-1 if side=='L' else 1)*.23,.10,.05))).length)
        for n,(a,b) in pairs.items():max_joint=max(max_joint,(rods[n][0]-p[a]).length,(rods[n][1]-p[b]).length)
        # Non-adjacent arm/body envelopes; adjoining shoulder joints excluded.
        for name in ['L_forearm','R_forearm','L_upperarm','R_upperarm']:
            a,b,r=rods[name]
            for other in ['torso','L_thigh','R_thigh','L_shin','R_shin']:
                c,d,r2=rods[other];min_clear=min(min_clear,segment_distance(a,b,c,d)-r-r2)
            min_clear=min(min_clear,point_segment(p['head'],a,b)-r-.14,
                          point_segment(target(sign),a,b)-r-.085,
                          segment_distance(a,b,Vector((sign*1.12,.55,.02)),target(sign))-r-.018)
        a,b,r=rods['L_forearm'];c,d,r2=rods['R_forearm']
        min_clear=min(min_clear,segment_distance(a,b,c,d)-r-r2)
        # Quiet wrist is fixed in the yawed torso's local space.
        expected=pose(sign,t)[0][quiet+'_hand']
        max_quiet=max(max_quiet,(p[quiet+'_hand']-expected).length)
        if previous:max_step=max(max_step,*[(p[n]-previous[n]).length for n in names])
        previous=p
        if t>=3.15:max_return=max(max_return,*[(p[n]-baseline[n]).length for n in names])
        if 1.4<=t<=2.2:
            cue=bpy.data.objects['Index cue'];direction=(cue.matrix_world@Vector((0,0,.5))-cue.matrix_world@Vector((0,0,-.5))).normalized()
            min_aim=min(min_aim,direction.dot((target(sign)-p[active+'_hand']).normalized()))
            face=(bpy.data.objects['Nose'].matrix_world.translation-p['head']).normalized()
            min_face=min(min_face,face.dot((target(sign)-p['head']).normalized()))
            def screen(value):
                uv=world_to_camera_view(sc,sc.camera,value)
                return Vector((uv.x*sc.render.resolution_x,uv.y*sc.render.resolution_y))
            elbow,wrist=screen(p[active+'_elbow']),screen(p[active+'_hand'])
            tip=screen(cue.matrix_world@Vector((0,0,.5)))
            start=screen(cue.matrix_world@Vector((0,0,-.5)))
            target_obj=bpy.data.objects['Target'];center=target_obj.matrix_world.translation
            target_px=screen(center)
            camera_right=sc.camera.matrix_world.to_3x3()@Vector((1,0,0))
            radius_px=(screen(center+camera_right*.085)-target_px).length
            forearm=wrist-elbow
            min_forearm_px=min(min_forearm_px,forearm.length)
            max_forearm_slope=max(max_forearm_slope,abs(forearm.y)/max(abs(forearm.x),1e-8))
            min_pointer_px=min(min_pointer_px,(tip-start).length)
            min_target_gap=min(min_target_gap,(tip-target_px).length-radius_px)
        if i%16==0:
            for obj in sc.objects:
                if obj.type=='MESH' and obj.name!='Floor':
                    for corner in obj.bound_box:
                        uv=world_to_camera_view(sc,sc.camera,obj.matrix_world@Vector(corner))
                        min_margin=min(min_margin,uv.x,uv.y,1-uv.x,1-uv.y)
    report=dict(samples=1665,frames=COUNT,fps=FPS,foot_drift=max_foot,length_error=max_len,
                joint_error=max_joint,max_step=max_step,return_error=max_return,quiet_wrist_error=max_quiet,
                min_checked_clearance=min_clear,min_floor=min_floor,min_margin=min_margin,
                hold_pointer_dot=min_aim,hold_face_dot=min_face,motion_onset_seconds=onset,
                hold_projection=dict(forearm_pixels=min_forearm_px,pointer_pixels=min_pointer_px,
                    max_forearm_slope=max_forearm_slope,target_gap_pixels=min_target_gap),
                camera_xyz=list(sc.camera.location),engine=sc.render.engine,blender_version=bpy.app.version_string)
    if not onset.get('head',100)<onset.get('body',0)<onset.get('hand',0):
        raise ValueError('Attention order: '+str(onset))
    if (max_foot>2e-6 or max_len>2e-6 or max_joint>.002 or max_step>.006 or max_return>2e-5 or
        max_quiet>2e-5 or min_clear<-.0001 or min_floor<-.0001 or min_margin<.025 or min_aim<.995 or min_face<.995 or
        min_forearm_px<32 or min_pointer_px<8 or max_forearm_slope>.7 or min_target_gap<6):
        raise ValueError(str(report))
    return report

def negative_tests(sign):
    results=[]
    for name,field,axis,delta in [('L_foot','delta_location',0,.01),('L_forearm','scale',2,.02),('Nose','delta_location',0,.06)]:
        obj=bpy.data.objects[name];old=getattr(obj,field).copy();getattr(obj,field)[axis]+=delta
        try:
            validate(sign)
        except ValueError:results.append(name)
        else:raise AssertionError('Missed '+name)
        finally:setattr(obj,field,old)
    camera=bpy.context.scene.camera;location=camera.location.copy();rotation=camera.rotation_euler.copy()
    camera.location.x=sign*2.6
    camera.rotation_euler=(Vector((0,.2,.86))-camera.location).to_track_quat('-Z','Y').to_euler()
    try:
        validate(sign)
    except ValueError:results.append('foreshortened_camera')
    else:raise AssertionError('Missed unreadable camera')
    finally:camera.location=location;camera.rotation_euler=rotation
    return results

def review(folder,ff):
    movie=folder/'pointing.mp4'
    header=subprocess.run([str(ff),'-hide_banner','-i',str(movie)],capture_output=True,text=True).stderr
    if not re.search(r'640x360',header) or not re.search(r'30 fps',header) or 'Audio:' in header:
        raise ValueError('Expected silent 640x360/30 fps movie')
    def decode(args):
        r=subprocess.run([str(ff),'-v','error',*args,'-vf','scale=160:90','-an','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,check=True)
        return np.frombuffer(r.stdout,np.uint8).reshape((-1,90,160,3))
    raw=decode(['-i',str(movie)]);src=decode(['-framerate','30','-i',str(folder/'frames/f%04d.png')])
    if raw.shape!=src.shape or len(raw)!=COUNT:raise ValueError('Decoded count')
    error=float(np.abs(raw.astype(float)-src).mean(axis=(1,2,3)).max())
    if error>6 or raw.mean(axis=(1,2,3)).min()<15:raise ValueError('Encoding mismatch/dark frame')
    (folder/'review').mkdir(exist_ok=True)
    subprocess.run([str(ff),'-y','-v','error','-i',str(movie),'-vf','scale=320:180,tile=5x3:nb_frames=15:padding=2:margin=2','-fps_mode','passthrough','-q:v','2',str(folder/'review/sheet%02d.jpg')],check=True)
    return dict(sha256=hashlib.sha256(movie.read_bytes()).hexdigest(),bytes=movie.stat().st_size,frames=len(raw),duration=3.5,max_encoding_error=error)

def compare_baseline(baseline,fresh):
    """Compare actual saved mesh geometry and world matrices; ignore camera/materials."""
    def sample(path):
        bpy.ops.wm.open_mainfile(filepath=str(path))
        sc=bpy.context.scene
        objects=sorted((ob for ob in sc.objects if ob.type=='MESH'),key=lambda ob:ob.name)
        geometry={ob.name:hashlib.sha256(np.asarray([tuple(v.co) for v in ob.data.vertices],dtype=np.float64).tobytes()).hexdigest()
                  for ob in objects}
        matrices=[]
        for i in range((COUNT-1)*16+1):
            frame=i/16;sc.frame_set(int(frame),subframe=frame%1);bpy.context.view_layer.update()
            matrices.append([list(map(tuple,ob.matrix_world)) for ob in objects])
        return geometry,np.asarray(matrices)
    before,old=sample(baseline);after,new=sample(fresh)
    if before!=after or old.shape!=new.shape:raise ValueError('Baseline geometry differs')
    delta=float(np.abs(old-new).max())
    if delta>2e-6:raise ValueError('Baseline motion differs: '+str(delta))
    return dict(mesh_objects=len(before),samples=1665,geometry_identical=True,max_world_matrix_delta=delta)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mode',choices=['block','render','review'],default='block');parser.add_argument('--ffmpeg',type=Path)
    parser.add_argument('--case',choices=['both','left','right'],default='both')
    parser.add_argument('--engine',choices=['cycles','eevee'],default='cycles')
    parser.add_argument('--baseline-root',type=Path,help='Optional original left/right scenes, compared during review')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.out.resolve()
    if args.mode!='review' and out.exists():raise ValueError('Use new directory')
    if args.mode in ('render','review') and not args.ffmpeg:raise ValueError('--ffmpeg is required')
    assert abs(segment_distance(Vector((0,0,0)),Vector((1,0,0)),Vector((.5,-1,0)),Vector((.5,1,0))))<1e-6
    assert abs(segment_distance(Vector((0,0,0)),Vector((1,0,0)),Vector((0,1,0)),Vector((1,1,0)))-1)<1e-6
    assert abs(segment_distance(Vector((0,0,0)),Vector((1,0,0)),Vector((2,-1,0)),Vector((2,1,0)))-1)<1e-6
    for sign,case in [(-1,'left'),(1,'right')]:
        if args.case!='both' and args.case!=case:continue
        folder=out/case;start=time.perf_counter()
        if args.mode=='review':bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
        else:
            folder.mkdir(parents=True);sc=setup(sign,args.engine);sc.frame_set(0)
            bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))
            bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
        comparison=None
        if args.mode=='review' and args.baseline_root:
            comparison=compare_baseline(args.baseline_root/case/'scene.blend',folder/'scene.blend')
        qa=validate(sign)
        if comparison is not None:qa['baseline_comparison']=comparison
        if args.mode=='review':qa['negative_tests']=negative_tests(sign);qa['movie']=review(folder,args.ffmpeg)
        else:
            sc=bpy.context.scene;(folder/'frames').mkdir()
            if args.mode=='block':
                for f in [32,54,82]:
                    sc.frame_set(f);sc.render.filepath=str(folder/'frames'/f'f{f:04d}.png');bpy.ops.render.render(write_still=True)
            else:
                sc.render.filepath=str(folder/'frames/f');bpy.ops.render.render(animation=True)
                subprocess.run([str(args.ffmpeg),'-v','error','-framerate','30','-i',str(folder/'frames/f%04d.png'),'-frames:v','105','-an','-c:v','libx264','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(folder/'pointing.mp4')],check=True)
        qa['elapsed_seconds']=time.perf_counter()-start;(folder/(args.mode+'.json')).write_text(json.dumps(qa,indent=2));print(case,json.dumps(qa),flush=True)

if __name__=='__main__':main()
