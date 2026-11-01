"""Careful set-down/release study on the existing rigid mannequin, Blender 5.2.

Run with --out NEW_DIR --mode block, then a separate NEW_DIR --mode render.
--mode review reopens scene.blend, checks playback, corruption tests and MP4.
No assets, addons, sound, new character, dynamics or game-rig transfer.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_lift as lift

CONTACT, RELEASE = 2.15, 2.75
FPS, FRAMES = 30, 135
# Map the validated light lift backwards, with a stable contact dwell added.
# Linear source-time segments retain the source's zero-velocity pose endpoints.
PHASES = [(0.,1.55), (.35,1.55), (CONTACT,1.02),
          (RELEASE, .90), (3.75,.25), (4.25,0.)]
BLOCK_FRAMES = [0, 11, 32, 54, 65, 76, 83, 98, 113, 134]


def source_time(t):
    for (a,x), (b,y) in zip(PHASES, PHASES[1:]):
        if t <= b:
            return x+(y-x)*max(0., min(1., (t-a)/(b-a)))
    return PHASES[-1][1]


def setup():
    scene = lift.setup('light')
    # Reuse only the same geometry/materials/camera and rigid pose solver.
    # Clear the lift animation before authoring an independent action sequence.
    for obj in scene.objects:
        obj.animation_data_clear()
    for action in list(bpy.data.actions):
        if action.users == 0:
            bpy.data.actions.remove(action)
    for i in range((FRAMES-1)*8+1):
        f, t = i/8, i/(8*FPS)
        points, segments, center = lift.pose('light', source_time(t))
        box = bpy.data.objects['Box']
        box.location = center
        lift.key(box, ['location'], f)
        for name, position in points.items():
            obj = bpy.data.objects[name]
            obj.location = position
            lift.key(obj, ['location'], f)
        down = lift.smooth((t-.15)/.65)*(1-lift.smooth((t-3.2)/.7))
        nose = bpy.data.objects['Nose']
        nose.location = points['head']+Vector((0,.13*math.cos(down*.8),-.13*math.sin(down*.8)))
        lift.key(nose, ['location'], f)
        for name, (a,b) in segments.items():
            obj = bpy.data.objects[name]
            lift.orient(obj,a,b)
            lift.key(obj, ['location','rotation_quaternion'], f)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:
                            point.interpolation = 'LINEAR'
    scene['study_case'] = 'setdown'
    scene['contact_seconds'], scene['release_seconds'] = CONTACT, RELEASE
    return scene


def frame_at(t):
    frame = t*FPS
    bpy.context.scene.frame_set(math.floor(frame), subframe=frame%1)
    bpy.context.view_layer.update()


def box_at(t):
    frame_at(t)
    return bpy.data.objects['Box'].matrix_world.translation.copy()


def validate():
    scene = bpy.context.scene
    if (scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base) != (0,134,30,1.):
        raise ValueError('Unexpected timeline/fps')
    # The shared geometry validator also assumes a lift-specific grip interval.
    # Disable that one interval locally, then enforce set-down grip/release
    # independently below. Restore even when a negative test raises. No files
    # or scene actions are changed; this script runs in one Blender process.
    original_grab = lift.GRAB['light']
    try:
        lift.GRAB['light'] = 1e9
        geometry = lift.validate('light')
    finally:
        lift.GRAB['light'] = original_grab
    geometry['case'] = 'setdown'
    geometry.pop('grab_seconds', None)
    geometry.pop('max_grip_error_m', None)  # Replaced by the temporal check.
    contact_center = Vector((0,.70,lift.HALF.z))
    max_grip = max_rest_error = max_rise = max_box_step = 0.
    min_gap_step = 1.
    previous = None
    previous_gaps = None
    previous_hands = None
    max_hand_step = 0.
    release_end_gap = None
    # Independent sixteenth-frame samples from the saved object's transforms.
    for i in range((FRAMES-1)*16+1):
        t = i/(16*FPS)
        center = box_at(t)
        if previous is not None:
            max_rise = max(max_rise, center.z-previous.z)
            max_box_step = max(max_box_step, (center-previous).length)
        if t >= CONTACT:
            max_rest_error = max(max_rest_error,(center-contact_center).length)
        gaps = []
        hands = []
        for side, sign in [('L',-1),('R',1)]:
            hand = bpy.data.objects[f'{side}_hand'].matrix_world.translation.copy()
            hands.append(hand)
            gap = (hand-center-Vector((sign*.34,0,0))).length
            gaps.append(gap)
            if t <= RELEASE:
                max_grip = max(max_grip,gap)
        if t > RELEASE and previous_gaps is not None:
            min_gap_step = min(min_gap_step, *(a-b for a,b in zip(gaps,previous_gaps)))
        if previous_hands is not None:
            max_hand_step = max(max_hand_step, *((a-b).length for a,b in zip(hands,previous_hands)))
        previous_hands = hands
        previous, previous_gaps = center, gaps
        release_end_gap = min(gaps)
    # Actual local velocity around contact/release, not just the authored keys.
    dt = 1/(32*FPS)
    contact_speed = (box_at(CONTACT+dt)-box_at(CONTACT-dt)).length/(2*dt)
    hand_steps = []
    for side in ('L','R'):
        positions = []
        for t in (RELEASE-dt,RELEASE,RELEASE+dt):
            frame_at(t)
            positions.append(bpy.data.objects[f'{side}_hand'].matrix_world.translation.copy())
        hand_steps.append((positions[2]-positions[0]).length/(2*dt))
    frame_at((FRAMES-1)/FPS)
    baseline = lift.pose('light',0)[0]
    stand_error = max((bpy.data.objects[name].matrix_world.translation-point).length
                      for name,point in baseline.items())
    temporal = dict(contact_seconds=CONTACT, release_seconds=RELEASE,
                    supported_dwell_seconds=RELEASE-CONTACT,
                    max_grip_error_before_release_m=max_grip,
                    max_box_rest_error_after_contact_m=max_rest_error,
                    max_box_upward_step_m=max_rise,
                    max_box_step_per_sixteenth_frame_m=max_box_step,
                    max_hand_step_per_sixteenth_frame_m=max_hand_step,
                    final_stance_point_error_m=stand_error,
                    contact_speed_m_s=contact_speed,
                    hand_release_speeds_m_s=hand_steps,
                    min_release_gap_step_m=min_gap_step,
                    final_min_hand_handle_gap_m=release_end_gap)
    if (max_grip>2e-5 or max_rest_error>2e-6 or max_rise>2e-6 or
            max_box_step>.003 or max_hand_step>.005 or stand_error>.001 or
            contact_speed>.01 or max(hand_steps)>.01 or
            min_gap_step < -2e-6 or release_end_gap<.60):
        raise ValueError(f'Setdown/contact/release failure: {temporal}')
    return dict(geometry=geometry,temporal=temporal,blender=bpy.app.version_string,
                limits='Finite sampled rigid mannequin; no dynamics, fingers, skin, physical support certification or arbitrary rig transfer.')


def negative_tests():
    detected = []
    for name,field,axis,amount in [('L_foot','delta_location',0,.01),
                                  ('L_upperarm','scale',2,.01),
                                  ('Box','delta_location',2,-.02)]:
        obj = bpy.data.objects[name]
        original = getattr(obj,field).copy()
        getattr(obj,field)[axis] += amount
        try:
            validate()
        except ValueError:
            detected.append(name+':'+field)
        else:
            raise AssertionError('Undetected corruption: '+name)
        finally:
            setattr(obj,field,original)
    # Early hand separation before touchdown, and a post-contact hop above the
    # floor: the latter must fail even though it has no floor penetration.
    for name,axis,expression,label in [
            ('L_hand',0,'0.01 if 59 <= frame <= 61 else 0','early_release'),
            ('Box',2,'0.015 if 72 <= frame <= 74 else 0','post_contact_hop')]:
        obj = bpy.data.objects[name]
        curve = obj.driver_add('delta_location',axis)
        curve.driver.expression = expression
        try:
            validate()
        except ValueError:
            detected.append(label)
        else:
            raise AssertionError('Undetected corruption: '+label)
        finally:
            obj.driver_remove('delta_location',axis)
            obj.delta_location[axis] = 0
    return detected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mode',choices=['block','render','verify','review'],default='block')
    parser.add_argument('--ffmpeg',type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out = args.out.resolve()
    existing = args.mode in ('verify','review')
    if not existing and out.exists():
        raise ValueError('Use a new output directory')
    if args.ffmpeg and not args.ffmpeg.is_file():
        raise ValueError('FFmpeg missing')
    lift.self_test()  # Includes signed overlap/contact/separation regressions.
    started = time.perf_counter()
    if existing:
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'))
    else:
        out.mkdir(parents=True)
        setup()
    qa = validate()
    if not existing:
        scene = bpy.context.scene
        scene.frame_set(0)
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
        (out/'frames').mkdir()
        if args.mode == 'block':
            for f in BLOCK_FRAMES:
                scene.frame_set(f)
                scene.render.filepath = str(out/'frames'/f'f{f:04d}.png')
                bpy.ops.render.render(write_still=True)
        else:
            scene.render.filepath = str(out/'frames/f')
            bpy.ops.render.render(animation=True)
            if args.ffmpeg:
                subprocess.run([str(args.ffmpeg),'-v','error','-framerate','30','-start_number','0',
                                '-i',str(out/'frames/f%04d.png'),'-frames:v','135','-an',
                                '-c:v','libx264','-crf','19','-pix_fmt','yuv420p',
                                '-movflags','+faststart',str(out/'lift_setdown.mp4')],check=True)
    if args.mode == 'review':
        if not args.ffmpeg:
            raise ValueError('Review requires FFmpeg')
        qa['negative_tests'] = negative_tests()
        qa['movie'] = lift.movie_review(out,'setdown',args.ffmpeg)
    qa['elapsed_seconds'] = time.perf_counter()-started
    (out/(args.mode+'.json')).write_text(json.dumps(qa,indent=2),encoding='utf-8')
    print('SETDOWN_QA '+json.dumps(qa),flush=True)


if __name__ == '__main__':
    main()
