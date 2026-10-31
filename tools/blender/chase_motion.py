"""Static rest-derived T-pose for a moving chase root, with frozen parts.

apply_frozen_tpose(arm, start, end, *, root=None, scene=None, horizontal_arms=True)
uses inclusive, zero-based FRAME numbers (not seconds). It freezes every
pose bone for the interval with two identical endpoint keys, no cycles,
no NLA blend or repetition. The actor root, its animation and ground offset
are untouched. Call after renderer source actions/NLA and bone merge exist.

Kunkka's exported rest arms point down. By default the rest shoulder/elbow/
wrist chains are straightened along the root's lateral X axis, in its XY
plane, preserving segment lengths and transporting wrist/finger orientation.
All other main bones remain at rest. horizontal_arms=False freezes literal
export rest (useful for nonhuman rigs); it is not a human T-pose guarantee.

All armatures under root are frozen too. Their same-name bones follow the
main armature via full-influence WORLD COPY_TRANSFORMS; extra part bones keep
their local rest pose. Existing valid merge constraints are retained. Source
tracks remain unchanged and play outside the interval; an active action is
preserved as a source NLA strip below the freeze. The top freeze action keys
all bone channels AND rig-local object transforms at full influence.
Repeated application and unsupported constraints,
drivers, solo/tweak NLA and noninheriting limb rotation are rejected.

This freezes skeletons, not animated shape keys/materials or cloth simulation.
The helper does not align feet to terrain or claim weapon collision safety.
All created tracks/actions/merge constraints are removed on failure; previous
source action slots, track mutes and object transforms are restored. No render.
"""
import math
import re

import bpy
from mathutils import Matrix, Vector

from contact_reaction import _action, _basis, _uniform_world

_PREFIX = 'frozen_tpose_'


def _frame(scene, frame):
    scene.frame_set(math.floor(frame),subframe=frame-math.floor(frame))


def _bone(arm, stems, side):
    suffixes = (side, 'left' if side == 'l' else 'right')
    names = {stem+suffix for stem in stems for suffix in suffixes}
    names |= {suffix+stem for stem in stems for suffix in suffixes}
    matches = [b for b in arm.pose.bones if re.sub('[^a-z]','',b.name.lower()) in names]
    if len(matches) != 1:
        raise ValueError(f'{arm.name}: T-pose needs one {stems}/{side} bone')
    return matches[0]


def _rest_tpose(arm, root, horizontal):
    desired = {b.name:b.bone.matrix_local.copy() for b in arm.pose.bones}
    chains = []
    if horizontal:
        axis = (arm.matrix_world.inverted().to_3x3() @ root.matrix_world.to_3x3() @ Vector((1,0,0))).normalized()
        for side in ('l','r'):
            upper = _bone(arm,('bicep','upperarm'),side)
            lower = _bone(arm,('elbow','forearm'),side)
            wrist = _bone(arm,('wrist','hand'),side)
            if lower.parent != upper or wrist.parent != lower:
                raise ValueError('T-pose requires direct upperarm->forearm->wrist chains')
            if any(not b.bone.use_inherit_rotation for b in upper.children_recursive):
                raise ValueError('T-pose requires inherited rotation throughout each arm')
            chains.append((upper,lower,wrist))
        midpoint = (desired[chains[0][0].name].translation+desired[chains[1][0].name].translation)/2
        for upper,lower,wrist in chains:
            offset = desired[upper.name].translation-midpoint
            dot = offset.dot(axis)
            if abs(dot) < 1e-6:
                raise ValueError('T-pose shoulders must have a lateral separation')
            target = axis if dot > 0 else -axis
            for joint,child in ((upper,lower),(lower,wrist)):
                pivot = desired[joint.name].translation.copy()
                direction = desired[child.name].translation-pivot
                if direction.length < 1e-8:
                    raise ValueError('T-pose arm segment is degenerate')
                rotation = direction.rotation_difference(target).to_matrix().to_4x4()
                rotate = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
                for bone in [joint,*joint.children_recursive]:
                    desired[bone.name] = rotate @ desired[bone.name]
    basis = {}
    for bone in arm.pose.bones:
        parent = desired[bone.parent.name] if bone.parent else None
        basis[bone.name] = _basis(bone,desired[bone.name],parent)
    return basis,[(a.name,b.name,c.name) for a,b,c in chains]


def _valid_merge(constraint, main, name):
    return (constraint.type == 'COPY_TRANSFORMS' and constraint.target == main
            and constraint.subtarget == name and not constraint.mute
            and constraint.influence == 1 and constraint.owner_space == 'WORLD'
            and constraint.target_space == 'WORLD' and constraint.mix_mode == 'REPLACE')


def _object_keys(action, rig, start, end, loc, rot, quat, axis_angle, scale):
    bag = next(bag for layer in action.layers for strip in layer.strips
               for bag in strip.channelbags if bag.slot_handle == action.slots[0].handle)
    rotation = ('rotation_quaternion',quat) if rig.rotation_mode == 'QUATERNION' else (
        ('rotation_axis_angle',axis_angle) if rig.rotation_mode == 'AXIS_ANGLE' else ('rotation_euler',rot))
    for path,values in [('location',loc),rotation,('scale',scale)]:
        for index,value in enumerate(values):
            curve = bag.fcurves.new(data_path=path,index=index)
            for frame in (start,end):
                point = curve.keyframe_points.insert(frame,value)
                point.interpolation = 'LINEAR'


def _apply_frozen_tpose(arm, root, start, end, scene=None, horizontal_arms=True):
    """Freeze the complete actor; return armature/action and chain diagnostics."""
    scene = scene or bpy.context.scene
    if (any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x)
            for x in (start,end)) or start < 0 or end <= start):
        raise ValueError('T-pose start/end must be finite frames with 0 <= start < end')
    if arm.type != 'ARMATURE' or arm not in root.children_recursive:
        raise ValueError('T-pose main armature must be beneath the actor root')
    rigs = [arm]+[o for o in root.children_recursive if o.type == 'ARMATURE' and o != arm]
    snapshots, merges = [], []
    for rig in rigs:
        _uniform_world(rig.matrix_world,rig.name)
        if any(not c.mute and c.influence for c in rig.constraints):
            raise ValueError(f'{rig.name}: object constraints would move the frozen skeleton')
        ad = rig.animation_data
        if ad and (ad.use_tweak_mode or any(t.is_solo for t in ad.nla_tracks) or ad.drivers):
            raise ValueError(f'{rig.name}: drivers/solo/tweak mode unsupported for a frozen actor')
        if ad and any(t.name.startswith(_PREFIX) for t in ad.nla_tracks):
            raise ValueError(f'{rig.name}: frozen T-pose already applied')
        for bone in rig.pose.bones:
            if bone.rotation_mode == 'AXIS_ANGLE':
                raise ValueError('T-pose does not support axis-angle bone channels')
            active = [c for c in bone.constraints if not c.mute and c.influence]
            shared = rig != arm and bone.name in arm.pose.bones
            if active and (not shared or len(active) != 1 or not _valid_merge(active[0],arm,bone.name)):
                raise ValueError(f'{rig.name}/{bone.name}: unsupported pose constraint')
            if shared and not active:
                merges.append((bone,arm,bone.name))
        snapshots.append(dict(rig=rig, had_ad=ad is not None, action=ad.action if ad else None,
                              slot=getattr(ad,'action_slot',None) if ad else None,
                              use_nla=ad.use_nla if ad else True,
                              mutes=[(t,t.mute) for t in ad.nla_tracks] if ad else [],
                              location=rig.location.copy(),rotation_mode=rig.rotation_mode,
                              rotation=rig.rotation_euler.copy(),quaternion=rig.rotation_quaternion.copy(),
                              axis_angle=tuple(rig.rotation_axis_angle),scale=rig.scale.copy()))
    saved = scene.frame_current,scene.frame_subframe
    actions,tracks,created_constraints = [],[],[]
    try:
        _frame(scene,start)
        plans=[]
        for rig in rigs:
            basis,chains = (_rest_tpose(rig,root,True) if rig == arm and horizontal_arms else
                            ({b.name:Matrix.Identity(4) for b in rig.pose.bones},[]))
            # Freeze rig-local object transforms too, leaving root trajectory intact.
            plans.append((rig,basis,chains,rig.location.copy(),rig.rotation_euler.copy(),
                          rig.rotation_quaternion.copy(),tuple(rig.rotation_axis_angle),rig.scale.copy()))
        for rig,basis,chains,loc,rot,quat,axis_angle,scale in plans:
            action = _action(rig,list(rig.pose.bones),
                             [dict(frame=f,basis=basis) for f in (start,end)],_PREFIX+rig.name,scene)
            actions.append(action)
            _object_keys(action,rig,start,end,loc,rot,quat,axis_angle,scale)
            ad = rig.animation_data_create()
            if ad.action is not None:
                source,slot = ad.action,getattr(ad,'action_slot',None)
                first,last = map(float,source.frame_range)
                source_track = ad.nla_tracks.new(prev=ad.nla_tracks[-1]) if ad.nla_tracks else ad.nla_tracks.new()
                tracks.append((ad,source_track));source_track.name='tpose_preserved_source_'+rig.name
                source_strip = source_track.strips.new(source.name,math.floor(first),source)
                if slot is not None:source_strip.action_slot=slot
                source_strip.action_frame_start=first;source_strip.action_frame_end=max(last,first+1e-3)
                source_strip.frame_start=first;source_strip.frame_end=max(last,first+1e-3)
                source_strip.extrapolation=ad.action_extrapolation
                source_strip.blend_type=ad.action_blend_type
                source_strip.influence=ad.action_influence
                source_strip.use_auto_blend=False;source_strip.blend_in=source_strip.blend_out=0.
            ad.action = None
            ad.use_nla = True
            track = ad.nla_tracks.new(prev=ad.nla_tracks[-1]) if ad.nla_tracks else ad.nla_tracks.new()
            tracks.append((ad,track));track.name=_PREFIX+rig.name
            strip = track.strips.new(action.name,math.floor(start),action)
            strip.action_slot=action.slots[0]
            strip.action_frame_start=start;strip.action_frame_end=end
            strip.frame_start=start;strip.frame_end=end
            strip.repeat=1.;strip.scale=1.;strip.extrapolation='NOTHING';strip.blend_type='REPLACE'
            strip.use_auto_blend=False;strip.blend_in=strip.blend_out=0.
            strip.influence=1.;strip.use_animated_influence=False
        for bone,target,name in merges:
            constraint=bone.constraints.new('COPY_TRANSFORMS');created_constraints.append((bone,constraint))
            constraint.name=_PREFIX+'merge';constraint.target=target;constraint.subtarget=name
            constraint.owner_space=constraint.target_space='WORLD';constraint.mix_mode='REPLACE'
            constraint.influence=1.
        _frame(scene,start)
        bpy.context.view_layer.update()
        return dict(start_frame=float(start),end_frame=float(end),
                    armatures=[dict(name=rig.name,bones=len(rig.pose.bones),action=action.name)
                               for (rig,*_),action in zip(plans,actions)],
                    horizontal_chains=plans[0][2],new_merge_constraints=len(created_constraints),
                    root_untouched=True,shape_keys_frozen=False)
    except Exception:
        for bone,constraint in reversed(created_constraints):bone.constraints.remove(constraint)
        for ad,track in reversed(tracks):ad.nla_tracks.remove(track)
        for snap in snapshots:
            rig=snap['rig'];ad=rig.animation_data
            if ad:
                ad.action=snap['action']
                if snap['slot'] is not None:ad.action_slot=snap['slot']
                ad.use_nla=snap['use_nla']
                for track,mute in snap['mutes']:track.mute=mute
                if not snap['had_ad']:rig.animation_data_clear()
            rig.location=snap['location'];rig.rotation_mode=snap['rotation_mode']
            rig.rotation_euler=snap['rotation'];rig.rotation_quaternion=snap['quaternion']
            rig.rotation_axis_angle=snap['axis_angle'];rig.scale=snap['scale']
        for action in actions:
            if action.users == 0:bpy.data.actions.remove(action)
        raise
    finally:
        scene.frame_set(saved[0],subframe=saved[1])


def apply_frozen_tpose(arm, start_frame, end_frame, *, root=None, scene=None, horizontal_arms=True):
    """Public hard-cut human T-pose helper; bounds are inclusive frame numbers."""
    root = root or arm.parent
    if root is None:
        raise ValueError('freeze_tpose needs an actor root or arm.parent')
    return _apply_frozen_tpose(arm,root,start_frame,end_frame,scene=scene,horizontal_arms=horizontal_arms)


