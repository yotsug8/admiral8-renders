"""Build a reviewable fleet v3 candidate from the preserved v2 scene.

Blender --background --python tools/blender/fleet_revision.py
Produces a candidate, not a quality approval or a published final video.
"""
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/blender'))
BASE = ROOT/'_game/skits/fleet_battle'
OUT = BASE/'v3'


def counterattack_exchange():
    from fleet_fall import values
    from fleet_battle import turn_between
    from kunkka_ghostship import linear_keys
    scene = bpy.context.scene
    actor = bpy.data.objects['Captain05_kunkka_placement']
    arm = bpy.data.objects['Captain05_kunkka_rig']
    scene.frame_set(286)
    initial_yaw = actor.rotation_euler.z
    route = [(296,3.5,7.4),(307,4.5,3.6),(316,6.5,2.5),(326,7.8,2.5)]
    previous = initial_yaw
    for frame in range(286,540):
        if frame < 296:
            scene.frame_set(frame)
            yaw = turn_between(initial_yaw,0,frame,286,296)
        else:
            x,y = values(frame,route)
            actor.location = (x,y,.04)
            actor.keyframe_insert('location',frame=frame)
            if frame < 326:
                a,b = values(frame-.1,route),values(frame+.1,route)
                yaw = math.atan2(b[0]-a[0],-(b[1]-a[1]))
            else:
                yaw = turn_between(math.pi/2,math.atan2(-7.8,-9.5),frame,326,340)
        delta = math.atan2(math.sin(yaw-previous),math.cos(yaw-previous))
        yaw = previous + max(-math.radians(12),min(math.radians(12),delta))
        actor.rotation_euler.z = yaw
        actor.keyframe_insert('rotation_euler',frame=frame)
        previous = yaw
    running = next(s for t in arm.animation_data.nla_tracks for s in t.strips
                   if abs(s.frame_start-296)<.01)
    running.scale = .72
    running.repeat = 30/((running.action_frame_end-running.action_frame_start)*running.scale)
    running.frame_start,running.frame_end = 296,326
    running.blend_in,running.blend_out = 3,5
    linear_keys(actor.animation_data.action)
    camera = bpy.data.objects['05c_Counterattack']
    camera.location = (15,0,4)
    target = Vector((2.8,7,3.2))
    camera.rotation_euler = (target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.lens = 22
    camera.data.dof.focus_distance = (target-camera.location).length


def staging_updates():
    from contact_reaction import _curves
    scene = bpy.context.scene
    for name, position, target, lens in (
        ('08_Fall',(-18,4,8),(0,18,4.2),29),
        ('09_Aftermath',(20,3,18),(0,18,2.7),24),
    ):
        camera = bpy.data.objects[name]
        camera.location = position
        camera.rotation_euler = (Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.lens = lens
        camera.data.dof.focus_distance = (Vector(target)-camera.location).length
    # Ground-hit effects follow the new body landing, rather than the old faceplant.
    for obj in scene.objects:
        if not obj.name.startswith(('Impact_6_', 'Ground powder 483-')):
            continue
        for curve in _curves(obj.animation_data.action):
            for key in curve.keyframe_points:
                if curve.data_path == 'location' and curve.array_index == 1:
                    for point in (key.co,key.handle_left,key.handle_right):
                        point.y += 18
                if 440 < key.co.x < 530:
                    for point in (key.co,key.handle_left,key.handle_right):
                        point.x -= 3
        if obj.name.startswith('Ground powder'):
            # Dust starts at the perimeter of the giant's actual back contact;
            # a small plume under the body's centre is entirely occluded.
            index = int(obj.name.rsplit('-',1)[1])
            edge = (4*math.cos(index*math.pi/2),3*math.sin(index*math.pi/2))
            for curve in _curves(obj.animation_data.action):
                if curve.data_path == 'location' and curve.array_index < 2:
                    for key in curve.keyframe_points:
                        for point in (key.co,key.handle_left,key.handle_right):
                            point.y += edge[curve.array_index]
                elif curve.data_path == 'scale':
                    for key in curve.keyframe_points:
                        for point in (key.co,key.handle_left,key.handle_right):
                            point.y *= 1.6
            for slot in obj.material_slots:
                if slot.material and slot.material.node_tree.animation_data:
                    for curve in _curves(slot.material.node_tree.animation_data.action):
                        for key in curve.keyframe_points:
                            for point in (key.co,key.handle_left,key.handle_right):
                                point.y *= 3
                            if 440 < key.co.x < 530:
                                for point in (key.co,key.handle_left,key.handle_right):
                                    point.x -= 3
    # These responses are triggered by the fall, not by an idle oscillation.
    return brace_reactions()


def brace_reactions():
    from contact_reaction import _action, _basis, _solve_leg
    from fleet_fall import rotate_branch, values
    scene = bpy.context.scene
    actors = {str(i):{'root':bpy.data.objects[f'Captain{i:02d}_kunkka_placement'],
                     'arm':bpy.data.objects[f'Captain{i:02d}_kunkka_rig']}
              for i in (2,4,6)}
    # Sample original poses once, before creating any action. The generic contact
    # helper failed its fractional idle-loop witness here; do not relax its test.
    # This authored brace has explicit support feet and a finite return to idle.
    original = {who:{} for who in actors}
    for frame in range(475,522):
        scene.frame_set(frame)
        deps = bpy.context.evaluated_depsgraph_get()
        for who,actor in actors.items():
            arm = actor['arm'].evaluated_get(deps)
            original[who][frame] = (arm.matrix_world.copy(),
                                   {b.name:arm.matrix_world@b.matrix for b in arm.pose.bones})
    for offset,(who,actor) in enumerate(actors.items()):
        arm = actor['arm']
        if any(t.name == 'Fleet impact brace' for t in arm.animation_data.nla_tracks):
            raise RuntimeError('Brace already exists')
        frames = []
        poles = [None,None]
        axis = actor['root'].matrix_world.to_3x3()@Vector((1,0,0))
        for frame,(world,base) in original[who].items():
            weight = values(frame,[(475,0),(479+offset,0),(485+offset,1),(494,.8),(516,0),(521,0)])[0]
            drop = Vector((0,0,-(.12+.02*offset)*weight))
            desired = {name:matrix.copy() for name,matrix in base.items()}
            for matrix in desired.values():
                matrix.translation += drop
            rotate_branch(arm,desired,'spine1',axis,10*weight)
            rotate_branch(arm,desired,'neck1',axis,6*weight)
            rotate_branch(arm,desired,'bicep_L',axis,-22*weight)
            for index,side in enumerate(('L','R')):
                leg = ('thigh_'+side,'knee_'+side,'ankle_'+side)
                loc_a,rot_a,scale_a = base[leg[-1]].decompose()
                loc_b,rot_b,scale_b = original[who][479][1][leg[-1]].decompose()
                rotation = rot_a.slerp(rot_b,weight).normalized()
                target = Matrix.LocRotScale(loc_a.lerp(loc_b,weight),rotation,scale_a.lerp(scale_b,weight))
                before = {name:matrix.copy() for name,matrix in desired.items()}
                poles[index] = _solve_leg(base,desired,leg,drop,poles[index],Vector((0,-1,0)),target)
                for name in leg:
                    delta = desired[name]@before[name].inverted()
                    for bone in arm.pose.bones[name].children_recursive:
                        if bone.name not in leg and next((a.name for a in bone.parent_recursive if a.name in leg),None)==name:
                            desired[bone.name] = delta@before[bone.name]
            inverse = world.inverted()
            basis = {bone.name:_basis(bone,inverse@desired[bone.name],
                                      inverse@desired[bone.parent.name] if bone.parent else None)
                     for bone in arm.pose.bones}
            frames.append({'frame':frame,'basis':basis})
        action = _action(arm,list(arm.pose.bones),frames,'Fleet impact brace '+who,scene)
        track = arm.animation_data.nla_tracks.new();track.name = 'Fleet impact brace'
        strip = track.strips.new(action.name,475,action);strip.action_slot = action.slots[0]
        strip.action_frame_start,strip.action_frame_end = 475,521
        strip.frame_start,strip.frame_end = 475,521
        strip.blend_type,strip.extrapolation = 'REPLACE','NOTHING'
        strip.blend_in = strip.blend_out = 0


def defeat_expression():
    head = next(o for o in bpy.context.scene.objects if o.type == 'MESH'
                and o.name.startswith('Giant_') and o.name.endswith('.head'))
    keys = head.data.shape_keys
    for name,frames in (
        ('eyeClosed',((0,0),(478,0),(484,.8),(490,1),(539,1))),
        ('browLowerer',((0,0),(428,0),(435,.4),(449,.7),(457,.9),(480,.5),(500,.2),(539,.2))),
        ('upperLidRaiser',((0,0),(428,0),(438,.35),(457,0),(539,0))),
    ):
        key = keys.key_blocks[name]
        for frame,value in frames:
            key.value = value
            key.keyframe_insert('value',frame=frame)


def repair_dust_volumes():
    """Use the visible, isolated-tested scatter closure; retain event envelopes.

    The previous graph and Generated-coordinate helper produced no visible
    cloud in this saved EEVEE scene. A constant scatter closure and a surface
    diagnostic verified visibility. Explicit Object coordinates with a bounded
    scatter field are verified here; this is not a general upstream bug claim.
    """
    for material in bpy.data.materials:
        if not material.name.startswith('Ground powder') or not material.use_nodes:
            continue
        tree = material.node_tree
        volume = next((n for n in tree.nodes if n.type == 'PRINCIPLED_VOLUME'),None)
        if volume is None:
            continue
        density = volume.inputs['Density'].links[0].from_socket
        coord = tree.nodes.new('ShaderNodeTexCoord')
        noise = next(n for n in tree.nodes if n.type == 'TEX_NOISE')
        tree.links.new(coord.outputs['Object'],noise.inputs['Vector'])
        distance = tree.nodes.new('ShaderNodeVectorMath');distance.operation = 'DISTANCE'
        distance.inputs[1].default_value = (0,0,0)
        tree.links.new(coord.outputs['Object'],distance.inputs[0])
        fade = tree.nodes.new('ShaderNodeMapRange')
        fade.inputs['From Min'].default_value = .24
        fade.inputs['From Max'].default_value = 1
        fade.inputs['To Min'].default_value = 1
        fade.inputs['To Max'].default_value = 0
        tree.links.new(distance.outputs['Value'],fade.inputs['Value'])
        multiply = tree.nodes.new('ShaderNodeMath');multiply.operation = 'MULTIPLY'
        tree.links.new(density,multiply.inputs[0]);tree.links.new(fade.outputs[0],multiply.inputs[1])
        scatter = tree.nodes.new('ShaderNodeVolumeScatter')
        scatter.inputs['Color'].default_value = (.36,.30,.20,1)
        tree.links.new(multiply.outputs[0],scatter.inputs['Density'])
        output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL')
        tree.links.new(scatter.outputs[0],output.inputs['Volume'])
        tree.nodes.remove(volume)


def threat_camera_clearance():
    """Keep the threat camera ahead of approaching sails through the cut."""
    from mathutils import Vector
    camera = bpy.data.objects['03_Giant_threat']
    assert camera.animation_data is None
    camera.location = (8,-1,2.6)
    camera.rotation_euler = (Vector((0,12,5.2))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.lens = 28


def build():
    from fleet_look import apply as look
    from fleet_fall import apply as fall
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(BASE/'v2/scene.blend'),use_scripts=False)
    bpy.context.preferences.filepaths.save_version = 0
    look()
    counterattack_exchange()
    fall()
    staging_updates()
    threat_camera_clearance()
    repair_dust_volumes()
    defeat_expression()
    scene = bpy.context.scene
    scene.render.resolution_percentage = 100
    scene.eevee.taa_render_samples = 48
    scene.render.use_motion_blur = True
    scene['fleet_review_status'] = 'candidate: requires full scene and fall review'
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene_candidate.blend'))
    meta = json.loads((BASE/'v2/staging.json').read_text(encoding='utf8'))
    meta['revision'] = 'v3 candidate'
    meta['unreviewed'] = ['whole fall motion and skin twist','interaction clearance',
                          'counterattack target','final impact framing','audio sync']
    (OUT/'staging.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    events = json.loads((BASE/'v2/audio/events_picture.json').read_text(encoding='utf8'))
    for event in events['events']:
        if event['id'] == 'giant_shore_fall':
            event['frame'] = 480
    events['status'] = 'v3 picture timings; requires final picture review, not heard'
    (OUT/'audio').mkdir(exist_ok=True)
    (OUT/'audio/events_picture.json').write_text(
        json.dumps(events,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('FLEET_V3_CANDIDATE_READY')


if __name__ == '__main__':
    build()
