"""Time-erasure environment and reference-aligned reveal; input v9."""
import bpy, math
from pathlib import Path
s=bpy.context.scene
out=Path('out/dota-jojo/v10');out.mkdir(parents=True,exist_ok=True)
# Reference image timings: first red distortion ~2.4s; streaks ~3.9s;
# transformed character ~4.65s. Audio stays at its original timestamps.
s.frame_set(154);before={o.name:o.hide_render for o in s.objects}
s.frame_set(155);changes=[(o,o.hide_render)for o in s.objects if before[o.name]!=o.hide_render]
for o,hidden in changes:
 for f in range(140,155):o.hide_render=hidden;o.keyframe_insert('hide_render',frame=f)
for marker in s.timeline_markers:
 if marker.frame==155:marker.frame=140
# Reveal starts at the original establishing pose; close-up motion is retained.
cam=bpy.data.objects['03_Diavolo_glimpse'];s.frame_set(155)
for key in ['location','rotation_euler']:cam.keyframe_insert(key,frame=140)
for key in ['lens','dof.focus_distance']:cam.data.keyframe_insert(key,frame=140)

def envelope(socket,values):
 for f,v in values:socket.default_value=v;socket.keyframe_insert('default_value',frame=f)

def mathnode(nodes,links,operation,a,b=None):
 n=nodes.new('ShaderNodeMath');n.operation=operation
 if isinstance(a,(int,float)):n.inputs[0].default_value=a
 else:links.new(a,n.inputs[0])
 if b is not None:
  if isinstance(b,(int,float)):n.inputs[1].default_value=b
  else:links.new(b,n.inputs[1])
 return n.outputs[0]

# A dark star field with faint cloudy colour. World direction keeps it at infinity.
w=s.world.copy();s.world=w;n=w.node_tree.nodes;l=w.node_tree.links
output=next(x for x in n if x.type=='OUTPUT_WORLD');old=output.inputs['Surface'].links[0].from_socket
coord=n.new('ShaderNodeTexCoord')
noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=3;noise.inputs['Detail'].default_value=5;l.new(coord.outputs['Normal'],noise.inputs['Vector'])
ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.3;ramp.color_ramp.elements[0].color=(.0004,.0002,.001,1);ramp.color_ramp.elements[1].position=.75;ramp.color_ramp.elements[1].color=(.035,.006,.065,1);l.new(noise.outputs['Fac'],ramp.inputs[0])
stars=n.new('ShaderNodeTexVoronoi');stars.inputs['Scale'].default_value=145;l.new(coord.outputs['Normal'],stars.inputs['Vector'])
star=mathnode(n,l,'LESS_THAN',stars.outputs['Distance'],.038)
star=mathnode(n,l,'MULTIPLY',star,4)
add=n.new('ShaderNodeMixRGB');add.blend_type='ADD';add.inputs[0].default_value=1;l.new(ramp.outputs[0],add.inputs[1]);l.new(star,add.inputs[2])
cosmos=n.new('ShaderNodeBackground');cosmos.inputs['Strength'].default_value=1;l.new(add.outputs[0],cosmos.inputs['Color'])
mix=n.new('ShaderNodeMixShader');l.new(old,mix.inputs[1]);l.new(cosmos.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],output.inputs['Surface'])
envelope(mix.inputs[0],[(1,0),(70,0),(88,1),(198,1),(216,0),(504,0)])

# Erase surrounding architecture; keep a bounded floor, stairs, the anchor
# column and a piece of its supporting vault, rather than an unsupported pole.
normal_names={o.name for o in bpy.data.objects['PUDGE_DOPPIO'].children_recursive if o.type=='MESH'}
normal_names.update(o.name for name in ['observer','sentry'] for o in bpy.data.objects['ITEM / '+name].children_recursive if o.type=='MESH')
normal_names.update(o.name for o in s.objects if o.name.startswith('ANATOMY / fitted neck / PUDGE_DOPPIO'))
objects=[]
for o in s.objects:
 if o.type!='MESH':continue
 if o.name in normal_names or o.name.startswith(('Continuous sanctuary','Curved landing','DOTA rear','DOTA landing','DOTA roots','Continuous stone floor')) or ('hoodwink_debut_pillar.vmdl_c' in o.name and o.name.endswith(('.001','.002'))) or o.name.startswith(('Vault fitted column capital.001','Vault fitted column capital.002')):
  objects.append(o)
for o in objects:
 for slot in o.material_slots:
  if not slot.material or not slot.material.use_nodes:continue
  mat=slot.material.copy();slot.material=mat
  n=mat.node_tree.nodes;l=mat.node_tree.links
  output=next(x for x in n if x.type=='OUTPUT_MATERIAL');old=output.inputs['Surface'].links[0].from_socket
  geo=n.new('ShaderNodeNewGeometry');sep=n.new('ShaderNodeSeparateXYZ');l.new(geo.outputs['Position'],sep.inputs[0])
  noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=1.7;noise.inputs['Detail'].default_value=2;l.new(geo.outputs['Position'],noise.inputs['Vector'])
  progress=n.new('ShaderNodeValue');progress.name='Erased time progression'
  timing=[(1,-.1),(100,-.1),(114,1.1),(504,1.1)] if o.name in normal_names else [(1,-.1),(70,-.1),(100,1.1),(198,1.1),(216,-.1),(504,-.1)]
  envelope(progress.outputs[0],timing)
  erased=mathnode(n,l,'LESS_THAN',noise.outputs['Fac'],progress.outputs[0])
  outside=None
  if o.name.startswith('Continuous stone floor'):
   x=mathnode(n,l,'GREATER_THAN',mathnode(n,l,'ABSOLUTE',sep.outputs['X']),5.2)
   front=mathnode(n,l,'LESS_THAN',sep.outputs['Y'],-8.8)
   back=mathnode(n,l,'GREATER_THAN',sep.outputs['Y'],2.5)
   outside=mathnode(n,l,'MAXIMUM',x,mathnode(n,l,'MAXIMUM',front,back))
   erased=mathnode(n,l,'MULTIPLY',erased,outside)
  elif o.name.startswith('Continuous sanctuary'):
   x=mathnode(n,l,'GREATER_THAN',mathnode(n,l,'ABSOLUTE',sep.outputs['X']),1.5)
   front=mathnode(n,l,'LESS_THAN',sep.outputs['Y'],-2.7)
   back=mathnode(n,l,'GREATER_THAN',sep.outputs['Y'],.3)
   low=mathnode(n,l,'LESS_THAN',sep.outputs['Z'],7.8)
   outside=mathnode(n,l,'MAXIMUM',mathnode(n,l,'MAXIMUM',x,low),mathnode(n,l,'MAXIMUM',front,back))
   erased=mathnode(n,l,'MULTIPLY',erased,outside)
  edge=mathnode(n,l,'ABSOLUTE',mathnode(n,l,'SUBTRACT',noise.outputs['Fac'],progress.outputs[0]))
  edge=mathnode(n,l,'LESS_THAN',edge,.025)
  if outside is not None:edge=mathnode(n,l,'MULTIPLY',edge,outside)
  emission=n.new('ShaderNodeEmission');emission.inputs['Color'].default_value=(.8,.008,.08,1);emission.inputs['Strength'].default_value=2
  glow=n.new('ShaderNodeMixShader');l.new(edge,glow.inputs[0]);l.new(old,glow.inputs[1]);l.new(emission.outputs[0],glow.inputs[2])
  transparent=n.new('ShaderNodeBsdfTransparent');m=n.new('ShaderNodeMixShader');l.new(erased,m.inputs[0]);l.new(glow.outputs[0],m.inputs[1]);l.new(transparent.outputs[0],m.inputs[2]);l.new(m.outputs[0],output.inputs['Surface'])
  mat.surface_render_method='DITHERED'
# Colour reflection belongs to the effect, not a permanent purple skin change.
ld=bpy.data.lights.new('Time rupture reflected light','AREA');lo=bpy.data.objects.new(ld.name,ld);s.collection.objects.link(lo);lo.location=(0,-2,5);ld.color=(1,.025,.13);ld.shape='DISK';ld.size=5
for f,e in [(1,0),(70,0),(80,240),(102,30),(117,30),(120,420),(126,30),(198,30),(216,0),(504,0)]:ld.energy=e;ld.keyframe_insert('energy',frame=f)
s.frame_start=1;s.frame_end=504;s.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'jojo-v10.blend'))
s.render.resolution_percentage=40;s.eevee.taa_render_samples=32
p=Path('D:/Admiral8-temp/dota-jojo/v10-probes');p.mkdir(exist_ok=True)
for f in [84,108,118,140,170,202,216]:
 s.frame_set(f);s.render.filepath=str(p/f'{f:04d}.png');bpy.ops.render.render(write_still=True)
