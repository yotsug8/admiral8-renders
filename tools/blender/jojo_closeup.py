"""Push in after the column-anchored transformation; run on preserved v8."""
import bpy
from pathlib import Path
from mathutils import Vector
s=bpy.context.scene
out=Path('out/dota-jojo/v9');out.mkdir(parents=True,exist_ok=True)
c=bpy.data.objects['03_Diavolo_glimpse'];c.animation_data_clear();c.data.animation_data_clear()
c.data.lens=32;c.data.dof.aperture_fstop=8
# Establish the same column for half a second, then approach into a face-and-shoulders portrait.
for f,loc,target in [(155,(4.6,-7.6,3.3),(1.7,-.6,2.4)),(170,(4.6,-7.6,3.3),(1.7,-.6,2.4)),(244,(1.2,-3.8,2.8),(2.15,-.4,2.4))]:
 c.location=loc;c.rotation_euler=(Vector(target)-c.location).to_track_quat('-Z','Y').to_euler()
 c.data.lens=40 if f==244 else 32
 c.data.keyframe_insert('lens',frame=f)
 c.data.dof.focus_distance=(Vector(target)-c.location).length
 for key in ['location','rotation_euler']:c.keyframe_insert(key,frame=f)
 c.data.keyframe_insert('dof.focus_distance',frame=f)
s.frame_start=1;s.frame_end=504;s.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'jojo-v9.blend'))
s.render.resolution_percentage=50;s.eevee.taa_render_samples=32
p=Path('D:/Admiral8-temp/dota-jojo/v9-probes');p.mkdir(exist_ok=True)
for f in [155,190,220,244]:
 s.frame_set(f);s.render.filepath=str(p/f'{f:04d}.png');bpy.ops.render.render(write_still=True)
