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
