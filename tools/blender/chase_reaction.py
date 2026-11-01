"""Quiet startle for a stationary close-up ending on a hard cut to running.

Hold the entry pose, lean the torso slightly away, then hold until the cut.
No flail clip, returning pulse, or advancing idle is mixed into this shot.
Not a transition helper for continuous shots or moving actor roots.
"""
import math
import bpy
from mathutils import Matrix, Quaternion, Vector
from contact_reaction import _action


def apply_calm_startle(actors, *, scene=None, FPS=30, who='hoodwink',
                      start=4.2, end=4.8, lean_deg=4.):
    scene=scene or bpy.context.scene
    if not all(math.isfinite(v) for v in (FPS,start,end,lean_deg)) or FPS<=0 or end<=start or start<0 or not 0<=lean_deg<=8:
        raise ValueError('Invalid stationary startle window or lean')
    arm=actors[who]['arm']; ad=arm.animation_data
    if not ad or ad.action or any(t.name.startswith('chase_panic_') for t in ad.nla_tracks):
        raise ValueError('Install once over source NLA with no active action')
    saved=scene.frame_current,scene.frame_subframe
    f0=start*FPS; f1=end*FPS
    if f1-f0<2:raise ValueError('Startle needs at least two frames')
    # The next shot owns f1. Never replace its first running pose with the hold.
    last=f1-.001
    scene.frame_set(math.floor(f0),subframe=f0%1)
    ev=arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    bones=list(arm.pose.bones)
    basis={b.name:ev.pose.bones[b.name].matrix_basis.copy() for b in bones}
    torso=ev.pose.bones['spine_0']
    world=ev.matrix_world@torso.matrix
    forward=(ev.matrix_world@ev.pose.bones['head'].matrix).translation-(ev.matrix_world@ev.pose.bones['pelvis'].matrix).translation
    forward.z=0
    if forward.length<.01:raise ValueError('Cannot derive the actor facing direction')
    right=forward.normalized().cross(Vector((0,0,1)))
    local_axis=world.to_quaternion().inverted()@right
    reference={b.name:ev.matrix_world@b.matrix for b in ev.pose.bones if b.name.lower().startswith(('ankle','ball_'))}
    if len(reference)<2:raise ValueError('Cannot validate the held feet on this rig')
    arm_world=ev.matrix_world.copy()
    loc,q,scale=basis['spine_0'].decompose()
    frames=sorted({f0+i/4 for i in range(math.ceil((last-f0)*4)) if f0+i/4<last}|{last})
    samples=[]
    for f in frames:
        u=(f-f0)/(f1-f0)
        x=max(0.,min(1.,(u-.25)/.65));weight=x*x*x*(10+x*(-15+6*x))
        pose={n:m.copy() for n,m in basis.items()}
        pose['spine_0']=Matrix.LocRotScale(loc,q@Quaternion(local_axis,math.radians(lean_deg)*weight),scale)
        samples.append(dict(frame=f,basis=pose))
    action=_action(arm,bones,samples,'chase_panic_calm_'+who,scene)
    track=ad.nla_tracks.new(prev=ad.nla_tracks[-1]);track.name='chase_panic_'+who
    strip=track.strips.new(action.name,math.floor(f0),action);strip.action_slot=action.slots[0]
    strip.action_frame_start=f0;strip.action_frame_end=last
    strip.frame_start=f0;strip.frame_end=last;strip.extrapolation='NOTHING'
    strip.blend_type='REPLACE';strip.blend_in=strip.blend_out=0
    maximum=0.
    try:
        for i in range(math.ceil((last-f0)*8)+1):
            f=min(last,f0+i/8);scene.frame_set(math.floor(f),subframe=f%1)
            ev=arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            if max(abs(ev.matrix_world[r][c]-arm_world[r][c]) for r in range(4) for c in range(4))>1e-5:
                raise ValueError('Stationary reaction requires fixed actor/object transforms')
            for n,expected in reference.items():
                actual=ev.matrix_world@ev.pose.bones[n].matrix
                maximum=max(maximum,max(abs(actual[r][c]-expected[r][c]) for r in range(4) for c in range(4)))
        if maximum>1e-5:raise ValueError('Quiet reaction moved the held feet')
    except Exception:
        ad.nla_tracks.remove(track)
        if action.users==0:bpy.data.actions.remove(action)
        raise
    finally:scene.frame_set(saved[0],subframe=saved[1])
    return dict(action=action.name,seconds=[start,end],lean_deg=lean_deg,
                hold_fraction=.25,recoil_fraction=.65,max_foot_matrix_error=maximum,
                limitations='Stationary root, flat entry support, hard cut at end. Clothing and image composition require visual review.')
