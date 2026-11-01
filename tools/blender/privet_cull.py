"""Conservatively exclude distant map objects outside every greeting camera."""
import json
import math
from pathlib import Path
import bpy
from mathutils import Vector

OUT = Path(__file__).resolve().parents[2] / '_game/skits/privet'
bpy.ops.wm.open_mainfile(filepath=str(OUT / 'privet_review.blend'))
scene = bpy.context.scene
camera = scene.camera
data = json.loads((OUT / 'scene.json').read_text(encoding='utf-8'))
frames = set(range(0, data['frames'], 12)) | {data['frames'] - 1}
for shot in data['shots'][1:]:
    cut = round(shot[0] * data['fps'])
    frames.update((cut - 1, cut))
views = []
for frame in sorted(frames):
    scene.frame_set(frame)
    # Enlarge the camera by 35% to cover motion between sampled frames.
    corners = camera.data.view_frame(scene=scene)
    tx = max(abs(v.x / v.z) for v in corners) * 1.35
    ty = max(abs(v.y / v.z) for v in corners) * 1.35
    views.append((camera.matrix_world.inverted().copy(), tx, ty))
roots = [bpy.data.objects[name + '_root'] for name in ('pudge', 'sniper')]
protected = {o for root in roots for o in (root, *root.children_recursive)}
centers = [root.matrix_world.translation.copy() for root in roots]
culled = []
for obj in list(scene.objects):
    if obj.type != 'MESH' or obj in protected or 'sky' in obj.name.lower() or 'blob' in obj.name.lower():
        continue
    corners = [obj.matrix_world @ Vector(v) for v in obj.bound_box]
    center = sum(corners, Vector()) / 8
    radius = max((v - center).length for v in corners)
    # Keep nearby shadow casters, large terrain aggregates and environment domes.
    if radius > 25 or any((center - hero).length - radius < 40 for hero in centers):
        continue
    visible = False
    for inverse, tx, ty in views:
        p = inverse @ center
        depth = -p.z
        if depth + radius <= 0:
            continue
        if (abs(p.x) <= depth * tx + radius * math.sqrt(1 + tx * tx)
                and abs(p.y) <= depth * ty + radius * math.sqrt(1 + ty * ty)):
            visible = True
            break
    if not visible:
        culled.append(obj)
bpy.data.batch_remove(culled)
report = {'culled': len(culled), 'remaining': len(scene.objects),
          'camera_samples': len(views), 'shadow_radius': 40, 'frustum_margin': 1.35}
(OUT / 'cull.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
scene.frame_set(0)
scene.render.filepath = str(OUT / 'frames_culled/f#####')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'privet_culled.blend'))
for frame in (41, 176, 323, 420):
    scene.frame_set(frame)
    scene.render.filepath = str(OUT / f'culled_{frame:05d}.png')
    bpy.ops.render.render(write_still=True)
print(report, flush=True)
