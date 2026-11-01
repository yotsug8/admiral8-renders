"""Render the revised boarding background from the preserved full scene."""
from pathlib import Path
import bpy
from mathutils import Vector
s=bpy.context.scene
s.frame_set(65)
s.camera.animation_data_clear();s.camera.data.animation_data_clear()
s.camera.rotation_euler=(Vector((-81.7,87.8,5.95))-s.camera.location).to_track_quat('-Z','Y').to_euler()
s.camera.data.lens=24
for name in ('pudge_root','detailed_tank','heavy_launcher','enemy_ancient'):
    root=bpy.data.objects[name]
    for o in (root,*root.children_recursive):o.hide_render=True
for o in s.objects:
    if o.name.startswith('blast volume') or o.name=='pudge_blob':o.hide_render=True
s.render.film_transparent=False
s.render.filepath=str(Path(__file__).resolve().parents[2]/'_game/skits/pudge_tank/action_v3/plate_1.png')
bpy.ops.render.render(write_still=True)
s.camera.location=(-79.2,81,9)
target=Vector((-83.4,86.1,7.4))
s.camera.rotation_euler=(target-s.camera.location).to_track_quat('-Z','Y').to_euler()
s.camera.data.lens=26
s.camera.data.dof.aperture_fstop=2.8
s.camera.data.dof.focus_distance=(target-s.camera.location).length
s.render.filepath=str(Path(__file__).resolve().parents[2]/'_game/skits/pudge_tank/action_v3/plate_2.png')
bpy.ops.render.render(write_still=True)
