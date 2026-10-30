"""CPU contact sampling of an evaluated, already assembled Blender scene.

Example (no rendering):
  blender -b scene.blend -P tools/blender/contact_metrics.py -- \
      --actor pudge --target sniper --frames 499-550 --max-depth 0.04 \
      --json contact.json

Distances are metres (scene.unit_settings.scale_length is respected).
Exit status: 0 = no confirmed deep samples (not proof of correct contact),
1 = deep samples, 2 = error, 3 = at least one entirely inconclusive frame.

Limits: vertex sampling can miss triangle/edge intersections; the reported gap
is a sampled point-to-surface distance, not an exact mesh-to-mesh distance.
Only skin vertices near the wrist are tested, not the weapon or whole arm.
Parity assumes closed solids: open/nonmanifold surfaces may be inconclusive
or occasionally agree incorrectly. Six agreeing rays reduce, not eliminate,
that risk. Inconclusive samples are reported separately, never called inside.
Separate target meshes are treated as a union of solids, not stitched shells.
Name-based exclusions cannot identify weapons merged into a body mesh.
No scene changes are saved, no render or GPU operation is requested.
"""

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


EXCLUDE = re.compile(r"physics|collision|shadow|blob|ground|terrain|floor", re.I)
WEAPON = re.compile(
    r"weapon|hook|sword|blade|axe|staff|gun|bow|cleaver|anchor|hammer|"
    r"mace|spear|club|dagger|katana|chain|shield", re.I
)
DIRECTIONS = tuple(Vector(v).normalized() for v in (
    (1, .37, .23), (-.31, 1, .19), (.11, -.27, 1),
))


def lineage(obj):
    while obj is not None:
        yield obj
        obj = obj.parent


def names(obj, root=None):
    """Part names only: an actor root must not classify all of its meshes."""
    parts = []
    for part in lineage(obj):
        if part == root or part.name.casefold().endswith('_root'):
            break
        parts.append(part.name)
    return " ".join(parts)


def descendants(root, objects):
    return [o for o in objects if any(p == root for p in lineage(o))]


def resolve(label, objects):
    """Prefer an explicit actor root; refuse ambiguous hero instances."""
    exact = [o for o in objects if o.name.casefold() in
             {label.casefold(), (label + "_root").casefold()}]
    roots = [o for o in exact if o.type != 'MESH']
    if len(roots) == 1:
        root = roots[0]
    else:
        arms = [o for o in objects if o.type == 'ARMATURE'
                and label.casefold() in o.name.casefold()
                and not EXCLUDE.search(names(o)) and not WEAPON.search(names(o))]
        # Prefer the base hero over accessory rigs, but do not pick arbitrarily.
        base = [o for o in arms if re.search(
            re.escape(label) + r"\.vmdl_c(?:\.\d+)?$", o.name, re.I)]
        arms = base or arms
        if len(arms) != 1:
            raise ValueError(f"{label}: expected one actor root/armature; found "
                             f"{[o.name for o in arms]}; use an exact root name")
        root = arms[0]
        if root.parent and root.parent.name.casefold().endswith('_root'):
            root = root.parent
    members = descendants(root, objects)
    arms = [o for o in members if o.type == 'ARMATURE'
            and not EXCLUDE.search(names(o)) and not WEAPON.search(names(o))]
    primary = [o for o in arms if label.casefold() in o.name.casefold()]
    animated = [o for o in arms if o.animation_data and
                (o.animation_data.action or len(o.animation_data.nla_tracks))]
    pool = primary if len(primary) == 1 else animated if len(animated) == 1 else arms
    if len(pool) != 1:
        raise ValueError(f"{label}: ambiguous main armature: {[o.name for o in pool]}")
    return root, pool[0], members


def wrist_bone(arm, override):
    if override:
        bone = arm.pose.bones.get(override)
        if bone is None:
            raise ValueError(f"Bone {override!r} not found in {arm.name}")
        return bone.name
    aliases = {'wristl', 'leftwrist', 'wristleft', 'handl', 'lefthand', 'handleft'}
    candidates = [b.name for b in arm.pose.bones
                  if re.sub(r'[^a-z]', '', b.name.lower()) in aliases]
    preferred = [n for n in candidates if 'wrist' in n.lower()]
    candidates = preferred or candidates
    if len(candidates) != 1:
        raise ValueError(f"Ambiguous/missing left wrist: {candidates}; use --wrist")
    return candidates[0]


def skin_mesh(obj, root=None):
    return (obj.type == 'MESH' and not EXCLUDE.search(names(obj, root))
            and not WEAPON.search(names(obj, root))
            and any(m.type == 'ARMATURE' and m.object for m in obj.modifiers))


def visible_meshes(scene):
    """Intersect render collection paths with current view-layer visibility.

    Invisible LODs are not geometry samples. Recompute after frame_set so
    animated object visibility is respected. Viewport-hidden/render-visible
    geometry is deliberately omitted; enable it in the view layer to test it.
    """
    enabled = set()

    def visit(collection):
        if collection.hide_render:
            return
        for obj in collection.objects:
            if obj.type == 'MESH' and not obj.hide_render and obj.visible_get():
                enabled.add(obj)
        for child in collection.children:
            visit(child)

    visit(scene.collection)
    return enabled


def mesh_geometry(obj, graph, scale):
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    try:
        vertices = [(evaluated.matrix_world @ v.co) * scale for v in mesh.vertices]
        polygons = [tuple(p.vertices) for p in mesh.polygons]
        return vertices, polygons
    finally:
        evaluated.to_mesh_clear()


def ray_parity(tree, point, direction, epsilon, limit=4096):
    """None means numerical ambiguity or hit cap, never assume outside then."""
    origin = point.copy()
    count = 0
    for _ in range(limit):
        location, normal, index, distance = tree.ray_cast(origin, direction)
        if location is None:
            return count % 2
        if distance is None or distance < epsilon * .1:
            return None
        count += 1
        origin = location + direction * epsilon
    return None


def containment(tree, point, epsilon):
    votes = [ray_parity(tree, point, sign * direction, epsilon)
             for direction in DIRECTIONS for sign in (1, -1)]
    if all(v == 1 for v in votes):
        return 'inside'
    if all(v == 0 for v in votes):
        return 'outside'
    return 'inconclusive'


def frame_metrics(frame, arm, wrist, own, targets, scale, args):
    scene = bpy.context.scene
    scene.frame_set(frame)
    graph = bpy.context.evaluated_depsgraph_get()
    visible = visible_meshes(scene)
    evaluated_arm = arm.evaluated_get(graph)
    center = (evaluated_arm.matrix_world @
              evaluated_arm.pose.bones[wrist].matrix.translation) * scale
    trees = []
    for obj in targets:
        if obj not in visible:
            continue
        vertices, polygons = mesh_geometry(obj, graph, scale)
        if vertices and polygons:
            trees.append((obj.name, BVHTree.FromPolygons(vertices, polygons)))
    if not trees:
        raise ValueError(f"Frame {frame}: no target surfaces")
    gap = None
    depth = 0.0
    deep = inside = uncertain = samples = 0
    worst = None
    for obj in own:
        if obj not in visible:
            continue
        vertices, _ = mesh_geometry(obj, graph, scale)
        for index, point in enumerate(vertices):
            if (point - center).length > args.radius:
                continue
            samples += 1
            vertex_depth = 0.0
            vertex_uncertain = False
            vertex_target = None
            for target_name, tree in trees:
                location, normal, face, distance = tree.find_nearest(point)
                if location is None:
                    continue
                gap = distance if gap is None else min(gap, distance)
                if distance <= args.epsilon:
                    continue  # surface contact, not confirmed penetration
                state = containment(tree, point, args.epsilon)
                if state == 'inside' and distance > vertex_depth:
                    vertex_depth, vertex_target = distance, target_name
                elif state == 'inconclusive':
                    vertex_uncertain = True
            if vertex_depth:
                inside += 1
                deep += vertex_depth > args.max_depth
                if vertex_depth > depth:
                    depth = vertex_depth
                    worst = dict(mesh=obj.name, vertex=index, target=vertex_target,
                                 position_m=list(point))
            elif vertex_uncertain:
                uncertain += 1
    if not samples or gap is None:
        raise ValueError(f"Frame {frame}: no skin samples/surface distances; "
                         "check skin modifiers, wrist and --radius")
    return dict(frame=frame, samples=samples, min_surface_gap_m=gap,
                max_confirmed_depth_m=depth, confirmed_inside_vertices=inside,
                vertices_deeper_than_threshold=deep,
                inconclusive_vertices=uncertain, worst_sample=worst)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--frames', required=True, help='Inclusive START-END or single frame')
    parser.add_argument('--max-depth', type=float, default=.04, help='Metres')
    parser.add_argument('--radius', type=float, default=.65, help='Wrist sampling radius, metres')
    parser.add_argument('--epsilon', type=float, default=.00001, help='Ray step, metres')
    parser.add_argument('--wrist', help='Explicit left wrist pose bone name')
    parser.add_argument('--json', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    match = re.fullmatch(r'(-?\d+)(?:-(-?\d+))?', args.frames)
    if not match:
        parser.error('--frames must be START-END or a single integer')
    args.start = int(match[1])
    args.end = int(match[2]) if match[2] else args.start
    if args.end < args.start:
        parser.error('frame range is reversed')
    if (not all(math.isfinite(v) for v in (args.radius, args.epsilon, args.max_depth))
            or args.radius <= 0 or args.epsilon <= 0 or args.max_depth < 0):
        parser.error('radius/epsilon must be positive; max-depth must be nonnegative')
    return args


def run(args):
    objects = list(bpy.context.scene.objects)
    root, arm, members = resolve(args.actor, objects)
    target_root, _, target_members = resolve(args.target, objects)
    if root == target_root or any(o in target_members for o in members):
        raise ValueError('Actor and target hierarchies must be disjoint')
    wrist = wrist_bone(arm, args.wrist)
    own = [o for o in members if skin_mesh(o, root)]
    targets = [o for o in target_members if o.type == 'MESH'
               and not EXCLUDE.search(names(o, target_root))]
    if not own or not targets:
        raise ValueError('No actor skin meshes or target meshes after exclusions')
    scale = bpy.context.scene.unit_settings.scale_length
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid scene unit scale')
    print(f"CONTACT actor={root.name}, arm={arm.name}, wrist={wrist}; "
          f"skin={len(own)}, target={target_root.name}, meshes={len(targets)}", flush=True)
    rows = []
    original_frame = bpy.context.scene.frame_current
    original_subframe = bpy.context.scene.frame_subframe
    try:
        for frame in range(args.start, args.end + 1):
            row = frame_metrics(frame, arm, wrist, own, targets, scale, args)
            rows.append(row)
            print(f"frame {frame}: gap={row['min_surface_gap_m']:.6f} m; "
                  f"depth={row['max_confirmed_depth_m']:.6f} m; "
                  f"deep={row['vertices_deeper_than_threshold']}/{row['samples']}; "
                  f"inconclusive={row['inconclusive_vertices']}", flush=True)
    finally:
        bpy.context.scene.frame_set(original_frame, subframe=original_subframe)
    failing = [r['frame'] for r in rows if r['vertices_deeper_than_threshold']]
    inconclusive_frames = [r['frame'] for r in rows
                           if r['inconclusive_vertices'] == r['samples']]
    status = ('deep_penetration' if failing else 'inconclusive'
              if inconclusive_frames else 'no_confirmed_deep_penetration')
    summary = dict(status=status,
                   frames_checked=len(rows), failing_frames=failing,
                   fully_inconclusive_frames=inconclusive_frames,
                   contact_correctness_verified=False,
                   min_surface_gap_m=min(r['min_surface_gap_m'] for r in rows),
                   max_confirmed_depth_m=max(r['max_confirmed_depth_m'] for r in rows),
                   deep_vertex_samples=sum(r['vertices_deeper_than_threshold'] for r in rows),
                   inconclusive_vertex_samples=sum(r['inconclusive_vertices'] for r in rows))
    report = dict(schema_version=1, actor_root=root.name, armature=arm.name,
                  target_root=target_root.name, wrist=wrist,
                  skin_meshes=[o.name for o in own], target_meshes=[o.name for o in targets],
                  radius_m=args.radius, max_depth_m=args.max_depth, epsilon_m=args.epsilon,
                  metres_per_blender_unit=scale,
                  method='vertex samples; per-target solid union; 3 bidirectional parity rays',
                  limitations=__doc__.split('Limits: ', 1)[1].strip(),
                  summary=summary, frames=rows)
    print(f"CONTACT {summary['status']}: max depth="
          f"{summary['max_confirmed_depth_m']:.6f} m; "
          f"deep frames={len(failing)}; inconclusive samples="
          f"{summary['inconclusive_vertex_samples']}", flush=True)
    return report, 1 if failing else 3 if inconclusive_frames else 0


def main():
    args = arguments()
    try:
        report, status = run(args)
    except Exception as exc:
        report = dict(schema_version=1, summary=dict(status='error', error=str(exc)))
        status = 2
        print(f"CONTACT ERROR: {exc}", file=sys.stderr, flush=True)
    try:
        # Parent directory must already exist; do not modify the scene or create folders.
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                        allow_nan=False) + '\n', encoding='utf-8')
    except Exception as exc:
        print(f"CONTACT JSON ERROR: {exc}", file=sys.stderr, flush=True)
        status = 2
    if status:
        # Blender may swallow SystemExit from -P unless --python-exit-code is set.
        # Flush the completed report/log, then guarantee the requested process status.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)


if __name__ == '__main__':
    main()
