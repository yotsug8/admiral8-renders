"""Keep the column as the visual anchor across the identity change (v8).
Run on preserved v7 final scene; actor animation and environment stay intact.
"""
import bpy
from pathlib import Path
from mathutils import Vector
s=bpy.context.scene
out=Path('out/dota-jojo/v8');out.mkdir(parents=True,exist_ok=True)
def pose(cam,frame,loc,target,lens):
 cam.location=loc
 cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
 cam.data.lens=lens
 cam.data.dof.focus_distance=(Vector(target)-cam.location).length
 for key in ['location','rotation_euler']:cam.keyframe_insert(key,frame=frame)
 for key in ['lens','dof.focus_distance']:cam.data.keyframe_insert(key,frame=frame)
def clear(name):
 c=bpy.data.objects[name];c.animation_data_clear();c.data.animation_data_clear();c.data.dof.aperture_fstop=8;return c
left=((-4.5,-7.5,3.2),(-1.9,-.6,2.4),31)
right=((4.6,-7.6,3.3),(1.7,-.6,2.4),32)
# Preserve the close opening. The following paired views retain the same
# recognizable column on opposite edges, connecting both sides of the reveal.
c=clear('02_Time_erasure')
for f in [91,154]:pose(c,f,*left)
c=clear('03_Diavolo_glimpse')
for f in [155,244]:pose(c,f,*right)
# Keep the existing transformation cut, now anchored by visible architecture.
s.frame_start=1;s.frame_end=504;s.frame_set(1)
s.eevee.shadow_pool_size='1024'
bpy.ops.wm.save_as_mainfile(filepath=str(out/'jojo-v8.blend'))
s.render.resolution_percentage=40;s.eevee.taa_render_samples=24
probes=Path('D:/Admiral8-temp/dota-jojo/v8-probes');probes.mkdir(exist_ok=True)
for f in [91,132,154,155,180,223]:
 s.frame_set(f);s.render.filepath=str(probes/f'{f:04d}.png');bpy.ops.render.render(write_still=True)
