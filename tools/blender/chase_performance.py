"""Native Hoodwink chase actions; no renderer hooks, FACS or root movement.

make_seamless_run(arm, native_run, scene=None) returns (new_action, report).
Source action/rig/NLA are unchanged. Native frame range/units are preserved.
All bone local channels get a distributed smoothstep endpoint correction;
position/quaternion/scale endpoints coincide. Quarter-frame samples retain
the native gait. FREE Bezier Hermite handles share endpoint channel slopes,
closing C1 at the repeat boundary instead of inserting a pause or blend.
Caller installs the returned action in its own run strip with its own rate.

apply_panic(ACTORS, scene=None, FPS=None, who='hoodwink', start=4.2, end=4.8,
            native_flail=None, strength=.75) adds a REPLACE upper-body strip.
Times are seconds, absolute frames=time*FPS. Install after the source idle/run
strips so zero-weight endpoints match the actual underlying transition.
Only descendants of spine_0 are keyed: native flail rotations, bounded per
joint, with sin^2 attack/release. Pelvis, lower limbs, actor/object transforms,
root trajectory, source actions, meshes and facial morphs are untouched.
No baked face-expression claims: Hoodwink's native bone ears/head are used.
Source feet are preserved, not planted by this helper. Dense keys and midpoint
foot witnesses validate the installed stack. Weapon/cloth/visual QA is separate.
"""
import math
import re
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

from contact_reaction import _action, _curves


def _positive(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise ValueError(f'chase performance: {label} must be positive and finite')
    return float(value)


def _frame(scene,frame):
    scene.frame_set(math.floor(frame),subframe=frame-math.floor(frame))


def _slot(action):
    if not action.slots:
        raise ValueError('native action has no object slot')
    candidates=[]
    for slot in action.slots:
        curves=[c for layer in action.layers for strip in layer.strips for bag in strip.channelbags
                if bag.slot_handle==slot.handle for c in bag.fcurves if c.data_path.startswith('pose.bones[')]
        if curves:candidates.append(slot)
    if len(candidates)!=1:
        raise ValueError('native action must have exactly one skeletal object slot')
    return candidates[0]


def load_native_action(filepath,name='mouse_flail'):
    """Read one main-body GLB action; clean temporary import objects/resources."""
    filepath=Path(filepath).resolve()
    if not filepath.is_file():raise ValueError(f'native GLB missing: {filepath.name}')
    kinds=('objects','meshes','armatures','materials','images','actions','collections')
    before={kind:{item.as_pointer() for item in getattr(bpy.data,kind)} for kind in kinds}
    selected=list(bpy.context.selected_objects);active=bpy.context.view_layer.objects.active
    result=None;success=False
    try:
        bpy.ops.import_scene.gltf(filepath=str(filepath),bone_heuristic='BLENDER')
        candidates=[a for a in bpy.data.actions if a.as_pointer() not in before['actions']
                    and re.sub(r'\.\d{3}$','',a.name)==name]
        if len(candidates)!=1:raise ValueError(f'GLB does not contain one native {name} action')
        result=candidates[0].copy();result.name='chase_native_'+name
        _slot(result)
        success=True
        return result
    finally:
        for obj in list(bpy.data.objects):
            if obj.as_pointer() not in before['objects']:bpy.data.objects.remove(obj,do_unlink=True)
        for kind in ('collections','meshes','armatures','materials','images','actions'):
            data=getattr(bpy.data,kind)
            for item in list(data):
                if item.as_pointer() not in before[kind] and (item!=result or not success):
                    if kind=='collections':data.remove(item,do_unlink=True)
                    elif item.users==0:data.remove(item)
        for obj in selected:obj.select_set(True)
        bpy.context.view_layer.objects.active=active


def _proxy(arm,action,scene):
    slot=_slot(action)
    proxy=bpy.data.objects.new('chase_performance_sample',arm.data)
    scene.collection.objects.link(proxy)
    bpy.context.view_layer.update()
    for bone in arm.pose.bones:
        proxy.pose.bones[bone.name].rotation_mode=bone.rotation_mode
    ad=proxy.animation_data_create();ad.action=action;ad.action_slot=slot
    return proxy


def _read(proxy,scene,frame,names):
    _frame(scene,frame)
    evaluated=proxy.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result={name:evaluated.pose.bones[name].matrix_basis.copy() for name in names}
    if not all(math.isfinite(v) for matrix in result.values() for row in matrix for v in row):
        raise ValueError('native pose contains nonfinite values')
    return result


def _validate_rig(arm,bones):
    if arm.type!='ARMATURE':raise ValueError('expected an armature')
    for bone in bones:
        if bone.rotation_mode=='AXIS_ANGLE' or any(not c.mute and c.influence for c in bone.constraints):
            raise ValueError(f'{bone.name}: unsupported native pose constraint/rotation')
    ad=arm.animation_data
    if ad and (ad.use_tweak_mode or any(t.is_solo for t in ad.nla_tracks)):
        raise ValueError('solo/tweak NLA unsupported')
    if ad and any(not c.mute and any(c.data_path.startswith(b.path_from_id()+'.') for b in bones) for c in ad.drivers):
        raise ValueError('driven performance bones unsupported')


def _close_curve_handles(action):
    for curve in _curves(action):
        points=list(curve.keyframe_points)
        points[-1].co[1]=points[0].co[1]
        slopes=[]
        for i,p in enumerate(points):
            a,b=points[max(0,i-1)],points[min(len(points)-1,i+1)]
            slopes.append((b.co[1]-a.co[1])/(b.co[0]-a.co[0]))
        common=(slopes[0]+slopes[-1])/2
        slopes[0]=slopes[-1]=common
        for i,p in enumerate(points):
            p.interpolation='BEZIER';p.handle_left_type=p.handle_right_type='FREE'
            dl=(p.co[0]-points[i-1].co[0])/3 if i else (points[1].co[0]-p.co[0])/3
            dr=(points[i+1].co[0]-p.co[0])/3 if i+1<len(points) else dl
            p.handle_left=(p.co[0]-dl,p.co[1]-slopes[i]*dl)
            p.handle_right=(p.co[0]+dr,p.co[1]+slopes[i]*dr)
        curve.update()


def make_seamless_run(arm,native_run,*,scene=None,name='chase_hoodwink_run'):
    """Return a new run action and numerical seam diagnostics, without install."""
    scene=scene or bpy.context.scene
    bones=list(arm.pose.bones);_validate_rig(arm,bones)
    first,last=map(float,native_run.frame_range);period=_positive(last-first,'native cycle period')
    saved=scene.frame_current,scene.frame_subframe
    proxy=None;action=None
    try:
        proxy=_proxy(arm,native_run,scene)
        begin=_read(proxy,scene,first,[b.name for b in bones])
        finish=_read(proxy,scene,last,[b.name for b in bones])
        frames=sorted({first+i/4 for i in range(math.ceil(period*4))}|{last})
        samples=[];max_position=max_angle=0.
        for frame in frames:
            native=_read(proxy,scene,frame,begin)
            u=(frame-first)/period;weight=u*u*(3-2*u);basis={}
            for bone in bones:
                loc,q,scale=native[bone.name].decompose()
                l0,q0,s0=begin[bone.name].decompose();l1,q1,s1=finish[bone.name].decompose()
                if q1.dot(q0)<0:q1.negate()
                delta=q1.inverted() @ q0
                correction=Quaternion().slerp(delta,weight)
                rotation=q @ correction
                if frame==first:rotation=q0
                if frame==last:rotation=q0
                basis[bone.name]=Matrix.LocRotScale(loc+(l0-l1)*weight,rotation,scale+(s0-s1)*weight)
                if frame==first:
                    max_position=max(max_position,(l1-l0).length)
                    angle=q1.rotation_difference(q0).angle
                    max_angle=max(max_angle,min(abs(angle),abs(2*math.pi-angle)))
            samples.append(dict(frame=frame,basis=basis))
        action=_action(arm,bones,samples,name,scene)
        _close_curve_handles(action)
        report=dict(source=native_run.name,action=action.name,frame_range=[first,last],
                    native_max_local_position_seam=max_position,native_max_angle_seam_deg=math.degrees(max_angle),
                    samples=len(samples),endpoint_channels_closed=True,endpoint_channel_slopes_matched=True,
                    root_keys_untouched=True,limitation='native gait with distributed closure; not a ground-contact solver')
        return action,report
    except Exception:
        if action and action.users==0:bpy.data.actions.remove(action)
        raise
    finally:
        if proxy:bpy.data.objects.remove(proxy,do_unlink=True)
        scene.frame_set(saved[0],subframe=saved[1])


def apply_panic(ACTORS,*,scene=None,FPS=None,who='hoodwink',start=4.2,end=4.8,native_flail=None,strength=.75):
    """Install native upper-body flail overlay; return JSON-safe diagnostics."""
    scene=scene or bpy.context.scene;fps=_positive(FPS or scene.render.fps,'FPS')
    if not isinstance(start,(int,float)) or not math.isfinite(start) or start<0:raise ValueError('invalid panic start')
    if not isinstance(end,(int,float)) or not math.isfinite(end) or end<=start:raise ValueError('invalid panic end')
    if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not 0<strength<=1:
        raise ValueError('panic strength must be in (0,1]')
    actor=ACTORS[who];arm=actor['arm'];ad=arm.animation_data
    if ad is None or ad.action is not None:raise ValueError('panic requires assembled source NLA, no active action')
    if any(t.name.startswith('chase_panic_') for t in ad.nla_tracks):raise ValueError('panic already applied')
    torso=arm.pose.bones.get('spine_0')
    if torso is None or torso.parent is None or 'pelvis' not in torso.parent.name.lower():
        raise ValueError('panic requires spine_0 below pelvis, isolated from leg chains')
    bones=[torso,*torso.children_recursive];_validate_rig(arm,bones)
    if any(b.name.lower().startswith(('leg_upper','leg_lower','ankle','ball_')) for b in bones):
        raise ValueError('panic subtree contains leg bones')
    native_flail=native_flail or actor.get('acts',{}).get('mouse_flail') or bpy.data.actions.get('mouse_flail')
    flail_path=None
    if native_flail is None:
        glb=actor.get('info',{}).get('glb')
        if not glb:raise ValueError('native mouse_flail missing; supply native_flail or actor.info.glb')
        flail_path=Path(__file__).resolve().parents[2]/'_game/models/render'/Path(glb).name
    f0,f1=start*fps,end*fps
    frames=sorted({f0+i/4 for i in range(math.ceil((f1-f0)*4))}|{f1,(f0+f1)/2})
    checks=sorted(set(frames)|{(a+b)/2 for a,b in zip(frames,frames[1:])})
    feet=[b.name for b in arm.pose.bones if b.name.lower().startswith(('ankle','ball_'))]
    if len(feet)<2:raise ValueError('panic needs native ankle bones for validation')
    saved=scene.frame_current,scene.frame_subframe;proxy=None;track=None;action=None
    try:
        if flail_path is not None:native_flail=load_native_action(flail_path)
        witnesses={};baseposes={}
        for frame in checks:
            _frame(scene,frame);evaluated=arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            witnesses[frame]={name:evaluated.matrix_world @ evaluated.pose.bones[name].matrix for name in feet}
            if frame in frames:baseposes[frame]={b.name:evaluated.pose.bones[b.name].matrix_basis.copy() for b in bones}
        proxy=_proxy(arm,native_flail,scene);a,b=map(float,native_flail.frame_range);samples=[]
        for frame in frames:
            u=(frame-f0)/(f1-f0);weight=math.sin(math.pi*u)**2*strength
            native=_read(proxy,scene,a+(b-a)*u,[bone.name for bone in bones]);basis={}
            for bone in bones:
                loc,q,scale=baseposes[frame][bone.name].decompose();_,target,_=native[bone.name].decompose()
                if q.dot(target)<0:target.negate()
                delta=q.rotation_difference(target);angle=min(delta.angle,2*math.pi-delta.angle)
                limit=math.radians(10 if bone.name.startswith('spine') else 28 if ('head' in bone.name or 'neck' in bone.name or 'ear_' in bone.name) else 45)
                blend=weight*min(1.,limit/max(angle,1e-9))
                basis[bone.name]=Matrix.LocRotScale(loc,q.slerp(target,blend),scale)
            samples.append(dict(frame=frame,basis=basis))
        action=_action(arm,bones,samples,'chase_panic_'+who,scene)
        track=ad.nla_tracks.new(prev=ad.nla_tracks[-1]) if ad.nla_tracks else ad.nla_tracks.new();track.name='chase_panic_'+who
        strip=track.strips.new(action.name,math.floor(f0),action);strip.action_slot=action.slots[0]
        strip.action_frame_start=f0;strip.action_frame_end=f1;strip.frame_start=f0;strip.frame_end=f1
        strip.blend_type='REPLACE';strip.extrapolation='NOTHING';strip.repeat=1.;strip.scale=1.
        strip.use_auto_blend=False;strip.blend_in=strip.blend_out=0.;strip.influence=1.;strip.use_animated_influence=False
        error=0.
        for frame in checks:
            _frame(scene,frame);evaluated=arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            for name,expected in witnesses[frame].items():
                actual=evaluated.matrix_world @ evaluated.pose.bones[name].matrix
                difference=max(abs(actual[i][j]-expected[i][j]) for i in range(4) for j in range(4))
                if not math.isfinite(difference) or difference>1e-5:raise ValueError('panic modified native lower-body/feet')
                error=max(error,difference)
        return dict(action=action.name,track=track.name,source=native_flail.name,seconds=[start,end],
                    keyed_bones=[bone.name for bone in bones],ear_bones=[bone.name for bone in bones if bone.name.startswith('ear_')],
                    max_foot_matrix_error=error,independent_midpoints=len(checks)-len(frames),
                    root_pelvis_keys_added=False,facial_morphs_used=False)
    except Exception:
        if track:ad.nla_tracks.remove(track)
        if action and action.users==0:bpy.data.actions.remove(action)
        raise
    finally:
        if proxy:bpy.data.objects.remove(proxy,do_unlink=True)
        if flail_path is not None and native_flail is not None and native_flail.users==0:
            bpy.data.actions.remove(native_flail)
        scene.frame_set(saved[0],subframe=saved[1])
