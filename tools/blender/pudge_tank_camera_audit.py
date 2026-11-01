"""Report scene geometry immediately in front of the boarding camera."""
import bpy
from mathutils import Vector
s=bpy.context.scene
s.frame_set(65)
origin=s.camera.matrix_world.translation
for x in (-.3,0,.3):
    for y in (-.5,0,.5):
        direction=s.camera.matrix_world.to_quaternion()@Vector((x,y,-1)).normalized()
        hit,point,normal,index,obj,matrix=s.ray_cast(bpy.context.evaluated_depsgraph_get(),origin,direction,distance=15)
        print('CAMERA_HIT',obj.name if hit else None,tuple(point),flush=True)
