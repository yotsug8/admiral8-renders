"""Native forest horizon around an existing chase, outside the actor/camera area."""
import math
import bpy
from mathutils import Matrix, Vector
from chase_environment import _environment_meshes, _environment_bounds, _extend_native_ground


def add_depth(scene, center=(-83.,96.), radii=(48.,63.,78.)):
    for obj in list(scene.objects):
        if obj.get('chase_horizon'):
            bpy.data.objects.remove(obj,do_unlink=True)
    originals=_environment_meshes(scene)
    pairs=[];seen=set()
    for obj in sorted(originals,key=lambda o:o.name):
        if 'tree_pine_0' not in obj.name or '_model.' not in obj.name or obj.name.startswith('chase_'):continue
        leaves=bpy.data.objects.get(obj.name.replace('_model.','_inspector.'))
        if leaves not in originals:continue
        key=(obj.data.name,leaves.data.name)
        if key in seen:continue
        seen.add(key);pairs.append((obj,leaves))
        if len(pairs)==6:break
    if not pairs:raise ValueError('No complete native tree pairs')
    x,y=center;added=[]
    for band,radius in enumerate(radii):
        count=round(2*math.pi*radius/8.)
        for i in range(count):
            angle=2*math.pi*(i+.37*band)/count
            px=x+radius*math.cos(angle);py=y+radius*math.sin(angle)
            pair=pairs[(i+band)%len(pairs)];lo,hi=_environment_bounds(pair)
            anchor=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z))
            scale=.9+.08*((i+2*band)%4)
            transform=Matrix.Translation(Vector((px,py,3.23)))@Matrix.Rotation(i*.77,4,'Z')@Matrix.Scale(scale,4)@Matrix.Translation(-anchor)
            for part in pair:
                obj=part.copy();obj.parent=None;obj.animation_data_clear();obj.constraints.clear()
                obj.name=f'chase_horizon_{band}_{i:03d}_{part.name}';obj['chase_horizon']=True
                scene.collection.objects.link(obj);obj.matrix_world=transform@part.matrix_world
                obj.hide_render=obj.hide_viewport=False;obj.hide_set(False);added.append(obj.name)
    # Reuse a cropped native ground mesh, including its UVs/materials. Tile only
    # the distant zone: existing performance terrain is never replaced.
    template=_extend_native_ground(scene,x=x,end_y=128.)[0];ground=[]
    for ix in range(-4,5):
        for iy in range(-7,8):
            px=x+18*ix;py=y+12*iy
            if abs(px-x)<36 and 60<py<140:continue
            obj=template.copy();obj.name=f'chase_horizon_ground_{ix}_{iy}';obj['chase_horizon']=True
            if 'chase_v2_environment' in obj:del obj['chase_v2_environment']
            scene.collection.objects.link(obj);obj.location=Vector((px-x,py-122,-.02));ground.append(obj.name)
    bpy.data.objects.remove(template,do_unlink=True)
    bpy.context.view_layer.update()
    return dict(tree_parts=len(added),ground_tiles=len(ground),radii=list(radii),center=list(center),
                limitations='Horizon geometry only; camera framing and occlusion must be checked per scene.')
