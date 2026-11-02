"""Seven-second authored blocking: casual tug, surprise, deliberate preparation.

Run in background Blender; build/audit or a small CPU motion preview.
Optional --probes: two 320x240 denoised CPU stills, AFTER saved-scene checks.
Geometry/IK reuse study_lift, links study_throw, capsule tests study_pointing.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_lift as geom
from study_throw import LINKS
from study_pointing import point_segment, segment_distance
from study_reconsider import curve

FPS, COUNT = 30, 210
ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / '_game/study/confidence'
BOX = Vector((0, .62, .62))
GRIPS = {s: BOX + Vector((sign*.36, 0, .06))
         for s, sign in [('L', -1), ('R', 1)]}
STAND = Vector((0, .62, .20))
STAND_HALF = Vector((.17, .16, .20))
BLOCK = (12, 65, 105, 190)
PROBES = (65, 105)
# time, pelvis y/z, torso pitch. Holds are authored, not an IK side effect.
BODY = [(0, -.08, .92, -.10), (.55, -.08, .92, -.10),
        (1.55, -.08, .86, .42), (1.75, -.08, .86, .42),
        (2.05, -.08, .89, .42), (2.22, -.08, .89, .42),
        (2.50, -.09, .80, .48), (2.95, -.09, .80, .48),
        (3.70, -.13, .87, .08), (4.05, -.13, .87, .08),
        (5.50, -.13, .63, .55), (5.85, -.13, .63, .55),
        (6.30, -.14, .66, .50), (7.00, -.14, .66, .50)]
BEATS = [(0, 'Easy: chin up, free hand at hip'),
         (1.55, 'One-hand grip; crate still supported'),
         (2.05, 'Tug meets resistance; crate does not move'),
         (2.50, 'Knees yield; attention follows to the hand'),
         (2.95, 'Release and reassess'),
         (4.05, 'Decision: lower hips, approach with both hands'),
         (5.50, 'Two-hand grip, low preparation'),
         (6.30, 'Brace and hold; no lift yet')]


def hand_path(t, keys, bows):
    """Authored arcs; bows are midpoint offsets with zero endpoint speed."""
    for i, ((a, p), (b, q)) in enumerate(zip(keys, keys[1:])):
        if t <= b:
            u = geom.smooth((t-a)/(b-a))
            return Vector(p).lerp(Vector(q), u) + Vector(bows[i]) * (4*u*(1-u))
    return Vector(keys[-1][1])


def pose(t):
    py, pz, lean = [curve(t, [(row[0], row[k]) for row in BODY]) for k in (1, 2, 3)]
    pelvis = Vector((0, py, pz))
    neck = pelvis + Vector((0, .5*math.sin(lean), .5*math.cos(lean)))
    head_pitch = curve(t, [(0, -.20), (.70, -.20), (1.55, .20), (2.22, .20),
                           (2.65, .65), (2.95, .65), (3.65, .18), (4.05, .18),
                           (5.50, .42), (6.30, .24), (7, .24)])
    head = neck + Vector((0, .19*math.sin(head_pitch), .19*math.cos(head_pitch)))
    gaze = Vector((0, math.cos(head_pitch), -math.sin(head_pitch)))
    p = dict(pelvis=pelvis, neck=neck, head=head, Nose=head+gaze*.145)
    # R: dismissive display -> wide descending arc -> locked tug -> upward
    # release/reassessment -> deliberate downward arc to the SAME handle.
    right = hand_path(t, [(0, (.43, .18, 1.28)), (.55, (.43, .18, 1.28)),
                        (1.55, GRIPS['R']), (2.95, GRIPS['R']),
                        (3.70, (.49, .10, 1.08)), (4.05, (.49, .10, 1.08)),
                        (5.50, GRIPS['R']), (7, GRIPS['R'])],
                      [(0,0,0), (.13, -.04, .10), (0,0,0), (.16,-.04,.09),
                       (0,0,0), (.07,-.03,.06), (0,0,0)])
    left = hand_path(t, [(0, (-.38, -.18, 1.0)), (2.95, (-.38, -.18, 1.0)),
                       (3.70, (-.48, .18, .93)), (4.05, (-.48, .18, .93)),
                       (5.50, GRIPS['L']), (7, GRIPS['L'])],
                     [(0,0,0), (-.10,-.03,.04), (0,0,0), (-.10,0,.08), (0,0,0)])
    for side, sign in [('L', -1), ('R', 1)]:
        hip = pelvis + Vector((sign*.15, 0, 0))
        ankle = Vector((sign*.27, .10 if side == 'L' else -.10, .10))
        shoulder = neck + Vector((sign*.23, 0, 0))
        hand = left if side == 'L' else right
        try:
            knee = geom.solve(hip, ankle, .46, .46, Vector((0, 1, 0)))
            elbow = geom.solve(shoulder, hand, .44, .42, Vector((sign, -.20, .10)))
        except ValueError as exc:
            raise ValueError(f'Impossible pose/contact at {t:.6f}s {side}: {exc}') from exc
        for name, value in [('hip', hip), ('ankle', ankle), ('knee', knee),
                            ('shoulder', shoulder), ('elbow', elbow), ('hand', hand)]:
            p[side+'_'+name] = value
    return p


def contact_error(t, p, grips):
    sides = ['R'] if 1.55 <= t <= 2.95 else []
    if t >= 5.50:
        sides = ['L', 'R']
    error = max(((p[s+'_hand']-grips[s]).length for s in sides), default=0.)
    if error > .001:
        raise ValueError(f'Lost required grip at {t:.6f}s: {error:.6f}m')
    return error


def preflight():
    for i in range(8*(COUNT-1)+1):
        t = i/(8*FPS)
        contact_error(t, pose(t), GRIPS)
    # Negative probes ensure unreachable chains and displaced contact fail closed.
    rejected = []
    try:
        geom.solve(Vector(), Vector((0, 0, 2)), .44, .42, Vector((1, 0, 0)))
    except ValueError:
        rejected.append('unreachable_IK')
    for side in ('R', 'L'):
        p = pose(6.30)
        p[side+'_hand'] += Vector((.01, 0, 0))
        try:
            contact_error(6.30, p, GRIPS)
        except ValueError:
            rejected.append('lost_'+side+'_grip')
    if len(rejected) != 3:
        raise ValueError('Negative probes did not reject invalid poses')
    return rejected


def cpu_settings(sc):
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 8
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    sc.cycles.denoising_use_gpu = False
    sc.cycles.seed = 0
    sc.cycles.use_animated_seed = False
    sc.render.threads_mode = 'FIXED'
    sc.render.threads = 2
    sc.render.resolution_x, sc.render.resolution_y = 320, 240
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'


def setup():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    cpu_settings(sc)
    sc.render.fps, sc.frame_start, sc.frame_end = FPS, 0, COUNT-1
    sc.view_settings.view_transform = 'AgX'
    sc.world = bpy.data.worlds.new('Studio')
    sc.world.use_nodes = True
    background = next(n for n in sc.world.node_tree.nodes if n.type == 'BACKGROUND')
    background.inputs['Color'].default_value = (.19, .23, .29, 1)
    background.inputs['Strength'].default_value = .5
    body = geom.material('Ivory', (.72, .76, .75))
    dark = geom.material('Joints', (.055, .10, .13))
    crate = geom.material('Heavy crate', (.48, .19, .055))
    geom.cube('Floor', (0, 0, -.06), (20, 20, .12), geom.material('Floor', (.10,.15,.19)))
    geom.cube('Plinth', STAND, STAND_HALF*2, dark, .012)
    geom.cube('Box', BOX, geom.HALF*2, crate, .012)
    for side, sign in [('L', -1), ('R', 1)]:
        grip = GRIPS[side]
        bar = geom.rod(side+'_handle', .016, dark)
        geom.orient(bar, grip+Vector((0,-.08,0)), grip+Vector((0,.08,0)))
        # Hand is a socket marker on the bar, not a simulated finger grasp.
        for j, y in enumerate((-.08,.08)):
            rod = geom.rod(side+'_mount_'+str(j), .012, dark)
            geom.orient(rod, BOX+Vector((sign*.28,y,.06)), grip+Vector((0,y,0)))
        geom.cube(side+'_foot', (sign*.27, (.10 if side == 'L' else -.10)+.06,.05),
                  (.18,.34,.10), dark, .018)
    for name in pose(0):
        radius = .14 if name == 'head' else (.10 if name == 'pelvis' else .047)
        if name == 'Nose':
            radius = .035
        obj = geom.sphere(name, radius, body if name == 'head' else dark)
        obj['radius'] = radius
    for name in LINKS:
        obj = geom.rod(name, geom.radius_for(name), body)
        obj['radius'] = geom.radius_for(name)
    for name, position, energy in [('Key',(2,3,5),900), ('Rim',(-3,-1,4),600)]:
        obj = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        sc.collection.objects.link(obj)
        obj.location = position
        obj.data.energy, obj.data.size = energy, 4
        obj.rotation_euler = (Vector((0,.3,1))-obj.location).to_track_quat('-Z','Y').to_euler()
    for name, position in [('three_quarter',(2.8,6,2.3)), ('profile',(6,.35,2.1))]:
        obj = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        sc.collection.objects.link(obj)
        obj.location = position
        obj.rotation_euler = (Vector((0,.25,.92))-obj.location).to_track_quat('-Z','Y').to_euler()
        obj.data.type, obj.data.ortho_scale = 'ORTHO', 3.0
    sc.camera = bpy.data.objects['three_quarter']
    for t, label in BEATS:
        sc.timeline_markers.new(label, frame=round(t*FPS))
    for i in range(4*(COUNT-1)+1):
        frame = i/4
        p = pose(frame/FPS)
        for name, value in p.items():
            obj = bpy.data.objects[name]
            obj.location = value
            geom.key(obj, ['location'], frame)
        for name, (a,b) in LINKS.items():
            obj = bpy.data.objects[name]
            geom.orient(obj, p[a], p[b])
            geom.key(obj, ['location','rotation_quaternion','scale'], frame)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for key in fc.keyframe_points:
                            key.interpolation = 'LINEAR'
    sc['study'] = 'confidence_v1'
    sc['limits'] = 'Blocking only; no physical mass, skin, fingers, balance simulation or artistic acceptance.'
    sc.frame_set(0)
    return sc


def projection_audit():
    """Four poses, two existing cameras; screen-space diagnostics, no render."""
    sc = bpy.context.scene
    rows = []
    for frame in BLOCK:
        sc.frame_set(frame)
        bpy.context.view_layer.update()
        p = {n: bpy.data.objects[n].matrix_world.translation.copy() for n in pose(frame/FPS)}
        for camera in ('three_quarter', 'profile'):
            cam = bpy.data.objects[camera]
            def project(v):
                uv = world_to_camera_view(sc, cam, v)
                return Vector((uv.x*320, uv.y*240, 0))
            q = {n: project(v) for n,v in p.items()}
            pixels_per_m = 320/cam.data.ortho_scale
            row = dict(frame=frame, camera=camera,
                       nose_head_offset_px=(q['Nose']-q['head']).length)
            for side in ('L', 'R'):
                a, b, c = [q[side+'_'+n] for n in ('shoulder','elbow','hand')]
                row[side+'_elbow_angle_deg'] = math.degrees((a-b).angle(c-b))
                row[side+'_upperarm_projected_fraction'] = (b-a).length/(.44*pixels_per_m)
                row[side+'_forearm_projected_fraction'] = (c-b).length/(.42*pixels_per_m)
                row[side+'_arm_head_gap_px'] = min(
                    point_segment(q['head'],a,b)-(.14+.055)*pixels_per_m,
                    point_segment(q['head'],b,c)-(.14+.04)*pixels_per_m)
                row[side+'_elbow_neck_gap_px'] = (b-q['neck']).length-(.047+.065)*pixels_per_m
            rows.append(row)
    selected = [r for r in rows if r['camera'] == sc.camera.name]
    passed = len(selected) == 4 and all(
        r[s+'_arm_head_gap_px'] > 2 and r[s+'_upperarm_projected_fraction'] > .35
        and r[s+'_forearm_projected_fraction'] > .35 and 25 < r[s+'_elbow_angle_deg'] < 170
        for r in selected for s in ('L', 'R'))
    return dict(rows=rows, selected_camera=sc.camera.name, selected_four_poses_passed=passed,
                limits='Orthographic projected capsule estimates; not a visibility or beauty pass.')


def audit():
    sc = bpy.context.scene
    if sc.get('study') != 'confidence_v1':
        raise ValueError('Wrong scene')
    worst = joint = length = grip = drift = hold = step = 0.
    head_clear = body_clear = box_clear = stand_clear = floor = margin = 10.
    foot_ground = box_support = 0.
    previous = final = None
    fixed = {n: bpy.data.objects[n].matrix_world.copy() for n in
             ('L_foot','R_foot','Box','Plinth','L_handle','R_handle')}
    meshes = [o for o in sc.objects if o.type == 'MESH' and o.name != 'Floor']
    for i in range(8*(COUNT-1)+1):
        f = i/8
        t = f/FPS
        sc.frame_set(int(f), subframe=f%1)
        bpy.context.view_layer.update()
        p = {n: bpy.data.objects[n].matrix_world.translation.copy() for n in pose(t)}
        worst = max(worst, max((p[n]-v).length for n,v in pose(t).items()))
        actual_grips = {s: bpy.data.objects[s+'_handle'].matrix_world.translation for s in ('L','R')}
        grip = max(grip, contact_error(t, p, actual_grips))
        if previous:
            step = max(step, max((p[n]-previous[n]).length for n in p))
        previous = p
        if t >= 6.30:
            final = final or p
            hold = max(hold, max((p[n]-final[n]).length for n in p))
        for n,m in fixed.items():
            drift = max(drift, max(abs(a-b) for row0,row1 in zip(m,bpy.data.objects[n].matrix_world)
                                   for a,b in zip(row0,row1)))
        rods = {}
        center = bpy.data.objects['Box'].matrix_world.translation
        for n,(a,b) in LINKS.items():
            ob = bpy.data.objects[n]
            ends = [ob.matrix_world@Vector((0,0,z)) for z in (-.5,.5)]
            rods[n] = ends
            joint = max(joint, (ends[0]-p[a]).length, (ends[1]-p[b]).length)
            length = max(length, abs((ends[1]-ends[0]).length-geom.LENGTHS[n.split('_')[-1]]))
            box_clear = min(box_clear, geom.segment_box_distance(*ends, center)-geom.radius_for(n))
            # Conservative lower bound using existing segment/AABB distance:
            # scale pedestal to the existing box, multiply by minimum scale.
            ratio = Vector(tuple(geom.HALF[k]/STAND_HALF[k] for k in range(3)))
            scaled = [Vector(tuple((e[k]-STAND[k])*ratio[k] for k in range(3))) for e in ends]
            stand_clear = min(stand_clear, geom.segment_box_distance(*scaled, Vector())/max(ratio)-geom.radius_for(n))
            if n.endswith(('upperarm','forearm')):
                head_clear = min(head_clear, point_segment(p['head'],*ends)-.14-geom.radius_for(n))
        for n in ('L_upperarm','R_upperarm','L_forearm','R_forearm'):
            for other in ('torso','L_thigh','R_thigh','L_shin','R_shin'):
                body_clear = min(body_clear, segment_distance(*rods[n],*rods[other])-
                                 geom.radius_for(n)-geom.radius_for(other))
        for n, value in p.items():
            box_clear = min(box_clear, geom.segment_box_distance(value,value,center)-bpy.data.objects[n]['radius'])
        # Bounding boxes include all visible meshes; floor and both camera
        # margins sampled at whole frames, capsules/contact at eighth frames.
        if i%8 == 0:
            for ob in meshes:
                corners = [ob.matrix_world@Vector(c) for c in ob.bound_box]
                bottom = min(c.z for c in corners)
                floor = min(floor, bottom)
                if ob.name in ('L_foot','R_foot'):
                    foot_ground = max(foot_ground, abs(bottom))
                if ob.name == 'Box':
                    box_support = max(box_support, abs(bottom-.4))
                for cam in ('profile','three_quarter'):
                    for corner in corners:
                        uv = world_to_camera_view(sc, bpy.data.objects[cam], corner)
                        margin = min(margin, uv.x, uv.y, 1-uv.x, 1-uv.y)
    report = dict(samples=8*(COUNT-1)+1, duration_s=COUNT/FPS, max_playback_error_m=worst,
                  max_joint_error_m=joint, max_length_error_m=length, max_grip_error_m=grip,
                  min_arm_head_clearance_m=head_clear, min_arm_body_clearance_m=body_clear,
                  min_character_box_clearance_m=box_clear, min_limb_plinth_clearance_bound_m=stand_clear,
                  min_frame_margin=margin, min_floor_m=floor, max_foot_ground_error_m=foot_ground,
                  max_box_support_error_m=box_support, max_fixed_transform_drift=drift,
                  max_final_hold_drift_m=hold, max_eighth_frame_step_m=step)
    report['passed'] = (worst < .002 and joint < .002 and length < .0001 and grip < .001
                        and min(head_clear,body_clear,box_clear,stand_clear) > 0
                        and margin > .025 and floor > -.0001 and foot_ground < .0001
                        and box_support < .0001 and drift < 1e-6 and hold < 1e-6 and step < .02)
    report['limits'] = ('Selected capsule/AABB checks, whole-frame bounds; no complete mesh self-collision, '
                        'finger grasp, physical mass/balance, face acting or temporal visual review.')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=('build','audit','render'), default='build')
    parser.add_argument('--probes', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    out = args.out.resolve()
    if not out.is_relative_to(OUTPUT_ROOT.resolve()) or out == OUTPUT_ROOT.resolve():
        raise ValueError('Output must be a fresh child of _game/study/confidence')
    if args.probes and args.mode != 'build':
        raise ValueError('Probes only on a fresh build; no overwrite or full-render mode')
    if args.mode == 'build':
        out.mkdir(parents=True, exist_ok=False)
        rejected = preflight()
        setup()
        # Preserve exact authored poses and source fingerprints beside the bake.
        sources = [Path(__file__), *[Path(m.__file__) for m in (geom,sys.modules['study_throw'],
                    sys.modules['study_pointing'],sys.modules['study_reconsider'])]]
        manifest = dict(sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                        negative_probes=rejected, fps=FPS, count=COUNT, beats=BEATS,
                        blocking_frames=BLOCK, probe_frames=PROBES,
                        render='optional 2 stills, Cycles CPU, 320x240, 8 samples, CPU OIDN, 2 threads')
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        (out/'poses.json').write_text(json.dumps({str(f):{n:list(v) for n,v in pose(f/FPS).items()}
                                                for f in sorted(set(BLOCK) | {round(t*FPS) for t,_ in BEATS})},
                                               indent=2), encoding='utf-8')
        bpy.context.preferences.filepaths.file_preview_type = 'NONE'
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'), use_scripts=False)
    report = audit()
    report['saved_scene_reopened'] = True
    # Audit never replaces old evidence; reserve report path exclusively.
    evidence = out
    if args.mode == 'render':
        evidence = out/'motion'
        evidence.mkdir(exist_ok=False)
        report['scene_sha256'] = hashlib.sha256((out/'scene.blend').read_bytes()).hexdigest()
    name = 'audit.json' if args.mode in ('build','render') else 'audit_repeat.json'
    with (evidence/name).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report), flush=True)
    if not report['passed']:
        raise ValueError('Saved-scene geometry failed; rendering forbidden')
    projection = projection_audit()
    with (evidence/('projection.json' if args.mode in ('build','render') else 'projection_repeat.json')).open('x', encoding='utf-8') as stream:
        json.dump(projection, stream, indent=2)
    if not projection['selected_four_poses_passed']:
        raise ValueError('Selected camera failed four-pose projection checks; rendering forbidden')
    if args.probes:
        folder = out/'probes'
        folder.mkdir(exist_ok=False)
        sc = bpy.context.scene
        cpu_settings(sc)
        for frame in PROBES:
            sc.frame_set(frame)
            sc.render.filepath = str(folder/f'key_{frame:03d}.png')
            bpy.ops.render.render(write_still=True)
    if args.mode == 'render':
        folder = evidence/'frames'
        folder.mkdir(exist_ok=False)
        sc = bpy.context.scene
        cpu_settings(sc)
        sc.render.resolution_x, sc.render.resolution_y = 480, 360
        sc.cycles.samples = 12
        sc.render.fps, sc.render.fps_base = FPS, 1.0
        sc.frame_start, sc.frame_end, sc.frame_step = 0, COUNT-1, 1
        sc.render.filepath = str(folder/'frame_')
        bpy.ops.render.render(animation=True)


if __name__ == '__main__':
    main()
