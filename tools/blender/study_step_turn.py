"""Three planted steps turn a rigid mannequin 90 degrees; CPU previews.

Blender --python-exit-code 2 -P tools/blender/study_step_turn.py --
  --out _game/study/step_turn/run01 --mode build|verify|probes|render
Build requires a new directory; verify/probes reopen its baked scene.
No external assets, handlers or new rig framework.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

# Imports must not create caches alongside the shared source files.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from bpy_extras.object_utils import world_to_camera_view
import study_lift as lift
import study_foot_roll as roll
import study_prop_turn as common
from study_start_stop import curve
from study_step_touch import LINKS, mesh_vertices
from study_pointing import segment_distance

FPS, COUNT, REST = 30, 144, 4.25
CAMERAS = {'profile': (4.5, 6.5, 3.0)}
PROBES = (0, 29, 69, 139)
# World-space sole origins and clockwise headings, independent of the body.
INITIAL = {'L': (-.18, 0., 0.), 'R': (.18, 0., 0.)}
STEPS = (
    ('R', .60, 1.30, (.30, .12, -45.)),
    ('L', 1.85, 2.75, (.60, .54, -90.)),
    ('R', 3.20, 3.85, (.60, .18, -90.)),
)
ANGLE_KEYS = {
    'head': ((0., 0.), (.15, 0.), (.95, -55.), (1.80, -90.)),
    'chest': ((0., 0.), (.35, 0.), (1.30, -40.), (3.05, -90.)),
    'pelvis': ((0., 0.), (.60, 0.), (1.30, -35.), (1.85, -35.),
               (2.75, -75.), (3.2, -75.), (3.85, -90.)),
}


def yaw(degrees):
    return Quaternion((0, 0, 1), math.radians(degrees))


def placement(spec, height=0.):
    x, y, degrees = spec
    return Matrix.LocRotScale(Vector((x, y, height)), yaw(degrees), Vector((1, 1, 1)))


def stance(side, t):
    """A contact target exists only outside that foot's open swing interval."""
    spec = INITIAL[side]
    for moving, off, land, target in STEPS:
        if moving != side:
            continue
        if off < t < land:
            return None
        if t >= land:
            spec = target
    return spec


def foot_frames(side, t):
    spec = INITIAL[side]
    for moving, off, land, target in STEPS:
        if moving != side:
            continue
        if off < t < land:
            u = (t-off)/(land-off)
            # Lift first; translation and yaw finish before the sole lands.
            travel = lift.smooth((u-.08)/.84)
            rotate = lift.smooth((u-.12)/.76)
            x = spec[0]+(target[0]-spec[0])*travel
            y = spec[1]+(target[1]-spec[1])*travel
            if side == 'L':
                y += .12*math.sin(math.pi*travel)**2
            rear = placement((x, y, spec[2]+(target[2]-spec[2])*rotate),
                             .13*math.sin(math.pi*u)**2)
            break
        if t >= land:
            spec = target
    else:
        rear = placement(spec)
    toe = rear @ Matrix.Translation((0, .14, 0))
    return rear, toe


def pose(t):
    px = curve(t, ((0, 0), (.55, -.15), (1.30, -.15), (1.80, .30),
                   (2.75, .30), (3.15, .62), (3.85, .62), (REST, .52)))
    py = curve(t, ((0, -.035), (.55, 0), (1.30, 0), (1.80, .14),
                   (2.75, .14), (3.15, .51), (3.85, .51), (REST, .36)))
    pz = curve(t, ((0, .90), (.55, .82), (1.0, .845), (1.30, .82),
                   (1.80, .82), (2.30, .845), (2.75, .82),
                   (3.15, .82), (3.50, .845), (3.85, .82), (REST, .90)))
    rotations = {n: yaw(curve(t, keys)) for n, keys in ANGLE_KEYS.items()}
    pelvis = Vector((px, py, pz))
    lean = .025*lift.smooth(t/.55)*(1-lift.smooth((t-3.85)/.4))
    neck = pelvis+rotations['chest']@Vector((0, .5*math.sin(lean), .5*math.cos(lean)))
    head = neck+Vector((0, 0, .19))
    p = {'pelvis': pelvis, 'neck': neck, 'head': head,
         'Nose': head+rotations['head']@Vector((0, .145, 0))}
    for side, sign in (('L', -1), ('R', 1)):
        rear, _ = foot_frames(side, t)
        ankle = rear@Vector((0, -.075, .10))
        hip = pelvis+rotations['pelvis']@Vector((sign*.15, 0, 0))
        # Blend knee direction between the fixed foot and pelvis; no pole flips.
        forward = (rear.to_quaternion()@Vector((0, 1, 0))+
                   rotations['pelvis']@Vector((0, 1, 0))).normalized()
        knee = lift.solve(hip, ankle, .46, .46, forward)
        shoulder = neck+rotations['chest']@Vector((sign*.23, 0, 0))
        hand = pelvis+rotations['chest']@Vector((sign*.43, .07, -.22))
        elbow = lift.solve(shoulder, hand, .44, .42,
                           rotations['chest']@Vector((sign, -.15, .12)))
        for name, value in (('hip', hip), ('knee', knee), ('ankle', ankle),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)):
            p[side+'_'+name] = value
    return p


def cpu_settings(sc):
    sc.render.engine, sc.cycles.device, sc.cycles.samples = 'CYCLES', 'CPU', 8
    sc.cycles.use_denoising = False
    sc.cycles.use_adaptive_sampling = False
    sc.render.resolution_x, sc.render.resolution_y = 320, 320
    sc.render.resolution_percentage = 100
    sc.render.threads_mode, sc.render.threads = 'FIXED', 2
    sc.render.use_persistent_data = False


def setup():
    # The existing builder supplies identical geometry, IK segments and dense bake.
    keys = ('pose', 'foot_frames', 'CAMERAS', 'COUNT')
    previous = {key: getattr(roll, key) for key in keys}
    try:
        roll.pose, roll.foot_frames, roll.CAMERAS, roll.COUNT = pose, foot_frames, CAMERAS, COUNT
        sc = roll.setup()
    finally:
        for key, value in previous.items():
            setattr(roll, key, value)
    cpu_settings(sc)
    camera = sc.camera
    camera.rotation_euler = (Vector((.23, .18, .86))-camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.ortho_scale = 2.35
    sc['study'] = 'step_turn'
    sc['limits'] = 'Rigid kinematics; pelvis projection is not physical COM; no skin or dynamics.'
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    bpy.context.preferences.filepaths.save_version = 0
    return sc


def heading(v):
    return math.degrees(math.atan2(-v.x, v.y))


def foot_separation(left, right):
    """Separating axes for the yaw-only bounding boxes of the complete feet."""
    gaps = [min(v.z for v in left)-max(v.z for v in right),
            min(v.z for v in right)-max(v.z for v in left)]
    for vertices in (left, right):
        # Known cuboid vertex ordering is unnecessary: use each horizontal edge.
        for a in vertices:
            for b in vertices:
                edge = b-a
                if abs(edge.z) < 1e-6 and edge.length > 1e-6:
                    axis = Vector((-edge.y, edge.x, 0)).normalized()
                    l, r = [v.dot(axis) for v in left], [v.dot(axis) for v in right]
                    gaps.append(max(min(l)-max(r), min(r)-max(l)))
    return max(gaps)


def validate():
    sc = bpy.context.scene
    geometry = {s+'_'+part: mesh_vertices(bpy.data.objects[s+'_'+part])
                for s in INITIAL for part in roll.PARTS}
    soles = {n: [v for v in vs if abs(v.z-min(p.z for p in vs)) < 1e-6]
             for n, vs in geometry.items()}
    if any(len(vs) != 4 for vs in soles.values()):
        raise ValueError('Expected four actual sole vertices per foot part')
    names = tuple(pose(0))
    r = dict(samples=(COUNT-1)*16+1, contact_drift=0., contact_speed=0.,
             min_floor=1., length_error=0., joint_error=0., hinge_error=0.,
             min_arm_clearance=1., min_leg_clearance=1., min_foot_separation=1.,
             min_support_pelvis_margin=1., hold_drift=0., camera_margin=1.,
             heading_error_deg=0., witnesses={}, double_airborne_samples=0)
    tracks, directions, previous_contacts = [], [], {}
    air = {s: [] for s in INITIAL}
    hold = None
    witness_indices = {round((a+b)/2*FPS*16): str(j+1)
                       for j, (_, a, b, _) in enumerate(STEPS)}
    # A complete foot bound: local x +/- .09, y [-.16,.24], z [0,.08].
    box = [Vector((x, y, z)) for x in (-.09, .09) for y in (-.16, .24) for z in (0, .08)]
    for i in range(r['samples']):
        frame, t = i/16, i/(FPS*16)
        sc.frame_set(int(frame), subframe=frame%1)
        bpy.context.view_layer.update()
        p = {n: bpy.data.objects[n].matrix_world.translation.copy() for n in names}
        rods = {}
        for n, (a, b) in LINKS.items():
            ob = bpy.data.objects[n]
            start, end = (ob.matrix_world@Vector((0, 0, z)) for z in (-.5, .5))
            rods[n] = start, end, ob['radius']
            r['length_error'] = max(r['length_error'], abs((end-start).length-ob['length']))
            r['joint_error'] = max(r['joint_error'], (start-p[a]).length, (end-p[b]).length)
            r['min_floor'] = min(r['min_floor'], start.z-ob['radius'], end.z-ob['radius'])
        for n in names:
            r['min_floor'] = min(r['min_floor'], p[n].z-bpy.data.objects[n]['radius'])
        r['length_error'] = max(r['length_error'], abs((p['head']-p['neck']).length-.19))
        angles = {'head': heading(p['Nose']-p['head']),
                  'chest': heading(Vector((-(p['R_shoulder']-p['L_shoulder']).y,
                                           (p['R_shoulder']-p['L_shoulder']).x, 0))),
                  'pelvis': heading(Vector((-(p['R_hip']-p['L_hip']).y,
                                            (p['R_hip']-p['L_hip']).x, 0)))}
        r['heading_error_deg'] = max(r['heading_error_deg'],
            max(abs(angles[n]-curve(t, keys)) for n, keys in ANGLE_KEYS.items()))
        directions.append(angles)
        surfaces, contacts, bounds, heights = {}, {}, {}, {}
        for side in INITIAL:
            rear, toe = (bpy.data.objects[side+'_'+n].matrix_world for n in ('rear', 'toe_root'))
            bounds[side] = [rear@v for v in box]
            r['joint_error'] = max(r['joint_error'], (p[side+'_ankle']-rear@Vector((0, -.075, .10))).length)
            r['hinge_error'] = max(r['hinge_error'], (rear@roll.BALL-toe@Vector((0, 0, .06))).length)
            spec = stance(side, t)
            for part, (center, _) in roll.PARTS.items():
                n = side+'_'+part
                ob = bpy.data.objects[n]
                surfaces[n] = [ob.matrix_world@v for v in soles[n]]
                r['min_floor'] = min(r['min_floor'], min((ob.matrix_world@v).z for v in geometry[n]))
                if spec is not None:
                    target = placement(spec)
                    offset = Vector(center)+Vector((0, .14 if part == 'toe' else 0, 0))
                    for j, (local, world) in enumerate(zip(soles[n], surfaces[n])):
                        key = (n, j, spec)
                        contacts[key] = world
                        r['contact_drift'] = max(r['contact_drift'], (world-target@(offset+local)).length)
                        if key in previous_contacts:
                            r['contact_speed'] = max(r['contact_speed'],
                                (world-previous_contacts[key]).length*FPS*16)
            heights[side] = min(v.z for part in roll.PARTS for v in surfaces[side+'_'+part])
            air[side].append(heights[side] > .0001)
            other = 'R' if side == 'L' else 'L'
            if spec is not None and stance(other, t) is None:
                local = rear.inverted()@p['pelvis']
                r['min_support_pelvis_margin'] = min(r['min_support_pelvis_margin'],
                                                     .09-abs(local.x), local.y+.16, .24-local.y)
        separation = foot_separation(bounds['L'], bounds['R'])
        if separation < r['min_foot_separation']:
            r['min_foot_separation'], r['min_foot_separation_time'] = separation, t
        if all(h > .0001 for h in heights.values()):
            r['double_airborne_samples'] += 1
        if i in witness_indices:
            r['witnesses'][witness_indices[i]] = dict(t=t, heights=heights, headings=angles)
        for n in ('L_upperarm', 'R_upperarm', 'L_forearm', 'R_forearm'):
            a, b, rad = rods[n]
            for other in ('torso', 'L_thigh', 'L_shin', 'R_thigh', 'R_shin'):
                c, d, rad2 = rods[other]
                r['min_arm_clearance'] = min(r['min_arm_clearance'], segment_distance(a, b, c, d)-rad-rad2)
        for left in ('L_thigh', 'L_shin'):
            for right in ('R_thigh', 'R_shin'):
                a, b, rad = rods[left]
                c, d, rad2 = rods[right]
                r['min_leg_clearance'] = min(r['min_leg_clearance'], segment_distance(a, b, c, d)-rad-rad2)
        current = np.array([tuple(p[n]) for n in names]+[tuple(v) for n in geometry for v in surfaces[n]])
        tracks.append(current)
        if t >= REST:
            if hold is None:
                hold = current.copy()
            r['hold_drift'] = max(r['hold_drift'], float(np.linalg.norm(current-hold, axis=1).max()))
        previous_contacts = contacts
        # Bound boxes at every subframe, not just at rendered frames.
        for ob in sc.objects:
            if ob.type == 'MESH' and ob.name != 'Floor':
                for corner in ob.bound_box:
                    uv = world_to_camera_view(sc, sc.camera, ob.matrix_world@Vector(corner))
                    if uv.z <= 0:
                        raise ValueError('Geometry behind camera')
                    r['camera_margin'] = min(r['camera_margin'], uv.x, uv.y, 1-uv.x, 1-uv.y)
    velocity = np.diff(np.array(tracks), axis=0)*FPS*16
    r['max_point_step'] = float(np.linalg.norm(velocity, axis=2).max()/(FPS*16))
    fastest = np.unravel_index(np.linalg.norm(velocity, axis=2).argmax(), velocity.shape[:2])
    r['fastest_point'] = dict(t=float(fastest[0]/(FPS*16)), index=int(fastest[1]))
    r['max_acceleration'] = float(np.linalg.norm(np.diff(velocity, axis=0)*FPS*16, axis=2).max())
    events = sorted({v for keys in ANGLE_KEYS.values() for v, _ in keys if v > 0} |
                    {v for _, a, b, _ in STEPS for v in (a, b)} | {.55, 1.80, 3.15, REST})
    r['max_event_velocity_jump'] = max(float(np.linalg.norm(velocity[round(t*FPS*16)]-
        velocity[round(t*FPS*16)-1], axis=1).max()) for t in events)
    r['airborne_intervals'] = {s: sum(b and not a for a, b in zip([False]+vs, vs)) for s, vs in air.items()}
    r['final_headings_deg'] = directions[-1]
    r['lead_at_0_75_deg'] = directions[round(.75*FPS*16)]
    r['phase_pass'] = all(r['witnesses'][str(j+1)]['heights'][side] > .12
                          for j, (side, _, _, _) in enumerate(STEPS))
    limits = {'contact_drift': 2e-5, 'contact_speed': .003, 'length_error': 2e-6,
              'joint_error': .002, 'hinge_error': 2e-5, 'hold_drift': 2e-6,
              'heading_error_deg': .02, 'max_point_step': .008,
              'max_acceleration': 100., 'max_event_velocity_jump': .10}
    failures = [n for n, limit in limits.items() if r[n] > limit]
    for n, limit in {'min_floor': -2e-5, 'min_arm_clearance': -.0001,
                     'min_leg_clearance': -.0001, 'min_foot_separation': -.0001,
                     'min_support_pelvis_margin': .02, 'camera_margin': .025}.items():
        if r[n] < limit:
            failures.append(n)
    if r['double_airborne_samples'] or r['airborne_intervals'] != {'L': 1, 'R': 2} or not r['phase_pass']:
        failures.append('step_phases')
    lead = r['lead_at_0_75_deg']
    if not lead['head'] < lead['chest']-5 < lead['pelvis']-10:
        failures.append('heading_order')
    r['failures'] = failures
    if failures:
        raise ValueError(json.dumps(r))
    return r


def negative_test():
    # Move the complete planted left foot during the first right-foot swing.
    saved = []
    for name in ('L_rear', 'L_toe_root'):
        ob = bpy.data.objects[name]
        fc = next(c for c in common.curves(ob) if c.data_path == 'location' and c.array_index == 0)
        coords = [k.co.copy() for k in fc.keyframe_points]
        saved.append((ob, fc, coords))
        for k in fc.keyframe_points:
            k.co.y += .015*lift.smooth((k.co.x/FPS-.65)/.40)*(1-lift.smooth((k.co.x/FPS-1.10)/.15))
        fc.update()
        ob.animation_data.action.update_tag()
    try:
        try:
            validate()
        except ValueError as exc:
            broken = json.loads(str(exc))
            if broken['contact_drift'] < .014 or 'contact_drift' not in broken['failures']:
                raise AssertionError('Wrong negative-test failure') from exc
        else:
            raise AssertionError('Broken support was not detected')
    finally:
        for ob, fc, coords in saved:
            for k, co in zip(fc.keyframe_points, coords):
                k.co = co
            fc.update()
            ob.animation_data.action.update_tag()
    restored = validate()
    return dict(case='animated_support_slide_15mm', caught=True,
                drift=broken['contact_drift'], speed=broken['contact_speed'],
                restored_contact_drift=restored['contact_drift'], restored_pass=True)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--mode', choices=('build', 'verify', 'probes', 'render'), default='build')
    args = ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    root = Path(__file__).resolve().parents[2]/'_game/study/step_turn'
    out = args.out.resolve()
    if not out.is_relative_to(root.resolve()):
        raise ValueError('Output must stay inside _game/study/step_turn')
    started = time.perf_counter()
    report = {'blender': bpy.app.version_string, 'mode': args.mode}
    if args.mode == 'build':
        out.mkdir(parents=True, exist_ok=False)
        setup()
        report['before_save'] = validate()
        bpy.context.scene.frame_set(0)
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'), use_scripts=False)
    if bpy.context.scene.get('study') != 'step_turn':
        raise ValueError('Wrong saved study')
    report['reopened'] = validate()
    if args.mode in ('build', 'verify'):
        report['negative_test'] = negative_test()
    if args.mode in ('probes', 'render'):
        # A separate successful verify is required before any pixel work.
        verified = json.loads((out/'verify.json').read_text(encoding='utf-8'))
        digest = hashlib.sha256((out/'scene.blend').read_bytes()).hexdigest()
        if verified['scene_sha256'] != digest or not verified['negative_test']['restored_pass']:
            raise ValueError('Saved scene must pass verify before probes')
        destination = out
        if args.mode == 'render':
            destination = out/'motion'
            destination.mkdir(exist_ok=False)
        frames = destination/('frames' if args.mode == 'render' else 'probes')
        frames.mkdir(exist_ok=False)
        sc = bpy.context.scene
        cpu_settings(sc)
        report['render'] = dict(engine='CYCLES', device=sc.cycles.device, samples=sc.cycles.samples,
                                width=320, height=320, threads=2, frames=PROBES)
        if args.mode == 'probes':
            for frame in PROBES:
                sc.frame_set(frame)
                sc.render.filepath = str(frames/f'f{frame:04d}.png')
                bpy.ops.render.render(write_still=True)
        else:
            # This run has just validated the reopened bake, not an old report.
            write_json(destination/'audit.json', dict(passed=True, scene_sha256=digest,
                       reopened=report['reopened'], fps=FPS, count=COUNT))
            sc.render.resolution_x = sc.render.resolution_y = 480
            sc.cycles.samples = 12
            sc.cycles.use_denoising = True
            sc.cycles.denoiser = 'OPENIMAGEDENOISE'
            sc.cycles.denoising_use_gpu = False
            sc.cycles.seed = 0
            sc.cycles.use_animated_seed = False
            sc.render.threads = 4
            sc.render.fps, sc.render.fps_base = FPS, 1.0
            sc.frame_start, sc.frame_end, sc.frame_step = 0, COUNT-1, 1
            sc.render.filepath = str(frames/'frame_')
            bpy.ops.render.render(animation=True)
            report['render'] = dict(engine='CYCLES', device='CPU', samples=12,
                                    width=480, height=480, frames=COUNT, fps=FPS, threads=4, denoise='CPU OIDN')
    report['scene_sha256'] = hashlib.sha256((out/'scene.blend').read_bytes()).hexdigest()
    report['elapsed_seconds'] = time.perf_counter()-started
    write_json(out/(args.mode+'.json'), report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
