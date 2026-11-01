"""Render static camera plates and animated heroes separately for the greeting."""
import json
from pathlib import Path
import bpy

OUT = Path(__file__).resolve().parents[2] / '_game/skits/privet'
bpy.ops.wm.open_mainfile(filepath=str(OUT / 'privet_culled.blend'))
scene = bpy.context.scene
camera = scene.camera
data = json.loads((OUT / 'scene.json').read_text(encoding='utf-8'))
cuts = [round(shot[0] * data['fps']) for shot in data['shots']] + [data['frames']]
poses = []
for start, end in zip(cuts, cuts[1:]):
    frame = round((start + end) / 2)
    scene.frame_set(frame)
    poses.append((start, end, frame, camera.location.copy(), camera.rotation_euler.copy(),
                  camera.data.lens, camera.data.dof.focus_distance, camera.data.dof.aperture_fstop))
camera.animation_data_clear()
camera.data.animation_data_clear()
for start, end, _, position, rotation, lens, distance, aperture in poses:
    for frame in (start, end - 1):
        camera.location = position
        camera.rotation_euler = rotation
        camera.data.lens = lens
        camera.data.dof.focus_distance = distance
        camera.data.dof.aperture_fstop = aperture
        camera.keyframe_insert('location', frame=frame)
        camera.keyframe_insert('rotation_euler', frame=frame)
        camera.data.keyframe_insert('lens', frame=frame)
        camera.data.dof.keyframe_insert('focus_distance', frame=frame)
        camera.data.dof.keyframe_insert('aperture_fstop', frame=frame)
for owner in (camera, camera.data):
    for layer in owner.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = 'CONSTANT'
roots = [bpy.data.objects[name + '_root'] for name in ('pudge', 'sniper')]
heroes = {o for root in roots for o in (root, *root.children_recursive)}
visibility = {o: o.hide_render for o in heroes}
scene.render.image_settings.color_mode = 'RGBA'
scene.render.film_transparent = False
for index, pose in enumerate(poses):
    scene.frame_set(pose[2])
    for obj in heroes:
        obj.hide_render = True
    scene.render.filepath = str(OUT / f'plate_{index}.png')
    bpy.ops.render.render(write_still=True)
for obj, hidden in visibility.items():
    obj.hide_render = hidden
# The established soft contact shadows are children of the actor roots.
bpy.data.batch_remove([o for o in scene.objects if o not in heroes and o.type not in ('LIGHT', 'CAMERA')])
scene.render.film_transparent = True
scene.render.filepath = str(OUT / 'layers/f#####')
scene.frame_set(0)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'privet_layers.blend'))
(OUT / 'layers.json').write_text(json.dumps({'cuts': cuts, 'reference_frames': [p[2] for p in poses]}, indent=2), encoding='utf-8')
scene.frame_start, scene.frame_end = 0, data['frames'] - 1
scene.render.use_overwrite = True
scene.render.use_placeholder = False
bpy.ops.render.render(animation=True)
