"""Check Rain FK grip state isolation; run inside Blender with --disable-autoexec."""
import sys, hashlib, json, math, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/study/rain_handoff/helper_check'
OUT.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'_game/external/rain_v33/Rain v3.3/rain_v3.2.blend'
HELPER=ROOT/'tools/blender/rain_grip.py'
def save(name,data):
    (OUT/name).write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
import bpy
from mathutils import Matrix, Euler, Vector

# Execute an exact in-memory snapshot, without writing imported bytecode.
helper_bytes = HELPER.read_bytes()
namespace = {'__name__': 'reviewed_rain_grip'}
exec(compile(helper_bytes, str(HELPER), 'exec'), namespace)
capture, apply = namespace['capture'], namespace['apply']
report = {'helper_sha256': hashlib.sha256(helper_bytes).hexdigest(),
          'blender_version': bpy.app.version_string, 'checks': [], 'sides': {},
          'scope': 'Numeric FK controls only; no skin/contact/render/artistic assessment.',
          'tolerance': 2e-6}

def check(label, passed, **data):
    report['checks'].append({'name': label, 'passed': bool(passed), **data})

def flat(m):
    return tuple(float(v) for row in m for v in row)

def delta(a, b):
    values = [abs(x-y) for x, y in zip(a, b)]
    return max(values, default=0) if all(math.isfinite(x) for x in values) else math.inf

def snapshot():
    return {b.name: flat(b.matrix_basis) for b in rig.pose.bones}

def difference(a, b, names=None):
    return max((delta(a[n], b[n]) for n in (names if names is not None else a)), default=0)

def metric(label, value, tolerance=2e-6):
    check(label, value <= tolerance, max_abs_error=value if math.isfinite(value) else 'nonfinite')

def update():
    rig.update_tag()
    bpy.context.view_layer.update()

def expected(state, amounts, angles=None):
    targets = {f: (0, 0, 0) if f == 'thumb' else (35, 60, 40) for f in fingers}
    targets.update(angles or {})
    result = {}
    for f in fingers:
        a = amounts.get(f, 0) if isinstance(amounts, dict) else amounts
        t = max(0, min(1, a))
        t = t*t*(3-2*t)
        for j in (1, 2, 3):
            n = f'FK-{f.title()}{j}.{state["side"]}'
            x = math.radians(targets[f][j-1])*t
            c, s = math.cos(x), math.sin(x)
            # Analytic rotation matrix independent of the helper's Quaternion.
            rx = Matrix(((1,0,0,0),(0,c,-s,0),(0,s,c,0),(0,0,0,1)))
            result[n] = flat(state['basis'][n] @ rx)
    return result

fingers = ('index', 'middle', 'ring', 'pinky', 'thumb')
try:
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
    rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE' and 'FK-Index1.L' in o.pose.bones)
    report['rig'] = rig.name
    report['removed_meshes'] = sum(o.type == 'MESH' for o in bpy.data.objects)
    for o in list(bpy.data.objects):
        if o.type == 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)
    props = rig.pose.bones['Properties_IKFK']
    for side in ('left', 'right'):
        props['ik_fingers_' + side] = 0
    update()
    modes = {b.name: b.rotation_mode for b in rig.pose.bones}
    report['bone_count'] = len(rig.pose.bones)
    for side in ('L', 'R'):
        prefix = side + ':'
        before_capture = snapshot()
        state = capture(rig, side)
        metric(prefix+'capture_readonly', difference(before_capture, snapshot()), 0)
        check(prefix+'capture_15_names', len(state['names']) == 15)
        original = {n: m.copy() for n, m in state['basis'].items()}
        states = [('source', state)]
        # Test translations, pre-rotation, uniform scale and non-neutral thumb.
        for n in state['names']:
            rig.pose.bones[n].matrix_basis = Matrix.LocRotScale(
                Vector((.001, -.002, .003)), Euler((.13, -.19, .07)).to_quaternion(),
                Vector((1.03, 1.03, 1.03)))
        update()
        authored = capture(rig, side)
        metric(prefix+'capture_copies_not_aliases', max(delta(flat(state['basis'][n]), flat(m)) for n,m in original.items()), 0)
        states.append(('authored', authored))
        for kind, st in states:
            tag = prefix+kind+':'
            apply(rig, st, 0)
            update()
            base = snapshot()
            outside = [n for n in base if n not in st['names']]
            thumb = [n for n in st['names'] if 'Thumb' in n]
            for amount in (-3, 0, .25, .5, .75, 1, 3):
                apply(rig, st, amount)
                update()
                actual = snapshot()
                metric(tag+f'default_{amount}_expected', difference(expected(st, amount), actual))
                metric(tag+f'default_{amount}_thumb_unchanged', difference(base, actual, thumb))
                metric(tag+f'default_{amount}_outside_unchanged', difference(base, actual, outside), 0)
            custom = {'index': (12, 27, -4), 'thumb': (24, -18, 36)}
            apply(rig, st, .65, angles=custom)
            update()
            first = snapshot()
            metric(tag+'custom_angles_expected', difference(expected(st, .65, custom), first))
            for repeat in range(100):
                apply(rig, st, .65, angles=custom)
                update()
            metric(tag+'repeat100', difference(first, snapshot()), 0)
            for f in fingers:
                apply(rig, st, 1, angles=custom)
                apply(rig, st, {f: .8}, angles=custom)
                update()
                current = snapshot()
                metric(tag+f'independent_{f}_expected', difference(expected(st, {f:.8}, custom), current))
                unaffected = [n for n in base if not n.startswith('FK-'+f.title()) or not n.endswith('.'+side)]
                metric(tag+f'independent_{f}_others', difference(base, current, unaffected))
            apply(rig, st, 0, angles=custom)
            update()
            metric(tag+'reset', difference(base, snapshot()))
            metric(tag+'captured_reference_immutable', max(delta(flat(st['basis'][n]), base[n]) for n in st['names']))

        st = authored
        invalid = [
            ('unknown_finger', {'index': (4,5,6), 'thmub': (1,2,3)}),
            ('short', {'index': (4,5,6), 'thumb': (1,2)}),
            ('long', {'index': (4,5,6), 'thumb': (1,2,3,4)}),
            ('empty', {'index': (4,5,6), 'thumb': ()}),
            ('nan', {'index': (4,5,6), 'thumb': (1,float('nan'),3)}),
            ('inf', {'index': (4,5,6), 'thumb': (1,float('inf'),3)}),
            ('minus_inf', {'index': (4,5,6), 'thumb': (1,-float('inf'),3)}),
            ('nonnumeric', {'index': (4,5,6), 'thumb': (1,'bad',3)}),
            ('scalar_value', {'index': (4,5,6), 'thumb': 4}),
            ('none_value', {'index': (4,5,6), 'thumb': None}),
            ('nested_value', {'index': (4,5,6), 'thumb': (1,[],3)}),
            ('nonmapping', []),
        ]
        report['sides'][side] = {'invalid_angles': []}
        for name, angles in invalid:
            apply(rig, st, .37, angles={'thumb': (7,11,19)})
            update()
            before = snapshot()
            exc = None
            try:
                apply(rig, st, 1, angles=angles)
            except Exception as e:
                exc = {'type': type(e).__name__, 'message': str(e)}
            err = difference(before, snapshot())
            check(prefix+'invalid_'+name, exc is not None and err == 0,
                  exception=exc, max_abs_error=err if math.isfinite(err) else 'nonfinite')
            report['sides'][side]['invalid_angles'].append({'case': name, 'exception': exc, 'max_abs_error': err})
        # Finite Python float can overflow Blender's float32 quaternion angle.
        apply(rig, st, .37)
        before = snapshot()
        exc = None
        try:
            apply(rig, st, 1, angles={'thumb': (1e308, 2, 3)})
        except Exception as e:
            exc = {'type': type(e).__name__, 'message': str(e)}
        after = snapshot()
        nonfinite = [n for n,v in after.items() if not all(math.isfinite(x) for x in v)]
        changed = [n for n in after if delta(before[n], after[n]) > 0]
        check(prefix+'finite_extreme_angles_safe', not nonfinite and (exc is None or not changed),
              exception=exc, nonfinite_bones=nonfinite, changed_bones=changed)
        apply(rig, state, 0)
        update()
        metric(prefix+'final_source_reset', difference({n:flat(m) for n,m in original.items()}, snapshot()))
    check('rotation_modes_unchanged', all(b.rotation_mode == modes[b.name] for b in rig.pose.bones))
    check('fk_switches_unchanged', props['ik_fingers_left'] == 0 and props['ik_fingers_right'] == 0)
except Exception:
    report['fatal_exception'] = traceback.format_exc().replace(str(ROOT), '<project>')
finally:
    report['passed_count'] = sum(c['passed'] for c in report['checks'])
    report['failed_count'] = sum(not c['passed'] for c in report['checks'])
    save('review.json', report)
    print('REVIEW', report['passed_count'], 'passed', report['failed_count'], 'failed')
    for c in report['checks']:
        if not c['passed']:
            print('FINDING', c)
    if report.get('fatal_exception'):
        print(report['fatal_exception'])

if report.get('fatal_exception') or report['failed_count']:
    raise RuntimeError('Rain grip validation failed; see review.json')
