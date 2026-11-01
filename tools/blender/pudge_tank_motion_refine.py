"""Apply the final boarding correction to an existing motion build."""
from pathlib import Path
import bpy
from mathutils import Vector

s=bpy.context.scene
out=Path(bpy.data.filepath).parent
obstruction=bpy.data.objects.get('radiant_tower002.radiant_tower002_model.004')
if obstruction:
    bpy.data.objects.remove(obstruction,do_unlink=True)
h=bpy.data.objects['pudge_root']
start=Vector((-78.8,87,3.2511901855))
seat=Vector((-83.5,88.4,5.8))
for frame in range(54,84):
    u=frame/30-1.8
    k=min(1.,u/.75)
    h.location=start.lerp(seat,k*k*(3-2*k))
    h.location.z=start.z+(seat.z-start.z)*u+12.5*u*(1-u)
    h.keyframe_insert('location',frame=frame)
s.frame_set(0)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'),compress=True)
for frame in (65,81,91):
    s.frame_set(frame)
    s.render.filepath=str(out/f'probe_{frame:05d}.png')
    bpy.ops.render.render(write_still=True)
