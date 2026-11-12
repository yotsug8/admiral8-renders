"""Replace the rejected dot field with an HDR sky and matched scene lighting.
Input v10. NASA/SVS/Gaia source and usage credits are stored with local assets.
"""
import bpy,math,json,hashlib
from pathlib import Path
from mathutils import Vector
s=bpy.context.scene;out=Path('out/dota-jojo/v11');out.mkdir(parents=True,exist_ok=True)
s.frame_set(1)
w=s.world.copy();s.world=w;n=w.node_tree.nodes;l=w.node_tree.links
output=next(x for x in n if x.type=='OUTPUT_WORLD');mix=output.inputs['Surface'].links[0].from_node
cosmos=mix.inputs[2].links[0].from_node
tex=n.new('ShaderNodeTexEnvironment');tex.name='NASA Gaia HDR celestial sky'
p=Path('out/dota-jojo/space-assets/starmap_2020_8k_gal.exr').resolve();tex.image=bpy.data.images.load(str(p));tex.interpolation='Linear'
coords=n.new('ShaderNodeTexCoord');mapping=n.new('ShaderNodeMapping');mapping.inputs['Rotation'].default_value=(math.radians(-8),math.radians(5),math.radians(90))
l.new(coords.outputs['Normal'],mapping.inputs['Vector']);l.new(mapping.outputs[0],tex.inputs['Vector']);l.new(tex.outputs['Color'],cosmos.inputs['Color']);cosmos.inputs['Strength'].default_value=1.8
# The surviving architecture must belong to the new light environment.
for o in s.objects:
 if o.type!='LIGHT' or o.name=='Time rupture reflected light':continue
 power=o.data.energy
 factor=.35 if any(x in o.name.lower() for x in ['wall','vault','apse','masonry']) else .82
 for f,e in [(1,power),(70,power),(100,power*factor),(198,power*factor),(216,power),(504,power)]:o.data.energy=e;o.data.keyframe_insert('energy',frame=f)
ld=bpy.data.lights.new('Cosmic cool rim','AREA');lo=bpy.data.objects.new(ld.name,ld);s.collection.objects.link(lo);lo.location=(3,3,5);lo.rotation_euler=(Vector((1,0,2))-lo.location).to_track_quat('-Z','Y').to_euler();ld.color=(.22,.42,1);ld.size=5
for f,e in [(1,0),(70,0),(100,350),(198,350),(216,0),(504,0)]:ld.energy=e;ld.keyframe_insert('energy',frame=f)
# Remove the broad neon outline from the rejected dissolution treatment.
for mat in bpy.data.materials:
 if not mat.use_nodes or not mat.node_tree.nodes.get('Erased time progression'):continue
 for node in mat.node_tree.nodes:
  if node.type=='EMISSION':node.inputs['Color'].default_value=(.35,.001,.008,1);node.inputs['Strength'].default_value=0
  if node.type=='MATH' and node.operation=='LESS_THAN' and abs(node.inputs[1].default_value-.025)<1e-5:node.inputs[1].default_value=.007
# Break the ruler-straight erased floor boundary, outside every foot contact.
floor=bpy.data.objects['Continuous stone floor and stair']
for mat in floor.data.materials:
 if not mat or not mat.use_nodes:continue
 ns=mat.node_tree.nodes;ls=mat.node_tree.links
 geo=next(x for x in ns if x.type=='NEW_GEOMETRY')
 noise=ns.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=2.1;noise.inputs['Detail'].default_value=3
 ls.new(geo.outputs['Position'],noise.inputs['Vector'])
 scale=ns.new('ShaderNodeMath');scale.operation='MULTIPLY_ADD';scale.inputs[1].default_value=.65;scale.inputs[2].default_value=-.325;ls.new(noise.outputs['Fac'],scale.inputs[0])
 for node in list(ns):
  if node.type=='MATH' and node.operation in ['GREATER_THAN','LESS_THAN'] and not node.inputs[1].is_linked and any(abs(node.inputs[1].default_value-v)<.001 for v in [5.2,2.5,-8.8]):
   threshold=ns.new('ShaderNodeMath');threshold.operation='ADD';threshold.inputs[1].default_value=node.inputs[1].default_value
   ls.new(scale.outputs[0],threshold.inputs[0]);ls.new(threshold.outputs[0],node.inputs[1])
s.frame_set(1);bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(out/'jojo-v11.blend'))
s.render.resolution_percentage=60;s.eevee.taa_render_samples=48;s.frame_set(140)
s.render.filepath='D:/Admiral8-temp/dota-jojo/v11-key.png';bpy.ops.render.render(write_still=True)
print('NASA_IMAGE',tuple(tex.image.size),tex.image.colorspace_settings.name)
