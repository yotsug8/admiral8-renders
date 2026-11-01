"""Refine the greeting's first portrait and keep speech articulation restrained."""
import json
from pathlib import Path
import bpy
from mathutils import Vector

OUT = Path(__file__).resolve().parents[2] / '_game/skits/privet'
bpy.ops.wm.open_mainfile(filepath=str(OUT / 'privet.blend'))
scene = bpy.context.scene
camera = scene.camera
poses = []
data = json.loads((OUT / 'scene.json').read_text(encoding='utf-8'))
first_cut = round(data['shots'][1][0] * data['fps'])
for frame in range(first_cut):
    scene.frame_set(frame)
    distance = camera.data.dof.focus_distance
    target = camera.location + camera.rotation_euler.to_quaternion() @ Vector((0, 0, -distance))
    position = target + (camera.location - target) * 1.65 + Vector((0, 0, 0.6))
    rotation = (target - position).to_track_quat('-Z', 'Y').to_euler()
    poses.append((frame, position, rotation, camera.data.lens * 1.4, (position - target).length))
for frame, position, rotation, lens, distance in poses:
    camera.location = position
    camera.rotation_euler = rotation
    camera.data.lens = lens
    camera.data.dof.focus_distance = distance
    camera.keyframe_insert('location', frame=frame)
    camera.keyframe_insert('rotation_euler', frame=frame)
    camera.data.keyframe_insert('lens', frame=frame)
    camera.data.dof.keyframe_insert('focus_distance', frame=frame)

head = next(o for o in bpy.data.objects['pudge_root'].children_recursive
            if o.type == 'MESH' and o.data.shape_keys)
action = head.data.shape_keys.animation_data.action
for layer in action.layers:
    for strip in layer.strips:
        for bag in strip.channelbags:
            for curve in bag.fcurves:
                if curve.data_path != 'key_blocks["jawOpen"].value':
                    continue
                for key in curve.keyframe_points:
                    key.co.y *= 0.65
                    key.handle_left.y *= 0.65
                    key.handle_right.y *= 0.65
                curve.update()
scene.frame_set(0)
scene.render.filepath = str(OUT / 'frames/f#####')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'privet_review.blend'))
for frame in (0, 41, first_cut - 1, first_cut, 323):
    scene.frame_set(frame)
    scene.render.filepath = str(OUT / f'refined_{frame:05d}.png')
    bpy.ops.render.render(write_still=True)
