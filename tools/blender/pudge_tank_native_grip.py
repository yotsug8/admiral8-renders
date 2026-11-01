"""Native hook reference, independent of the candidate launcher attachment."""
import bpy
from pathlib import Path
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[2]
sc = bpy.context.scene
hero = bpy.data.objects['pudge_root']
arm = max((o for o in hero.children_recursive if o.type=='ARMATURE'), key=lambda o:len(o.pose.bones))
for o in [bpy.data.objects['held_launcher'], *bpy.data.objects['held_launcher'].children_recursive]: o.hide_render=True
before = set(sc.objects)
bpy.ops.import_scene.gltf(filepath=str(ROOT/'_game/models/render/models_heroes_pudge_righthook.glb'))
objects = set(sc.objects)-before
for pa in [o for o in objects if o.type=='ARMATURE']:
    pa.animation_data_clear()
    pa.parent=hero
    pa.matrix_world=arm.matrix_world.copy()
    for b in pa.pose.bones:
        if b.name in arm.pose.bones:
            c=b.constraints.new('COPY_TRANSFORMS')
            c.target,c.subtarget=arm,b.name
bpy.context.view_layer.update()
center=arm.matrix_world@arm.pose.bones['weapon_rt_1'].head
cam=sc.camera
sc.render.resolution_x=sc.render.resolution_y=700
for name, delta in [('native_front',(0,-3,.3)),('native_side',(-3,0,.3))]:
    cam.location=center+Vector(delta)
    cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.lens=60
    cam.data.dof.use_dof=False
    sc.render.filepath=str(ROOT/'_game/skits/pudge_tank/revision'/f'{name}.png')
    bpy.ops.render.render(write_still=True)
import json
points=[]
dg=bpy.context.evaluated_depsgraph_get()
for o in objects:
    if o.type!='MESH':continue
    ev=o.evaluated_get(dg)
    points += [ev.matrix_world@v.co for v in ev.data.vertices if (ev.matrix_world@v.co-center).length<.55]
(ROOT/'_game/skits/pudge_tank/revision/native_handle.json').write_text(json.dumps([list(p) for p in points]))
