"""Author an alarm, a glance, a step and a deliberate button press."""
import argparse
import json
import math
from pathlib import Path
import sys
import wave

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from beacon_preview import area, box, camera, material, sphere
from study_lift import key, orient, solve
import study_step_touch as step


FPS, COUNT = 30, 147
ALARM, LOOK, MOVE = .60, .73, 1.05
TOUCH = MOVE + step.TOUCH
PRESSED = TOUCH + .16
RECOVER = TOUCH + .33
STROKE = .055
CUT = 76
RECOIL_START, RECOIL_PEAK, RECOIL_END = 23, 28, 38
CONSOLE_OFFSET = Vector((0, -.075, 0))
BUTTON_HOME = step.TARGET + CONSOLE_OFFSET
ALARM_CENTER = Vector((.32, 1.079, 1.67)) + CONSOLE_OFFSET


def action_time(t, delay):
    return t - min(max(t - PRESSED, 0.), delay)


def travel(t):
    return STROKE * step.progress(t, TOUCH, PRESSED) * (1 - step.progress(t, RECOVER, MOVE + step.RELEASE))


def lamp(name, center, color, keys, *, dark_idle=False):
    base = tuple(.055 * component for component in color) if dark_idle else color
    coat = material(name, base, roughness=.27)
    shader = coat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Emission Color'].default_value = (*color, 1)
    strength = shader.inputs['Emission Strength']
    for t, power in keys:
        strength.default_value = power
        strength.keyframe_insert('default_value', frame=1 + t * FPS)
    return sphere(name, center, .059, coat)


def recoil_pose(points, weight):
    retreat = Vector((0, -.043, -.034)) * weight
    torso = points['neck'] - points['pelvis']
    lean = Quaternion((1, 0, 0), .24 * weight) @ torso
    shoulder_shift = retreat + lean - torso
    points['pelvis'] += retreat
    points['neck'] += shoulder_shift
    points['head'] += shoulder_shift + Vector((0, .034, -.021)) * weight
    for side, hand_lift in (('L', .13), ('R', .18)):
        points[f'{side}_hip'] += retreat
        points[f'{side}_knee'] = solve(points[f'{side}_hip'], points[f'{side}_ankle'],
                                       .46, .46, Vector((0, 1, 0)))
        points[f'{side}_shoulder'] += shoulder_shift
        points[f'{side}_hand'] += Vector((0, .08, hand_lift)) * weight
        sign = -1 if side == 'L' else 1
        points[f'{side}_elbow'] = solve(points[f'{side}_shoulder'], points[f'{side}_hand'],
                                        .44, .42, Vector((sign, -.15, .12)))
    points['Palm'] = points['R_hand'] + Vector((0, .025, 0))


def portrait_stage(scene):
    scene.render.resolution_x, scene.render.resolution_y = 720, 1280
    scene.eevee.taa_render_samples = 16
    wall = material('Maintenance bay panels', (.065, .091, .105), .15, .56)
    trim = material('Maintenance bay ribs', (.035, .059, .068), .24, .48)
    box('Bay back wall', (-3.2, .8, 1.8), (.15, 9.2, 3.6), wall)
    box('Bay kick plate', (-3.07, .8, .17), (.16, 9.2, .34), trim)
    for y in (-2.0, -.60, .80, 2.20, 3.60):
        box('Bay panel rib', (-3.09, y, 1.99), (.12, .085, 3.25), trim)
    camera(scene, 'Wide', (4.75, .37, 2.14), (.12, .55, .93), 44, 1)
    camera(scene, 'Press', (3.07, .47, 1.96), (.21, .57, 1.27), 37, CUT)
    area('Key', (1.8, -2.9, 4.3), (.12, .52, 1), 565, 3.5, (1, .88, .73))
    area('Rim', (-2.2, 3.2, 3.6), (.12, .52, 1), 780, 2.6, (.55, .80, 1))
    area('Fill', (3.2, 2.4, 2.9), (.12, .52, 1.2), 290, 3.1, (.83, .91, 1))


def build(out, *, alarm_recoil=False, portrait=False, extra_frames=0, draft=False):
    scene = step.setup()
    for obj in scene.objects:
        obj.animation_data_clear()
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 32
    count = COUNT + extra_frames
    delay = extra_frames / FPS
    scene.frame_start, scene.frame_end = 1, count

    graphite = material('Console graphite', (.035, .074, .096), .45)
    turquoise = material('Service enamel', (.052, .29, .31), .22)
    orange = material('Manual reset', (.60, .26, .046), .17)
    visor_coat = material('Smoked visor', (.025, .062, .075), .29)
    eye_coat = material('Visor cyan', (.09, .58, .73))
    eye_shader = eye_coat.node_tree.nodes.get('Principled BSDF')
    eye_shader.inputs['Emission Color'].default_value = (.06, .53, .74, 1)
    eye_shader.inputs['Emission Strength'].default_value = .6
    objects = bpy.data.objects
    for name in ('Target post', 'Target base', 'Key', 'Rim'):
        objects.remove(objects[name], do_unlink=True)
    objects['Floor'].data.materials[0] = material('Studio deck', (.037, .056, .074), roughness=.61)
    button = objects['Target']
    button.name = 'Reset button'
    button.data.materials.clear()
    button.data.materials.append(orange)
    for name, center, size, coat, bevel in (
        ('Console base', (.32, 1.23, .045), (.57, .52, .09), graphite, .026),
        ('Console pedestal', (.32, 1.23, .60), (.43, .34, 1.04), graphite, .032),
        ('Console case', (.32, 1.27, 1.33), (.64, .34, .77), turquoise, .045),
        ('Console face', (.32, 1.114, 1.33), (.56, .040, .67), graphite, .016),
    ):
        box(name, Vector(center) + CONSOLE_OFFSET, size, coat, bevel)
    alarm_color = (1, .035, .009) if portrait else (.91, .20, .022)
    ready_color = (.025, .82, .13) if portrait else (.11, .76, .29)
    lamp('Alarm', ALARM_CENTER, alarm_color,
         ((0, 0), (ALARM - .03, 0), (ALARM, 2.7), (PRESSED + delay, 2.7), (PRESSED + delay + .08, 0)),
         dark_idle=portrait)
    lamp('Ready', ALARM_CENTER - Vector((0, 0, .16)), ready_color,
         ((0, 0), (PRESSED + delay, 0), (PRESSED + delay + .08, 2.0)), dark_idle=portrait)

    # The old nose is hidden by a rigid visor aligned with the gaze axis.
    objects['Nose'].hide_render = True
    head = objects['head']
    visor = box('Visor', (0, 0, 0), (.20, .046, .092), visor_coat, .016)
    visor.parent, visor.location = head, (0, .130, .018)
    for x in (-.05, .05):
        eye = box('Status light', (0, 0, 0), (.034, .014, .038), eye_coat, .006)
        eye.parent, eye.location = visor, (x, .025, .005)
    chest = box('Service shell', (0, 0, 0), (.36, .22, .30), turquoise, .045)
    neck_joint = sphere('Neck swivel', (0, 0, 0), .061, graphite)
    for i in range((count - 1) * 4 + 1):
        frame = 1 + i / 4
        t = action_time(i / (4 * FPS), delay)
        action = max(0., t - MOVE)
        points = step.pose(action)
        recoil = (step.progress(frame, RECOIL_START, RECOIL_PEAK)
                  * (1 - step.progress(frame, RECOIL_PEAK, RECOIL_END))) if alarm_recoil else 0.
        if recoil:
            recoil_pose(points, recoil)
        depth = travel(t)
        reach = step.progress(action, 1.40, step.TOUCH) * (1 - step.progress(action, step.RELEASE, step.REST))
        palm_offset = CONSOLE_OFFSET * reach + Vector((0, depth, 0))
        points['R_hand'] += palm_offset
        points['Palm'] += palm_offset
        elbow_plane = Vector((1, -.15, .12)).lerp(Vector((.65, -.20, -.72)), reach)
        points['R_elbow'] = solve(points['R_shoulder'], points['R_hand'], .44, .42, elbow_plane)
        glance = step.progress(t, LOOK, 1.02)
        glance += (1 - glance) * recoil * .70
        eye_target = ALARM_CENTER.lerp(BUTTON_HOME, step.progress(t, 2.21, 2.59))
        if portrait:
            ready_center = ALARM_CENTER - Vector((0, 0, .16))
            eye_target = eye_target.lerp(ready_center, step.progress(t, PRESSED + .12, PRESSED + .52))
        direction = Vector((-.60, .80, -.05)).lerp((eye_target - points['head']).normalized(), glance)
        head.rotation_euler = direction.to_track_quat('Y', 'Z').to_euler()
        key(head, ['rotation_euler'], frame)
        for name, position in points.items():
            if name != 'Nose':
                objects[name].location = position
                key(objects[name], ['location'], frame)
        neck_joint.location = points['neck'] + Vector((0, 0, .055))
        key(neck_joint, ['location'], frame)
        chest.location = points['pelvis'].lerp(points['neck'], .70)
        chest.rotation_euler.x = (.24 * recoil - .08 * step.progress(t, 2.33, TOUCH)
                                  * (1 - step.progress(t, 3.68, 4.25)))
        key(chest, ['location', 'rotation_euler'], frame)
        button.location = BUTTON_HOME + Vector((0, depth, 0))
        key(button, ['location'], frame)
        for side in ('L', 'R'):
            foot = objects[side + '_foot']
            foot.location = step.foot_center(side, action)
            key(foot, ['location'], frame)
        for name, (start, end) in step.LINKS.items():
            segment = objects[name]
            orient(segment, points[start], points[end])
            key(segment, ['location', 'rotation_quaternion'], frame)
    if portrait:
        portrait_stage(scene)
    else:
        camera(scene, 'Wide', (4.85, .30, 2.34), (.12, .53, .85), 48, 1)
        camera(scene, 'Press', (2.62, .42, 1.99), (.28, .53, 1.29), 46, CUT)
        area('Key', (2, -3.4, 5.8), (.12, .52, 1), 700, 4.4, (.76, .89, 1))
        area('Rim', (-2.2, 3.5, 4.7), (.12, .52, .9), 1000, 3.4, (.53, .78, 1))
        area('Fill', (3.5, 2.4, 3.4), (.12, .52, 1.1), 210, 3.7, (1, .83, .65))
    if draft:
        scene.render.resolution_x, scene.render.resolution_y = (360, 640) if portrait else (640, 360)
        scene.eevee.taa_render_samples = 8
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'scene.blend'))


def verify(out, extra_frames=0):
    bpy.ops.wm.open_mainfile(filepath=str(out / 'scene.blend'), use_scripts=False)
    scene = bpy.context.scene
    objects = bpy.data.objects
    palm, button = objects['Palm'], objects['Reset button']
    local_palm = step.mesh_vertices(palm)
    palm_face = [p for p in local_palm if abs(p.y - max(v.y for v in local_palm)) < 1e-6]
    assert len(palm_face) == 4
    local_button = step.mesh_vertices(button)
    min_gap, max_hold_gap, max_travel = 1., 0., 0.
    left_foot = objects['L_foot']
    left_start = left_foot.location.copy()
    full_depth = []
    for i in range((scene.frame_end - 1) * 8 + 1):
        frame = 1 + i / 8
        elapsed = i / (8 * FPS)
        t = action_time(elapsed, extra_frames / FPS)
        scene.frame_set(int(frame), subframe=frame % 1)
        front = [palm.matrix_world @ v for v in palm_face]
        target = [button.matrix_world @ v for v in local_button]
        gap = min(v.y for v in target) - max(v.y for v in front)
        min_gap = min(min_gap, gap)
        if TOUCH <= t <= MOVE + step.RELEASE:
            max_hold_gap = max(max_hold_gap, abs(gap))
            for vertex in front:
                for axis in (0, 2):
                    assert min(v[axis] for v in target) + .01 < vertex[axis] < max(v[axis] for v in target) - .01
        depth = button.location.y - BUTTON_HOME.y
        max_travel = max(max_travel, depth)
        if abs(depth - STROKE) < .000002:
            full_depth.append(elapsed)
        assert (left_foot.location - left_start).length < 1e-5
        right = objects['R_foot']
        assert right.location.z >= .05 - 1e-5
        if t >= MOVE + step.LAND:
            assert (right.location - step.foot_center('R', step.LAND)).length < 1e-5
    assert min_gap > -.0001 and max_hold_gap < .0001 and abs(max_travel - STROKE) < .0001
    print(f'Contact: minimum gap {min_gap:.6f} m, hold error {max_hold_gap:.6f} m, stroke {max_travel:.3f} m.')
    if extra_frames:
        expected = RECOVER - PRESSED + extra_frames / FPS
        hold = full_depth[-1] - full_depth[0]
        if abs(hold - expected) > .01:
            raise RuntimeError(f'Expected {expected:.3f} s at full depth, measured {hold:.3f} s')
        report = dict(full_depth_seconds=hold, stroke_m=max_travel, palm_gap_m=max_hold_gap,
                      minimum_gap_m=min_gap, geometry_samples=(scene.frame_end - 1) * 8 + 1)
        (out / 'contact.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


def check_portrait(out, scene):
    bounds = {}
    for name, frames, subjects in (
        ('Wide', range(1, CUT), ('head', 'L_foot', 'R_foot', 'Alarm')),
        ('Press', range(CUT, scene.frame_end + 1), ('head', 'Palm', 'Reset button', 'Alarm', 'Ready')),
    ):
        border = 1.
        for frame in frames:
            scene.frame_set(frame)
            for subject in subjects:
                obj = bpy.data.objects[subject]
                for vertex in obj.bound_box:
                    world = obj.matrix_world @ Vector(vertex)
                    p = world_to_camera_view(scene, bpy.data.objects[name], world)
                    border = min(border, p.x - .0556, .8704 - p.x, p.y - .1875, .921875 - p.y)
        if border < 0:
            raise RuntimeError(f'{name} has action outside the vertical safe area: {border:.4f}')
        bounds[name] = border
    if bpy.utils.blend_paths(absolute=True, packed=False):
        raise RuntimeError('The portrait scene still references external files')
    (out / 'portrait.json').write_text(json.dumps(bounds, indent=2) + '\n', encoding='utf-8')


def write_sound(path, extra_frames=0):
    """Stereo cues for the alarm, planted step, bottom of the switch and ready lamp."""
    rate = 48_000
    samples = np.zeros(((COUNT + extra_frames) * rate // FPS, 2))
    cues = (
        (ALARM, .14, (660, 905), .32, (0.57, 1)),
        (ALARM + .22, .12, (660, 905), .25, (0.57, 1)),
        (MOVE + step.LAND, .16, (72, 118), .35, (1, .69)),
        (math.ceil(PRESSED * FPS) / FPS, .10, (235, 1140), .47, (.66, 1)),
        ((math.ceil((PRESSED + .08) * FPS) + extra_frames) / FPS, .25, (523, 784), .24, (.65, 1)),
    )
    for onset, length, (fundamental, partial), gain, pan in cues:
        start = round(onset * rate)
        t = np.arange(round(length * rate)) / rate
        envelope = np.minimum(t / .006, 1) * np.exp(-4 * t / length)
        envelope *= np.minimum((length - t) / .02, 1)
        sound = gain * envelope * (.74 * np.sin(math.tau * fundamental * t)
                                  + .26 * np.sin(math.tau * partial * t))
        samples[start:start + len(t)] += sound[:, None] * np.asarray(pan)
    with wave.open(str(path), 'wb') as output:
        output.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(np.round(samples * 32767).astype('<i2').tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--alarm-recoil', action='store_true', help='Add a brief supported recoil before the step')
    parser.add_argument('--portrait', action='store_true', help='Stage a vertical service bay and keep its sound')
    parser.add_argument('--plan', type=Path, help='Use a local robot contact plan')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    extra_frames = 0
    sound = args.portrait
    if args.plan:
        if args.portrait or args.alarm_recoil:
            parser.error('--plan sets the scene variant')
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        if (not isinstance(plan, dict) or plan.get('schema_version') != 1 or plan.get('actor') != 'robot'
                or plan.get('action') != 'reset_button' or plan.get('aspect') not in ('portrait', 'landscape')
                or type(plan.get('hold_frames')) is not int or plan['hold_frames'] not in (15, 30)
                or type(plan.get('sound')) is not bool):
            raise ValueError('Use a version 1 robot contact plan')
        args.portrait = plan['aspect'] == 'portrait'
        sound = plan['sound']
        extra_frames = plan['hold_frames'] - round((RECOVER - PRESSED) * FPS)
    out = args.out.resolve()
    out.mkdir(parents=True)
    build(out, alarm_recoil=args.alarm_recoil, portrait=args.portrait,
          extra_frames=extra_frames, draft=bool(args.plan))
    verify(out, extra_frames)
    scene = bpy.context.scene
    if args.portrait:
        check_portrait(out, scene)
    if not args.plan or sound:
        write_sound(out / 'mix.wav', extra_frames)
    job = dict(schema_version=1, scene='scene.blend', out='draft', frames=[1, scene.frame_end + 1],
               size=[scene.render.resolution_x, scene.render.resolution_y], fps=FPS)
    if sound:
        job['wav'] = 'mix.wav'
    (out / 'job.json').write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
    if args.alarm_recoil:
        insert = dict(job, out='insert', frames=[RECOIL_START + 1, RECOIL_END])
        insert.pop('wav', None)
        (out / 'insert.json').write_text(json.dumps(insert, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
