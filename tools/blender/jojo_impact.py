"""Restore a sharp time-erasure beat on v11; preserve the HDR space look."""
import bpy
from pathlib import Path
s=bpy.context.scene
out=Path('out/dota-jojo/v12');out.mkdir(parents=True,exist_ok=True)
normal={o.name for o in bpy.data.objects['PUDGE_DOPPIO'].children_recursive if o.type=='MESH'}
normal.update(o.name for name in ['observer','sentry'] for o in bpy.data.objects['ITEM / '+name].children_recursive if o.type=='MESH')
normal.update(o.name for o in s.objects if o.name.startswith('ANATOMY / fitted neck / PUDGE_DOPPIO'))
for o in s.objects:
 if o.type!='MESH':continue
 for mat in o.data.materials:
  if not mat or not mat.use_nodes:continue
  node=mat.node_tree.nodes.get('Erased time progression')
  if not node:continue
  values=[(100,-.1),(114,-.1),(116,-.1),(120,1.1)] if o.name in normal else [(70,-.1),(84,-.1),(90,1.1),(100,1.1)]
  for f,v in values:node.outputs[0].default_value=v;node.outputs[0].keyframe_insert('default_value',frame=f)
# Use true rendered detail instead of scaling or sharpening compressed previews.
s.render.resolution_x=720;s.render.resolution_y=1280;s.render.resolution_percentage=100
s.eevee.taa_render_samples=32
s.render.use_motion_blur=False
s.frame_start=1;s.frame_end=504;s.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'jojo-v12.blend'))
p=Path('D:/Admiral8-temp/dota-jojo/v12-frames');p.mkdir(exist_ok=True)
s.frame_start=70;s.frame_end=244;s.render.filepath=str(p/'frame_')
bpy.ops.render.render(animation=True)
