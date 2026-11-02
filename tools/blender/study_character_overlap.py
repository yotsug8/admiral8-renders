"""Bounded character overlap study; outputs only below _game/study/character_overlap."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import subprocess
import struct
import zlib
import shutil

sys.dont_write_bytecode = True

import bpy
from mathutils import Matrix, Quaternion, Vector
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contact_metrics import resolve, visible_meshes
from contact_reaction import _basis, _curves

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/study/character_overlap'
SOURCES = ['_game/study/foundations/reach_witness/point_A.blend',
           '_game/skits/probe17/skin_trial.blend', '_game/skits/probe19/gaze_head.blend']
FPS, COUNT, DENSITY = 30, 84, 4
OMEGA, DAMPING, HZ = 12., .72, 960
AMPLITUDE = 5.
SPINE_SHARES = [('spine1', 1.)]


def smooth(x):
    x = min(1., max(0., x))
    return x*x*x*(10+x*(-15+6*x))


def body(t):
    return math.radians(-AMPLITUDE) * smooth((t-.3)/.35) * (1-smooth((t-1.)/.35))


def response_table():
    """Same fixed-step RK4 oscillator as study_followthrough; angular input."""
    x = v = 0.
    result = [x]
    dt = 1/HZ
    def derivative(t, px, pv):
        return pv, OMEGA**2*(body(t)-px)-2*DAMPING*OMEGA*pv
    for i in range(math.ceil(COUNT/FPS*HZ)):
        t = i*dt
        a = derivative(t, x, v)
        b = derivative(t+dt/2, x+a[0]*dt/2, v+a[1]*dt/2)
        c = derivative(t+dt/2, x+b[0]*dt/2, v+b[1]*dt/2)
        d = derivative(t+dt, x+c[0]*dt, v+c[1]*dt)
        x += dt*(a[0]+2*b[0]+2*c[0]+d[0])/6
        v += dt*(a[1]+2*b[1]+2*c[1]+d[1])/6
        result.append(x)
    return result


RESPONSE = response_table()


def head(t):
    q = min(max(0., t*HZ), len(RESPONSE)-1)
    i = int(q)
    x = RESPONSE[i] if i == len(RESPONSE)-1 else RESPONSE[i]+(RESPONSE[i+1]-RESPONSE[i])*(q-i)
    return x*(1-smooth((t-2.3)/.3))


def pivot_rotate(matrix, axis, angle):
    p = matrix.translation
    return Matrix.Translation(p) @ Quaternion(axis, angle).to_matrix().to_4x4() @ Matrix.Translation(-p)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    node = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    node.inputs['Base Color'].default_value = (*color, 1)
    node.inputs['Emission Color'].default_value = (*color, 1)
    node.inputs['Emission Strength'].default_value = .5
    node.inputs['Roughness'].default_value = .85
    return mat


def label(words, loc, size, mat):
    data = bpy.data.curves.new(words, 'FONT')
    data.body, data.align_x, data.size = words, 'CENTER', size
    ob = bpy.data.objects.new(words, data)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (math.pi/2, 0, 0)
    ob.data.materials.append(mat)


def freeze(root, arm, members):
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    matrices = {o.name: o.evaluated_get(graph).matrix_world.copy() for o in members}
    poses = {o.name: {b.name: b.matrix_basis.copy() for b in o.pose.bones}
             for o in members if o.type == 'ARMATURE'}
    for ob in members:
        ob.animation_data_clear()
        if ob.type == 'MESH' and ob.data.shape_keys:
            ob.data.shape_keys.animation_data_clear()
        ob.matrix_world = matrices[ob.name]
        if ob.type == 'ARMATURE':
            for b in ob.pose.bones:
                b.matrix_basis = poses[ob.name][b.name]
    bpy.context.view_layer.update()
    if any(c.influence and not c.mute for b in arm.pose.bones for c in b.constraints):
        raise ValueError('Main rig constraints unsupported')
    # Keep the actual exported pose. Reposition the actor once for the study layout.
    root.location -= root.matrix_world.translation
    bpy.context.view_layer.update()


def clone(members, prefix):
    mapping = {}
    for old in members:
        new = old.copy()
        if old.type == 'ARMATURE':
            new.data = old.data.copy()
        new.name = prefix+'.'+old.name
        bpy.context.scene.collection.objects.link(new)
        mapping[old] = new
    for old, new in mapping.items():
        new.parent = mapping.get(old.parent, old.parent)
        for mod in new.modifiers:
            if mod.type == 'ARMATURE':
                mod.object = mapping.get(mod.object, mod.object)
        if new.type == 'ARMATURE':
            for b in new.pose.bones:
                for con in b.constraints:
                    if hasattr(con, 'target'):
                        con.target = mapping.get(con.target, con.target)
    return mapping


def bake(arm, case):
    """Rotate the spine subtree; compensate inherited head rotation, 30/70 neck/head."""
    bpy.context.view_layer.update()
    base = {b.name: b.matrix.copy() for b in arm.pose.bones}
    # Actor faces +world X in this source. Convert the horizontal pitch axis to rig space.
    axis = arm.matrix_world.inverted().to_3x3() @ Vector((0, 1, 0))
    axis.normalize()
    selected = [n for n, _ in SPINE_SHARES]+['neck1', 'head']
    previous = {}
    for i in range((COUNT-1)*DENSITY+1):
        f = i/DENSITY
        t = f/FPS
        desired = {n: m.copy() for n, m in base.items()}
        values = [(n, share*body(t)) for n, share in SPINE_SHARES]
        lag = head(t)-body(t) if case == 'follow' else 0.
        values += [('neck1', .3*lag), ('head', .7*lag)]
        for name, angle in values:
            bone = arm.pose.bones[name]
            transform = pivot_rotate(desired[name], axis, angle)
            for child in [bone, *bone.children_recursive]:
                desired[child.name] = transform @ desired[child.name]
        for name in selected:
            b = arm.pose.bones[name]
            m = _basis(b, desired[name], desired[b.parent.name] if b.parent else None)
            loc, rot, scale = m.decompose()
            if name in previous and previous[name].dot(rot) < 0:
                rot.negate()
            previous[name] = rot.copy()
            b.rotation_mode = 'QUATERNION'
            b.location, b.rotation_quaternion, b.scale = loc, rot, scale
            for channel in ('location', 'rotation_quaternion', 'scale'):
                b.keyframe_insert(channel, frame=f, group=name)
    arm.animation_data.action.name = 'character_overlap_'+case
    for curve in _curves(arm.animation_data.action):
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'


def build(folder):
    bpy.ops.wm.open_mainfile(filepath=str(ROOT/SOURCES[0]))
    sc = bpy.context.scene
    root, arm, members = resolve('pudge', list(sc.objects))
    # The source cleaver is already hidden; preserve that deliberate source state.
    members = [o for o in members if 'blob' not in o.name]
    for ob in list(sc.objects):
        if ob not in members:
            bpy.data.objects.remove(ob, do_unlink=True)
    freeze(root, arm, members)
    originals = list(members)
    actors = []
    # Two orthographic views of the same frozen pose, in a simultaneous 2x2 plate.
    for row, angle in enumerate((-65., -175. if AMPLITUDE == 4. else -5.)):
        for col, case in enumerate(('control', 'follow')):
            prefix = f'{row}_{case}'
            mapping = clone(originals, prefix)
            r, a = mapping[root], mapping[arm]
            bake(a, case)
            r.rotation_euler.z += math.radians(angle)
            r.location += Vector((-3.65 if col == 0 else 3.65, 0, 5.3 if row == 0 else 0))
            r['study_actor'] = prefix
            a['study_main'] = prefix
            actors.append(a)
    for ob in originals:
        bpy.data.objects.remove(ob, do_unlink=True)
    sc.render.engine = 'BLENDER_EEVEE'
    sc.eevee.taa_render_samples = 32
    sc.render.resolution_x, sc.render.resolution_y = 960, 540
    sc.render.resolution_percentage, sc.render.fps = 100, FPS
    sc.frame_start, sc.frame_end = 0, COUNT-1
    sc.render.image_settings.file_format = 'PNG'
    sc.render.film_transparent = False
    sc.render.use_file_extension = True
    sc.world = bpy.data.worlds.new('Overlap studio')
    sc.world.use_nodes = True
    bg = next(n for n in sc.world.node_tree.nodes if n.type == 'BACKGROUND')
    bg.inputs['Color'].default_value = (.035, .045, .055, 1)
    bg.inputs['Strength'].default_value = .5
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    sc.view_settings.exposure = 0
    cam = bpy.data.objects.new('OverlapCamera', bpy.data.cameras.new('OverlapCamera'))
    sc.collection.objects.link(cam)
    cam.location = (0, -30, 4.8)
    cam.rotation_euler = (math.pi/2, 0, 0)
    cam.data.type, cam.data.ortho_scale = 'ORTHO', 19.2
    sc.camera = cam
    white = material('Overlap text', (.78, .82, .85))
    blue = material('Control label', (.32, .65, .86))
    amber = material('Follow label', (.96, .66, .28))
    floor = material('Support', (.09, .11, .13))
    for row in range(2):
        base_z = 5.3 if row == 0 else 0
        for col, title in enumerate(('CONTROL', 'FOLLOW-THROUGH')):
            x = -3.65 if col == 0 else 3.65
            label(title, (x, -3, base_z+4.55), .32, blue if col == 0 else amber)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0, base_z-.10))
            ob = bpy.context.object
            ob.name = f'Platform_{row}_{col}'
            ob.scale = (6.7, 5.5, .12)
            ob.data.materials.append(floor)
    label('3/4', (-8.6, -3, 7.7), .25, white)
    label('SIDE', (-8.6, -3, 2.4), .25, white)
    sc['study'] = 'character_overlap'
    sc['source'] = SOURCES[0]
    sc['amplitude_deg'] = AMPLITUDE
    sc['spine_shares'] = json.dumps(SPINE_SHARES)
    sc['limits'] = 'Pudge frozen frame 0 only; hidden source cleaver; no universal retarget or cloth simulation.'
    sc.frame_set(0)
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))


def evaluated_vertices(ob, graph):
    obj = ob.evaluated_get(graph)
    mesh = obj.to_mesh()
    try:
        coords = np.array([tuple(obj.matrix_world @ v.co) for v in mesh.vertices])
        edges = np.array([tuple(e.vertices) for e in mesh.edges], dtype=int)
        return coords, edges
    finally:
        obj.to_mesh_clear()


def support_pairs():
    """Resolve each displayed actor separately; retain the original sole band."""
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    pairs = []
    for arm in sorted((o for o in sc.objects if o.get('study_main')), key=lambda o: o.name):
        tag = arm['study_main']
        row, case = tag.split('_', 1)
        platform = sc.objects[f'Platform_{row}_{0 if case == "control" else 1}']
        mesh = next(o for o in sc.objects if o.name.startswith(tag+'.') and o.name.endswith('pudge.vmdl_c.lower_body'))
        points, _ = evaluated_vertices(mesh, graph)
        feet = {}
        for side in ('L', 'R'):
            ankle = arm.pose.bones['ankle_'+side]
            names = {ankle.name, *[b.name for b in ankle.children_recursive]}
            groups = {g.index for g in mesh.vertex_groups if g.name in names}
            feet[side] = np.array([v.index for v in mesh.data.vertices if
                sum(g.weight for g in v.groups if g.group in groups) > .5], dtype=int)
            if not len(feet[side]):
                raise ValueError(f'{tag}: empty {side} foot selection')
        foot_indices = np.unique(np.concatenate(list(feet.values())))
        lowest = float(points[foot_indices, 2].min())
        if abs(lowest-float(points[:, 2].min())) > 2e-5:
            raise ValueError(f'{tag}: lowest lower-body point is outside the feet')
        sole = foot_indices[points[foot_indices, 2] < lowest+.045]
        if platform.parent or platform.animation_data or platform.constraints:
            raise ValueError('Only static unparented study platforms are supported')
        corners = [platform.matrix_world @ Vector(v) for v in platform.bound_box]
        top = max(v.z for v in corners)
        if max(v.z for v in corners)-min(v.z for v in corners) <= 0:
            raise ValueError('Invalid platform height')
        pairs.append(dict(tag=tag, platform=platform, mesh=mesh, sole=sole, feet=feet,
                          lowest=lowest, old_top=top, reference=points[sole].copy()))
    if len(pairs) != 4:
        raise ValueError('Expected four displayed actors')
    return pairs


def scene_motion_fingerprint():
    """Hash evaluated non-platform objects, bones and surfaces on all 84 frames."""
    sc = bpy.context.scene
    objects = sorted((o for o in sc.objects if not o.name.startswith('Platform_')), key=lambda o: o.name)
    animation = hashlib.sha256()
    for ob in objects:
        ad = ob.animation_data
        if ad and ad.action:
            animation.update(ob.name.encode())
            for curve in _curves(ad.action):
                animation.update(json.dumps([curve.data_path, curve.array_index, curve.extrapolation]).encode())
                for key in curve.keyframe_points:
                    animation.update(json.dumps([list(key.co), list(key.handle_left), list(key.handle_right),
                        key.interpolation, key.handle_left_type, key.handle_right_type]).encode())
    evaluated = hashlib.sha256()
    for f in range(COUNT):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        for ob in objects:
            current = ob.evaluated_get(graph)
            evaluated.update(ob.name.encode())
            evaluated.update(np.array(current.matrix_world, dtype='<f8').tobytes())
            if ob.type == 'ARMATURE':
                for bone in current.pose.bones:
                    evaluated.update(np.array(bone.matrix, dtype='<f8').tobytes())
            elif ob.type == 'MESH' and not ob.hide_render:
                points, _ = evaluated_vertices(ob, graph)
                evaluated.update(points.astype('<f8').tobytes())
    return dict(animation_sha256=animation.hexdigest(), evaluated_sha256=evaluated.hexdigest(), frames=COUNT)


def support_audit(folder):
    """Minimum-point contact only: not full contact of both soles or balance."""
    sc = bpy.context.scene
    pairs = support_pairs()
    report = dict(samples=(COUNT-1)*8+1, actors={}, limits=
        'Horizontal plane at the minimum evaluated sole point. Not full contact of both feet or physical balance.')
    for pair in pairs:
        report['actors'][pair['tag']] = dict(sole_vertices=len(pair['sole']), min_gap=1e10, max_gap=-1e10,
            max_sole_drift=0., min_xy_margin=1e10, foot_min_gap_ranges={s: [1e10, -1e10] for s in pair['feet']})
    for i in range(report['samples']):
        f = i/8
        sc.frame_set(int(f), subframe=f%1)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        for pair in pairs:
            points, _ = evaluated_vertices(pair['mesh'], graph)
            platform = pair['platform']
            corners = np.array([tuple(platform.matrix_world @ Vector(v)) for v in platform.bound_box])
            top = float(corners[:, 2].max())
            sole = points[pair['sole']]
            gap = float(sole[:, 2].min()-top)
            rec = report['actors'][pair['tag']]
            rec['min_gap'], rec['max_gap'] = min(rec['min_gap'], gap), max(rec['max_gap'], gap)
            rec['max_sole_drift'] = max(rec['max_sole_drift'], float(np.linalg.norm(sole-pair['reference'], axis=1).max()))
            rec['min_xy_margin'] = min(rec['min_xy_margin'], float(np.minimum(
                sole[:, :2]-corners[:, :2].min(axis=0), corners[:, :2].max(axis=0)-sole[:, :2]).min()))
            for side, indices in pair['feet'].items():
                foot_gap = float(points[indices, 2].min()-top)
                span = rec['foot_min_gap_ranges'][side]
                span[0], span[1] = min(span[0], foot_gap), max(span[1], foot_gap)
    # Existing animation/deformation thresholds in validate() remain unchanged.
    report['contact_precision'] = 2e-5
    report['pass'] = all(abs(r['min_gap']) <= 2e-5 and abs(r['max_gap']) <= 2e-5
        and r['max_sole_drift'] < .0002 and r['min_xy_margin'] > 0 for r in report['actors'].values())
    (folder/'support_contact.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['pass']:
        raise ValueError('Minimum-point support contact failed')
    print('SUPPORT_CONTACT', json.dumps(report), flush=True)
    return report


def fix_support(folder):
    """Complete trial2 by translating only the four platforms, never rebake motion."""
    source = OUT/'trial2'
    folder.mkdir(exist_ok=False)
    before_hashes = {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                     for name in ('scene.blend', 'character_overlap.mp4')}
    shutil.copy2(source/'character_overlap.mp4', folder/'baseline.mp4')
    bpy.ops.wm.open_mainfile(filepath=str(source/'scene.blend'))
    before = scene_motion_fingerprint()
    corrections = {}
    for pair in support_pairs():
        delta = pair['lowest']-pair['old_top']
        pair['platform'].location.z += delta
        corrections[pair['tag']] = dict(platform=pair['platform'].name, delta_z=delta,
            target_top=pair['lowest'], previous_top=pair['old_top'])
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
    after = scene_motion_fingerprint()
    report = dict(source='trial2', corrections=corrections, before=before, after=after,
                  motion_unchanged=before == after, baseline_hashes=before_hashes)
    report['baseline_unchanged'] = all(hashlib.sha256((source/n).read_bytes()).hexdigest() == h for n, h in before_hashes.items())
    report['baseline_copy_identical'] = hashlib.sha256((folder/'baseline.mp4').read_bytes()).hexdigest() == before_hashes['character_overlap.mp4']
    (folder/'support_fix.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not all(report[k] for k in ('motion_unchanged', 'baseline_unchanged', 'baseline_copy_identical')):
        raise ValueError('Preservation check failed')
    support_audit(folder)
    if not validate(folder)['technical_pass']:
        raise ValueError('Existing validation failed')
    # Exactly one preview frame before the separately requested animation render.
    sc = bpy.context.scene
    sc.frame_set(20)
    sc.render.filepath = str(folder/'support_key_f0020.png')
    bpy.ops.render.render(write_still=True)


def surface_audit(folder):
    """Triangle overlaps of the visible hook against skin; explicit weighted grip mask."""
    sc = bpy.context.scene
    report = {'frames': COUNT, 'cases': {}, 'checked_pairs': 0,
              'limits': 'Visible view-layer meshes, integer frames, triangle crossings only; not containment, cloth clearance or proof of valid grip.'}
    for case in ('control', 'follow'):
        meshes = [o for o in sc.objects if o.type == 'MESH' and o.name.startswith('0_'+case+'.')]
        rows = []
        def bvh(ob, exclude_grip=False):
            graph = bpy.context.evaluated_depsgraph_get()
            evaluated = ob.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                mesh.calc_loop_triangles()
                grip = set()
                if exclude_grip:
                    groups = {g.index: g.name.lower() for g in ob.vertex_groups}
                    for v in ob.data.vertices:
                        weight = sum(g.weight for g in v.groups if
                            ('wrist_r' in groups[g.group] or ('finger' in groups[g.group] and '_r' in groups[g.group])))
                        if weight > .5:
                            grip.add(v.index)
                tris = [tuple(t.vertices) for t in mesh.loop_triangles if not all(v in grip for v in t.vertices)]
                if not tris:
                    raise ValueError(f'Inconclusive surface audit: no tested triangles in {ob.name} at {sc.frame_current}')
                return BVHTree.FromPolygons([evaluated.matrix_world @ v.co for v in mesh.vertices], tris, all_triangles=True), len(grip)
            finally:
                evaluated.to_mesh_clear()
        for frame in range(COUNT):
            sc.frame_set(frame)
            bpy.context.view_layer.update()
            visible = visible_meshes(sc)
            weapons = [o for o in meshes if o in visible and 'righthook_model' in o.name]
            body_meshes = [o for o in meshes if o in visible and any(
                s in o.name for s in ('upper_body', 'lower_body', '.head', 'leftarm_model'))]
            if len(weapons) != 1 or not body_meshes:
                raise ValueError(f'Inconclusive surface audit: {case} frame {frame} needs one visible hook and body surfaces')
            weapon = weapons[0]
            hook, _ = bvh(weapon)
            row = {'frame': frame, 'pairs': {}, 'excluded_grip_vertices': {}}
            for ob in body_meshes:
                tree, grip = bvh(ob, True)
                row['pairs'][ob.name] = len(hook.overlap(tree))
                row['excluded_grip_vertices'][ob.name] = grip
                report['checked_pairs'] += 1
            rows.append(row)
        report['cases'][case] = rows
    report['max_non_grip_crossings'] = max(sum(r['pairs'].values()) for rows in report['cases'].values() for r in rows)
    (folder/'surfaces.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Surface crossings excluding weighted grip:', report['max_non_grip_crossings'], flush=True)
    return report


def movie_review(folder, ffmpeg):
    movie = folder/'character_overlap.mp4'
    run = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(movie), '-an', '-pix_fmt', 'rgb24',
                          '-f', 'rawvideo', '-'], capture_output=True, check=True)
    raw = np.frombuffer(run.stdout, np.uint8).reshape((-1, 540, 960, 3))
    if len(raw) != COUNT:
        raise ValueError('Incorrect decoded frame count')
    source = subprocess.run([str(ffmpeg), '-v', 'error', '-framerate', str(FPS), '-i',
        str(folder/'frames/f%04d.png'), '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True, check=True)
    reference = np.frombuffer(source.stdout, np.uint8).reshape(raw.shape)
    errors = np.abs(raw.astype(np.int16)-reference.astype(np.int16)).mean(axis=(1, 2, 3))
    differences = np.abs(np.diff(raw.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    report = dict(frames=len(raw), fps=FPS, size=[960, 540], duration=len(raw)/FPS,
        sha256=hashlib.sha256(movie.read_bytes()).hexdigest(), max_encoding_mae=float(errors.max()),
        frame_changes=differences.tolist(), min_brightness=float(raw.mean(axis=(1, 2, 3)).min()),
        visual_review='Contact sheets require human/model inspection; numerical checks alone are insufficient.')
    review = folder/'review'
    review.mkdir(exist_ok=True)
    # Assemble independent decoded frame copies. Do not rely on a temporal tile filter.
    scaled = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(movie), '-vf', 'scale=640:360',
        '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True, check=True)
    small = np.frombuffer(scaled.stdout, np.uint8).reshape((-1, 360, 640, 3))
    for page in range(COUNT//12):
        sheet = np.zeros((1440, 1920, 3), dtype=np.uint8)
        for cell in range(12):
            y, x = cell//3*360, cell%3*640
            sheet[y:y+360, x:x+640] = small[page*12+cell]
        def chunk(tag, data):
            return struct.pack('!I', len(data))+tag+data+struct.pack('!I', zlib.crc32(tag+data))
        scanlines = b''.join(b'\0'+row.tobytes() for row in sheet)
        png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!2I5B', 1920, 1440, 8, 2, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(scanlines))+chunk(b'IEND', b'')
        (review/f'all_frames_{page+1:02d}.png').write_bytes(png)
    (folder/'movie_review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['max_encoding_mae'] > 4 or report['min_brightness'] < 10:
        raise ValueError('Decoded movie quality check failed')
    print('Movie decoded:', COUNT, 'frames; max encoding MAE', report['max_encoding_mae'], flush=True)


def validate(folder):
    sc = bpy.context.scene
    arms = [o for o in sc.objects if o.get('study_main')]
    sc.frame_set(0)
    bpy.context.view_layer.update()
    base = {a.name: {b.name: b.matrix.copy() for b in a.pose.bones} for a in arms}
    roots = {a.name: a.parent.matrix_world.copy() for a in arms}
    local = {a.name: {b.name: b.matrix_basis.copy() for b in a.pose.bones} for a in arms}
    report = dict(samples=(COUNT-1)*8+1, protected_bone_error=0., root_error=0.,
                  unrelated_local_error=0., expected_rotation_error_deg=0.,
                  max_step_deg=0., min_margin=1., max_edge_ratio=1., max_sole_drift=0.,
                  meshes={}, selected_key_frames=[0, 16, 20, 25, 35, 41, 47, 69, 78, 83])
    def error(a, b):
        return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))
    meshes = [o for o in sc.objects if o.type == 'MESH' and not o.hide_render and o.name.startswith('0_follow.')]
    geometry = {}
    graph = bpy.context.evaluated_depsgraph_get()
    for ob in meshes:
        points, edges = evaluated_vertices(ob, graph)
        lengths = np.linalg.norm(points[edges[:, 0]]-points[edges[:, 1]], axis=1)
        sole = np.where(points[:, 2] < points[:, 2].min()+.045)[0] if 'lower_body' in ob.name else np.array([], dtype=int)
        geometry[ob.name] = (points, edges, lengths, sole)
        report['meshes'][ob.name] = dict(vertices=len(points), edge_ratio=1., sole_vertices=len(sole))
        if len(sole):
            top = (sc.objects['Platform_0_1'].matrix_world @ Vector((0, 0, .5))).z
            report['initial_lowest_sole_to_platform'] = float(points[sole, 2].min()-top)
    # Only already-coincident vertices define a measurable mesh junction.
    head_name = next(n for n in geometry if n.endswith('pudge.vmdl_c.head'))
    upper_name = next(n for n in geometry if n.endswith('pudge.vmdl_c.upper_body'))
    distance = np.linalg.norm(geometry[head_name][0][:, None]-geometry[upper_name][0][None, :], axis=2)
    junction = np.where(distance < .005)
    report['head_body_junction'] = dict(baseline_pairs=len(junction[0]), max_gap=0., max_gap_change=0.)
    last = {}
    for i in range(report['samples']):
        f = i/8
        sc.frame_set(int(f), subframe=f%1)
        bpy.context.view_layer.update()
        for a in arms:
            moved = {'spine1', *[b.name for b in a.pose.bones['spine1'].children_recursive]}
            for b in a.pose.bones:
                if b.name not in moved:
                    report['protected_bone_error'] = max(report['protected_bone_error'], error(b.matrix, base[a.name][b.name]))
                if b.name not in [n for n, _ in SPINE_SHARES]+['neck1', 'head']:
                    report['unrelated_local_error'] = max(report['unrelated_local_error'], error(b.matrix_basis, local[a.name][b.name]))
            report['root_error'] = max(report['root_error'], error(a.parent.matrix_world, roots[a.name]))
            # Evaluate magnitude of the persisted head rotation, independently of authored keys.
            q = (a.pose.bones['head'].matrix.to_quaternion() @ base[a.name]['head'].to_quaternion().inverted())
            actual = math.degrees(q.angle)
            expected = abs(math.degrees(head(f/FPS) if 'follow' in a['study_main'] else body(f/FPS)))
            report['expected_rotation_error_deg'] = max(report['expected_rotation_error_deg'], abs(actual-expected))
            if a.name in last:
                report['max_step_deg'] = max(report['max_step_deg'], math.degrees(q.rotation_difference(last[a.name]).angle))
            last[a.name] = q
        if i % 8 == 0:
            graph = bpy.context.evaluated_depsgraph_get()
            current_geometry = {}
            for ob in meshes:
                points, edges = evaluated_vertices(ob, graph)
                current_geometry[ob.name] = points
                original, _, lengths, sole = geometry[ob.name]
                new = np.linalg.norm(points[edges[:, 0]]-points[edges[:, 1]], axis=1)
                good = lengths > 1e-5
                ratio = float(np.maximum(new[good]/lengths[good], lengths[good]/np.maximum(new[good], 1e-9)).max())
                if ratio > report['meshes'][ob.name]['edge_ratio']:
                    index = np.where(good)[0][np.argmax(np.maximum(new[good]/lengths[good], lengths[good]/np.maximum(new[good], 1e-9)))]
                    report['meshes'][ob.name]['worst_edge'] = dict(frame=f, vertices=edges[index].tolist(),
                        baseline_length=float(lengths[index]), length=float(new[index]),
                        baseline_points=original[edges[index]].tolist(), points=points[edges[index]].tolist())
                report['meshes'][ob.name]['edge_ratio'] = max(report['meshes'][ob.name]['edge_ratio'], ratio)
                report['max_edge_ratio'] = max(report['max_edge_ratio'], ratio)
                if len(sole):
                    report['max_sole_drift'] = max(report['max_sole_drift'], float(np.linalg.norm(points[sole]-original[sole], axis=1).max()))
            if len(junction[0]):
                gap = np.linalg.norm(current_geometry[head_name][junction[0]]-current_geometry[upper_name][junction[1]], axis=1)
                seam = report['head_body_junction']
                seam['max_gap'] = max(seam['max_gap'], float(gap.max()))
                seam['max_gap_change'] = max(seam['max_gap_change'], float(np.abs(gap-distance[junction]).max()))
            for ob in sc.objects:
                if ob.type == 'MESH' and not ob.hide_render and not ob.name.startswith('Platform'):
                    for v in ob.bound_box:
                        uv = world_to_camera_view(sc, sc.camera, ob.matrix_world @ Vector(v))
                        report['min_margin'] = min(report['min_margin'], uv.x, 1-uv.x, uv.y, 1-uv.y)
    times = np.arange(COUNT*32)/(FPS*32)
    bb = np.array([body(t) for t in times])
    hh = np.array([head(t) for t in times])
    report['response'] = dict(body_first_peak_s=float(times[np.argmin(bb)]), head_peak_s=float(times[np.argmin(hh)]),
        max_relative_deg=float(np.degrees(np.max(np.abs(hh-bb)))), head_peak_deg=float(np.degrees(hh.min())),
        head_return_overshoot_deg=float(np.degrees(hh.max())), final_head_deg=float(np.degrees(head((COUNT-1)/FPS))))
    report['technical_pass'] = (report['protected_bone_error'] < 2e-5 and report['root_error'] < 2e-5
        and report['unrelated_local_error'] < 2e-5 and report['max_sole_drift'] < .0002
        and report['max_edge_ratio'] < 1.35 and report['expected_rotation_error_deg'] < .08
        and report['min_margin'] > .015)
    report['limits'] = 'Edge distortion and selected soles are not full collision/cloth certification. Inspect every movie frame and extreme poses.'
    (folder/'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    return report


def render_keys(folder):
    sc = bpy.context.scene
    (folder/'keys').mkdir(exist_ok=True)
    for frame in (0, 16, 20, 25, 35, 41, 47, 78, 83):
        sc.frame_set(frame)
        sc.render.filepath = str(folder/'keys'/f'f{frame:04d}.png')
        bpy.ops.render.render(write_still=True)
    # The two views at larger scale: visible surfaces, seams, grip and hook.
    saved = sc.camera.location.copy(), sc.camera.data.ortho_scale
    sc.render.resolution_x = sc.render.resolution_y = 540
    for row in (0, 1):
        sc.camera.location.x = 3.65
        sc.camera.location.z = 7.45 if row == 0 else 2.15
        sc.camera.data.ortho_scale = 6.4
        for frame in (0, 20, 25, 41, 47):
            sc.frame_set(frame)
            sc.render.filepath = str(folder/'keys'/f'detail_{row}_{frame:04d}.png')
            bpy.ops.render.render(write_still=True)
    sc.camera.location, sc.camera.data.ortho_scale = saved
    sc.render.resolution_x, sc.render.resolution_y = 960, 540


def render_movie(folder, ffmpeg):
    sc = bpy.context.scene
    frames = folder/'frames'
    frames.mkdir()
    sc.render.filepath = str(frames/'f')
    bpy.ops.render.render(animation=True)
    subprocess.run([str(ffmpeg), '-v', 'error', '-framerate', str(FPS), '-start_number', '0',
                    '-i', str(frames/'f%04d.png'), '-frames:v', str(COUNT), '-an', '-c:v', 'libx264',
                    '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                    str(folder/'character_overlap.mp4')], check=True)


def main():
    global AMPLITUDE, SPINE_SHARES, RESPONSE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['inspect', 'build', 'keys', 'render', 'validate', 'surfaces', 'review', 'fix-support', 'support-contact'], default='inspect')
    parser.add_argument('--trial', choices=['trial1', 'trial2'], default='trial1')
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--support-fixed', action='store_true', help='Use the completed trial2 in support_fixed')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.trial == 'trial2' or args.support_fixed or args.mode == 'fix-support':
        AMPLITUDE = 4.
        SPINE_SHARES = [('spine1', .25), ('spine2', .35), ('spine3', .4)]
        RESPONSE = response_table()
    if args.mode == 'inspect':
        inspect()
        return
    folder = OUT/('support_fixed' if args.support_fixed or args.mode == 'fix-support' else args.trial)
    if args.mode == 'fix-support':
        fix_support(folder)
        return
    if args.support_fixed and args.mode == 'build':
        raise ValueError('Use fix-support to preserve trial2 animation')
    if args.mode == 'review':
        if not args.ffmpeg:
            raise ValueError('--ffmpeg required')
        movie_review(folder, args.ffmpeg)
        return
    if args.mode == 'build':
        folder.mkdir(parents=True, exist_ok=False)
        build(folder)
    bpy.ops.wm.open_mainfile(filepath=str(folder/'scene.blend'))
    if args.mode == 'support-contact':
        support_audit(folder)
        return
    if args.mode == 'surfaces':
        surface_audit(folder)
        return
    report = validate(folder)
    if args.mode == 'keys':
        render_keys(folder)
    elif args.mode == 'render':
        if args.support_fixed:
            support_audit(folder)
        if not report['technical_pass']:
            raise ValueError('Technical validation failed; movie blocked')
        if surface_audit(folder)['max_non_grip_crossings']:
            raise ValueError('Weapon crossings found; movie blocked')
        if not args.ffmpeg:
            raise ValueError('--ffmpeg required')
        render_movie(folder, args.ffmpeg)
    elif not report['technical_pass']:
        raise ValueError('Technical validation failed; see validation.json')


def inspect():
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for source in SOURCES:
        path = ROOT / source
        bpy.ops.wm.open_mainfile(filepath=str(path))
        sc = bpy.context.scene
        sc.frame_set(0)
        report = dict(source=source, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      frames=[sc.frame_start, sc.frame_end], objects=[])
        for ob in sc.objects:
            record = dict(name=ob.name, type=ob.type, parent=ob.parent.name if ob.parent else None,
                          hidden=ob.hide_render, position=list(ob.matrix_world.translation),
                          dimensions=list(ob.dimensions))
            if ob.type == 'ARMATURE':
                record['bones'] = [dict(name=b.name, parent=b.parent.name if b.parent else None,
                    head=list(ob.matrix_world @ b.head), tail=list(ob.matrix_world @ b.tail),
                    constraints=[c.type for c in b.constraints if not c.mute]) for b in ob.pose.bones]
            if ob.animation_data:
                ad = ob.animation_data
                record['action'] = ad.action.name if ad.action else None
                record['nla'] = [t.name for t in ad.nla_tracks]
            if ob.type == 'MESH':
                record['modifiers'] = [(m.type, getattr(getattr(m, 'object', None), 'name', None)) for m in ob.modifiers]
                record['vertices'] = len(ob.data.vertices)
            report['objects'].append(record)
        reports.append(report)
    (OUT / 'inventory.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print('Inventory saved', flush=True)


if __name__ == '__main__':
    main()
