"""Bounded static staging of the saved FACE_HOLD; never changes actor data.

Run in background Blender with -- inspect (CPU only), a, b, or verify.
Local evidence and staged copies live exclusively under
_game/study/face_staging/. Modes a/b render two stills each, never animation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/study/face_staging'
SOURCE = ROOT / '_game/study/face_hold/face_hold.blend'


def dump(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actor():
    import bpy
    root = bpy.data.objects['lina_root']
    return [root, *root.children_recursive]


def head():
    return next(o for o in actor() if o.type == 'MESH' and o.data.shape_keys)


def evaluated(obj):
    import bpy
    import numpy as np
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    try:
        a = np.array([v.co[:] for v in mesh.vertices])
        mat = np.array(ev.matrix_world)
        return a @ mat[:3, :3].T + mat[:3, 3]
    finally:
        ev.to_mesh_clear()


def islands(mesh):
    adjacent = [set() for _ in mesh.vertices]
    for e in mesh.edges:
        a, b = e.vertices
        adjacent[a].add(b)
        adjacent[b].add(a)
    unseen = set(range(len(adjacent)))
    result = []
    while unseen:
        stack = [unseen.pop()]
        group = set(stack)
        while stack:
            for j in adjacent[stack.pop()] & unseen:
                unseen.remove(j)
                group.add(j)
                stack.append(j)
        result.append(sorted(group))
    return sorted(result, key=len, reverse=True)


def inspect():
    import bpy
    import numpy as np
    sc = bpy.context.scene
    obj = head()
    kb = obj.data.shape_keys.key_blocks
    eye_ids = set(json.loads(sc['face_hold_eye_ids']))
    samples = {}
    for f in (0, 24, 51):
        sc.frame_set(f)
        samples[f] = evaluated(obj)
    groups = []
    eye_surfaces = []
    for ids in islands(obj.data):
        p = samples[0][ids]
        moved = eye_ids.intersection(ids)
        groups.append(dict(ids=ids, count=len(ids), eye_ids=sorted(moved),
                           min=p.min(axis=0).tolist(), max=p.max(axis=0).tolist(),
                           center=p.mean(axis=0).tolist(),
                           delta24=(samples[24][ids]-p).mean(axis=0).tolist()))
        if len(ids) == 15 and len(moved) == 15:
            faces = [list(poly.vertices) for poly in obj.data.polygons if set(poly.vertices) <= set(ids)]
            for f in (0, 24, 51):
                normals = []
                for poly in faces:
                    a, b, c = samples[f][poly[:3]]
                    normals.append(np.cross(b-a, c-a))
                normal = np.sum(normals, axis=0)
                normal /= np.linalg.norm(normal)
                eye_surfaces.append(dict(frame=f, ids=ids, center=samples[f][ids].mean(axis=0).tolist(),
                    surface_normal=normal.tolist(), vertices=samples[f][ids].tolist(),
                    uv=[list(obj.data.uv_layers.active.data[loop.index].uv)
                        for poly in obj.data.polygons if set(poly.vertices) <= set(ids)
                        for loop in [obj.data.loops[i] for i in poly.loop_indices]]))
    mats = []
    for m in obj.data.materials:
        mats.append(dict(name=m.name, images=[n.image.name for n in m.node_tree.nodes
                    if n.type == 'TEX_IMAGE' and n.image]))
    sc.frame_set(0)
    dump('geometry.json', dict(source_sha256=digest(SOURCE), head=obj.name,
        head_matrix=[list(row) for row in obj.matrix_world], islands=groups, eye_surfaces=eye_surfaces, materials=mats,
        cameras={o.name:dict(location=list(o.location),matrix=[list(row) for row in o.matrix_world],
                     lens=o.data.lens) for o in sc.objects if o.type == 'CAMERA'},
        objects=[dict(name=o.name,type=o.type,hidden=o.hide_render) for o in actor()],
        lights=[dict(name=o.name,type=o.data.type,energy=o.data.energy) for o in sc.objects if o.type == 'LIGHT']))
    print('FACE_STAGING_INSPECT_OK', flush=True)


def curves(action):
    if hasattr(action, 'layers') and len(action.layers):
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from action.fcurves


def witness():
    """Raw morph/topology/action hashes plus evaluated actor at all 108 frames."""
    import bpy
    import numpy as np
    sc = bpy.context.scene
    meshes = sorted([o for o in actor() if o.type == 'MESH'], key=lambda o:o.name)
    data = hashlib.sha256()
    for o in meshes:
        data.update(o.name.encode())
        data.update(np.array([v.co[:] for v in o.data.vertices]).tobytes())
        data.update(str([list(p.vertices) for p in o.data.polygons]).encode())
        if o.data.shape_keys:
            for k in o.data.shape_keys.key_blocks:
                data.update(k.name.encode())
                data.update(np.array([v.co[:] for v in k.data]).tobytes())
    actions = []
    for a in bpy.data.actions:
        actions.append((a.name, [(c.data_path, c.array_index,
            [(list(k.co),list(k.handle_left),list(k.handle_right),k.interpolation) for k in c.keyframe_points])
            for c in curves(a)]))
    sample_hashes = []
    for f in range(108):
        sc.frame_set(f)
        h = hashlib.sha256()
        for o in meshes:
            h.update(evaluated(o).tobytes())
            if o.data.shape_keys:
                h.update(np.array([k.value for k in o.data.shape_keys.key_blocks]).tobytes())
                assert o.data.shape_keys.key_blocks['eyeClosed'].value == 0
        sample_hashes.append(h.hexdigest())
    return dict(mesh_morph_hash=data.hexdigest(),
                actions_hash=hashlib.sha256(json.dumps(actions,sort_keys=True).encode()).hexdigest(),
                evaluated_frame_hashes=sample_hashes, samples=108, blink_zero=True)


def geometry_check(camera, target, stem):
    """Sample actual evaluated eye triangles and ray-test against visible surfaces."""
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    obj = head()
    p = evaluated(obj)
    eye_groups = [g for g in islands(obj.data) if len(g) == 15 and
                  set(g) <= set(json.loads(sc['face_hold_eye_ids']))]
    deps = bpy.context.evaluated_depsgraph_get()
    trees = []
    for o in sc.objects:
        if o.type != 'MESH' or o.hide_render:
            continue
        ev = o.evaluated_get(deps)
        mesh = ev.to_mesh()
        try:
            coords = [ev.matrix_world @ v.co for v in mesh.vertices]
            trees.append((o.name, BVHTree.FromPolygons(coords,[list(p.vertices) for p in mesh.polygons])))
        finally:
            ev.to_mesh_clear()
    def project(point):
        q = world_to_camera_view(sc,camera,Vector(point))
        return [q.x*640,(1-q.y)*360,q.z]
    eyes = []
    for group in eye_groups:
        samples = []
        for poly in obj.data.polygons:
            if set(poly.vertices) <= set(group):
                # Polygon centroids avoid duplicate seam vertices and boundary rays.
                point = Vector(p[list(poly.vertices)].mean(axis=0))
                ray = point-camera.location
                dist = ray.length
                ray.normalize()
                hits = []
                for name, tree in trees:
                    hit, normal, index, distance = tree.ray_cast(camera.location,ray,dist+.002)
                    if hit is not None:
                        hits.append((distance,name,index))
                nearest = min(hits) if hits else None
                samples.append(dict(pixel=project(point), visible=bool(nearest and abs(nearest[0]-dist)<.0005),
                                   first_hit=nearest[1] if nearest else None,
                                   blocker_gap=dist-nearest[0] if nearest else None))
        pixels = np.array([project(q) for q in p[group]])
        assert np.all(pixels[:,0]>8) and np.all(pixels[:,0]<632)
        assert np.all(pixels[:,1]>8) and np.all(pixels[:,1]<352) and np.all(pixels[:,2]>0)
        eyes.append(dict(ids=group,center_pixel=project(p[group].mean(axis=0)),
                         bounds_px=[pixels[:,:2].min(axis=0).tolist(),pixels[:,:2].max(axis=0).tolist()],
                         visible_samples=sum(s['visible'] for s in samples),samples=samples))
    tp = np.array([project(q) for q in evaluated(target)])
    assert np.all(tp[:,0]>8) and np.all(tp[:,0]<632) and np.all(tp[:,1]>8) and np.all(tp[:,1]<352)
    target_tree = next(t for n,t in trees if n == target.name)
    collisions = {n:len(target_tree.overlap(t)) for n,t in trees if n in {o.name for o in actor() if o.type=='MESH'}}
    assert not any(collisions.values()), collisions
    stem_tree = next(t for n,t in trees if n == stem.name)
    stem_collisions = {n:len(stem_tree.overlap(t)) for n,t in trees if n in {o.name for o in actor() if o.type=='MESH'}}
    # The source blob is a transparent ground-shadow plane, not body skin.
    # Keep its intersection as evidence; do not certify it as a body collision.
    blob = bpy.data.objects['lina_blob']
    blob_points = evaluated(blob)
    assert np.ptp(blob_points[:,2]) < 1e-6
    assert any(n.type=='BSDF_TRANSPARENT' for n in blob.active_material.node_tree.nodes)
    assert not any(v for n,v in stem_collisions.items() if n != blob.name), stem_collisions
    # Convex target box: also test containment, which triangle overlap alone misses.
    inv = target.matrix_world.inverted()
    contained = 0
    for o in actor():
        if o.type == 'MESH':
            for q in evaluated(o):
                local = inv @ Vector(q)
                contained += all(abs(v)<1 for v in local)
    assert contained == 0
    clearance = min(target_tree.find_nearest(Vector(q))[3] for o in actor()
                    if o.type=='MESH' for q in evaluated(o))
    gap = float(evaluated(target)[:,2].min()-evaluated(stem)[:,2].max())
    assert abs(gap)<1e-5
    kb = obj.data.shape_keys.key_blocks
    base = np.array([v.co[:] for v in kb[0].data])
    face_mask = np.zeros(len(base),dtype=bool)
    for name in ('eyeClosed','outerBrowRaiser','chinRaiser','lipPressor'):
        face_mask |= np.linalg.norm(np.array([v.co[:] for v in kb[name].data])-base,axis=1)>.001
    face_mask[json.loads(sc['face_hold_eye_ids'])] = True
    fp = np.array([project(q) for q in p[face_mask]])
    assert np.all(fp[:,0]>0) and np.all(fp[:,0]<640) and np.all(fp[:,1]>0) and np.all(fp[:,1]<360)
    return dict(frame=sc.frame_current,eyes=eyes,target_bounds_px=[tp[:,:2].min(axis=0).tolist(),tp[:,:2].max(axis=0).tolist()],
                face_bounds_px=[fp[:,:2].min(axis=0).tolist(),fp[:,:2].max(axis=0).tolist()],face_vertices=int(face_mask.sum()),
                target_actor_triangle_overlaps=collisions,stem_actor_triangle_overlaps=stem_collisions,actor_vertices_inside_target=contained,
                shadow_plane=dict(name=blob.name,z=float(blob_points[0,2]),physical_body=False),
                actor_vertex_to_target_min_distance=clearance, target_stem_gap=gap,
                limitation='Visibility samples cover eye-surface polygon centroids, not every iris pixel; no new self-intersection certification.')


def stage(variant):
    import bpy
    from mathutils import Vector
    sc = bpy.context.scene
    folder = OUT / variant
    folder.mkdir(parents=True,exist_ok=True)
    assert not list(folder.glob('*.png')), 'Preserve existing attempts; do not overwrite or exceed four renders.'
    budget = OUT / 'render_budget.json'
    ledger = json.loads(budget.read_text()) if budget.exists() else []
    assert len(ledger)+2 <= 4, 'Four static render attempts exhausted.'
    source_hash = digest(SOURCE)
    baseline = witness()
    geom = json.loads((OUT/'geometry.json').read_text())
    assert geom['source_sha256'] == source_hash
    centers = [Vector(g['center']) for g in geom['eye_surfaces'] if g['frame']==0]
    eye_center = sum(centers,Vector())/len(centers)
    # Composition only: normal of an eye patch is NOT a binocular optical axis.
    target_center = eye_center + Vector((.78,.20,.14) if variant=='a' else (.68,.20,.055))
    cube_size = .13
    bpy.ops.mesh.primitive_cube_add(size=2,location=target_center)
    target = bpy.context.object
    target.name = 'face_staging_target'
    target.scale = (cube_size/2,)*3
    bevel = target.modifiers.new('small_edge','BEVEL')
    bevel.width = .025
    bevel.segments = 3
    mat = bpy.data.materials.new('face_staging_matte_gray')
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (.28,.31,.33,1) if variant=='a' else (.06,.07,.08,1)
    bsdf.inputs['Roughness'].default_value = .72
    target.data.materials.append(mat)
    top = target_center.z-cube_size/2
    bpy.ops.mesh.primitive_cylinder_add(vertices=24,radius=.012,depth=top,location=(target_center.x,target_center.y,top/2))
    stem = bpy.context.object
    stem.name = 'face_staging_support'
    stem.data.materials.append(mat)
    receiver = bpy.data.collections.new('face_staging_light_receivers')
    sc.collection.children.link(receiver)
    for ob in (target,stem):
        receiver.objects.link(ob)
    lamp_data = bpy.data.lights.new('face_staging_target_softbox','AREA')
    lamp = bpy.data.objects.new(lamp_data.name,lamp_data)
    sc.collection.objects.link(lamp)
    lamp.location = target_center+Vector((.6,-.5,.8))
    lamp.rotation_euler = (target_center-lamp.location).to_track_quat('-Z','Y').to_euler()
    lamp_data.energy = 55 if variant=='a' else 8
    lamp_data.shape = 'DISK'
    lamp_data.size = .7
    lamp.light_linking.receiver_collection = receiver
    camera = bpy.data.objects['face_hold_front'].copy()
    camera.data = camera.data.copy()
    camera.name = 'face_staging_camera'
    sc.collection.objects.link(camera)
    yaw = math.radians(-23 if variant=='a' else -10)
    aim = eye_center+Vector((.20,.075,-.065))
    camera.location = aim+Vector((math.cos(yaw)*2.2,math.sin(yaw)*2.2,.06))
    camera.rotation_euler = (aim-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.sensor_fit = 'HORIZONTAL'
    camera.data.lens = 58 if variant=='a' else 68
    camera.data.dof.use_dof = False
    sc.camera = camera
    sc.render.resolution_x,sc.render.resolution_y = 640,360
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.use_compositing = False
    sc.render.use_sequencer = False
    sc.frame_set(51)
    bpy.context.view_layer.update()
    staged = witness()
    assert staged == baseline, 'Actor or animation changed during staging'
    sc.frame_set(51)
    destination = folder/'face_staging.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    bpy.ops.wm.open_mainfile(filepath=str(destination))
    assert witness() == baseline, 'Actor or animation changed on reopen'
    camera = bpy.data.objects['face_staging_camera']
    target = bpy.data.objects['face_staging_target']
    stem = bpy.data.objects['face_staging_support']
    checks = []
    for f in (0,51):
        bpy.context.scene.frame_set(f)
        checks.append(geometry_check(camera,target,stem))
    dump(variant+'/verification.json',dict(source_sha256=source_hash,staged_sha256=digest(destination),
        preserved=baseline, before_after_reopen_identical=True,geometry=checks,
        camera_position=list(camera.location),target_position=list(target.location)))
    for f in (0,51):
        ledger.append(dict(variant=variant,frame=f,status='started'))
        dump('render_budget.json',ledger)
        bpy.context.scene.frame_set(f)
        bpy.context.scene.render.filepath = str(folder/f'f{f:03d}.png')
        bpy.ops.render.render(write_still=True)
        ledger[-1]['status'] = 'finished'
        ledger[-1]['sha256'] = digest(folder/f'f{f:03d}.png')
        dump('render_budget.json',ledger)
    assert digest(SOURCE) == source_hash, 'Source file changed externally during run'
    print('FACE_STAGING_PAIR_OK',variant,flush=True)


def verify():
    """Reopen both local copies; compare original actor, without any render."""
    import bpy
    source_hash = digest(SOURCE)
    baseline = witness()
    result = {}
    for variant in ('a','b'):
        path = OUT/variant/'face_staging.blend'
        if not path.exists():
            continue
        bpy.ops.wm.open_mainfile(filepath=str(path))
        assert witness() == baseline
        checks = []
        for f in (0,51):
            bpy.context.scene.frame_set(f)
            checks.append(geometry_check(bpy.data.objects['face_staging_camera'],
                bpy.data.objects['face_staging_target'],bpy.data.objects['face_staging_support']))
        images = {}
        for f in (0,51):
            png = OUT/variant/f'f{f:03d}.png'
            image = bpy.data.images.load(str(png),check_existing=False)
            assert tuple(image.size) == (640,360)
            images[png.name] = digest(png)
            bpy.data.images.remove(image)
        result[variant] = dict(actor_identical=True,staged_sha256=digest(path),images=images,geometry=checks)
    assert digest(SOURCE)==source_hash
    dump('final_verification.json',dict(source_sha256=source_hash,preserved=baseline,variants=result,
         renders=json.loads((OUT/'render_budget.json').read_text())))
    print('FACE_STAGING_VERIFY_OK',flush=True)


def main():
    import bpy
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['inspect','a','b','verify'])
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    if args.mode=='inspect':
        inspect()
    elif args.mode=='verify':
        verify()
    else:
        stage(args.mode)


if __name__ == '__main__':
    main()
