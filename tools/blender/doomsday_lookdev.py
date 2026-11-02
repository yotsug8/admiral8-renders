"""Isolated v12 contact study. This is an art-direction probe, not a release."""
import math
import bpy
from mathutils import Vector, Matrix


def aim(ob, target):
    ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()


def apply(scene):
    scene.frame_set(300)
    if scene.get('v12_lookdev_applied'):
        raise RuntimeError('Reload the untouched v11 scene before applying this study')
    scene['v12_lookdev_applied']=True
    original=scene.camera
    cam=original.copy();cam.data=original.data.copy()
    cam.animation_data_clear();cam.data.animation_data_clear()
    scene.collection.objects.link(cam);scene.camera=cam;cam.name='v12 contact proof'
    target=Vector((-.7,-1.55,3.0))
    cam.location=(-3.5,-3.8,3.2);aim(cam,target);cam.data.lens=62
    cam.data.dof.use_dof=True;cam.data.dof.focus_distance=(target-cam.location).length
    cam.data.dof.aperture_fstop=2.8

    # Separate depth planes rather than surrounding the actors with a small wall.
    for ob in scene.objects:
        if ob.name.startswith('Background rock mass'):
            ob.location.x*=2
            ob.location.y=(ob.location.y+1)*2-1
            ob.scale*=1.4
        if ob.type=='MESH' and 'statue' in ob.name.lower():
            ob.hide_render=True
    for node in scene.world.node_tree.nodes:
        if node.type=='BACKGROUND':node.inputs['Strength'].default_value=.12
    settings={
        'Cold key':((-3.5,-4.7,4.5),450,(.70,.83,1),3),
        'Warm edge':((1.5,1.0,5.5),750,(1,.55,.29),2),
        'Reverse fill':((1,5,5),90,(.36,.60,1),5),
    }
    for name,(position,power,color,size) in settings.items():
        ob=scene.objects.get(name)
        if ob:
            ob.location=position;ob.data.energy=power;ob.data.color=color;ob.data.size=size
            aim(ob,(-.5,-1.0,2.8))
    scene.objects['Distant daylight'].data.energy=.035
    air=scene.objects.get('Distant air')
    if air:
        for material in air.data.materials:
            if not material or not material.use_nodes:continue
            for node in material.node_tree.nodes:
                if node.type=='MAP_RANGE':
                    node.inputs['From Min'].default_value=6
                    node.inputs['From Max'].default_value=35
                    node.inputs['To Max'].default_value=.018
                if node.type=='PRINCIPLED_VOLUME':
                    node.inputs['Color'].default_value=(.40,.55,.66,1)
                    node.inputs['Anisotropy'].default_value=.15

    # The source of the dramatic key is the charged blade, close to the actors.
    data=bpy.data.lights.new('v12 weapon incident light','POINT')
    data.color=(.40,.78,1);data.shadow_soft_size=.28
    light=bpy.data.objects.new(data.name,data);scene.collection.objects.link(light)
    light.location=(-1.9,-2.45,3.8)
    for f,power in ((0,0),(24,10),(120,25),(230,60),(260,160),(279,230),(300,180),(330,120),(419,80)):
        data.energy=power*1.7;data.keyframe_insert('energy',frame=f)
    for ob in scene.objects:
        if ob.type!='CURVE' or 'blade charge' not in ob.name:continue
        for f in (279,300,419):
            ob.hide_render=False;ob.hide_viewport=False
            ob.keyframe_insert('hide_render',frame=f);ob.keyframe_insert('hide_viewport',frame=f)
        for material in ob.data.materials:
            for node in material.node_tree.nodes:
                if node.type=='EMISSION':
                    for f,power in ((279,10),(300,8),(330,6),(419,3)):
                        node.inputs[1].default_value=power;node.inputs[1].keyframe_insert('default_value',frame=f)
    for ob in scene.objects:
        if ob.type!='MESH' or 'axe_model' not in ob.data.name:continue
        for material in ob.data.materials:
            if not material or not material.use_nodes:continue
            node=next((n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
            if node:
                node.inputs['Subsurface Weight'].default_value=.065
                node.inputs['Subsurface Scale'].default_value=.015
                base=node.inputs['Base Color']
                if base.is_linked:
                    source=base.links[0].from_socket
                    hue=material.node_tree.nodes.new('ShaderNodeHueSaturation')
                    hue.inputs['Saturation'].default_value=.95
                    material.node_tree.links.new(source,hue.inputs['Color'])
                    material.node_tree.links.new(hue.outputs[0],base)
    # Replace the wide-eyed surprise during the pressure phase with effort.
    # Snapshot first: dense source keys must not feed back into this adjustment.
    axe=next(o for o in scene.objects if o.type=='ARMATURE' and o.parent and o.parent.name=='axe_root')
    head=axe.pose.bones['head'];poses=[]
    def effort(f):
        ramp=max(0,min(1,(f-279)/15));release=max(0,min(1,(360-f)/18))
        return ramp*ramp*(3-2*ramp)*release*release*(3-2*release)
    for index in range(279*8,360*8+1):
        f=index/8;scene.frame_set(int(f),subframe=f-int(f));bpy.context.view_layer.update()
        world=axe.matrix_world@head.matrix;pivot=world.translation.copy()
        rotated=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(12*effort(f)),4,'X')@Matrix.Translation(-pivot)@world
        poses.append((f,axe.matrix_world.inverted()@rotated))
    for f,matrix in poses:
        scene.frame_set(int(f),subframe=f-int(f));head.matrix=matrix
        for key in ('location','rotation_quaternion','scale'):head.keyframe_insert(key,frame=f)
    for ob in scene.objects:
        if ob.type!='MESH' or 'axe_model' not in ob.data.name or not ob.data.shape_keys:continue
        keys=ob.data.shape_keys.key_blocks
        for f in range(279,361):
            w=effort(f)
            for name,value in {'browLowerer':.3+.55*w,'innerBrowRaiser':.45*(1-w),
                               'upperLidRaiser':.5*(1-w),'squint':.32*w,'eyeDown':.20*w,
                               'jawOpen':.24-.16*w,'jawClencher':.55*w,'lipPressor':.25*w}.items():
                if name in keys:keys[name].value=value;keys[name].keyframe_insert('value',frame=f)
    scene.frame_set(300);bpy.context.view_layer.update()
    return {'purpose':'contact art-direction probe','frame':300,
            'limits':'Static camera; acting and full environment remain under revision.'}
