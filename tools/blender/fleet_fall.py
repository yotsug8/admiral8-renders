"""Fleet fall blocking: recoil, failed support, backward fall and landing.

Experimental until multi-view motion and actual skin contacts are reviewed.
No per-frame lowest-vertex lift and no belly translations are used.
"""
import math
import bpy
from mathutils import Matrix, Vector
from contact_reaction import _action, _basis, _solve_leg


def ease(u):
    return u*u*(3-2*u)


def values(frame, keys):
    if frame <= keys[0][0]:
        return keys[0][1:]
    for i, (a, b) in enumerate(zip(keys, keys[1:])):
        if frame <= b[0]:
            duration = b[0]-a[0]
            u = (frame-a[0])/duration
            result = []
            for channel in range(1,len(a)):
                def tangent(index):
                    if index == 0 or index == len(keys)-1:
                        return 0
                    prev, here, following = keys[index-1:index+2]
                    left = (here[channel]-prev[channel])/(here[0]-prev[0])
                    right = (following[channel]-here[channel])/(following[0]-here[0])
                    return 0 if left*right <= 0 else 2*left*right/(left+right)
                m0, m1 = tangent(i)*duration, tangent(i+1)*duration
                result.append((2*u**3-3*u*u+1)*a[channel] + (u**3-2*u*u+u)*m0
                              + (-2*u**3+3*u*u)*b[channel] + (u**3-u*u)*m1)
            return tuple(result)
    return keys[-1][1:]


def rotate_branch(arm, desired, name, axis, degrees):
    pivot = desired[name].translation.copy()
    transform = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(degrees), 4, axis) @ Matrix.Translation(-pivot)
    for bone in (arm.pose.bones[name], *arm.pose.bones[name].children_recursive):
        desired[bone.name] = transform @ desired[bone.name]


def apply():
    scene = bpy.context.scene
    arm = bpy.data.objects['Giant_pudge_rig']
    root = bpy.data.objects['Giant_pudge_placement']
    if any(t.name == 'Fleet backward fall' for t in arm.animation_data.nla_tracks):
        raise RuntimeError('Reopen the saved baseline before applying fall again')
    for track in arm.animation_data.nla_tracks:
        if track.name in ('Grounded fall pose', 'pudge_death'):
            track.mute = True
    root.animation_data_clear()
    root.location = (0, 12, .03)
    scene.frame_set(428)
    evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    world = evaluated.matrix_world.copy()
    inverse = world.inverted()
    base = {b.name: world @ b.matrix for b in evaluated.pose.bones}
    lower = next(o for o in scene.objects if o.type == 'MESH'
                 and o.name.startswith('Giant_') and o.name.endswith('.lower_body'))
    surface = lower.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = surface.to_mesh()
    soles = {}
    for side in ('L', 'R'):
        group = lower.vertex_groups['ankle_'+side].index
        soles[side] = [surface.matrix_world@mesh.vertices[v.index].co-base['ankle_'+side].translation
                       for v in lower.data.vertices
                       if any(g.group == group and g.weight > .5 for g in v.groups)]
        if not soles[side]:
            raise RuntimeError('Cannot identify the support foot surface')
    surface.to_mesh_clear()
    pivot = base['root'].translation.copy()
    # frame, pelvis travel, pelvis drop, whole-body angle, spine recoil,
    # rear step, both feet travel, support-foot lift. Units are world metres.
    keys = [
        (428,0,0,0,0,0,0,0),
        (435,.20,-.25,-3,-10,0,0,0),
        (442,.35,-.32,-2,-6,1.0,0,0),
        (449,.80,-.60,-9,-17,1.5,0,0),
        (457,1.15,-.85,-16,-16,1.5,0,0),
        (465,2.3,-.70,-38,-12,1.0,1.3,.45),
        (473,4.2,-1.25,-72,-6,.5,3.3,.15),
        (480,5.0,-1.45,-91,-3,0,3.0,0),
        (486,5.0,-1.12,-88,-1,0,2.5,.12),
        (498,5.0,-1.45,-91,-3,0,3.0,0),
        (539,5.0,-1.45,-91,-3,0,3.0,0),
    ]
    frames = []
    poles = [None, None]
    for frame in range(428, 540):
        y, z, angle, recoil, step, feet, lift = values(frame, keys)
        turn = Matrix.Translation(pivot + Vector((0,y,z))) @ Matrix.Rotation(math.radians(angle),4,'X') @ Matrix.Translation(-pivot)
        desired = {n:turn@m for n,m in base.items()}
        rotate_branch(arm, desired, 'spine1', 'X', recoil)
        # Arms open in response to the loss of balance, then settle outward.
        spread = values(frame, [(428,0),(440,9),(457,27),(473,42),(498,32),(539,32)])[0]
        for side, sign in (('L',1),('R',-1)):
            rotate_branch(arm, desired, 'bicep_'+side, 'Y', spread*sign)
            # Raising the arms during lost balance prevents the back-facing
            # arm from following the torso through the ground on landing.
            raise_arm = values(frame,[(428,0),(450,0),(465,-18),(480,-40),(498,-35),(539,-35)])[0]
            rotate_branch(arm, desired, 'bicep_'+side, 'X', raise_arm)
        # Forearm pronation turns the projecting cuff away from the floor.
        forearm_axis = (desired['wrist_R'].translation-desired['elbow_R'].translation).normalized()
        roll = values(frame,[(428,0),(457,0),(473,-45),(480,-90),(498,-90),(539,-90)])[0]
        rotate_branch(arm,desired,'elbow_R',forearm_axis,roll)
        knife_swing = values(frame,[(428,0),(435,0),(449,-55),(457,-60),(465,-60),(473,-55),(480,-40),(498,-35),(539,-35)])[0]
        rotate_branch(arm,desired,'Knife_C','Y',knife_swing)
        tie = values(frame,[(428,0),(449,0),(457,-12),(465,-22),(480,-22),(498,-22),(539,-22)])[0]
        rotate_branch(arm,desired,'apron_tie_0','X',tie)
        for index, side in enumerate(('L','R')):
            leg = ('thigh_'+side, 'knee_'+side, 'ankle_'+side)
            before = {n:m.copy() for n,m in desired.items()}
            target = base[leg[-1]].copy()
            target.translation += Vector((0, feet + (step if side=='R' else 0), lift))
            # After back contact, release the standing-foot pose: legs extend
            # and feet roll onto their heels. Support is measured on the foot,
            # never by lifting the whole actor from its lowest vertex.
            release = values(frame,[(428,0),(482,0),(506,1),(539,1)])[0]
            if release > 0:
                foot_turn = Matrix.Rotation(math.radians(-55*release),4,'X')
                target = Matrix.LocRotScale(target.translation,
                            (foot_turn.to_quaternion()@target.to_quaternion()).normalized(),
                            target.to_scale())
                target.translation.y -= (0.95 if side == 'L' else 1.65)*release
                heel_height = .015-min((foot_turn.to_3x3()@p).z for p in soles[side])
                # The rotated sole must be supported throughout the roll,
                # not only once the blend has reached its end.
                target.translation.z = heel_height + lift*(1-release)
            if side == 'R' and 435 < frame < 449:
                target.translation.z += .55*math.sin(math.pi*(frame-435)/14)
            try:
                poles[index] = _solve_leg(before, desired, leg, Vector(), poles[index], Vector((0,-1,1)), target)
            except ValueError as exc:
                raise ValueError(f'Frame {frame}: {exc}') from exc
            for name in leg:
                delta = desired[name] @ before[name].inverted()
                for bone in arm.pose.bones[name].children_recursive:
                    if bone.name in leg:
                        continue
                    nearest = next((a.name for a in bone.parent_recursive if a.name in leg), None)
                    if nearest == name:
                        desired[bone.name] = delta @ before[bone.name]
        basis = {}
        for bone in arm.pose.bones:
            parent = inverse @ desired[bone.parent.name] if bone.parent else None
            basis[bone.name] = _basis(bone, inverse @ desired[bone.name], parent)
        frames.append({'frame':frame,'basis':basis})
    action = _action(arm,list(arm.pose.bones),frames,'Fleet backward fall',scene)
    track = arm.animation_data.nla_tracks.new()
    track.name = 'Fleet backward fall'
    strip = track.strips.new(action.name,428,action)
    strip.action_slot = action.slots[0]
    strip.action_frame_start, strip.action_frame_end = 428,539
    strip.frame_start, strip.frame_end = 428,539
    strip.blend_type, strip.extrapolation = 'REPLACE','HOLD_FORWARD'
    strip.blend_in = strip.blend_out = 0
    return action
