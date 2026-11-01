"""Small study of ballistic timing, arcs and volume-preserving impact shapes.

Blender -b --python-exit-code 2 -P tools/blender/study_bounce.py -- --out PATH
A stylized kinematic exercise, not a mass/soft-body simulation or character rig.
"""
from pathlib import Path
import argparse,json,math,sys


def trajectory(t,restitution,height=2.6,gravity=9.81,radius=.38):
    if not 0<restitution<1 or height<=0 or gravity<=0:raise ValueError('Invalid trajectory')
    first=math.sqrt(2*height/gravity);impacts=[first];speed=gravity*first
    segments=[];at=first
    while (speed*restitution)**2/(2*gravity)>.008:
        speed*=restitution;duration=2*speed/gravity
        segments.append((at,at+duration,speed));at+=duration;impacts.append(at)
    if t<first:h=height-.5*gravity*t*t;v=-gravity*t
    else:
        h=v=0.
        for a,b,initial in segments:
            if a<=t<b:u=t-a;h=initial*u-.5*gravity*u*u;v=initial-gravity*u;break
    pulse=max((math.exp(-((t-i)/.065)**2) for i in impacts),default=0.)
    z=(1+.08*min(abs(v)/9,1))*(1-pulse)+(1-.22)*pulse
    # The compressed lower surface stays on the floor; volume is invariant.
    xy=1/math.sqrt(z)
    stop=impacts[-1];u=max(0,min(1,(t-stop)/.3))
    progress=t if t<=stop else stop+.3*(u-u**3+.5*u**4)
    return (-2+1.4*progress,radius*z+max(0,h)),(xy,xy,z),impacts


def main():
    import bpy
    from mathutils import Vector
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True);sc=bpy.context.scene
    sc.render.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=32
    sc.render.resolution_x=640;sc.render.resolution_y=360;sc.render.resolution_percentage=100
    sc.render.fps=30;sc.frame_start=0;sc.frame_end=119
    sc.world=bpy.data.worlds.new('StudyWorld');sc.world.use_nodes=True;sc.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.18,.2,.24,1)
    sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.45
    def material(name,color):
        mat=bpy.data.materials.new(name);mat.diffuse_color=(*color,1);mat.use_nodes=True
        node=mat.node_tree.nodes.get('Principled BSDF');node.inputs['Base Color'].default_value=(*color,1);node.inputs['Roughness'].default_value=.55
        return mat
    bpy.ops.mesh.primitive_plane_add(size=200);bpy.context.object.data.materials.append(material('Ground',(.16,.18,.2)))
    balls=[];report=[]
    for name,y,e,color in [('Elastic',.95,.62,(.10,.38,.52)),('Damped',-.95,.28,(.62,.28,.10))]:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=.38);obj=bpy.context.object;obj.name=name
        obj.data.materials.append(material(name+'Mat',color))
        for poly in obj.data.polygons:poly.use_smooth=True
        minimum=1.;volume_error=0.
        for i in range(477):
            f=i/4;t=f/30;(x,z),scale,impacts=trajectory(t,e)
            obj.location=(x,y,z);obj.scale=scale;obj.keyframe_insert('location',frame=f);obj.keyframe_insert('scale',frame=f)
            minimum=min(minimum,z-.38*scale[2]);volume_error=max(volume_error,abs(math.prod(scale)-1))
        for layer in obj.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:key.interpolation='LINEAR'
        report.append(dict(name=name,restitution=e,impacts_s=impacts,min_analytic_floor_gap=minimum,max_analytic_volume_error=volume_error));balls.append(obj)
    cam=bpy.data.objects.new('Camera',bpy.data.cameras.new('Camera'));sc.collection.objects.link(cam);sc.camera=cam
    cam.location=(6,-9,6);target=Vector((.2,0,1));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=8.8
    light=bpy.data.objects.new('Softbox',bpy.data.lights.new('Softbox','AREA'));sc.collection.objects.link(light);light.location=(-3,-4,8);light.data.energy=1400;light.data.shape='DISK';light.data.size=5
    light.rotation_euler=(Vector((0,0,0))-light.location).to_track_quat('-Z','Y').to_euler()
    saved_min=1.;saved_volume=0.
    for i in range(953):
        f=i/8;sc.frame_set(int(f),subframe=f%1)
        for obj in balls:
            saved_min=min(saved_min,obj.location.z-.38*obj.scale.z);saved_volume=max(saved_volume,abs(math.prod(obj.scale)-1))
    assert saved_min>=-1e-6 and saved_volume<.003
    (out/'qa.json').write_text(json.dumps(dict(cases=report,saved_min_floor_gap=saved_min,saved_max_volume_error=saved_volume,limits='Analytic spheres and saved key playback; no character balance, cloth or real soft-body simulation.'),indent=2))
    from bpy_extras.object_utils import world_to_camera_view
    points=[]
    for f in range(120):
        sc.frame_set(f);bpy.context.view_layer.update()
        points.extend(obj.matrix_world@Vector(v) for obj in balls for v in obj.bound_box)
    for attempt in range(20):
        uv=[world_to_camera_view(sc,cam,p) for p in points]
        if all(.03<=p.x<=.97 and .03<=p.y<=.97 and p.z>0 for p in uv):break
        cam.data.ortho_scale*=1.05
    else:raise ValueError('Study camera cannot fit the complete trajectory')
    qa=json.loads((out/'qa.json').read_text());qa['framing_samples']=len(points);qa['ortho_scale']=cam.data.ortho_scale
    (out/'qa.json').write_text(json.dumps(qa,indent=2))
    sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    (out/'frames').mkdir(exist_ok=True);sc.render.image_settings.file_format='PNG';sc.render.filepath=str(out/'frames/f');bpy.ops.render.render(animation=True)

if __name__=='__main__':main()
