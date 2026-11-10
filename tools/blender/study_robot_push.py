"""Build a procedural robot pushing a crate from a local text plan."""

import argparse
import json
from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_step_touch as step
from study_lift import cube, key, material, orient, solve


FPS, COUNT = 30, 135
START, STOP, RELEASE = 2.24, 3.04, 3.22
SIZE = (640, 360)
CRATE_SIZE = (.68, .52, 1.40)
CRATE_HOME = Vector((step.TARGET.x, step.TARGET.y - step.TARGET_SIZE.y / 2 + CRATE_SIZE[1] / 2,
                     CRATE_SIZE[2] / 2))


def base_time(t):
    return t - min(max(0., t - step.RELEASE), RELEASE - step.RELEASE)


def placement(t, distance):
    local_t = base_time(t)
    points = step.pose(local_t)
    reach = step.progress(local_t, 1.40, step.TOUCH) * (1 - step.progress(local_t, step.RELEASE, step.REST))
    travel = distance * step.progress(t, START, STOP)
    drive = (distance / .20 * step.progress(t, step.TOUCH, STOP)
             * (1 - step.progress(t, RELEASE, 4.12)))
    shift = Vector((0, .12, -.018)) * drive
    tilt = Quaternion((1, 0, 0), -.19 * drive)
    pivot = points['pelvis'].copy()
    for name in ('pelvis', 'neck', 'head', 'Nose', 'L_hip', 'R_hip', 'L_shoulder', 'R_shoulder'):
        points[name] = pivot + tilt @ (points[name] - pivot) + shift
    points['L_hand'] += shift
    points['R_hand'].y += travel * reach
    points['Palm'] = points['R_hand'] + Vector((0, .025, 0))
    for side, sign in (('L', -1), ('R', 1)):
        points[f'{side}_knee'] = solve(points[f'{side}_hip'], points[f'{side}_ankle'],
                                       .46, .46, Vector((0, 1, 0)))
        points[f'{side}_elbow'] = solve(points[f'{side}_shoulder'], points[f'{side}_hand'],
                                        .44, .42, Vector((sign, -.15, .12)))
    return points, travel


def build(out, distance):
    scene = step.setup(animate=False)
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 8
    scene.frame_start, scene.frame_end = 1, COUNT
    objects = bpy.data.objects
    for name in ('Target', 'Target post', 'Target base'):
        objects.remove(objects[name], do_unlink=True)
    crate = cube('Cargo crate', CRATE_HOME, CRATE_SIZE, material('Ochre crate', (.48, .24, .06)), .015)
    paint = material('Crate runners', (.085, .055, .028))
    for z in (.18, 1.03):
        for sign in (-1, 1):
            rib = cube('Crate reinforcement', (0, 0, 0), (.045, .44, .065), paint, .008)
            rib.parent = crate
            rib.location = (sign * CRATE_SIZE[0] / 2, 0, z - CRATE_HOME.z)
    camera = objects['profile']
    camera.location = (6.5, .18, 2.1)
    camera.rotation_euler = (Vector((0, .77, .81)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.ortho_scale = 3.65
    scene.camera = camera

    for i in range((COUNT - 1) * 4 + 1):
        frame, t = 1 + i / 4, i / (4 * FPS)
        points, travel = placement(t, distance)
        crate.location = CRATE_HOME + Vector((0, travel, 0))
        key(crate, ('location',), frame)
        for name, position in points.items():
            objects[name].location = position
            key(objects[name], ('location',), frame)
        for side in ('L', 'R'):
            foot = objects[f'{side}_foot']
            foot.location = step.foot_center(side, base_time(t))
            key(foot, ('location',), frame)
        for name, (start, end) in step.LINKS.items():
            orient(objects[name], points[start], points[end])
            key(objects[name], ('location', 'rotation_quaternion'), frame)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'scene.blend'))


def verify(out, distance):
    bpy.ops.wm.open_mainfile(filepath=str(out / 'scene.blend'), use_scripts=False)
    scene, objects = bpy.context.scene, bpy.data.objects
    palm, crate = objects['Palm'], objects['Cargo crate']
    palm_mesh = step.mesh_vertices(palm)
    palm_face = [v for v in palm_mesh if v.y >= max(p.y for p in palm_mesh) - 1e-6]
    if len(palm_face) != 4:
        raise ValueError('The palm must have one flat contact face')
    crate_mesh = step.mesh_vertices(crate)
    local_back = min(v.y for v in crate_mesh)
    flat = [v for v in crate_mesh if abs(v.y - local_back) < 1e-6]
    bounds = [(min(v[k] for v in flat), max(v[k] for v in flat)) for k in (0, 2)]
    feet = {side: objects[f'{side}_foot'] for side in ('L', 'R')}
    samples = (COUNT - 1) * 8 + 1
    report = dict(samples=samples, min_gap_m=1., max_contact_gap_m=0., min_contact_margin_m=1.,
                  floor_error_m=0., support_drift_m=0., body_clearance_m=1., frame_margin=1.)
    foot_starts = {side: step.foot_center(side, 0 if side == 'L' else step.LAND) for side in feet}
    previous = 0.
    for i in range(samples):
        frame, t = 1 + i / 8, i / (8 * FPS)
        scene.frame_set(int(frame), subframe=frame % 1)
        center = crate.matrix_world.translation
        travel = center.y - CRATE_HOME.y
        if abs(travel - distance * step.progress(t, START, STOP)) > .00001 or travel < previous - 1e-6:
            raise RuntimeError(f'Unexpected crate motion at frame {frame}')
        previous = travel
        back = center.y + local_back
        for v in palm_face:
            world = palm.matrix_world @ v
            gap = back - world.y
            report['min_gap_m'] = min(report['min_gap_m'], gap)
            if step.TOUCH <= t <= RELEASE:
                report['max_contact_gap_m'] = max(report['max_contact_gap_m'], abs(gap))
                for axis, (lo, hi) in zip((0, 2), bounds):
                    local = world[axis] - center[axis]
                    report['min_contact_margin_m'] = min(report['min_contact_margin_m'], local - lo, hi - local)
        for name in step.LINKS:
            limb = objects[name]
            extent = max((limb.matrix_world @ Vector((0, 0, z))).y for z in (-.5, .5))
            report['body_clearance_m'] = min(report['body_clearance_m'], back - extent - limb['radius'])
        report['floor_error_m'] = max(report['floor_error_m'], abs(center.z + min(v.z for v in crate_mesh)))
        for side, foot in feet.items():
            if side == 'L' or t >= step.LAND:
                drift = (foot.matrix_world.translation - foot_starts[side]).length
                report['support_drift_m'] = max(report['support_drift_m'], drift)
        if i % 8 == 0:
            for obj in (crate, palm, objects['head'], *feet.values()):
                for v in obj.bound_box:
                    p = world_to_camera_view(scene, scene.camera, obj.matrix_world @ Vector(v))
                    report['frame_margin'] = min(report['frame_margin'], p.x, 1-p.x, p.y, 1-p.y)
    report['travel_m'] = previous
    report['release_gap_m'] = back - max((palm.matrix_world @ v).y for v in palm_face)
    if (abs(previous - distance) > 1e-5 or report['min_gap_m'] < -.0001
            or report['max_contact_gap_m'] > .0001 or report['min_contact_margin_m'] < .015
            or report['floor_error_m'] > .0001 or report['support_drift_m'] > .0001
            or report['body_clearance_m'] < .005 or report['release_gap_m'] < .10
            or report['frame_margin'] < .04):
        raise RuntimeError(f'Crate contact did not pass: {report}')
    (out / 'contact.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    if (not isinstance(plan, dict) or plan.get('schema_version') != 1 or plan.get('actor') != 'robot'
            or plan.get('action') != 'push_crate' or type(plan.get('distance_cm')) is not int
            or plan['distance_cm'] not in (10, 20)):
        raise ValueError('Use a version 1 robot push plan')
    out = args.out.resolve()
    out.mkdir(parents=True)
    distance = plan['distance_cm'] / 100
    build(out, distance)
    verify(out, distance)
    job = dict(schema_version=1, scene='scene.blend', out='draft', frames=[1, COUNT+1], size=SIZE, fps=FPS)
    (out / 'job.json').write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
