"""Isolated constant lateral shift; preserve original actions and camera.

Run on a prepared chase camera blend. This is a shot study, not a timeline
integration: the root delta applies outside the audited interval too.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_audit import available_meshes, lineage


def animated(owner, path):
    ad = owner.animation_data
    if not ad:
        return False
    if any(c.data_path == path for c in ad.drivers) or any(not t.mute for t in ad.nla_tracks):
        return True
    if ad.action:
        return any(c.data_path == path for layer in ad.action.layers
                   for strip in layer.strips for bag in strip.channelbags
                   if bag.slot_handle == ad.action_slot.handle for c in bag.fcurves)
    return False


def surface(objects, graph):
    vertices, faces = [], []
    for obj in objects:
        ev = obj.evaluated_get(graph)
        mesh = ev.to_mesh()
        try:
            offset = len(vertices)
            vertices.extend(ev.matrix_world @ v.co for v in mesh.vertices)
            faces.extend(tuple(offset+i for i in p.vertices) for p in mesh.polygons)
        finally:
            ev.to_mesh_clear()
    if not faces:
        raise ValueError('Empty collision surface')
    return BVHTree.FromPolygons(vertices, faces)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--actors', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--shift-x', type=float, required=True)
    p.add_argument('--camera-shift-x', type=float, default=0.)
    p.add_argument('--lens', type=float)
    p.add_argument('--start', type=int, default=240)
    p.add_argument('--end', type=int, default=335)
    p.add_argument('--frames', type=int, nargs='+', default=[240, 288, 335])
    p.add_argument('--render', action='store_true')
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.end < args.start or any(not args.start <= f <= args.end for f in args.frames):
        p.error('Invalid frame range')
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    scene = bpy.context.scene
    camera = scene.camera
    if (camera.delta_location.length > 1e-8 or camera.parent or camera.constraints
            or animated(camera, 'delta_location')):
        raise ValueError('Camera requires a dedicated transform integration')
    if args.lens is not None:
        if args.lens <= 0 or animated(camera.data, 'lens'):
            raise ValueError('Expected positive unanimated lens')
        camera.data.lens = args.lens
    camera.delta_location.x = args.camera_shift_x
    meta = json.loads(args.actors.read_text(encoding='utf-8'))
    roots = {who: bpy.data.objects[a['root']] for who, a in meta.items()}
    root = roots['kunkka']
    if root.parent or root.constraints or root.delta_location.length > 1e-8:
        raise ValueError('Expected unparented, unconstrained root without delta translation')
    # A keyed/driven delta would override the study offset on frame change.
    ad = root.animation_data
    if ad:
        if ad.drivers or any(not t.mute for t in ad.nla_tracks):
            raise ValueError('Root drivers/NLA require a dedicated integration')
        if ad.action:
            for layer in ad.action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        if bag.slot_handle == ad.action_slot.handle:
                            if any(c.data_path == 'delta_location' for c in bag.fcurves):
                                raise ValueError('Animated root delta')
    original = {}
    for f in range(args.start, args.end+1):
        scene.frame_set(f)
        original[f] = root.matrix_world.copy()
    meshes = available_meshes(scene)
    actors = {who: [bpy.data.objects[n] for n in a['objs']
                   if bpy.data.objects[n] in meshes
                   and not any(s in n.lower() for s in ('physics', 'hitbox', 'blob'))]
              for who, a in meta.items()}
    scene.frame_set(args.start)
    graph = bpy.context.evaluated_depsgraph_get()
    # Use actual evaluated scenery, including new ground and trees. Static
    # bounds cull distant horizon only; transparent leaves remain conservative.
    corridor = [v.translation for v in original.values()]
    xmin = min(v.x for v in corridor)+args.shift_x-5
    xmax = max(v.x for v in corridor)+args.shift_x+5
    ymin, ymax = min(v.y for v in corridor)-5, max(v.y for v in corridor)+5
    scenery = []
    for obj in meshes:
        if any(r in lineage(obj) for r in roots.values()):
            continue
        ev = obj.evaluated_get(graph)
        corners = [ev.matrix_world @ Vector(v) for v in ev.bound_box]
        if (max(v.x for v in corners) < xmin or min(v.x for v in corners) > xmax
                or max(v.y for v in corners) < ymin or min(v.y for v in corners) > ymax):
            continue
        if 'sky' not in obj.name.lower():
            scenery.append(obj)
    environment = surface(scenery, graph)
    root.delta_location.x = args.shift_x
    rows, bad = [], []
    for f in range(args.start, args.end+1):
        scene.frame_set(f)
        graph = bpy.context.evaluated_depsgraph_get()
        expected = original[f].copy()
        expected.translation.x += args.shift_x
        actual = root.matrix_world
        error = max(abs(actual[i][j]-expected[i][j]) for i in range(4) for j in range(4))
        points = []
        for objects in actors.values():
            for obj in objects:
                ev = obj.evaluated_get(graph)
                points.extend(ev.matrix_world @ Vector(v) for v in ev.bound_box)
        uv = [world_to_camera_view(scene, scene.camera, v) for v in points]
        bounds_ok = all(.065 <= v.x <= .87 and .19 <= v.y <= .92 and v.z > .1 for v in uv)
        k = surface(actors['kunkka'], graph)
        env_hits = len(k.overlap(environment))
        actor_hits = len(k.overlap(surface(actors['hoodwink'], graph)))
        row = dict(frame=f, root_matrix_error=error, framing_ok=bounds_ok,
                   uv_bounds=[min(v.x for v in uv), min(v.y for v in uv),
                              max(v.x for v in uv), max(v.y for v in uv)],
                   scenery_surface_pairs=env_hits, actor_surface_pairs=actor_hits)
        rows.append(row)
        if error > 1e-5 or not bounds_ok or env_hits or actor_hits:
            bad.append(row)
    report = dict(shift_x=args.shift_x, camera_shift_x=args.camera_shift_x,
                  lens=camera.data.lens, frames=rows, failures=bad,
                  scenery_meshes=[o.name for o in scenery],
                  limits='Isolated shot only. Static evaluated scenery at first frame; '
                  'triangle surface intersections, not containment, minimum clearance, '
                  'self-collision or alpha-aware visibility. Integer samples only. '
                  'No timeline cuts or close-up integration. Source never overwritten.')
    (args.out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if bad:
        raise ValueError(f'{len(bad)} frames rejected; see report.json')
    scene.frame_start, scene.frame_end = args.start, args.end
    scene.render.resolution_x, scene.render.resolution_y = 360, 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out/'spacing_candidate.blend'), copy=True)
    if args.render:
        for f in args.frames:
            scene.frame_set(f)
            scene.render.filepath = str(args.out/f'after_{f:04d}.png')
            bpy.ops.render.render(write_still=True)
    print('SPACING_STUDY', len(rows), 'frames, no sampled surface intersections')


if __name__ == '__main__':
    main()
