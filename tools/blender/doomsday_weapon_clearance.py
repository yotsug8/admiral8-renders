"""CPU surface audit of the evaluated Axe weapon against his visible meshes.

Call audit(scene, axe, output=OUT/'weapon_clearance.json') after author().
No scene assembly, render, saved blend or automatic pose correction is performed.
The triangle/grip method follows views_world.clip_check (A8_CLIP); render
visibility and six-ray containment reuse contact_metrics directly.
"""
import json
import math
from pathlib import Path
import re
import sys
import time

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contact_metrics import containment, descendants, visible_meshes

HELPER = re.compile(r'physics|collision|hitbox|blob|shadow', re.I)
FINGER = re.compile(r'^(?:finger|thumb|index|mid|middle|ring|pinky|little)(?:_?\d+)*_[lr]$', re.I)
HAND = re.compile(r'^(?:wrist|hand)_[lr]$', re.I)


def select_meshes(scene, axe, weapon=None):
    """Use actor membership, never the word 'axe' as a generic weapon filter."""
    root = axe.parent if axe.parent and axe.parent.name.casefold().endswith('_root') else axe
    members = set(descendants(root, scene.objects))
    members.update(o for o in scene.objects if any(
        m.type == 'ARMATURE' and m.object == axe for m in o.modifiers))
    excluded = [o for o in members if o.type == 'MESH' and HELPER.search(o.name)]
    meshes = sorted((o for o in members if o.type == 'MESH' and o not in excluded), key=lambda o:o.name)
    weapons = [weapon] if weapon else [o for o in meshes if 'axe_weapon' in (o.name+' '+o.data.name).casefold()]
    if not weapons or any(o not in meshes for o in weapons):
        raise ValueError('No explicit Axe weapon mesh in the supplied actor; pass weapon=object')
    bodies = [o for o in meshes if o not in weapons]
    if not bodies:
        raise ValueError('No body/head/clothing surfaces; refusing an empty audit')
    return weapons, bodies, excluded


def _surface(obj, graph, allow_wrist, mask_grip):
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
    try:
        mesh.calc_loop_triangles()
        points = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
        polygon_ids = [t.polygon_index for t in mesh.loop_triangles]
        bones = {b.name for m in obj.modifiers if m.type == 'ARMATURE' and m.object
                 for b in m.object.data.bones}
        names = {g.index:g.name for g in obj.vertex_groups if g.name in bones}
        allowed = {index for index, name in names.items()
                   if FINGER.fullmatch(name) or (allow_wrist and HAND.fullmatch(name))}
        weights, grip = [], set()
        for v in mesh.vertices:
            values = [(g.group, float(g.weight)) for g in v.groups]
            weights.append(values)
            total = sum(value for _, value in values)
            legal = sum(value for index, value in values if index in allowed)
            if mask_grip and total > 0 and legal / total >= .8:
                grip.add(v.index)
        excluded = {i for i,t in enumerate(triangles) if mask_grip and all(v in grip for v in t)}
        kept = [i for i in range(len(triangles)) if i not in excluded]
        tree = BVHTree.FromPolygons(points, [triangles[i] for i in kept], all_triangles=True) if kept else None
        full = (BVHTree.FromPolygons(points, triangles, all_triangles=True)
                if excluded and triangles else tree)
        bounds = tuple((min(p[i] for p in points), max(p[i] for p in points)) for i in range(3)) if points else None
        return dict(points=points, triangles=triangles, polygon_ids=polygon_ids,
                    kept=kept, excluded=excluded, tree=tree, full=full, bounds=bounds,
                    weights=weights, names=names, allowed_groups=[names[i] for i in sorted(allowed)],
                    weighted_vertices=sum(bool(v) for v in weights))
    finally:
        evaluated.to_mesh_clear()


def _bounds_overlap(a, b):
    return a is not None and b is not None and all(x[0] <= y[1] and y[0] <= x[1] for x,y in zip(a,b))


def _render_meshes(scene):
    enabled = set()
    def visit(collection):
        if collection.hide_render:
            return
        enabled.update(o for o in collection.objects if o.type == 'MESH' and not o.hide_render)
        for child in collection.children:
            visit(child)
    visit(scene.collection)
    return enabled


def _samples(surface, count):
    points = surface['points']
    if not points or count < 1:
        return []
    n = min(count,len(points))
    ids = {round(i*(len(points)-1)/max(1,n-1)) for i in range(n)}
    for axis in range(3):
        ids.add(min(range(len(points)), key=lambda i:points[i][axis]))
        ids.add(max(range(len(points)), key=lambda i:points[i][axis]))
    return sorted(ids)


def _hit_example(weapon, body, pair):
    wi, bi = weapon['kept'][pair[0]], body['kept'][pair[1]]
    tri = body['triangles'][bi]
    center = sum((body['points'][v] for v in tri), body['points'][tri[0]] * 0) / 3
    weights = {}
    for vertex in tri:
        for group,value in body['weights'][vertex]:
            if group in body['names']:
                name = body['names'][group]
                weights[name] = weights.get(name,0) + value/3
    return {'weapon_triangle':wi, 'body_triangle':bi,
            'body_polygon':body['polygon_ids'][bi], 'body_triangle_center_world':list(center),
            'dominant_skin_weights':sorted(weights.items(), key=lambda item:-item[1])[:4]}


def _phase(frame):
    return ('prepare' if frame < 252 else 'flight' if frame < 279 else
            'arrest' if frame < 290 else 'landing' if frame < 311 else 'recovery')


def audit_forearms(scene, axe, frames, output):
    """Check nonadjacent forearm/hand skin against torso skin on the same mesh.

    A weapon-only test cannot detect a free arm passing through the chest.
    Strict vertex-weight regions exclude shoulder seams; unclassified transition
    faces and clothing still require multi-view visual review.
    """
    _, bodies, _ = select_meshes(scene, axe)
    skins=[o for o in bodies if 'axe_model' in o.data.name.casefold()]
    if not skins:raise ValueError('Missing Axe skin for self-intersection review')
    rows=[]
    for frame in frames:
        scene.frame_set(math.floor(frame),subframe=frame-math.floor(frame))
        graph=bpy.context.evaluated_depsgraph_get()
        findings=[]
        for ob in skins:
            surface=_surface(ob,graph,False,False)
            def region(groups):
                vertices={i for i,weights in enumerate(surface['weights'])
                          if sum(w for g,w in weights if groups(surface['names'].get(g,'')))>.65}
                return [i for i,t in enumerate(surface['triangles']) if all(v in vertices for v in t)]
            torso=region(lambda n:n.startswith('spine') or n in ('root','pelvis'))
            tree=BVHTree.FromPolygons(surface['points'],[surface['triangles'][i] for i in torso],all_triangles=True)
            for side in ('L','R'):
                arm=region(lambda n:n in ('elbow_'+side,'wrist_'+side) or
                           (n.endswith('_'+side) and bool(FINGER.fullmatch(n))))
                limb=BVHTree.FromPolygons(surface['points'],[surface['triangles'][i] for i in arm],all_triangles=True)
                overlaps=limb.overlap(tree)
                if overlaps:findings.append({'mesh':ob.name,'side':side,'pairs':len(overlaps),
                    'examples':[[arm[a],torso[b]] for a,b in overlaps[:12]]})
        rows.append({'frame':frame,'triangle_pairs':sum(r['pairs'] for r in findings),'findings':findings})
    result={'method':'Disjoint weighted forearm/hand and torso skin regions, evaluated BVH',
            'limitations':'Transition faces, upper arms, accessories and containment are not covered.',
            'frames':rows,'critical_frames':[r['frame'] for r in rows if r['triangle_pairs']]}
    Path(output).write_text(json.dumps(result,indent=2),encoding='utf8')
    return result


def audit(scene, axe, *, frames=None, output=None, weapon=None, grip_meshes=None,
          containment_samples=12, epsilon=1e-5):
    """Return measured intersections. No clean result is an artistic PASS.

    Default: all integer scene frames. Pass fractional frames for extra samples.
    Wrist-weight exceptions apply only to named base-skin meshes (axe_model by
    default). Accessories get only exact finger-bone exceptions: no blanket
    cuff, bracer, clothing or spatial-radius exclusions. Grip borders stay tested.
    """
    requested = [float(f) for f in (frames if frames is not None else range(scene.frame_start,scene.frame_end+1))]
    if not requested or any(not math.isfinite(f) for f in requested):
        raise ValueError('A nonempty finite frame sample is required')
    requested = sorted(set(requested))
    weapons, bodies, ignored = select_meshes(scene, axe, weapon)
    skin = set(grip_meshes) if grip_meshes is not None else {
        o.name for o in bodies if 'axe_model' in o.data.name.casefold()}
    if not skin.issubset({o.name for o in bodies}):
        raise ValueError('grip_meshes must list exact body object names')
    report = {'method':'Evaluated triangulated BVH surface overlap + sparse six-ray containment',
              'reused':'views_world.clip_check algorithm; contact_metrics.visible_meshes/containment',
              'weapon_meshes':[o.name for o in weapons], 'body_meshes':[o.name for o in bodies],
              'excluded_helpers':[o.name for o in ignored], 'wrist_grip_meshes':sorted(skin),
              'requested_frames':requested, 'frames':[], 'phase_summary':{},
              'critical_frames':[], 'units':'Blender world units', 'grip_weight_threshold':.8,
              'limitations':['Integer default is not continuous collision detection.',
                             'BVH overlap counts triangle surface contacts, not penetration volume or severity.',
                             'Containment is sparse; open/nonmanifold or overlapping shells can be inconclusive or misleading.',
                             'Containment points nearest an excluded grip face are not called forbidden penetration.',
                             'Sample point distance is not an exact mesh-to-mesh clearance.',
                             'Only weapon-vertex containment is sampled; fully enclosed body islands can be missed.',
                             'Viewport-hidden/render-visible meshes are omitted by the shared visibility helper and reported.',
                             'No automatic exception for persistent intersections; no artistic PASS.']}
    started = time.monotonic()
    original_frame, original_subframe = scene.frame_current, scene.frame_subframe
    try:
        for frame in requested:
            base = math.floor(frame)
            scene.frame_set(base, subframe=frame-base)
            graph = bpy.context.evaluated_depsgraph_get()
            visible = visible_meshes(scene)
            render_enabled = _render_meshes(scene)
            ws = {o.name:_surface(o,graph,False,False) for o in weapons if o in visible}
            bs = {o.name:_surface(o,graph,o.name in skin,True) for o in bodies if o in visible}
            row = {'frame':frame, 'phase':_phase(frame), 'checked_pairs':0, 'triangle_pairs':0,
                   'contained_samples':0, 'inconclusive_containment_samples':0,
                   'omitted_meshes':[o.name for o in weapons+bodies if o in render_enabled and o not in visible],
                   'not_rendered_meshes':[o.name for o in weapons+bodies if o not in render_enabled],
                   'surfaces':{name:{'vertices':len(s['points']), 'triangles':len(s['triangles']),
                                     'tested_triangles':len(s['kept']), 'excluded_grip_triangles':len(s['excluded']),
                                     'allowed_grip_groups':s['allowed_groups'], 'weighted_vertices':s['weighted_vertices']}
                               for name,s in bs.items()}, 'findings':[]}
            for wn,w in ws.items():
                for bn,b in bs.items():
                    if w['tree'] is None or b['tree'] is None:
                        continue
                    row['checked_pairs'] += 1
                    if not _bounds_overlap(w['bounds'],b['bounds']):
                        continue
                    overlaps = w['tree'].overlap(b['tree'])
                    inside, uncertain, gap = [], 0, None
                    for vertex in _samples(w,containment_samples):
                        point = w['points'][vertex]
                        location,normal,triangle,distance = b['full'].find_nearest(point)
                        if location is None:
                            uncertain += 1
                            continue
                        gap = distance if gap is None else min(gap,distance)
                        # Full-tree indices are original triangle IDs when a
                        # grip was removed; otherwise kept is the identity map.
                        if triangle in b['excluded'] or distance <= epsilon:
                            continue
                        state = containment(b['full'],point,epsilon)
                        if state == 'inside':
                            inside.append({'weapon_vertex':vertex, 'position_world':list(point),
                                           'nearest_surface_distance':distance})
                        elif state == 'inconclusive':
                            uncertain += 1
                    row['triangle_pairs'] += len(overlaps)
                    row['contained_samples'] += len(inside)
                    row['inconclusive_containment_samples'] += uncertain
                    if overlaps or inside or uncertain:
                        row['findings'].append({'weapon':wn, 'body':bn, 'triangle_pairs':len(overlaps),
                            'triangle_examples':[_hit_example(w,b,pair) for pair in overlaps[:12]],
                            'contained_samples':inside, 'inconclusive_containment_samples':uncertain,
                            'sampled_point_gap':gap})
            row['complete_surface_coverage'] = bool(ws) and row['checked_pairs'] > 0 and not row['omitted_meshes']
            report['frames'].append(row)
            phase = report['phase_summary'].setdefault(row['phase'], {'frames':0,'intersection_frames':0,
                      'max_triangle_pairs':0,'max_contained_samples':0})
            phase['frames'] += 1
            phase['max_triangle_pairs'] = max(phase['max_triangle_pairs'],row['triangle_pairs'])
            phase['max_contained_samples'] = max(phase['max_contained_samples'],row['contained_samples'])
            if row['triangle_pairs'] or row['contained_samples']:
                phase['intersection_frames'] += 1
                report['critical_frames'].append({'frame':frame, 'phase':row['phase'],
                    'triangle_pairs':row['triangle_pairs'], 'contained_samples':row['contained_samples']})
    finally:
        scene.frame_set(original_frame,subframe=original_subframe)
    report['elapsed_seconds'] = time.monotonic()-started
    report['checked_frames'] = len(report['frames'])
    report['incomplete_frames'] = [r['frame'] for r in report['frames'] if not r['complete_surface_coverage']]
    report['status'] = ('intersections_found' if report['critical_frames'] else
                        'inconclusive' if report['incomplete_frames'] or any(r['inconclusive_containment_samples'] for r in report['frames'])
                        else 'no_intersections_in_tested_samples')
    if output is not None:
        path = Path(output);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
