"""Depth, local weapon arrest and landing effects over verified v3/v4 staging.

Blender --background --python tools/blender/doomsday_atmosphere.py -- probe|draft|patch
Assets are reused from the documented source scene; no new external dependency.
"""
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '_game/skits/doomsday/v3'
OUT = ROOT / '_game/skits/doomsday/v5'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from doomsday_refine import gpu, ground, smooth
from doomsday_composition import camera


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ridge(x, y):
    radius = math.hypot(x, y+1)
    angle = math.atan2(y+1, x)
    return smooth((radius-7.5)/6) * (2.2 + 1.1*math.sin(angle*3+.7))


def boulder_template(scene):
    return next(o for o in scene.objects if o.type == 'MESH' and any(
        n.type == 'TEX_IMAGE' and n.image and 'boulder_01' in n.image.name
        for m in o.data.materials if m and m.use_nodes for n in m.node_tree.nodes))


def environment(scene):
    floor = scene.objects['Stone court']
    flat_before = [v.co.z for v in floor.data.vertices if math.hypot(v.co.x, v.co.y+1)<7.5]
    for v in floor.data.vertices:
        v.co.z += ridge(v.co.x, v.co.y)
    if flat_before != [v.co.z for v in floor.data.vertices if math.hypot(v.co.x, v.co.y+1)<7.5]:
        raise ValueError('Action ground changed')
    # Keep existing props seated on the revised distant terrain.
    for ob in list(scene.objects):
        if ob.type != 'MESH' or ob == floor or ob.name == 'Distant air' or ob.parent:
            continue
        if any(m.type == 'ARMATURE' for m in ob.modifiers):
            continue
        ob.location.z += ridge(ob.location.x, ob.location.y)
    template = boulder_template(scene)
    layout = [(-13,6,6.5),(-3,12,6.8),(4,14,7.6),(10,9,5.5),
              (-12,-6,6.6),(-5,-13,5.8),(5,-14,7.1),(11,-5,5.2)]
    added = []
    for i,(x,y,height) in enumerate(layout):
        ob = template.copy()
        ob.data = template.data
        ob.name = f'Background rock mass {i}'
        ob.animation_data_clear()
        scene.collection.objects.link(ob)
        ob.location = (x,y,ground(x,y)+ridge(x,y)-height*.2)
        ob.scale = (height*(1.15 if i%2 else 1.5), height*.8, height)
        ob.rotation_euler = (0,0,i*2.39996)
        added.append(ob)
    # Cool, matte stone separates the warmer character lighting.
    for mat in template.data.materials:
        nt = mat.node_tree
        p = next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
        source = p.inputs['Base Color'].links[0].from_socket
        hue = nt.nodes.new('ShaderNodeHueSaturation')
        hue.inputs['Saturation'].default_value = .55
        hue.inputs['Value'].default_value = .50
        nt.links.new(source,hue.inputs['Color'])
        nt.links.new(hue.outputs[0],p.inputs['Base Color'])
    scene.objects['Cold key'].data.size = 4
    scene.objects['Warm edge'].data.energy = 2200
    scene.objects['Distant daylight'].data.energy = .5
    scene.frame_set(60)
    bpy.context.view_layer.update()
    # A conservative exclusion cylinder keeps the new rock masses away from
    # the action and cameras. This is not a general mesh-intersection test.
    clearances = []
    for ob in added:
        points = [ob.matrix_world @ Vector(p) for p in ob.bound_box]
        xmin,xmax = min(p.x for p in points),max(p.x for p in points)
        ymin,ymax = min(p.y for p in points),max(p.y for p in points)
        dx = max(xmin,0,-xmax)
        dy = max(ymin+1,0,-ymax-1)
        clearances.append(math.hypot(dx,dy))
    if min(clearances)<5:
        raise ValueError(f'Background rock enters action area: {min(clearances)}')
    return template, {'flat_ground_vertices':len(flat_before),'new_rock_count':len(added),
                      'minimum_rock_aabb_distance':min(clearances)}


def visible_during(ob, start, end):
    for f, hidden in ((0,True),(start-1,True),(start,False),(end,False),(end+1,True),(107,True)):
        ob.hide_render = hidden
        ob.keyframe_insert('hide_render', frame=f)


def filament(scene, name, points, color, width, power):
    curve = bpy.data.curves.new(name,'CURVE')
    curve.dimensions = '3D'
    curve.bevel_depth = width
    curve.bevel_resolution = 2
    spline = curve.splines.new('POLY')
    spline.points.add(len(points)-1)
    for i,(p,co) in enumerate(zip(spline.points,points)):
        p.co = (*co,1)
        p.radius = .18+.82*math.sin(math.pi*i/(len(points)-1))
    ob = bpy.data.objects.new(name,curve)
    scene.collection.objects.link(ob)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emission = nt.nodes.new('ShaderNodeEmission')
    emission.inputs[0].default_value = (*color,1)
    emission.inputs[1].default_value = power
    nt.links.new(emission.outputs[0],nt.nodes.new('ShaderNodeOutputMaterial').inputs['Surface'])
    curve.materials.append(mat)
    return ob


def arrest(scene, axe):
    scene.frame_set(44)
    point = Vector(json.loads((SOURCE.parent/'v2/staging.json').read_text())['contact'])
    wrist = axe.matrix_world @ axe.pose.bones['wrist_R'].head
    weapon = next(o for o in scene.objects if o.type=='MESH' and 'axe_weapon' in o.name)
    evaluated = weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
    vertices = [evaluated.matrix_world @ v.co for v in evaluated.data.vertices]
    axis = (point-wrist).normalized()
    extent = max((p-wrist).dot(axis) for p in vertices)
    blade = [p for p in vertices if (p-wrist).dot(axis)>extent-.8]
    ends = [min(blade,key=lambda p:p.z),max(blade,key=lambda p:p.z),
            min(blade,key=lambda p:p.x),max(blade,key=lambda p:p.x)]
    rng = random.Random(512)
    for event,start in enumerate((44,49,55,61,67,72)):
        for strand in range(3):
            end = ends[(event+strand)%len(ends)]
            points = []
            for j in range(27):
                t = j/26
                jitter = Vector((rng.uniform(-.035,.035),rng.uniform(-.045,.02),rng.uniform(-.035,.035)))
                points.append(point.lerp(end,t)+jitter*math.sin(math.pi*t))
            ob = filament(scene,f'Arrest filament {event} {strand}',points,(.12,1,.25),.004,24)
            visible_during(ob,start,start+4)
    for ob in scene.objects:
        if ob.type!='CURVE':continue
        if ob.name.startswith('Charge '):
            ob.data.bevel_depth *= 1.35
            for mat in ob.data.materials:
                for node in mat.node_tree.nodes:
                    if node.type=='EMISSION':node.inputs[1].default_value=12
        if ob.name.startswith('Contact spark '):
            ob.data.bevel_depth *= 1.5
            for p in ob.data.splines[0].points:p.co.z *= 1.8
    light = scene.objects['Arrest light'].data
    light.animation_data_clear()
    for f,power in ((0,0),(43,0),(44,300),(46,450),(51,130),(67,65),(76,20),(107,20)):
        light.energy=power
        light.keyframe_insert('energy',frame=f)


def dust_material():
    # Same bounded noise-volume method as the existing tank production.
    mat=bpy.data.materials.new('Landing dust');mat.use_nodes=True
    nt=mat.node_tree;nt.nodes.clear()
    volume=nt.nodes.new('ShaderNodeVolumePrincipled')
    volume.inputs['Color'].default_value=(.30,.26,.20,1)
    coords=nt.nodes.new('ShaderNodeTexCoord')
    noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=5
    nt.links.new(coords.outputs['Generated'],noise.inputs['Vector'])
    distance=nt.nodes.new('ShaderNodeVectorMath');distance.operation='DISTANCE'
    distance.inputs[1].default_value=(.5,.5,.5)
    nt.links.new(coords.outputs['Generated'],distance.inputs[0])
    fall=nt.nodes.new('ShaderNodeMapRange');fall.inputs['From Min'].default_value=.15
    fall.inputs['From Max'].default_value=.5;fall.inputs['To Min'].default_value=1;fall.inputs['To Max'].default_value=0
    nt.links.new(distance.outputs['Value'],fall.inputs['Value'])
    multiply=nt.nodes.new('ShaderNodeMath');multiply.operation='MULTIPLY'
    nt.links.new(noise.outputs['Fac'],multiply.inputs[0]);nt.links.new(fall.outputs[0],multiply.inputs[1])
    density=nt.nodes.new('ShaderNodeMath');density.operation='MULTIPLY';density.inputs[1].default_value=5
    nt.links.new(multiply.outputs[0],density.inputs[0]);nt.links.new(density.outputs[0],volume.inputs['Density'])
    nt.links.new(volume.outputs[0],nt.nodes.new('ShaderNodeOutputMaterial').inputs['Volume'])
    return mat


def landing(scene, axe, template):
    scene.frame_set(60)
    origins=[axe.matrix_world @ axe.pose.bones['ankle_'+side].head for side in ('L','R')]
    mat=dust_material()
    for i,origin in enumerate(origins):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1)
        ob=bpy.context.object;ob.name=f'Landing dust {i}';ob.data.materials.append(mat)
        visible_during(ob,60,83)
        for f in range(60,84):
            t=(f-60)/23;radius=.12+.8*smooth((f-60)/8)
            ob.location=(origin.x+(-1 if i==0 else 1)*.6*t,origin.y+.12*t,.08+.16*t)
            ob.scale=(radius,radius*.8,.10+.16*t)
            for prop in ('location','scale'):ob.keyframe_insert(prop,frame=f)
        # Separate material per cloud allows dissipation rather than shrinkage.
        ob.data.materials[0]=mat.copy()
        gain=next(n for n in ob.data.materials[0].node_tree.nodes if n.type=='MATH' and n.inputs[1].default_value==5)
        for f,value in ((60,0),(62,18),(68,12),(76,2),(83,0)):
            gain.inputs[1].default_value=value;gain.inputs[1].keyframe_insert('default_value',frame=f)
    rng=random.Random(50)
    for i in range(8):
        origin=origins[i%2]
        ob=template.copy();ob.data=template.data;ob.animation_data_clear()
        scene.collection.objects.link(ob);ob.name=f'Landing pebble {i}'
        radius=rng.uniform(.035,.075);ob.scale=(radius,)*3
        velocity=Vector(((-1 if i%2==0 else 1)*rng.uniform(.4,1.2),rng.uniform(-.6,.7),rng.uniform(.7,1.3)))
        airborne=2*velocity.z/9.81
        for f in range(60,108):
            t=min((f-60)/30,airborne)
            ob.location=(origin.x+velocity.x*t,origin.y+velocity.y*t,max(.015,velocity.z*t-4.905*t*t+.015))
            ob.rotation_euler=(t*4,t*3,i*.7)
            for prop in ('location','rotation_euler'):ob.keyframe_insert(prop,frame=f)
        for f,hidden in ((0,True),(59,True),(60,False),(107,False)):
            ob.hide_render=hidden;ob.keyframe_insert('hide_render',frame=f)


def glow(scene):
    """Optical bloom from the linear emission pass, never diffuse surfaces."""
    scene.view_layers[0].use_pass_emit=True
    tree=bpy.data.node_groups.new('Local magic bloom','CompositorNodeTree')
    tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
    layers=tree.nodes.new('CompositorNodeRLayers')
    glare=tree.nodes.new('CompositorNodeGlare')
    glare.inputs['Type'].default_value='Fog Glow'
    glare.inputs['Quality'].default_value='High'
    glare.inputs['Threshold'].default_value=.5
    glare.inputs['Size'].default_value=.25
    glare.inputs['Strength'].default_value=.65
    tree.links.new(layers.outputs['Emission'],glare.inputs['Image'])
    mix=tree.nodes.new('ShaderNodeMix');mix.data_type='RGBA';mix.blend_type='ADD'
    mix.clamp_result=False;mix.inputs[0].default_value=.5
    tree.links.new(layers.outputs['Image'],mix.inputs[6])
    tree.links.new(glare.outputs['Glare'],mix.inputs[7])
    tree.links.new(mix.outputs[2],tree.nodes.new('NodeGroupOutput').inputs['Image'])
    scene.compositing_node_group=tree
    scene.render.use_compositing=True


def main():
    mode=sys.argv[sys.argv.index('--')+1]
    if mode not in ('probe','draft','patch'):raise ValueError(mode)
    OUT.mkdir(parents=True,exist_ok=True)
    folder=OUT/('probe' if mode=='probe' else 'frames');folder.mkdir(exist_ok=True)
    manifest=folder/'manifest.json'
    previous=None
    if mode=='patch':
        previous=json.loads(manifest.read_text())
        for f,expected in zip(previous['source_frames'],previous['frame_sha256']):
            if sha(folder/f'{f:04d}.png')!=expected:raise ValueError('Patch base frame mismatch')
        (OUT/'base_manifest.json').write_bytes(manifest.read_bytes())
    manifest.unlink(missing_ok=True)
    source_manifest=json.loads((SOURCE/'frames/manifest.json').read_text())
    source_sha=sha(SOURCE/'scene.blend')
    if source_sha!=source_manifest['blend_sha256']:raise ValueError('Source scene/cache mismatch')
    staging=json.loads((SOURCE.parent/'v4/frames/manifest.json').read_text())['camera']
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE/'scene.blend'))
    scene=bpy.context.scene;gpu(scene);scene.cycles.samples=48
    scene.render.use_persistent_data=True
    axe=next(o for o in scene.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='axe_root')
    template,report=environment(scene)
    arrest(scene,axe);landing(scene,axe,template);glow(scene)
    # Preserve all other shots, including their discrete camera cuts.
    for f in range(108):
        scene.frame_set(f)
        if 44<=f<68:
            camera(scene,**staging)
            for prop in ('location','rotation_euler'):scene.camera.keyframe_insert(prop,frame=f)
            for prop in ('lens','dof.focus_distance'):scene.camera.data.keyframe_insert(prop,frame=f)
        scene.camera.data.dof.aperture_fstop=1.8 if f<19 or f>=76 else (4 if f<68 else 2.8)
        scene.camera.data.keyframe_insert('dof.aperture_fstop',frame=f)
    rocks=[o for o in scene.objects if o.name.startswith('Background rock mass ')]
    rubick=next(o for o in scene.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='rubick_root')
    rays=0
    for f in range(108):
        scene.frame_set(f);bpy.context.view_layer.update()
        targets=[axe.matrix_world @ axe.pose.bones['head'].head,
                 rubick.matrix_world @ rubick.pose.bones['Head_0'].head]
        for ob in rocks:
            inverse=ob.matrix_world.inverted()
            origin=inverse @ scene.camera.location
            for target in targets:
                direction=inverse @ target-origin
                hit,*_=ob.ray_cast(origin,direction.normalized(),distance=direction.length)
                if hit:raise ValueError(f'New scenery blocks head at frame {f}: {ob.name}')
                rays+=1
    report['clear_head_rays']=rays
    selected=source_manifest['source_frames'] if mode=='draft' else (list(range(44,77)) if mode=='patch' else [8,46,66,84])
    if mode=='probe' and '--frames' in sys.argv:
        selected=[int(f) for f in sys.argv[sys.argv.index('--frames')+1].split(',')]
        if not selected or any(f<0 or f>107 for f in selected):raise ValueError('Invalid probe frames')
    hashes=[]
    for f in selected:
        scene.frame_set(f);scene.render.filepath=str(folder/f'{f:04d}.png')
        bpy.ops.render.render(write_still=True)
        hashes.append(sha(Path(scene.render.filepath)))
    if mode=='patch':
        report['refined_frames']=selected
        report['base_manifest_sha256']=sha(OUT/'base_manifest.json')
        report['reused_frames']=[f for f in previous['source_frames'] if f not in selected]
        selected=previous['source_frames']
        hashes=[sha(folder/f'{f:04d}.png') for f in selected]
    report.update(source_frames=selected,fps=30,frame_sha256=hashes,source_blend_sha256=source_sha,
                  script_sha256=sha(Path(__file__)),camera=staging,
                  scope='Hero poses unchanged; action ground unchanged; environment, lighting and effects revised.')
    manifest.write_text(json.dumps(report,indent=2))


if __name__=='__main__':main()
