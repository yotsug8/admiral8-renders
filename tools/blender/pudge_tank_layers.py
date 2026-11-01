"""Render fixed-camera environment plates and the complete moving tank cast."""
import json
from pathlib import Path
import bpy

scene=bpy.context.scene
out=Path(bpy.data.filepath).parent
data=json.loads((out/'build.json').read_text(encoding='utf-8'))
roots=[bpy.data.objects[n] for n in ('pudge_root','detailed_tank','heavy_launcher','enemy_ancient')]
moving={o for root in roots for o in (root,*root.children_recursive)}
moving.update(o for o in scene.objects if o.name.startswith('blast volume'))
scene.render.image_settings.color_mode='RGBA'
scene.render.film_transparent=False
cuts=data['cuts']
for index,(start,end) in enumerate(zip(cuts,cuts[1:])):
    scene.frame_set((start+end)//2)
    visible={o:o.hide_render for o in moving}
    for o in moving:
        o.hide_render=True
    scene.render.filepath=str(out/f'plate_{index}.png')
    bpy.ops.render.render(write_still=True)
    for o,hidden in visible.items():
        o.hide_render=hidden
bpy.data.batch_remove([o for o in scene.objects if o not in moving and o.type not in ('LIGHT','CAMERA')])
scene.render.film_transparent=True
scene.render.filepath=str(out/'layers/f#####')
scene.frame_set(0)
scene.render.use_overwrite=True
scene.render.use_placeholder=False
bpy.ops.wm.save_as_mainfile(filepath=str(out/'layers.blend'),compress=True)
scene.frame_start,scene.frame_end=0,data['frames']-1
bpy.ops.render.render(animation=True)
