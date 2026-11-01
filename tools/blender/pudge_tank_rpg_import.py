"""Inspect an author-provided RPG prop through a safe Blender library append."""
import bpy
import json
from pathlib import Path
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[2]
folder = ROOT/'_game/external/pudge_tank/rpg7'
blend = next(folder.rglob('RPG-7.blend'))
bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(blend), link=False) as (src, dst):
    dst.objects = src.objects
for ob in dst.objects:
    if ob: bpy.context.scene.collection.objects.link(ob)
for image in bpy.data.images:
    match = next(folder.rglob(Path(image.filepath).name), None) if image.filepath else None
    if match:
        image.filepath = str(match)
        image.reload()
report = dict(objects=[], images=[dict(name=i.name, path=i.filepath) for i in bpy.data.images])
for ob in dst.objects:
    if not ob or ob.type!='MESH': continue
    points = [ob.matrix_world@Vector(v) for v in ob.bound_box]
    report['objects'].append(dict(name=ob.name, lo=[min(p[i] for p in points) for i in range(3)],
        hi=[max(p[i] for p in points) for i in range(3)],
        materials=[s.material.name for s in ob.material_slots if s.material]))
(folder/'inspection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(folder/'prepared.blend'))
