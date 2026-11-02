"""Isolated test of a stable seam merge + Corrective Smooth on a split head/torso.

Requires an existing baked character study. Does not patch the production rig.
Joining topology changes object lookup and therefore needs explicit integration.
"""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.dont_write_bytecode = True
import bpy
import bmesh
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deformation_metrics import compare

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'_game/study/neck_methods'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(ob):
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return dict(points=[ev.matrix_world@v.co for v in mesh.vertices],
                    edges=[tuple(e.vertices) for e in mesh.edges],
                    triangles=[tuple(t.vertices) for t in mesh.loop_triangles],
                    polygons=[tuple(p.vertices) for p in mesh.polygons],
                    world_matrix=[list(r) for r in ev.matrix_world])
    finally:
        ev.to_mesh_clear()


def install():
    head = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name.endswith('pudge.vmdl_c.head'))
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name.endswith('pudge.vmdl_c.upper_body'))
    rigs = []
    for ob in (head, body):
        mods = [m for m in ob.modifiers if m.show_viewport or m.show_render]
        if len(mods) != 1 or mods[0].type != 'ARMATURE' or not (mods[0].show_viewport and mods[0].show_render):
            raise ValueError('Expected one matching Armature modifier per source mesh')
        rigs.append(mods[0].object)
    if rigs[0] is None or rigs[0] != rigs[1]:
        raise ValueError('Head and body must use the same armature')
    if body.data.shape_keys:
        raise ValueError('Body shape-key merging is not covered by this study')
    head_points, body_points = np.array(snapshot(head)['points']), np.array(snapshot(body)['points'])
    original = np.concatenate((head_points, body_points))
    shape_names = [k.name for k in head.data.shape_keys.key_blocks] if head.data.shape_keys else []
    # A live Weld modifier also changes topology when tiny morph displacements
    # separate seam vertices. Merge only the junction once, in the base mesh.
    distances = np.linalg.norm(head_points[:,None]-body_points[None,:],axis=2)
    pairs = np.where(distances < .00001)
    if len(pairs[0]) < 3:
        raise ValueError('No sufficient coincident head/body junction')
    seam_shape_delta = 0.
    if head.data.shape_keys:
        basis = head.data.shape_keys.key_blocks[0]
        for index in set(pairs[0].tolist()):
            seam_shape_delta = max(seam_shape_delta, max((key.data[index].co-basis.data[index].co).length
                                   for key in head.data.shape_keys.key_blocks))
    group_name = 'Study_head_body_junction'
    for ob, indices in ((head,pairs[0]),(body,pairs[1])):
        ob.vertex_groups.new(name=group_name).add(sorted(set(indices.tolist())),1.,'REPLACE')
    bpy.ops.object.select_all(action='DESELECT')
    head.select_set(True)
    body.select_set(True)
    bpy.context.view_layer.objects.active = head
    bpy.ops.object.join()
    head = bpy.context.object
    head.name = 'Study_joined_head_torso'
    group_index = head.vertex_groups[group_name].index
    ids = {v.index for v in head.data.vertices if any(g.group == group_index and g.weight > .99 for g in v.groups)}
    bm = bmesh.new()
    try:
        bm.from_mesh(head.data)
        bm.verts.ensure_lookup_table()
        bmesh.ops.remove_doubles(bm, verts=[bm.verts[i] for i in sorted(ids)], dist=.00001)
        bm.to_mesh(head.data)
    finally:
        bm.free()
    head.data.update()
    # Preserve eyelid/brow deformation rather than damping the expression along
    # with the neck. One neighbour ring is protected, the next is blended.
    mask = head.vertex_groups.new(name='Study_preserve_expression')
    mask.add(list(range(len(head.data.vertices))),1.,'REPLACE')
    if head.data.shape_keys:
        keys = head.data.shape_keys.key_blocks
        protected = {i for i in range(len(head.data.vertices))
                     if any((keys[name].data[i].co-keys[0].data[i].co).length > .0001
                            for name in ('eyeClosed','browLowerer'))}
        adjacent = [set() for _ in head.data.vertices]
        for edge in head.data.edges:
            a,b=edge.vertices
            adjacent[a].add(b);adjacent[b].add(a)
        protected |= {j for i in list(protected) for j in adjacent[i]}
        blend = {j for i in protected for j in adjacent[i]}-protected
        if protected: mask.add(sorted(protected),0.,'REPLACE')
        if blend: mask.add(sorted(blend),.5,'REPLACE')
    bpy.context.view_layer.update()
    baseline = snapshot(head)
    distances = np.linalg.norm(original[:, None]-np.array(baseline['points'])[None, :], axis=2)
    join_error = float(max(distances.min(axis=0).max(), distances.min(axis=1).max()))
    mod = head.modifiers.new('Study_corrective', 'CORRECTIVE_SMOOTH')
    mod.factor, mod.iterations = .5, 5
    mod.smooth_type, mod.use_pin_boundary, mod.rest_source = 'LENGTH_WEIGHTED', True, 'BIND'
    mod.vertex_group = mask.name
    with bpy.context.temp_override(object=head, active_object=head):
        bpy.ops.object.correctivesmooth_bind(modifier=mod.name)
    bpy.context.view_layer.update()
    if not mod.is_bind:
        raise ValueError('Corrective modifier did not bind')
    current_names = [k.name for k in head.data.shape_keys.key_blocks] if head.data.shape_keys else []
    if current_names != shape_names:
        raise ValueError('Facial shape keys changed')
    rest_error = max((a-b).length for a, b in zip(snapshot(head)['points'], baseline['points']))
    if max(join_error, rest_error) > 1e-5:
        raise ValueError('Neutral surface changed')
    return head, baseline, dict(join_error=join_error, rest_error=rest_error,
        vertices_before=len(original), vertices_after=len(baseline['points']), shape_keys=len(shape_names),
        junction_pairs=len(pairs[0]), junction_shape_delta=seam_shape_delta)


def metrics(baseline, current, frame):
    args = SimpleNamespace(edge_epsilon=1e-10, area_epsilon=1.7e-8,
        growth_m=.04054, stretch_ratio=1.8, contraction_ratio=.2, top=2)
    result = compare(baseline, current, frame, args)
    return dict(frame=frame, passed=not result['threshold_exceeded'],
                min_area=result['min_area_ratio'], max_edge=result['max_edge_ratio'],
                contracted=result['contracted_triangle_count'], stretched=result['stretched_edge_count'])


def validate(head, baseline, first, last):
    sc=bpy.context.scene
    sc.frame_set(first)
    bpy.context.view_layer.update()
    original=np.array(baseline['points'])
    joins=[]
    for ob in sc.objects:
        if ob==head or ob.type!='MESH' or ob.hide_render or 'pudge' not in ob.name.lower():
            continue
        points=np.array(snapshot(ob)['points'])
        distance=np.linalg.norm(original[:,None]-points[None,:],axis=2)
        ids=np.where(distance<1e-5)
        if len(ids[0]): joins.append((ob,ids,distance[ids]))
    rows = []
    for i in range((last-first)*4+1):
        frame = first+i/4
        bpy.context.scene.frame_set(int(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        current=snapshot(head)
        row=metrics(baseline,current,frame)
        points=np.array(current['points'])
        gap=0.
        for ob,ids,old in joins:
            adjacent=np.array(snapshot(ob)['points'])
            gap=max(gap,float(np.abs(np.linalg.norm(points[ids[0]]-adjacent[ids[1]],axis=1)-old).max()))
        row['external_junction_gap_change']=gap
        row['passed']=row['passed'] and gap<.004054
        rows.append(row)
    return dict(passed=all(r['passed'] for r in rows), samples=len(rows),
                min_area=min(r['min_area'] for r in rows), max_edge=max(r['max_edge'] for r in rows),
                external_junctions=[dict(mesh=ob.name,pairs=len(ids[0])) for ob,ids,_ in joins],
                max_external_gap=max(r['external_junction_gap_change'] for r in rows),rows=rows)


def facial_checks(head):
    """Measure whether correction erases or changes three existing expressions.

    Compare expression displacement with correction on/off at the same pose;
    do not misclassify the repaired neck fold as a changed facial expression.
    """
    keys = head.data.shape_keys.key_blocks
    values = {k.name:k.value for k in keys}
    modifier = head.modifiers['Study_corrective']
    rows = []
    try:
        for frame in (0,39,96):
            bpy.context.scene.frame_set(frame)
            for name,value in [('eyeClosed',1.),('jawOpen',.2),('browLowerer',.4)]:
                motions = []
                for enabled in (False,True):
                    modifier.show_viewport = enabled
                    for key in keys:
                        key.value = values[key.name]
                    bpy.context.view_layer.update()
                    neutral = snapshot(head)
                    keys[name].value = value
                    bpy.context.view_layer.update()
                    expression = snapshot(head)
                    if neutral['polygons'] != expression['polygons']:
                        raise ValueError('Expression changes welded topology')
                    motions.append(np.array(expression['points'])-np.array(neutral['points']))
                error = float(np.linalg.norm(motions[1]-motions[0],axis=1).max())
                amplitude = [float(np.linalg.norm(m,axis=1).max()) for m in motions]
                rows.append(dict(frame=frame,shape=name,value=value,effect_error=error,
                    original_amplitude=amplitude[0],corrected_amplitude=amplitude[1],
                    passed=np.isfinite(error) and error<max(amplitude[0]*.2,1e-4) and min(amplitude)>1e-5))
    finally:
        modifier.show_viewport = True
        for key in keys:
            key.value = values[key.name]
        bpy.context.view_layer.update()
    return dict(passed=all(bool(r['passed']) for r in rows),rows=[{**r,'passed':bool(r['passed'])} for r in rows],
                limits='Three mild expressions at three poses; full phoneme combinations are not covered.')


def detail_layout(source):
    bpy.ops.wm.open_mainfile(filepath=str(source),use_scripts=False)
    head=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.endswith('pudge.vmdl_c.head'))
    rotation=Vector((-5,-8,-3)).to_track_quat('-Z','Y')
    points=[]
    for frame in range(144):
        bpy.context.scene.frame_set(frame)
        points.extend(snapshot(head)['points'])
    local=np.array(points)@np.array(rotation.to_matrix())
    low,high=local.min(axis=0),local.max(axis=0)
    center=Vector((low+high)/2)
    return dict(location=list(rotation@(center+Vector((0,0,10)))),
                rotation=list(rotation),scale=float(max((high-low)[:2])*1.16))


def set_detail(cam,layout):
    cam.location=layout['location']
    cam.rotation_mode='QUATERNION'
    cam.rotation_quaternion=layout['rotation']
    cam.data.ortho_scale=layout['scale']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--render', action='store_true')
    ap.add_argument('--motion', action='store_true', help='Render two views only after all checks pass')
    ap.add_argument('--detail-only',action='store_true',help='Reframe only the detail view of a verified existing output')
    args = ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, out = args.source.resolve(), args.out.resolve()
    if not out.is_relative_to(BASE.resolve()) or out == BASE.resolve() or source.is_relative_to(out):
        raise ValueError('Output must be a fresh child of _game/study/neck_methods, separate from input')
    source_hash = digest(source)
    if args.detail_only:
        report=json.loads((out/'audit.json').read_text(encoding='utf-8'))
        if not report['passed'] or report['source_sha256']!=source_hash or digest(out/'scene.blend')!=report['scene_sha256']:
            raise ValueError('Verified sources changed')
        layout=detail_layout(source)
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),use_scripts=False)
        sc=bpy.context.scene
        cam=bpy.data.objects['hand_side'];set_detail(cam,layout);sc.camera=cam
        sc.render.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=32
        sc.render.resolution_x=sc.render.resolution_y=480;sc.render.resolution_percentage=100
        destination=out/'motion_detail_framed';destination.mkdir(exist_ok=False)
        sc.render.filepath=str(destination/'f_')
        bpy.ops.render.render(animation=True)
        (out/'detail_layout.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')
        return
    out.mkdir(parents=True, exist_ok=False)
    layout=detail_layout(source) if args.render or args.motion else None
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    sc = bpy.context.scene
    first, last = sc.frame_start, sc.frame_end
    if first != 0 or last != 143 or sc.render.fps/sc.render.fps_base != 30:
        raise ValueError('This regression fixture expects frames 0..143 at 30 fps')
    sc.frame_set(0)
    head, baseline, report = install()
    report.update(source_sha256=source_hash, blender=bpy.app.version_string,
        limits='One fixture, moderate head turn. No full collision, volume, lip-sync or production integration claim.')
    sc.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'), use_scripts=False)
    sc = bpy.context.scene
    head = bpy.data.objects['Study_joined_head_torso']
    report['reopened'] = validate(head, baseline, first, last)
    report['facial_checks'] = facial_checks(head)
    report['scene_sha256'] = digest(out/'scene.blend')
    report['source_unchanged'] = digest(source) == source_hash
    report['passed'] = report['source_unchanged'] and report['reopened']['passed'] and report['facial_checks']['passed']
    (out/'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('NECK_STUDY', json.dumps({k:v for k,v in report.items() if k!='reopened'}), flush=True)
    if not report['passed']:
        raise ValueError('Corrected surface failed before rendering')
    if args.render:
        # Compare identical motion, camera, light and materials. Only correction changes.
        for source_case, path in [('before', source), ('after', out/'scene.blend')]:
            bpy.ops.wm.open_mainfile(filepath=str(path), use_scripts=False)
            sc=bpy.context.scene
            cam=bpy.data.objects['hand_side']
            set_detail(cam,layout)
            sc.camera=cam
            sc.render.engine='BLENDER_EEVEE'
            sc.eevee.taa_render_samples=32
            sc.render.resolution_x=sc.render.resolution_y=480
            sc.render.resolution_percentage=100
            destination=out/source_case
            destination.mkdir(exist_ok=False)
            for frame in (0,21,39,65,96):
                sc.frame_set(frame)
                sc.render.filepath=str(destination/f'f_{frame:04d}.png')
                bpy.ops.render.render(write_still=True)
    if args.motion:
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),use_scripts=False)
        sc=bpy.context.scene
        sc.render.engine='BLENDER_EEVEE'
        sc.eevee.taa_render_samples=32
        sc.render.resolution_x=sc.render.resolution_y=480
        sc.render.resolution_percentage=100
        for view in ('front','detail'):
            destination=out/('motion_'+view)
            destination.mkdir(exist_ok=False)
            cam=bpy.data.objects['front' if view=='front' else 'hand_side']
            if view=='detail':
                set_detail(cam,layout)
            sc.camera=cam
            sc.render.filepath=str(destination/'f_')
            bpy.ops.render.render(animation=True)


if __name__ == '__main__':
    main()
