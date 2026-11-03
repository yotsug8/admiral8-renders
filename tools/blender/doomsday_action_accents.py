"""Small takeoff/contact accents for the staged fourteen-second scene.

Call apply(scene), then review frames 258 and 283 before rendering a clip.
Uses existing noise-volume/filament helpers and existing game rock material.
Never renders, saves a scene, changes hero poses, or replaces electric geometry.
Positions are sampled from evaluated bones and the actual court/weapon surface.
Screen-space exclusions are conservative bone/contact proxies, not a skin audit.
The 255..265 dust envelope and 279..292 contact envelope assume this edit's timing.
"""
import json
import math
import random
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from doomsday_atmosphere import boulder_template, dust_material, filament
from doomsday_performance_fx import _interpolation, _power, _window
from doomsday_pressure_study import main_rig

PREFIX = 'Action accents '


def refine_impact_lines(scene):
    """Thin the bounded 279..303 burst; retain its surface path and timing."""
    changed=[]
    for ob in scene.objects:
        if not ob.name.startswith(('Performance FX impact burst ', 'Performance FX impact branch ')):
            continue
        curve=ob.data
        if 'accent_original_width' not in curve:
            curve['accent_original_width']=curve.bevel_depth
            curve['accent_original_radii']=json.dumps([[p.radius for p in s.points] for s in curve.splines])
        curve.bevel_depth=curve['accent_original_width']*.42
        original=json.loads(curve['accent_original_radii'])
        for spline,radii in zip(curve.splines,original):
            for i,(point,radius) in enumerate(zip(spline.points,radii)):
                point.radius=radius*(.62+.38*(.5+.5*math.sin(i*2.31)))
        changed.append(ob.name)
    return changed


def _curves(owner):
    action = owner.animation_data.action if owner.animation_data else None
    if action:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves


def _scaled_channel(owner, path, socket, factor):
    """Store original values once, allowing a later factor=1 to restore them."""
    key = 'action_accents_original_gain'
    if key not in owner:
        saved = {'value': float(socket()), 'keys': []}
        for curve in _curves(owner):
            if curve.data_path == path:
                saved['keys'].append([[float(k.co.y), float(k.handle_left.y),
                                       float(k.handle_right.y)] for k in curve.keyframe_points])
        owner[key] = json.dumps(saved)
    saved = json.loads(owner[key])
    matching = [curve for curve in _curves(owner) if curve.data_path == path]
    if matching:
        if len(matching) != len(saved['keys']):
            raise ValueError('Existing FX animation changed since gain calibration.')
        for curve, values in zip(matching, saved['keys']):
            if len(curve.keyframe_points) != len(values):
                raise ValueError('Existing FX key count changed since gain calibration.')
            for point, original in zip(curve.keyframe_points, values):
                point.co.y, point.handle_left.y, point.handle_right.y = [v * factor for v in original]
    return saved['value'] * factor


def set_impact_gain(scene, factor):
    """Reversible emission-only gain; other existing charge/arrest layers untouched."""
    if not 0 < factor <= 1:
        raise ValueError('impact_gain must be > 0 and <= 1; zero emission leaves opaque black curves.')
    changed, seen = [], set()
    for ob in scene.objects:
        if ob.name.startswith(('Performance FX impact burst ', 'Performance FX impact branch ')):
            for material in ob.data.materials:
                if not material or not material.use_nodes or material.name in seen:
                    continue
                seen.add(material.name)
                node = next(n for n in material.node_tree.nodes if n.type == 'EMISSION')
                strength = node.inputs[1]
                strength.default_value = _scaled_channel(material.node_tree,
                    strength.path_from_id('default_value'), lambda: strength.default_value, factor)
            changed.append(ob.name)
        elif ob.name == 'Performance FX bounded impact light':
            ob.data.energy = _scaled_channel(ob.data, 'energy', lambda: ob.data.energy, factor)
            changed.append(ob.name)
    return changed


def _surface(obj, graph):
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    result = BVHTree.FromPolygons(points, [tuple(p.vertices) for p in mesh.polygons])
    evaluated.to_mesh_clear()
    return result


def _bone(arm, name, graph):
    evaluated = arm.evaluated_get(graph)
    return evaluated.matrix_world @ evaluated.pose.bones[name].matrix


def _point_segment_distance(p, a, b):
    d = b - a
    t = max(0., min(1., (p-a).dot(d)/max(d.length_squared, 1e-12)))
    return (p - (a+d*t)).length


def _screen_point(scene, camera, point):
    value = world_to_camera_view(scene, camera, point)
    return Vector((value.x * scene.render.resolution_x / scene.render.resolution_y, value.y))


def _screen_clear(scene, camera, points, protected):
    # Project physical clearances rather than imposing a fixed pixel radius:
    # the same finger is much smaller in the wide impact shot than the insert.
    screen = [_screen_point(scene, camera, p) for p in protected]
    right = camera.matrix_world.to_3x3().col[0].normalized()
    finger_radius = (_screen_point(scene, camera, protected[1]+right*.045)-screen[1]).length
    hand_radii = [(_screen_point(scene, camera, h+right*radius)-s).length
                  for h, s, radius in zip(protected[2:], screen[2:], (.12, .12, .28, .22))]
    for point in points:
        p = _screen_point(scene, camera, point)
        if _point_segment_distance(p, screen[0], screen[1]) < finger_radius:
            return False
        if any((p-h).length < radius for h, radius in zip(screen[2:], hand_radii)):
            return False
    return True


def _pixels_per_unit(scene, camera, point, direction):
    a = _screen_point(scene, camera, point)
    b = _screen_point(scene, camera, point+direction.normalized()*.01)
    return max(1., (b-a).length*720/.01)


def _keys(ob, frame, location=None, scale=None):
    if location is not None:
        ob.location = location
        ob.keyframe_insert('location', frame=frame)
    if scale is not None:
        ob.scale = scale
        ob.keyframe_insert('scale', frame=frame)


def apply(scene, impact_gain=.20):
    """Author local FX in memory; return measured anchors and review limitations."""
    previous = scene.frame_current
    for ob in list(scene.objects):
        if ob.name.startswith(PREFIX):
            bpy.data.objects.remove(ob, do_unlink=True)
    rng = random.Random(253279)
    axe, rubick = (main_rig(scene, actor) for actor in ('axe', 'rubick'))
    scene.frame_set(253)
    graph = bpy.context.evaluated_depsgraph_get()
    court = scene.objects.get('Stone court')
    if court is None:
        raise ValueError('Expected the actual Stone court; no guessed ground plane.')
    surface = _surface(court, graph)
    feet = {}
    for side in ('L', 'R'):
        ankle = _bone(axe, 'ankle_'+side, graph).translation
        toe = _bone(axe, 'toeBase_'+side, graph).translation
        candidate = ankle.lerp(toe, .65)
        hit = surface.ray_cast(candidate + Vector((0, 0, 3)), Vector((0, 0, -1)), 6)[0]
        if hit is not None:
            feet[side] = (ankle.z-hit.z, hit)
    if not feet:
        raise ValueError('No actual ground under the takeoff feet.')
    side = min(feet, key=lambda s: feet[s][0])
    origin = feet[side][1]
    root_before = _bone(axe, 'root', graph).translation
    scene.frame_set(257)
    graph = bpy.context.evaluated_depsgraph_get()
    travel = _bone(axe, 'root', graph).translation-root_before
    travel.z = 0
    if travel.length < 1e-6:
        raise ValueError('No planar takeoff direction to motivate particles.')
    travel.normalize()
    sideways = Vector((-travel.y, travel.x, 0))
    base_dust = dust_material()
    base_dust.name = PREFIX+'dust source'
    volume = next(n for n in base_dust.node_tree.nodes if n.type == 'PRINCIPLED_VOLUME')
    volume.inputs['Color'].default_value = (.48, .39, .27, 1)
    volume.inputs['Anisotropy'].default_value = .2
    for i in range(5):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1)
        ob = bpy.context.object
        ob.name = PREFIX+f'foot dust {i}'
        material = base_dust.copy()
        ob.data.materials.append(material)
        density = next(n for n in material.node_tree.nodes if n.type == 'MATH'
                       and n.inputs[1].default_value == 5).inputs[1]
        start = 255+i%2
        ob.rotation_euler.z = math.atan2(-travel.y, -travel.x)+(i-2)*.18
        _window(ob, start, 265)
        for f in range(start, 266):
            t = (f-start)/max(1, 265-start)
            growth = 1-(1-t)**3
            position = origin-travel*(.12+.33*growth)+sideways*(i-2)*(.035+.075*growth)
            position.z += .21+.09*t
            _keys(ob, f, position, (.18+.18*growth, .09+.09*growth, (.12+.10*t)*1.8))
            density.default_value = (14 if i == 2 else 11)*math.sin(math.pi*t)**.5
            density.keyframe_insert('default_value', frame=f)
        _interpolation(material.node_tree, 'LINEAR')
    template = boulder_template(scene)
    for i in range(8):
        # Shared existing rock mesh/material; no new game/resource download.
        ob = bpy.data.objects.new(PREFIX+f'ground grain {i}', template.data)
        scene.collection.objects.link(ob)
        largest = max(max(v.co[j] for v in ob.data.vertices)-min(v.co[j] for v in ob.data.vertices)
                      for j in range(3))
        radius = rng.uniform(.018, .035)
        ob.scale = (radius*2/max(largest, 1e-5),)*3
        ob.rotation_euler = tuple(rng.uniform(0, 6) for _ in range(3))
        _window(ob, 255, 265)
        velocity = -travel*rng.uniform(1.2, 2.1)+sideways*rng.uniform(-.65, .65)
        velocity.z = rng.uniform(.8, 1.25)
        for f in range(255, 266):
            t = (f-255)/scene.render.fps
            position = origin+velocity*t
            position.z = max(origin.z+.008, origin.z+.02+velocity.z*t-4.905*t*t)
            _keys(ob, f, position)

    recipe = json.loads(Path(__file__).with_name('doomsday_contact_pose.json').read_text(encoding='utf8'))
    contact_local = Vector(recipe['contact_weapon_local'])
    scene.frame_set(279)
    graph = bpy.context.evaluated_depsgraph_get()
    weapon = next(o for o in scene.objects if o.type == 'MESH' and 'axe_weapon' in o.name)
    weapon_surface = _surface(weapon, graph)
    matrix = _bone(axe, 'axe_1', graph)
    expected = matrix @ contact_local
    hit, normal, _, gap = weapon_surface.find_nearest(expected)
    if hit is None or gap > .03:
        raise ValueError('Authored contact no longer lies near the evaluated blade.')
    contact_local = matrix.inverted() @ hit
    finger_wrist = _bone(rubick, 'wrist_R', graph).translation
    away = hit-finger_wrist
    away -= normal*away.dot(normal)
    if away.length < 1e-5:
        raise ValueError('Cannot infer a direction away from the stopping hand.')
    away.normalize()
    cross = normal.cross(away).normalized()
    # Orient the small off-surface clearance toward the current camera.
    if scene.camera and normal.dot(scene.camera.matrix_world.translation-hit) < 0:
        normal.negate()
        cross.negate()
    anchor = bpy.data.objects.new(PREFIX+'contact anchor', None)
    scene.collection.objects.link(anchor)
    anchor.rotation_mode = 'QUATERNION'
    contexts = {}
    for f in range(279, 293):
        scene.frame_set(f)
        graph = bpy.context.evaluated_depsgraph_get()
        m = _bone(axe, 'axe_1', graph)
        anchor.location, anchor.rotation_quaternion, anchor.scale = m.decompose()
        for channel in ('location', 'rotation_quaternion', 'scale'):
            anchor.keyframe_insert(channel, frame=f)
        protected = [_bone(rubick, 'wrist_R', graph).translation, m @ contact_local,
                     _bone(axe, 'wrist_L', graph).translation, _bone(axe, 'wrist_R', graph).translation,
                     _bone(axe, 'head', graph).translation, _bone(rubick, 'Head_0', graph).translation]
        contexts[f] = (m.copy(), scene.camera, protected)
    inverse = matrix.inverted()
    scale = sum(matrix.to_scale())/3
    accepted, rejected = [], []
    for event, start in enumerate((279, 283, 288)):
        for j in range(3):
            direction = (away+cross*((j-1)*.7)).normalized()
            points = []
            for step in range(9):
                t = step/8
                p = hit+direction*(.065+.17*t)+cross*rng.uniform(-.009, .009)*math.sin(math.pi*t)
                p += normal*(.012+.012*math.sin(math.pi*t))
                points.append(inverse @ p)
            end = min(start+2, 292)
            visible = True
            for f in range(start, end+1):
                scene.frame_set(f)
                m, camera, protected = contexts[f]
                if camera and not _screen_clear(scene, camera, [m@p for p in points], protected):
                    visible = False
                    break
            if not visible:
                rejected.append(f'arc {event} {j}')
                continue
            ob = filament(scene, PREFIX+f'fine arc {event} {j}', points,
                          (.32, 1, .48), .0011/scale, 9)
            ob.parent = anchor
            _window(ob, start, end)
            for f in range(start, end+1):
                scene.frame_set(f)
                m, camera, _ = contexts[f]
                center = m @ points[len(points)//2]
                right = camera.matrix_world.to_3x3().col[0].normalized()
                ob.data.bevel_depth = .5/_pixels_per_unit(scene, camera, center, right)/scale
                ob.data.keyframe_insert('bevel_depth', frame=f)
            _power(ob, ((start, 9), (start+1, 14), (end+1, 0)))
            accepted.append(ob.name)
    shard_measurements = []
    for i in range(18):
        start = 279+i%3
        end = min(start+11, 292)
        direction = (away*.35+cross*rng.uniform(-1.5, 1.5)+normal*.8).normalized()
        initial = hit+direction*.065+normal*.035
        reach = rng.uniform(.4, .8)
        target_pixels = rng.uniform(3.2, 4.8)
        trajectories = {}
        lengths = {}
        visible = True
        for f in range(start, end+1):
            progress = (f-start)/(end-start)
            t = (f-start)/scene.render.fps
            p = initial+direction*(reach*progress)+Vector((0, 0, -.35*t*t))
            trajectories[f] = p
            scene.frame_set(f)
            _, camera, protected = contexts[f]
            length = target_pixels/_pixels_per_unit(scene, camera, p, direction)
            lengths[f] = length
            if camera and not _screen_clear(scene, camera, (p, p+direction*length), protected):
                visible = False
                break
        if not visible:
            rejected.append(f'shard {i}')
            continue
        # Three points matter: the helper tapers endpoints to .18 radius.
        # A two-point filament had no bright full-width center and was subpixel.
        ob = filament(scene, PREFIX+f'light shard {i}', [Vector(), direction*.5, direction],
                      (.66, 1, .74), .20, 14)
        _window(ob, start, end)
        for f, p in trajectories.items():
            scene.frame_set(f)
            camera = contexts[f][1]
            right = camera.matrix_world.to_3x3().col[0].normalized()
            _keys(ob, f, p, (lengths[f],)*3)
            ob.data.bevel_depth = 1.0/_pixels_per_unit(scene, camera, p, right)/lengths[f]
            ob.data.keyframe_insert('bevel_depth', frame=f)
        _power(ob, ((start, 12), (start+2, 20), (end, 3), (end+1, 0)))
        accepted.append(ob.name)
        shard_measurements.append({'object': ob.name, 'target_length_pixels_at_720p': target_pixels,
                                   'target_center_diameter_pixels_at_720p': 2.0,
                                   'travel_from_spawn_world': reach,
                                   'world_length_range': [min(lengths.values()), max(lengths.values())]})
    changed = set_impact_gain(scene, impact_gain)
    refined = refine_impact_lines(scene)
    scene.frame_set(previous)
    bpy.context.view_layer.update()
    return {'module': 'doomsday_action_accents', 'foot_side': side,
            'foot_ground_world': list(origin), 'ankle_ground_heights': {s: v[0] for s,v in feet.items()},
            'takeoff_direction': list(travel), 'dust_frames': [255, 265],
            'dust_clouds': 5, 'dust_rear_extent_world': .81,
            'ground_grains': 8, 'contact_frames': [279, 292],
            'shard_projection': shard_measurements,
            'actual_contact_world': list(hit), 'recipe_surface_gap': gap,
            'contact_fx_created': accepted, 'screen_exclusion_rejections': rejected,
            'impact_gain': impact_gain, 'attenuated_existing_layers': changed,
            'thinner_variable_width_impact_lines':refined,
            'probe_frames': [258, 283], 'visual_reviewed': False,
            'limits': ['No general skin/geometry audit or visual acceptance.',
                       'Dust is a small procedural volume, not a fluid simulation; render cost must be checked.',
                       'Screen exclusions use bone/contact proxies, not a rendered finger silhouette.',
                       'Rock fragments are tiny real rock-mesh instances; exact floor bounces are not simulated.',
                       'Existing blade charge, arrest and held-core geometry remains unchanged.']}
