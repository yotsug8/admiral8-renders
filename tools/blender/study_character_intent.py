"""Authored character pose cards: withdrawal versus commitment, not an action library.

Reuses the frozen Pudge study, support IK, basis conversion and mesh snapshots.
Optional authored transition study; not a claim of physical balance or a prop grasp.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contact_metrics import resolve
from contact_reaction import _rig, _solve_leg
from study_character_overlap import freeze, evaluated_vertices, material

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'_game/study/foundations/reach_witness/point_A.blend'
OUT = ROOT/'_game/study/character_intent'
# Explicit authored contrasts. Fractions are relative to this character's height.
POSES = {
    'neutral': dict(shift=(0, 0, 0), pitch=0, shoulder=(0, 0, 0), elbow=(0, 0, 0)),
    'withdraw': dict(shift=(-.065, .015, -.025), pitch=-8, shoulder=(0, 15, 12), elbow=(0, -20, 0)),
    'commit': dict(shift=(.04, -.01, -.025), pitch=10, shoulder=(0, -15, -12), elbow=(0, -20, 0)),
}
FPS, COUNT = 30, 144


def motion_pose(frame):
    """Withdraw, pause, approach: the torso leads and the free arm follows.

    Independent head turning is excluded: the source head/body junction folds
    under modest rotations. Keeping its relative pose is a limitation, not a fix.
    """
    def ease(a, b):
        t = min(1., max(0., (frame-a)/(b-a)))
        return t*t*t*(10+t*(-15+6*t))
    timings = {'pitch': ((15, 39), (65, 96)),
               'shift': ((15, 39), (65, 96)), 'shoulder': ((23, 44), (74, 105)),
               'elbow': ((23, 44), (74, 105))}
    result = {}
    for key, (first, second) in timings.items():
        a, b, c = (np.asarray(POSES[name][key], dtype=float) for name in ('neutral', 'withdraw', 'commit'))
        value = a+(b-a)*ease(*first)+(c-b)*ease(*second)
        result[key] = float(value) if value.ndim == 0 else tuple(value)
    return result


def inspect_pose(sc, arm, meshes, baseline, foot_ids, sole_ids, height, cameras):
    current = surfaces(meshes)
    row = compare(meshes, baseline, current, foot_ids, sole_ids, height)
    row['floor_min'] = float(min(p[:, 2].min() for p in current.values()))
    margin = 1.
    # Project a vertex array once per camera rather than thousands of Python calls.
    points = np.concatenate(list(current.values()))
    for cam in cameras:
        inverse = np.array(cam.matrix_world.inverted())
        local = points@inverse[:3, :3].T + inverse[:3, 3]
        if np.any(local[:, 2] >= 0):
            raise ValueError('Behind camera')
        aspect = sc.render.resolution_x/sc.render.resolution_y
        uv = local[:, :2]/np.array([cam.data.ortho_scale, cam.data.ortho_scale/aspect]) + .5
        margin = min(margin, float(uv.min()), float((1-uv).min()))
    row['camera_margin'] = margin
    row['passed'] = row['skin_pass'] and row['support_pass'] and row['floor_min'] > -height*.001 and margin > .025
    return row


def surfaces(meshes):
    dg = bpy.context.evaluated_depsgraph_get()
    return {o.name: evaluated_vertices(o, dg)[0] for o in meshes}


def apply_pose(arm, base, basis, pelvis, legs, height, spec):
    for b in arm.pose.bones:
        b.matrix_basis = basis[b.name]
    bpy.context.view_layer.update()
    desired = {n: m.copy() for n, m in base.items()}
    delta = Vector(spec['shift'])*height
    pb = arm.pose.bones[pelvis]
    for b in [pb, *pb.children_recursive]:
        desired[b.name].translation += delta
    selected = {pelvis}
    for leg in legs:
        _solve_leg(base, desired, leg, delta, None, Vector((1, 0, 0)))
        selected.update(leg)
    # Share the bend along the back rather than hinging the entire torso at one joint.
    for name, fraction in [('spine1', .5), ('spine2', .3), ('spine3', .2)]:
        spine = arm.pose.bones[name]
        pivot = desired[name].translation
        transform = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(spec['pitch']*fraction), 4, 'Y') @ Matrix.Translation(-pivot)
        for b in [spine, *spine.children_recursive]:
            desired[b.name] = transform @ desired[b.name]
        selected.add(name)
    # Free gesture: the wrist follows the arm rather than a fictitious contact.
    # Rotate each subtree rigidly; keep the shoulder/elbow attachment positions.
    for name, angles in [('bicep_L', spec['shoulder']), ('elbow_L', spec['elbow'])]:
        bone = arm.pose.bones[name]
        pivot = desired[name].translation
        rotation = Euler(tuple(math.radians(a) for a in angles)).to_matrix().to_4x4()
        transform = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
        for b in [bone, *bone.children_recursive]:
            desired[b.name] = transform @ desired[b.name]
        selected.add(name)
    inv = arm.matrix_world.inverted()
    for b in sorted((arm.pose.bones[n] for n in selected), key=lambda b: len(b.parent_recursive)):
        b.matrix = inv @ desired[b.name]
        bpy.context.view_layer.update()
    errors = {n: (arm.matrix_world@arm.pose.bones[n].matrix).translation-desired[n].translation
              for n in selected}
    return max(v.length for v in errors.values())


def compare(meshes, baseline, current, foot_ids, sole_ids, height):
    rows = []
    for ob in meshes:
        p, q = baseline[ob.name], current[ob.name]
        if p.shape != q.shape or not np.isfinite(q).all():
            raise ValueError('Topology or finite-point check failed')
        edges = np.array([tuple(e.vertices) for e in ob.data.edges], dtype=int)
        if not len(edges):
            continue
        before = np.linalg.norm(p[edges[:, 0]]-p[edges[:, 1]], axis=1)
        after = np.linalg.norm(q[edges[:, 0]]-q[edges[:, 1]], axis=1)
        ratio = after/np.maximum(before, 1e-10)
        ob.data.calc_loop_triangles()
        triangles = np.array([tuple(t.vertices) for t in ob.data.loop_triangles], dtype=int)
        def area(v):
            a,b,c = (v[triangles[:, i]] for i in range(3))
            return np.linalg.norm(np.cross(b-a,c-a), axis=1)*.5
        a0, a1 = area(p), area(q)
        valid = a0 > height*height*1e-9
        contracted = valid & (a1/np.maximum(a0, 1e-15) < .2)
        stretched = (ratio > 1.8) & (after-before > height*.01)
        rows.append(dict(mesh=ob.name, max_edge_ratio=float(ratio.max()),
                         stretched=int(stretched.sum()), contracted=int(contracted.sum())))
    foot_drift = max(float(np.linalg.norm(current[name][ids]-baseline[name][ids], axis=1).max())
                     for name, ids in foot_ids.items())
    soles = {}
    for side, selections in sole_ids.items():
        p = np.concatenate([baseline[name][ids] for name, ids in selections.items()])
        q = np.concatenate([current[name][ids] for name, ids in selections.items()])
        soles[side] = dict(vertices=len(p), drift=float(np.linalg.norm(q-p, axis=1).max()),
                           floor_min=float(q[:, 2].min()))
    return dict(meshes=rows, lower_foot_surface_drift=foot_drift, soles=soles,
                skin_pass=not any(r['stretched'] or r['contracted'] for r in rows),
                support_pass=all(s['drift'] < height*.001 and abs(s['floor_min']) < height*.001
                                 for s in soles.values()))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--motion', action='store_true', help='Bake, reopen, validate, then render the short body study')
    args = ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    out = args.out.resolve()
    if not out.is_relative_to(OUT.resolve()) or out == OUT.resolve():
        raise ValueError('Output must be a fresh child of _game/study/character_intent')
    out.mkdir(parents=True, exist_ok=False)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    sc = bpy.context.scene
    root, arm, members = resolve('pudge', list(sc.objects))
    members = [o for o in members if 'blob' not in o.name]
    for ob in list(sc.objects):
        if ob not in members:
            bpy.data.objects.remove(ob, do_unlink=True)
    freeze(root, arm, members)
    for ob in members:
        if ob.type == 'MESH' and any(s in ob.name.lower() for s in ('weapon','hook','hitbox')):
            ob.hide_render = True
    meshes = [o for o in members if o.type == 'MESH' and not o.hide_render]
    if not meshes:
        raise ValueError('No visible character meshes')
    initial = surfaces(meshes)
    points = np.concatenate(list(initial.values()))
    low, high = points.min(axis=0), points.max(axis=0)
    height = float(high[2]-low[2])
    if height <= 0:
        raise ValueError('Degenerate actor height')
    root.location.z -= float(low[2])
    bpy.context.view_layer.update()
    baseline = surfaces(meshes)
    base = {b.name: arm.matrix_world@b.matrix for b in arm.pose.bones}
    basis = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
    pelvis, legs, _, _ = _rig(arm, ())
    foot_names = {b.name for leg in legs for b in [arm.pose.bones[leg[2]], *arm.pose.bones[leg[2]].children_recursive]}
    foot_ids = {}
    for ob in meshes:
        groups = {g.index for g in ob.vertex_groups if g.name in foot_names}
        ids = [v.index for v in ob.data.vertices
               if sum(g.weight for g in v.groups if g.group in groups) > .95
               and baseline[ob.name][v.index, 2] < height*.10]
        if ids:
            foot_ids[ob.name] = np.array(ids, dtype=int)
    if not foot_ids:
        raise ValueError('Empty actual-foot selection')
    # Separate the planted contact band from the deforming upper foot.
    # Keep the old broad measurement in the report; do not reinterpret it as slip.
    sole_ids = {}
    for leg in legs:
        ankle = arm.pose.bones[leg[2]]
        names = {b.name for b in [ankle, *ankle.children_recursive]}
        candidates = {}
        for ob in meshes:
            groups = {g.index for g in ob.vertex_groups if g.name in names}
            ids = [v.index for v in ob.data.vertices
                   if sum(g.weight for g in v.groups if g.group in groups) > .95]
            if ids:
                candidates[ob.name] = np.array(ids, dtype=int)
        if not candidates:
            raise ValueError(f'No surface for {ankle.name}')
        z = min(baseline[n][ids, 2].min() for n, ids in candidates.items())
        band = {n: ids[baseline[n][ids, 2] <= z + height*.003] for n, ids in candidates.items()}
        band = {n: ids for n, ids in band.items() if len(ids)}
        if sum(len(ids) for ids in band.values()) < 3:
            raise ValueError(f'Insufficient sole contacts for {ankle.name}')
        sole_ids[ankle.name] = band
    # Match the established material view; these are geometry/acting cards.
    sc.render.engine = 'BLENDER_EEVEE'
    sc.eevee.taa_render_samples = 16
    sc.render.resolution_x, sc.render.resolution_y = 480, 480
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.film_transparent = False
    sc.view_settings.view_transform, sc.view_settings.look = 'Standard', 'None'
    sc.world = bpy.data.worlds.new('Intent studio')
    sc.world.use_nodes = True
    sc.world.node_tree.nodes['Background'].inputs[0].default_value = (.065,.08,.095,1)
    sc.world.node_tree.nodes['Background'].inputs[1].default_value = .5
    bpy.ops.mesh.primitive_plane_add(size=height*20, location=(0,0,-.005))
    floor=bpy.context.object
    floor.data.materials.append(material('Intent floor',(.14,.17,.19)))
    cameras = []
    for name, direction in [('front',(8,-3,4)),('side',(1,-9,3)),('hand_side',(1,9,3))]:
        cam=bpy.data.objects.new(name,bpy.data.cameras.new(name));sc.collection.objects.link(cam)
        target=Vector((0,.5,height*.5))
        cam.location=target+Vector(direction)*height
        cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type,cam.data.ortho_scale='ORTHO',height*1.65
        cameras.append(cam)
    for name,pos,energy in [('Key',(4,-3,8),1200),('Fill',(-2,5,5),650)]:
        ob=bpy.data.objects.new(name,bpy.data.lights.new(name,'AREA'));sc.collection.objects.link(ob)
        ob.location=pos;ob.data.energy=energy;ob.data.size=5
        ob.rotation_euler=(Vector((0,0,height*.5))-ob.location).to_track_quat('-Z','Y').to_euler()
    report=dict(source_sha256=source_hash, height=height, poses={},
                limits='Three static poses only. No motion, full self-collision, physical COM, eyes or prop grasp validation.')
    for name,spec in POSES.items():
        error=apply_pose(arm,base,basis,pelvis,legs,height,spec)
        row=inspect_pose(sc,arm,meshes,baseline,foot_ids,sole_ids,height,cameras)
        row['target_error']=error
        row['passed']=row['passed'] and error<height*.0001
        report['poses'][name]=row
        # Diagnostic stills are allowed on failure; they never mark a pass.
        for cam in cameras:
            sc.camera=cam;sc.render.filepath=str(out/f'{name}_{cam.name}.png')
            bpy.ops.render.render(write_still=True)
    report['source_unchanged']=hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash
    report['passed']=report['source_unchanged'] and all(p['passed'] for p in report['poses'].values())
    (out/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    if not report['source_unchanged']:
        raise ValueError('Source changed')
    if not report['passed']:
        raise ValueError('Pose checks failed; diagnostic images are not accepted results')
    if args.motion:
        names = {pelvis, 'spine1', 'spine2', 'spine3', 'bicep_L', 'elbow_L'}
        names.update(n for leg in legs for n in leg)
        driven = [arm.pose.bones[n] for n in sorted(names)]
        for bone in driven:
            bone.rotation_mode = 'QUATERNION'
        last = {}
        for frame in range(COUNT):
            apply_pose(arm,base,basis,pelvis,legs,height,motion_pose(frame))
            for bone in driven:
                if bone.name in last and bone.rotation_quaternion.dot(last[bone.name]) < 0:
                    bone.rotation_quaternion.negate()
                last[bone.name] = bone.rotation_quaternion.copy()
                for prop in ('location', 'rotation_quaternion', 'scale'):
                    bone.keyframe_insert(prop, frame=frame)
        action = arm.animation_data.action
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
        sc.frame_start, sc.frame_end, sc.render.fps, sc.render.fps_base = 0, COUNT-1, FPS, 1.
        sc.frame_set(0)
        mesh_names, arm_name, camera_names = [o.name for o in meshes], arm.name, [c.name for c in cameras]
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'), use_scripts=False)
        sc, arm = bpy.context.scene, bpy.data.objects[arm_name]
        meshes, cameras = [bpy.data.objects[n] for n in mesh_names], [bpy.data.objects[n] for n in camera_names]
        checks = []
        for sample in range((COUNT-1)*4+1):
            frame = sample/4
            sc.frame_set(int(frame), subframe=frame % 1)
            bpy.context.view_layer.update()
            row = inspect_pose(sc,arm,meshes,baseline,foot_ids,sole_ids,height,cameras)
            row['frame'] = frame
            checks.append(row)
        result = dict(fps=FPS, frames=COUNT, samples=len(checks), passed=all(r['passed'] for r in checks),
                      scene_sha256=hashlib.sha256((out/'scene.blend').read_bytes()).hexdigest(), checks=checks,
                      limits='Pose skin/contact/framing checks only. No full collisions, balance, facial acting or audio.')
        (out/'motion_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        if not result['passed']:
            raise ValueError('Reopened transition failed before rendering')
        for cam in (cameras[0], cameras[2]):
            destination = out/('motion_'+cam.name)
            destination.mkdir(exist_ok=False)
            sc.camera=cam
            sc.render.filepath=str(destination/'f_')
            bpy.ops.render.render(animation=True)


if __name__ == '__main__':
    main()
