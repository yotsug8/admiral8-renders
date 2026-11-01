"""Restore legacy camera visibility and add linked Dota forest depth.

Only a prepared scene is changed; external GLBs and their meshes are untouched.
Static import cleanup remains hidden. New trees use existing complete trunk /
foliage pairs, outside the audited actor corridor, not a background image.
"""
import math
import random
import json
import re
from collections import Counter
import importlib.util
from pathlib import Path
import bpy
from mathutils import Matrix, Vector


def _restore_classify(obj, report_row=None):
    """Only ordinary trees/terrain; visibility tags never override cleanup."""
    if obj.type != 'MESH' or not obj.data.polygons:
        return None, 'not_surface'
    part=obj
    while part:
        if (part.name in ('kunkka_root','hoodwink_root','pudge_root','sniper_root')
                or re.search(r'heroes[\\/]',part.name,re.I)):
            return None, 'actor'
        part=part.parent
    mats=[s.material for s in obj.material_slots if s.material]
    if (re.search(r'glow_\d|stump|crystal\d*_refract|lightrays|vapors_|wildlife_',obj.name,re.I)
            or any(m.get('_water') or m.name.startswith(('tools','black'))
                   or re.search(r'tree_(magical|blossoms)',m.name,re.I) for m in mats)):
        return None, 'cleanup'
    if report_row is not None and report_row['recommendation'] not in (
            'restore_camera_hidden','restore_ordinary_map_candidate','already_render_enabled'):
        return None, 'report_cleanup_or_review'
    if re.search(r'tree_|roots_',obj.name,re.I):
        return 'tree', 'approved'
    terrain=re.search(r'mesh_overlay|terrain|ground|agg_merge.*mod_(?:radiant|dire)',obj.name,re.I)
    multiblend=any(m.get('vmat') and m['vmat'].get('ShaderName')=='multiblend.vfx' for m in mats)
    if terrain or multiblend:
        # Without an audit, mixed cliff/ground aggregates remain ambiguous.
        if report_row is None and re.search(r'cliff|rock|stone_wall|agg_merge.*mod_',obj.name,re.I):
            return None, 'unreviewed_mixed_geometry'
        return 'terrain', 'approved'
    return None, 'other_prop'


def _restore_world(obj):
    """Viewport-hidden matrix_world can be stale; use the RNA parent chain."""
    if obj.constraints or (obj.parent and obj.parent_type != 'OBJECT'):
        raise ValueError('unsupported map transform hierarchy')
    if obj.parent:
        return _restore_world(obj.parent) @ obj.matrix_parent_inverse @ obj.matrix_basis
    return obj.matrix_basis.copy()


def _visibility_curves(action, slot):
    if hasattr(action,'layers'):
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    if slot is not None and bag.slot_handle != slot.handle:
                        continue
                    for curve in list(bag.fcurves):
                        if curve.data_path in ('hide_render','hide_viewport'):
                            yield bag.fcurves,curve
    else:
        for curve in list(action.fcurves):
            if curve.data_path in ('hide_render','hide_viewport'):
                yield action.fcurves,curve


def _clear_map_visibility_keys(owner):
    action=owner.action
    slot=getattr(owner,'action_slot',None)
    if not action or not list(_visibility_curves(action,slot)):
        return False
    if action.users > 1:
        # Never remove another object's visibility keys through a shared Action.
        copied=action.copy()
        new_slot=next((s for s in copied.slots if s.identifier==slot.identifier),None) if slot else None
        owner.action=copied
        if new_slot is not None:
            owner.action_slot=new_slot
        action,slot=copied,new_slot
    for curves,curve in list(_visibility_curves(action,slot)):
        curves.remove(curve)
    return True


def _restore_map_visibility(scene, excluded=(), *, radius=80.,
                            corridor=((-83.,78.5),(-83.,108.)), report_path=None):
    """Restore approved scenery near the +Y actor/front-camera corridor.

    Radius is metres from the world XY bounding box to the corridor segment.
    The segment includes the front camera's headroom beyond the 16 m route.
    Hidden cleanup/prototype collections and ambiguous audit rows stay hidden.
    """
    if not math.isfinite(radius) or radius <= 0 or corridor[0][0] != corridor[1][0]:
        raise ValueError('Expected positive radius and a vertical XY corridor')
    report_path=Path(report_path) if report_path else Path(__file__).resolve().parents[2]/'_game/skits/chase_finish/map_visibility_report.json'
    rows={}
    if report_path.is_file():
        rows={r['name']:r for r in json.loads(report_path.read_text(encoding='utf-8'))['objects']}
    enabled=set()
    def visit(collection):
        if collection.hide_render or collection.hide_viewport:
            return
        enabled.update(collection.objects)
        for child in collection.children:
            visit(child)
    visit(scene.collection)
    excluded=set(excluded)
    unit=scene.unit_settings.scale_length
    cx=corridor[0][0];y0,y1=sorted((corridor[0][1],corridor[1][1]))
    restored=[];counts=Counter()
    for obj in list(scene.objects):
        if obj in excluded or obj not in enabled:
            continue
        row=rows.get(obj.name)
        if rows and row is None:
            continue
        family,reason=_restore_classify(obj,row)
        if family is None:
            counts['skip_'+reason]+=1
            continue
        try:
            mw=_restore_world(obj)
        except ValueError:
            counts['skip_hierarchy']+=1
            continue
        points=[(mw@Vector(p))*unit for p in obj.bound_box]
        if not all(math.isfinite(v) for p in points for v in p):
            counts['skip_nonfinite_bounds']+=1
            continue
        lo=[min(p[i] for p in points) for i in range(2)]
        hi=[max(p[i] for p in points) for i in range(2)]
        dx=max(lo[0]-cx,0.,cx-hi[0]);dy=max(lo[1]-y1,0.,y0-hi[1])
        if math.hypot(dx,dy)>radius:
            counts['skip_distance']+=1
            continue
        ad=obj.animation_data
        owners=([ad] if ad and ad.action else [])
        if ad:
            owners += [s for t in ad.nla_tracks for s in t.strips if s.action]
        animated=any([_clear_map_visibility_keys(owner) for owner in owners])
        if obj.hide_render or obj.hide_viewport or obj.hide_get() or animated or obj.get('a8_view_hid'):
            obj.hide_render=False
            obj.hide_viewport=False
            obj.hide_set(False)
            restored.append(obj.name)
            counts['restored_'+family]+=1
    bpy.context.view_layer.update()
    print('CHASE_MAP_RESTORE',dict(counts), 'audit_report',bool(rows),flush=True)
    return restored


def prepare_forest(scene, excluded=()):
    restored=_restore_map_visibility(scene,excluded)
    prototypes=[]
    for obj in list(scene.objects):
        if obj.type!='MESH' or obj.hide_render or '_model.' not in obj.name:
            continue
        if not any(k in obj.name for k in ('tree_pine_01','tree_pine_02','tree_pine_03')):
            continue
        leaves=bpy.data.objects.get(obj.name.replace('_model.','_inspector.'))
        if leaves is not None and leaves.type=='MESH':
            prototypes.append((obj,leaves))
        if len(prototypes)>=4:
            break
    if not prototypes:
        raise ValueError('Prepared map has no complete pine tree pairs')
    ground_path=Path(__file__).resolve().parents[1]/'dota_engine/ground_map.py'
    module_spec=importlib.util.spec_from_file_location('_chase_ground_map',ground_path)
    ground_module=importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(ground_module)
    ground=ground_module.Ground()
    rng=random.Random(1927)
    places=[(x,y) for y in (37.,49.,61.) for x in range(-115,-47,8)]
    places += [(x,y) for x in (-65.,-55.) for y in (78.,87.,96.,105.)]
    places += [(x,y) for y in (112.,123.) for x in (-103.,-94.,-73.,-63.)]
    added=[]
    for i,(x,y) in enumerate(places):
        parts=prototypes[i%len(prototypes)]
        bounds=[part.matrix_world@Vector(c) for part in parts for c in part.bound_box]
        source=Vector(((min(p.x for p in bounds)+max(p.x for p in bounds))/2,
                       (min(p.y for p in bounds)+max(p.y for p in bounds))/2,
                       min(p.z for p in bounds)))
        target=Vector((x+rng.uniform(-1.2,1.2),y+rng.uniform(-1.2,1.2),3.25))
        target.z=ground.h(-target.y*39.37,target.x*39.37)/39.37
        transform=(Matrix.Translation(target) @ Matrix.Rotation(rng.uniform(-math.pi,math.pi),4,'Z')
                   @ Matrix.Scale(rng.uniform(.82,1.18),4) @ Matrix.Translation(-source))
        for part in parts:
            clone=part.copy()
            clone.animation_data_clear()
            clone.parent=None
            clone.name=f'chase_forest_{i:02d}_{part.name}'
            scene.collection.objects.link(clone)
            clone.matrix_world=transform@part.matrix_world
            clone.hide_viewport=clone.hide_render=False
            clone.hide_set(False)
            added.append(clone.name)
    bpy.context.view_layer.update()
    return dict(restored_camera_visibility=restored,added_tree_meshes=added,
                limitations='Distant tree bases use the cached game height grid, not exact rendered terrain contact.')


def _environment_bounds(objects):
    points = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    return (Vector(tuple(min(p[i] for p in points) for i in range(3))),
            Vector(tuple(max(p[i] for p in points) for i in range(3))))


def _environment_bvh(objects):
    """Static world-space geometry only; material alpha is deliberately ignored."""
    from mathutils.bvhtree import BVHTree
    vertices, faces = [], []
    for obj in objects:
        offset = len(vertices)
        vertices.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        faces.extend(tuple(offset + i for i in p.vertices) for p in obj.data.polygons)
    return BVHTree.FromPolygons(vertices, faces) if faces else None


def _environment_meshes(scene):
    enabled = set()
    def visit(collection):
        if collection.hide_render or collection.hide_viewport:
            return
        enabled.update(collection.objects)
        for child in collection.children:
            visit(child)
    visit(scene.collection)
    return [o for o in scene.objects if o in enabled and o.type == 'MESH'
            and not o.hide_render and not o.hide_viewport and not o.hide_get()
            and not o.name.startswith('chase_v2_')
            and not any(p.type == 'ARMATURE' or p.name.endswith('_root')
                        for p in _environment_parents(o))]


def _environment_parents(obj):
    while obj:
        yield obj
        obj = obj.parent


def translated_chase_views(scene, *, x=-83., y=78.5, length=48., step=1., sample_times=None):
    """Read sampled side/front cameras, sweep offsets without changing animation.

    This is a provisional envelope, not an audit of future final cameras.
    Custom integration may instead supply (origin, target) world-space pairs.
    """
    if sample_times is None:
        storyboard = Path(__file__).resolve().parents[2] / 'skits/kunkka_chase.json'
        shots = json.loads(storyboard.read_text(encoding='utf-8'))['shots']
        sample_times = [(shot['start'] + shot['end']) / 2 for shot in shots
                        if shot['kind'] in ('side_chase', 'front_chase')]
    if not sample_times or step <= 0:
        raise ValueError('Need camera sample times and a positive sampling step')
    frame, subframe = scene.frame_current, scene.frame_subframe
    rays, cameras = [], []
    try:
        for seconds in sample_times:
            scene.frame_set(round(seconds * scene.render.fps / scene.render.fps_base))
            root = bpy.data.objects.get('kunkka_root')
            if root is None or scene.camera is None:
                raise ValueError('Expected prepared chase actors and camera')
            base = root.matrix_world.translation.copy()
            cam = scene.camera.matrix_world.copy()
            for i in range(math.ceil(length / step) + 1):
                progress = min(length, i * step)
                shift = Vector((x - base.x, y + progress - base.y, 0))
                moved = cam.copy(); moved.translation += shift
                cameras.append((moved, scene.camera.data.copy()))
                # A face/body window with margin, including both actors.
                for ahead in (0., 3.5):
                    for dx in (-.65, 0., .65):
                        for z in (1., 1.8, 2.7):
                            target = Vector((x + dx, y + progress + ahead, base.z + z))
                            rays.append((moved.translation.copy(), target))
    finally:
        scene.frame_set(frame, subframe=subframe)
    return rays, cameras


def extend_chase_forest(scene, *, x=-83., y=78.5, length=48., ground_end_y=134.,
                        protected_rays=None, corridor_half_width=4.5, sample_times=None):
    """Add native trees, low verges and copied ground; preserve existing objects.

    Call after camera/actor animation is installed. Returns a JSON-safe report.
    Repeat calls replace only objects tagged by this function. No save or render.
    Coordinates are Blender metres (the prepared scene must use unit scale 1).
    Ground contact uses actual visible terrain triangles, not the game height grid.
    """
    if scene.unit_settings.scale_length != 1 or length <= 0 or corridor_half_width < 3.5:
        raise ValueError('Expected metre scene, positive length and clear actor corridor')
    for obj in list(scene.objects):
        if obj.get('chase_v2_environment'):
            mesh = obj.data if obj.name.startswith('chase_v2_ground_') else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    bpy.context.view_layer.update()
    originals = _environment_meshes(scene)
    ground_added = _extend_native_ground(scene, x=x, end_y=max(ground_end_y, y+length+3.5))
    terrain = [o for o in originals if re.search(r'terrain|ground|agg_merge.*mod_(radiant|dire)', o.name, re.I)
               and 'overlay' not in o.name and not o.modifiers]
    ground = _environment_bvh(terrain + ground_added)
    if ground is None:
        raise ValueError('No native terrain geometry available')
    prototypes = []
    seen = set()
    for obj in sorted(originals, key=lambda o: o.name):
        if obj.name.startswith('chase_') or not re.search(r'tree_pine_0[123].*_model\.', obj.name):
            continue
        leaves = bpy.data.objects.get(obj.name.replace('_model.', '_inspector.'))
        if leaves not in originals or obj.modifiers or leaves.modifiers:
            continue
        key = (obj.data.name, leaves.data.name)
        if key in seen:
            continue
        seen.add(key); prototypes.append((obj, leaves))
        if len(prototypes) == 6:
            break
    if not prototypes:
        raise ValueError('No visible complete native pine pairs')
    cameras = []
    if protected_rays is None:
        protected_rays, cameras = translated_chase_views(scene, x=x, y=y, length=length,
                                                        sample_times=sample_times)
    protected_rays = [(Vector(a), Vector(b)) for a, b in protected_rays]
    # West side camera remains in the open lane. East middle ground supplies
    # fast parallax; outer bands provide slower silhouettes behind the runners.
    placements = []
    for band, dx, spacing, phase in (
            ('middle', 11., 9., 0.), ('depth', 22., 11., 4.),
            ('far', 36., 13., 7.), ('west', -23., 11., 2.),
            ('west_far', -36., 13., 6.)):
        for i in range(math.ceil((length + 42.) / spacing) + 1):
            placements.append((band, x + dx, y - 24. + phase + i * spacing))
    added, rejected = [], []
    for index, (band, px, py) in enumerate(placements):
        hit, normal, face, distance = ground.ray_cast(Vector((px, py, 60)), Vector((0, 0, -1)), 100)
        if hit is None or normal.z < .7:
            rejected.append(dict(index=index, reason='no_flat_native_ground')); continue
        parts = prototypes[index % len(prototypes)]
        lo, hi = _environment_bounds(parts)
        anchor = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        transform = (Matrix.Translation(Vector((px, py, hit.z - .025)))
                     @ Matrix.Rotation((index % 7) * .71, 4, 'Z')
                     @ Matrix.Translation(-anchor))
        clones = []
        for part in parts:
            clone = part.copy(); clone.animation_data_clear(); clone.constraints.clear()
            clone.parent = None; clone.name = f'chase_v2_{index:03d}_{part.name}'
            clone['chase_v2_environment'] = True
            scene.collection.objects.link(clone)
            clone.matrix_world = transform @ part.matrix_world
            clone.hide_viewport = clone.hide_render = False; clone.hide_set(False)
            clones.append(clone)
        bpy.context.view_layer.update()
        lower, upper = _environment_bounds(clones)
        reason = None
        if lower.x < x + corridor_half_width and upper.x > x - corridor_half_width:
            reason = 'actor_corridor_bounds'
        bvh = _environment_bvh(clones)
        if reason is None:
            for origin, target in protected_rays:
                ray = target - origin
                if bvh.ray_cast(origin, ray.normalized(), ray.length)[0] is not None:
                    reason = 'protected_camera_window'; break
        if reason:
            rejected.append(dict(index=index, reason=reason))
            for clone in clones:
                bpy.data.objects.remove(clone, do_unlink=True)
        else:
            added.append(dict(index=index, band=band, objects=[c.name for c in clones],
                              xyz=[px, py, hit.z], bounds=[list(lower), list(upper)]))
    for _, data in cameras:
        bpy.data.cameras.remove(data)
    verges = _extend_native_verges(scene, ground, x=x, y=y, length=length,
                                   half_width=corridor_half_width)
    for obj in list(verges):
        bvh = _environment_bvh([obj])
        if any(bvh.ray_cast(a, (b-a).normalized(), (b-a).length)[0] is not None
               for a, b in protected_rays):
            rejected.append(dict(object=obj.name, reason='verge_protected_camera_window'))
            verges.remove(obj)
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()
    return dict(route=dict(x=x, y=y, length=length), added=added, rejected=rejected,
                ground_added=[o.name for o in ground_added],
                verges_added=[o.name for o in verges],
                prototypes=[[o.name for o in pair] for pair in prototypes],
                protected_ray_count=len(protected_rays),
                preserved='Existing objects, ground, materials, lights, world and animation untouched',
                limitations='Static triangle rays ignore alpha/DOF. Provisional translated camera envelope; final cameras and visual quality require new probes.')


def _extend_native_ground(scene, *, x, end_y):
    """Copy/crop a native flat map patch, preserving all UV/color/material data.

    Added support sits 1 cm below the original floor to avoid coplanar overlap.
    Existing raised terrain is NOT removed; it remains a reported route blocker.
    """
    import bmesh
    name = 'n0_lr0_agg_merge_mod_radiant_base_angled_000_0'
    source = bpy.data.objects.get(name)
    if source is None or source.hide_render or source.modifiers:
        raise ValueError('Expected native flat ground patch is unavailable')
    result = []
    for index in range(max(0, math.ceil((end_y - 116.) / 12.))):
        mesh = source.data.copy()
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            for vertex in bm.verts:
                vertex.co = source.matrix_world @ vertex.co
            unwanted = [face for face in bm.faces
                        if any(abs(v.co.z - 3.25119) > .001 for v in face.verts)]
            bmesh.ops.delete(bm, geom=unwanted, context='FACES')
            for point, normal in (((x-9,0,0),(-1,0,0)), ((x+9,0,0),(1,0,0)),
                                  ((0,84,0),(0,-1,0)), ((0,96,0),(0,1,0))):
                bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                                      dist=.00001, plane_co=point, plane_no=normal,
                                      clear_outer=True, clear_inner=False)
            for vertex in bm.verts:
                vertex.co.y += 32. + 12.*index
                vertex.co.z -= .01
            bm.to_mesh(mesh)
        finally:
            bm.free()
        if not mesh.polygons:
            bpy.data.meshes.remove(mesh)
            raise ValueError('Native ground crop is empty')
        obj = bpy.data.objects.new(f'chase_v2_ground_{index:02d}', mesh)
        obj['chase_v2_environment'] = True
        scene.collection.objects.link(obj)
        result.append(obj)
    bpy.context.view_layer.update()
    return result


def _extend_native_verges(scene, ground, *, x, y, length, half_width):
    """Low native rocks/leaf clusters, deliberately placed outside the run lane."""
    candidates = []
    for obj in sorted(_environment_meshes(scene), key=lambda o: o.name):
        if not re.search(r'campfire_rocks|tree_oak_leaves', obj.name) or obj.modifiers:
            continue
        lo, hi = _environment_bounds([obj])
        size = hi-lo
        if .15 < size.z < 1.5 and max(size.x, size.y) < 3.5:
            candidates.append(obj)
    # Use different complete native shapes, with no scaling/material changes.
    candidates = candidates[:12]
    if not candidates:
        return []
    result = []
    for side in (-1, 1):
        for i in range(math.ceil((length+12)/5.5)):
            px = x + side*(half_width+2.2+(i%3)*.8)
            py = y-3+i*5.5+(2.2 if side>0 else 0)
            hit, normal, _, _ = ground.ray_cast(Vector((px,py,60)),Vector((0,0,-1)),100)
            if hit is None or normal.z < .8:
                continue
            source = candidates[(i+(4 if side>0 else 0))%len(candidates)]
            lo, hi = _environment_bounds([source])
            anchor = Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z))
            obj = source.copy(); obj.parent=None; obj.animation_data_clear(); obj.constraints.clear()
            obj.name=f'chase_v2_verge_{side}_{i:02d}'
            obj['chase_v2_environment']=True
            scene.collection.objects.link(obj)
            obj.matrix_world=(Matrix.Translation(hit-Vector((0,0,.025)))
                              @ Matrix.Rotation(i*.9,4,'Z')
                              @ Matrix.Translation(-anchor) @ source.matrix_world)
            obj.hide_render=obj.hide_viewport=False;obj.hide_set(False)
            result.append(obj)
    bpy.context.view_layer.update()
    return result
