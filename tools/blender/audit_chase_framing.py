"""Compare projected evaluated vertices with object bounding boxes, read-only.

Includes transparent surfaces; does not prove visibility or occlusion clearance.
"""
import argparse
import json
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def project(points, matrix):
    clip = np.c_[points, np.ones(len(points))] @ matrix.T
    if np.any(clip[:,3] <= 0):
        raise ValueError('Actor geometry reaches or crosses camera plane')
    return clip[:,:2]/clip[:,3,None]*.5+.5


def bounds(points):
    return [*points.min(axis=0).tolist(), *points.max(axis=0).tolist()]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--actors',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--start',type=int,default=240)
    p.add_argument('--stop',type=int,default=336)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.out.exists() or args.start>=args.stop:
        raise ValueError('New output file and nonempty range required')
    scene=bpy.context.scene
    actors=json.loads(args.actors.read_text(encoding='utf-8'))
    rows=[];exact_all=[];box_all=[]
    for frame in range(args.start,args.stop):
        scene.frame_set(frame);dg=bpy.context.evaluated_depsgraph_get()
        camera=scene.camera.evaluated_get(dg)
        projection=np.array(camera.calc_matrix_camera(dg,x=scene.render.resolution_x,
            y=scene.render.resolution_y,scale_x=scene.render.pixel_aspect_x,
            scale_y=scene.render.pixel_aspect_y))
        view=np.array(camera.matrix_world.inverted())
        row=dict(frame=frame,actors={})
        for hero,actor in actors.items():
            real=[];boxes=[]
            for name in actor['objs']:
                obj=bpy.data.objects[name]
                if obj.type!='MESH' or obj.hide_render or any(t in name.lower() for t in ('physics','hitbox','blob')):
                    continue
                evaluated=obj.evaluated_get(dg);mesh=evaluated.to_mesh()
                try:
                    if not mesh.vertices: continue
                    xyz=np.empty(len(mesh.vertices)*3,dtype=np.float32)
                    mesh.vertices.foreach_get('co',xyz);xyz=xyz.reshape(-1,3)
                    matrix=projection@view@np.array(evaluated.matrix_world)
                    uv=project(xyz,matrix)
                    witness=world_to_camera_view(scene,camera,evaluated.matrix_world@Vector(xyz[0]))
                    if np.max(np.abs(uv[0]-[witness.x,witness.y]))>1e-4:
                        raise ValueError('Projection differs from Blender reference')
                    real.append(uv);boxes.append(project(np.array(evaluated.bound_box),matrix))
                finally:evaluated.to_mesh_clear()
            if not real: raise ValueError('No visible actor geometry: '+hero)
            real=np.concatenate(real);boxes=np.concatenate(boxes)
            rb,bb=bounds(real),bounds(boxes)
            row['actors'][hero]=dict(vertices=rb,object_boxes=bb)
            exact_all.extend([rb[:2],rb[2:]]);box_all.extend([bb[:2],bb[2:]])
        rows.append(row)
    real=bounds(np.array(exact_all));boxes=bounds(np.array(box_all))
    zoom=min(.805/(real[2]-real[0]),.73/(real[3]-real[1]))
    result=dict(frames=rows,vertex_union=real,box_union=boxes,
        theoretical_zoom_with_recentering=zoom,
        limits='Integer frames only; includes transparent geometry. No occlusion or artistic pass. '
               'Zoom is a screen-space bound, not an implemented or verified new camera.')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='frames'}),flush=True)


if __name__=='__main__':main()
