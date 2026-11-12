"""Prepare a packed, reproducible EEVEE draft from jojo_parody.py's scene."""
import bpy,json,hashlib
from pathlib import Path
s=bpy.context.scene
out=Path(bpy.data.filepath).parent
column=bpy.data.objects['DOTA_RUIN_COLUMN']
from mathutils import Vector
points=[o.matrix_world@Vector(v) for o in column.children_recursive if o.type=='MESH' for v in o.bound_box]
column.location.y+=-1.65-(min(p.y for p in points)+max(p.y for p in points))*.5
bpy.data.cameras['03_Diavolo_glimpse'].lens=95
root=bpy.data.objects['SNIPER_POLNAREFF']
for o in root.children_recursive:
 for f,v in [(315,False),(316,True),(504,True)]:
  o.hide_render=v;o.keyframe_insert('hide_render',frame=f)
 # Existing dense visibility keys are replaced after the cut.
 if o.animation_data and o.animation_data.action:
  for layer in o.animation_data.action.layers:
   for strip in layer.strips:
    for bag in strip.channelbags:
     for fc in bag.fcurves:
      if fc.data_path=='hide_render':
       for k in fc.keyframe_points:
        if k.co.x>=316:k.co.y=1
s.render.engine='BLENDER_EEVEE'
s.eevee.taa_render_samples=64
s.render.resolution_x=540;s.render.resolution_y=960
s.render.resolution_percentage=100
s.render.filepath=str(out/'draft-frames/frame_')
s.render.image_settings.color_mode='RGB'
s.render.image_settings.compression=20
s.frame_set(1)
missing=[]
for i in bpy.data.images:
 if i.source=='FILE' and not i.packed_file and not Path(bpy.path.abspath(i.filepath)).is_file():missing.append(i.filepath)
assert not missing,missing
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'jojo-draft-reviewed.blend'))
scene=out/'jojo-draft-reviewed.blend'
(out/'render-manifest.json').write_text(json.dumps({'scene':str(scene),'sha256':hashlib.sha256(scene.read_bytes()).hexdigest(),'frames':504,'fps':30,'size':[540,960],'engine':'EEVEE','samples':64,'status':'draft, pending full motion review'},indent=2))
