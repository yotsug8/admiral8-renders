"""Extend contact occlusion to the two tracks, preserving the saved animation."""
import os
from pathlib import Path
import bpy
s=bpy.context.scene
s.frame_set(0)
o=bpy.data.objects['tank contact shadow']
if not o.get('track_footprint_v2'):
    o.scale.y*=1.25
    nt=o.data.materials[0].node_tree
    center=next(n for n in nt.nodes if n.type=='VECT_MATH' and n.operation=='SUBTRACT')
    absolute=nt.nodes.new('ShaderNodeVectorMath');absolute.operation='ABSOLUTE'
    nt.links.new(center.outputs[0],absolute.inputs[0])
    axes=nt.nodes.new('ShaderNodeSeparateXYZ');nt.links.new(absolute.outputs[0],axes.inputs[0])
    maximum=nt.nodes.new('ShaderNodeMath');maximum.operation='MAXIMUM'
    nt.links.new(axes.outputs[0],maximum.inputs[0]);nt.links.new(axes.outputs[1],maximum.inputs[1])
    ramp=next(n for n in nt.nodes if n.type=='MAP_RANGE')
    nt.links.new(maximum.outputs[0],ramp.inputs['Value'])
    ramp.inputs['From Min'].default_value=.34;ramp.inputs['To Min'].default_value=.85
    o['track_footprint_v2']=True
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath,compress=True)
if os.environ.get('PT_RENDER_LAYERS'):
    s.render.filepath=str(Path(bpy.data.filepath).parent/'layers/f#####')
    bpy.ops.render.render(animation=True)
