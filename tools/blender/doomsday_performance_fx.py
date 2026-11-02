"""Bounded weapon charge/arrest for the fourteen-second authored performance.

Call apply(scene, axe, rubick, contact) after author(). This module only authors
objects/keys in memory; it never renders, saves a blend, or changes hero meshes.
"""
import math
import random

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from doomsday_atmosphere import filament

N = 420
HIT = 279
PREFIX = 'Performance FX '


def _interpolation(owner, kind):
    if not owner.animation_data or not owner.animation_data.action:
        return
    for layer in owner.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = kind


def _window(ob, start, end):
    for frame, hidden in ((0, True), (start-1, True), (start, False),
                          (end, False), (end+1, True), (N, True)):
        ob.hide_render = hidden
        ob.keyframe_insert('hide_render', frame=frame)
        ob.hide_viewport = hidden
        ob.keyframe_insert('hide_viewport', frame=frame)
    _interpolation(ob, 'CONSTANT')


def _power(ob, keys):
    node = next(n for n in ob.data.materials[0].node_tree.nodes if n.type == 'EMISSION')
    socket = node.inputs[1]
    if 'blade charge' in ob.name:
        keys=list(keys);pulses=[]
        phase=sum(ord(c) for c in ob.name)*.73
        for frame in range(24,HIT,2):
            left,right=next((a,b) for a,b in zip(keys,keys[1:]) if a[0]<=frame<=b[0])
            value=left[1]+(right[1]-left[1])*(frame-left[0])/(right[0]-left[0])
            pulses.append((frame,value*(.3+.7*math.sin(frame*.21+phase)**2)))
        keys=[keys[0],*pulses,keys[-1]]
    for frame, value in keys:
        socket.default_value = value
        socket.keyframe_insert('default_value', frame=frame)
    _interpolation(ob.data.materials[0].node_tree, 'LINEAR')


def _light(scene, label, parent, position, color, keys):
    data = bpy.data.lights.new(PREFIX+label, 'POINT')
    data.color = color
    data.shadow_soft_size = .12
    ob = bpy.data.objects.new(PREFIX+label, data)
    scene.collection.objects.link(ob)
    if parent:
        ob.parent = parent
    ob.location = position
    for frame, value in keys:
        data.energy = value
        data.keyframe_insert('energy', frame=frame)
    _interpolation(data, 'LINEAR')
    return ob


def _hull(points):
    """Convex boundary indices in the two largest principal mesh directions."""
    array = np.asarray([tuple(p) for p in points], dtype=float)
    center = array.mean(axis=0)
    _, basis = np.linalg.eigh(np.cov(array-center, rowvar=False))
    projected = (array-center) @ basis[:, -2:]
    ordered = sorted(set((float(p[0]), float(p[1]), i) for i, p in enumerate(projected)))

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])

    lower, upper = [], []
    for sequence, chain in ((ordered, lower), (reversed(ordered), upper)):
        for item in sequence:
            while len(chain) >= 2 and cross(chain[-2], chain[-1], item) <= 0:
                chain.pop()
            chain.append(item)
    indices = [p[2] for p in lower[:-1]+upper[:-1]]
    if len(indices) < 3:
        raise ValueError('Weapon blade has no usable surface boundary')
    return [points[i] for i in indices], Vector(center), Vector(basis[:, 0])


def apply(scene, axe, rubick, contact):
    previous_frame = scene.frame_current
    # Rerunning the module does not duplicate event objects.
    for ob in list(scene.objects):
        if ob.name.startswith(PREFIX):
            bpy.data.objects.remove(ob, do_unlink=True)
    contact = Vector(contact)
    scene.frame_set(HIT)
    bpy.context.view_layer.update()
    weapon = next(o for o in scene.objects if o.type == 'MESH' and 'axe_weapon' in o.name)
    evaluated = weapon.evaluated_get(bpy.context.evaluated_depsgraph_get())
    world_points = [evaluated.matrix_world @ v.co for v in evaluated.data.vertices]
    wrist = axe.matrix_world @ axe.pose.bones['wrist_R'].head
    axis = (contact-wrist).normalized()
    distances = [(p-wrist).dot(axis) for p in world_points]
    span = max(distances)-min(distances)
    cutoff = max(distances)-min(.95, span*.43)
    blade = [p for p, distance in zip(world_points, distances) if distance >= cutoff]
    if len(blade) < 12:
        raise ValueError('Insufficient evaluated blade geometry for charge')
    boundary, center, normal = _hull(blade)
    surface = BVHTree.FromPolygons(world_points,
                                  [tuple(p.vertices) for p in evaluated.data.polygons])
    array = np.asarray([tuple(p-center) for p in blade])
    _, directions = np.linalg.eigh(np.cov(array, rowvar=False))
    horizontal, vertical = Vector(directions[:, 2]), Vector(directions[:, 1])
    half_u = max(abs((p-center).dot(horizontal)) for p in blade)
    half_v = max(abs((p-center).dot(vertical)) for p in blade)
    ray_distance = max((p-center).length for p in world_points)+.5
    basis_at_hit = axe.matrix_world @ axe.pose.bones['axe_1'].matrix
    inverse = basis_at_hit.inverted()

    # The weapon mesh is deformed by its rig. Parenting FX to that object would
    # miss bone deformation. Bake a separate transform from the controlling bone.
    anchor = bpy.data.objects.new(PREFIX+'weapon anchor', None)
    scene.collection.objects.link(anchor)
    anchor.empty_display_size = .04
    anchor.rotation_mode = 'QUATERNION'
    previous_q = None
    for frame in range(N):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        matrix = axe.matrix_world @ axe.pose.bones['axe_1'].matrix
        position, rotation, scale = matrix.decompose()
        if previous_q is not None and previous_q.dot(rotation) < 0:
            rotation.negate()
        previous_q = rotation.copy()
        anchor.location = position
        anchor.rotation_quaternion = rotation
        anchor.scale = scale
        for name in ('location', 'rotation_quaternion', 'scale'):
            anchor.keyframe_insert(name, frame=frame)
    _interpolation(anchor, 'LINEAR')

    rng = random.Random(279)
    created = []
    # Project onto actual front/back surfaces. Convex-hull chords can cross the
    # head's cutouts; never connect across a ray miss or a large surface jump.
    surface_strands = 0
    for side in (-1, 1):
        outward = normal*side
        for strand, (u0,v0) in enumerate(((-.65,-.25),(-.45,.1),(-.15,.35),
                                         (.18,-.3),(.42,.1),(.60,.3))):
            slope = -.48 if strand%2 else .48
            paths = [[],[]]
            for branch, path in enumerate(paths):
                for step in range(15 if branch==0 else 8):
                    t = step/(14 if branch==0 else 7)
                    u = u0+(.25*t if branch==0 else .13+.22*t)
                    v = v0+(slope*t if branch==0 else slope*.5-slope*.55*t)
                    target = center+horizontal*(half_u*u)+vertical*(half_v*v)
                    target += horizontal*rng.uniform(-.016,.016)+vertical*rng.uniform(-.015,.015)
                    hit,hit_normal,_,_ = surface.ray_cast(target+outward*ray_distance,
                                                        -outward,ray_distance*2)
                    if hit is None or (hit-wrist).dot(axis)<cutoff:
                        if len(path)>=3:break
                        path.clear();continue
                    world = hit+outward*.018
                    if path and (world-path[-1]).length>.14:
                        if len(path)>=3:break
                        path.clear()
                    path.append(world)
                if len(path)<3:continue
                points=[inverse@p for p in path]
                ob=filament(scene,PREFIX+f'blade charge {side} {strand} {branch}',
                            points,(.15,.55,1),.004 if branch==0 else .0028,4)
                ob.parent=anchor
                _window(ob,24,HIT-1)
                offset=strand%3
                strength=1 if branch==0 else .7
                _power(ob,tuple((f,p*strength) for f,p in
                       ((0,0),(24,2),(60+offset,4),(100,3),(160,3.5),(195,5),
                        (220+offset,8),(251+offset,11),(HIT-2,9),(HIT,0))))
                created.append(ob);surface_strands+=1
        _light(scene,f'charge light {side}',anchor,inverse@(center+outward*.20),(.16,.45,1),
               ((0,0),(23,0),(24,1),(60,4),(195,5),(231,10),(275,14),(279,0),(419,0)))
    if surface_strands<4:
        raise ValueError(f'Only {surface_strands} readable projected charge strands')

    scene.frame_set(HIT)
    bpy.context.view_layer.update()
    finger = rubick.matrix_world @ rubick.pose.bones['index_1_R'].tail
    # Use a short contact-local tether only; the finger can lie inside the blade
    # AABB, so choose surface points near contact rather than spanning the body.
    near = sorted(boundary, key=lambda p:(p-contact).length)[:min(4,len(boundary))]
    events = ((279,284),(286,291),(295,300),(305,310),(312,316),
              (329,332),(351,354),(377,380),(408,411))
    for event, (start,end) in enumerate(events):
        residual = start > 316
        for strand in range(2 if residual else 4):
            endpoint = near[(event+strand) % len(near)]
            if (endpoint-contact).length > .65:
                endpoint = contact+(endpoint-contact).normalized()*.65
            origin = contact.lerp(finger,.18) if (finger-contact).length < .3 else contact
            points = []
            for step in range(17):
                t = step/16
                jitter = Vector(tuple(rng.uniform(-.018,.018) for _ in range(3)))
                side=-1 if strand%2 else 1
                points.append(origin.lerp(endpoint,t)+normal*(side*.07)+jitter*math.sin(math.pi*t))
            ob = filament(scene, PREFIX+f'arrest {event} {strand}', points,
                          (.10,1,.24), .003 if residual else .005, 3 if residual else 12)
            # An Emission surface at strength zero is opaque black. Hide the
            # strand on that endpoint; its last visible frame still emits light.
            _window(ob,start,end-1)
            _power(ob, ((start,2 if residual else 9),
                        (start+1,4 if residual else 18),(end,0)))
            created.append(ob)
    # The small persistent core reads as sustained suspension after the initial
    # arrest, while the brighter filaments remain isolated brief discharges.
    core = filament(scene, PREFIX+'held contact',
                    [contact+Vector((-.025,0,-.015)), contact,
                     contact+Vector((.018,0,.022))], (.12,1,.30), .009, 1)
    _window(core,HIT,N-1)
    _power(core,((HIT,12),(285,16),(301,7),(316,2),(419,1.5)))
    created.append(core)
    _light(scene,'arrest light',None,contact+Vector((0,-.06,.04)),(.10,1,.25),
           ((0,0),(278,0),(279,24),(282,38),(289,18),(303,9),(316,3),(419,2)))

    # A strictly bounded additive contact burst keeps every cached frame outside
    # 279..303 unchanged. Use well-separated actual blade-surface vertices,
    # rather than repeatedly selecting the hull vertex nearest to the contact.
    candidates=[p for p in blade if .4 <= (p-contact).length <= .7]
    if len(candidates)<3:
        raise ValueError('Blade has fewer than three contact-burst endpoints at .4..7m')
    def plane_distance(a,b):
        delta=a-b
        return math.hypot(delta.dot(horizontal),delta.dot(vertical))
    endpoints=[max(candidates,key=lambda p:plane_distance(p,contact))]
    for _ in range(2):
        endpoints.append(max(candidates,key=lambda p:min(plane_distance(p,q) for q in endpoints)))
    minimum_separation=min(plane_distance(a,b) for i,a in enumerate(endpoints)
                           for b in endpoints[i+1:])
    if minimum_separation<.10:
        raise ValueError('Contact-burst endpoints collapsed in the blade plane')
    burst_rng=random.Random(3279)
    for side in (-1,1):
        for index,endpoint in enumerate(endpoints):
            outward=normal*side
            origin=contact+outward*.11
            destination=endpoint+outward*.11
            direction=(destination-origin).normalized()
            lateral=normal.cross(direction).normalized()
            points=[]
            for step in range(19):
                t=step/18
                jag=burst_rng.uniform(-.035,.035)*math.sin(math.pi*t)
                points.append(origin.lerp(destination,t)+lateral*jag+
                              outward*(.035*math.sin(math.pi*t)))
            ob=filament(scene,PREFIX+f'impact burst {side} {index}',points,
                        (.09,1,.23),.0065,30)
            _window(ob,279,303)
            _power(ob,((278,0),(279,26),(281,42),(285,16),(287,28),
                       (292,8),(296,15),(301,5),(303,2),(304,0)))
            created.append(ob)
            fork_start=points[9]
            fork_end=destination.lerp(origin,.20)+lateral*(.10 if index%2 else -.10)
            branch=[]
            for step in range(9):
                t=step/8
                branch.append(fork_start.lerp(fork_end,t)+
                              lateral*burst_rng.uniform(-.018,.018)*math.sin(math.pi*t))
            fork=filament(scene,PREFIX+f'impact branch {side} {index}',branch,
                          (.12,1,.28),.0035,18)
            _window(fork,279,303)
            _power(fork,((278,0),(279,16),(281,28),(285,10),(287,19),
                         (292,5),(296,9),(301,3),(303,1),(304,0)))
            created.append(fork)
    _light(scene,'bounded impact light',None,contact+Vector((0,-.08,.04)),(.10,1,.24),
           ((0,0),(278,0),(279,20),(281,26),(285,12),(292,5),(300,2),(303,.5),(304,0),(419,0)))
    impact_report={'frame_extent':[279,303], 'zero_or_hidden_outside_extent':True,
                   'unchanged_frame_ranges':[[0,278],[304,419]],
                   'main_arcs':6,'branches':6,'normal_offset_m':.11,
                   'endpoint_distances_m':[(p-contact).length for p in endpoints],
                   'minimum_endpoint_plane_separation_m':minimum_separation,
                   'additional_light_peak_watts':26}
    scene.frame_set(previous_frame)
    bpy.context.view_layer.update()
    return {'module': 'doomsday_performance_fx', 'frames': N,
            'blade_mesh': weapon.name, 'evaluated_blade_vertices': len(blade),
            'boundary_vertices': len(boundary), 'curve_objects': len(created),
            'anchor': anchor.name, 'anchor_source_bone': 'axe_1',
            'contact': list(contact), 'charge_frames': [24,HIT-1],
            'arrest_frames': [HIT,316], 'held_through': N-1,
            'surface_projected_charge_strands':surface_strands,
            'impact_reinforcement':impact_report,
            'maximum_light_watts': {'charge_per_side':14, 'arrest':38},
            'visual_reviewed': False}
