"""Reproduce a saved chase mix exactly, then repan only the camera edit window.

Run with Python: chase_camera_audio.py --blender PATH. Blender child processes
only evaluate event positions; they never render or save scenes. Existing source
hashes and a bit-exact full mix reconstruction are mandatory before output.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / '_game/skits/chase_v2'
START, END = 4.8, 8.0


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def project(events_path, output, start=START, end=END):
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    camera = sc.camera
    assert camera is not None
    fps = sc.render.fps / sc.render.fps_base
    assert fps == 30
    root = sc.objects['hoodwink_root']
    rows = []
    for event in json.loads(events_path.read_text(encoding='utf-8'))['footsteps']:
        t = event['at']
        if not start <= t < end:
            continue
        f = t * fps
        assert start*fps <= f < end*fps
        sc.frame_set(math.floor(f), subframe=f % 1)
        # The prepared candidate's selected camera is the intended camera.
        sc.camera = camera
        bpy.context.view_layer.update()
        point = root.matrix_world.translation
        uv = world_to_camera_view(sc, camera, point)
        assert all(math.isfinite(x) for x in (*point, *uv)) and uv.z > 0
        rows.append(dict(at=t, frame=f, camera=camera.name,
                         root=list(point), uv=list(uv),
                         pan=max(-.8, min(.8, 2 * uv.x - 1))))
    save(output, rows)


def main():
    global END
    import numpy as np
    import chase_audio as audio
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True, type=Path)
    parser.add_argument('--out', type=Path, default=BASE/'close_camera_audio')
    parser.add_argument('--second-shot', type=Path,
                        help='Optional camera-only scene for the second chase shot, 8.0–11.2 s')
    args = parser.parse_args()
    if args.second_shot:
        if args.out == BASE/'close_camera_audio':
            parser.error('--second-shot requires a separate --out directory')
        END = 11.2
    out = args.out.resolve()
    olddir = BASE/'lively_fix/audio'
    assert out != olddir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = olddir/'chase_candidate.wav'
    events_path = olddir/'events_used.json'
    report_path = olddir/'report.json'
    old = json.loads(report_path.read_text(encoding='utf-8'))
    events = json.loads(events_path.read_text(encoding='utf-8'))
    assets = REPO/'_game/skits/chase_finish/audio'
    protected = [original, events_path, report_path, BASE/'lively_fix/scene.blend',
                 BASE/'close_camera/camera_candidate.blend']
    if args.second_shot:
        protected.append(args.second_shot.resolve())
    hashes = {p: sha(p) for p in protected}
    assert sha(original) == old['candidate_sha256']
    assert sha(events_path) == old['events_sha256']
    for file, expected in old['source_sha256'].items():
        assert sha(assets/file) == expected, file
    cues = old['cues']
    assert len(cues) == len(events['footsteps']) + 2
    for cue, event in zip(cues[2:], events['footsteps']):
        assert cue['at'] == event['at'] and cue['pan'] == event['pan']
        assert cue['gain'] == .2 * event['gain']

    def assemble(pans=None):
        mix = np.zeros((round(old['timeline']['duration']*audio.SR), 2), np.float64)
        for i, cue in enumerate(cues):
            a = audio.decode(assets/cue['file'], 1, cue['pitch'])[:, 0]
            assert len(a) == cue['source_samples']
            a = a[:cue['retained_samples']].copy()
            fi, fo = ((.12, .15) if i == 0 else (0, 0) if i == 1 else (.005, .025))
            for seconds, incoming in ((fi, True), (fo, False)):
                k = min(len(a), round(seconds*audio.SR))
                if k:
                    if incoming:
                        a[:k] *= np.linspace(0, 1, k)
                    else:
                        a[-k:] *= np.linspace(1, 0, k)
            pan = pans.get(cue['at'], cue['pan']) if pans and i >= 2 else cue['pan']
            angle = (pan+1)*math.pi/4
            stereo = a[:, None]*cue['gain']*np.array([math.cos(angle), math.sin(angle)])
            start = round(cue['at']*audio.SR)
            mix[start:start+len(a)] += stereo
        return mix * 10**(old['master_gain_db']/20)

    baseline = assemble()
    restored = audio.encode(baseline)
    assert restored == original.read_bytes(), 'Exact reconstruction failed; no substitute mix allowed'
    projections = [('old', protected[3], START, END), ('new', protected[4], START, 8.0)]
    if args.second_shot:
        projections.append(('second', protected[5], 8.0, END))
    for label, blend, start, end in projections:
        cmd = [str(args.blender), '--disable-autoexec', '-b', str(blend), '-t', '2', '--python-exit-code', '1',
               '-P', str(Path(__file__).resolve()), '--', '--project', str(events_path),
               str(out/f'{label}_projection.json'), str(start), str(end)]
        with (out/f'{label}_projection.log').open('w', encoding='utf-8') as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    before = json.loads((out/'old_projection.json').read_text())
    after = json.loads((out/'new_projection.json').read_text())
    if args.second_shot:
        after += json.loads((out/'second_projection.json').read_text())
    selected = [e for e in events['footsteps'] if START <= e['at'] < END]
    assert len(before) == len(after) == len(selected) and selected
    for b, a, e in zip(before, after, selected):
        assert b['at'] == a['at'] == e['at']
        assert abs(b['pan'] - e['pan']) < 1e-6, 'Old camera does not reproduce saved pan'
        assert np.max(np.abs(np.array(b['root'])-a['root'])) < 1e-6
    pans = {a['at']: a['pan'] for a in after}
    revised = assemble(pans)
    lo, hi = round(START*audio.SR), round(END*audio.SR)
    # Complementary linear weights reach baseline on the last sample BEFORE END.
    # This removes the edit discontinuity without modifying any later PCM.
    transition_samples = round(.010 * audio.SR)
    fade_start = hi - transition_samples
    weight = np.linspace(0., 1., transition_samples)[:, None]
    revised[fade_start:hi] = ((1-weight)*revised[fade_start:hi]
                              + weight*baseline[fade_start:hi])
    revised[:lo] = baseline[:lo]
    revised[hi:] = baseline[hi:]
    wav = audio.encode(revised)
    target = out/'chase_candidate.wav'
    target.write_bytes(wav)
    a, b = audio.decode(target), audio.decode(original)
    assert np.array_equal(a[:lo], b[:lo]) and np.array_equal(a[hi:], b[hi:])
    assert len(a) == len(b) and not np.array_equal(a[lo:hi], b[lo:hi])
    boundary_difference = (a[hi]-a[hi-1]) - (b[hi]-b[hi-1])
    assert np.array_equal(a[hi-1:hi+1], b[hi-1:hi+1])
    assert np.count_nonzero(boundary_difference) == 0
    transition = dict(policy='Linear complementary PCM crossfade revised to baseline',
                      start_s=fade_start/audio.SR, end_s=END,
                      samples=transition_samples, baseline_weight_first=0,
                      baseline_weight_last=1,
                      endpoint=f'Last sample strictly before {END} s is baseline',
                      outside_window='Bit-exact original PCM')
    stats = {**audio.metrics(a, old['timeline']['black_start'], old['timeline']['duration']),
             **audio.loudness(wav)}
    assert stats['clipped_samples'] == 0 and stats['true_peak_dbtp'] <= -1
    assert stats['black_tail_nonzero_samples'] == 0
    updated = copy.deepcopy(events)
    for e, orig in zip(updated['footsteps'], events['footsteps']):
        if START <= e['at'] < END:
            e['pan'] = pans[e['at']]
        assert {k:v for k,v in e.items() if k != 'pan'} == {k:v for k,v in orig.items() if k != 'pan'}
    updated['camera_pan_window_s'] = [START, END]
    updated['tail_policy'] = f'Crossfade to original PCM over {END-.01:.3f}–{END:.3f} s; original PCM after window.'
    updated['transition'] = transition
    save(out/'events_used.json', updated)
    assert all(sha(p) == h for p,h in hashes.items())
    assert all(sha(assets/f) == h for f,h in old['source_sha256'].items())
    report = dict(status='verified', audio_heard=False, window_s=[START, END],
        changed_events=len(selected), total_events=len(events['footsteps']),
        exact_original_wav_reconstruction=True, outside_window_pcm_bit_exact=True,
        times_samples_pitch_gain_voice_unchanged=True, source_files_unchanged=True,
        master_gain_db=old['master_gain_db'], candidate=stats,
        transition=transition,
        boundary_jump_difference_vs_baseline_per_channel=boundary_difference.tolist(),
        boundary_adjacent_samples_bit_exact=True,
        boundary_sample_jump={str(t):float(abs(a[round(t*audio.SR)]-a[round(t*audio.SR)-1]).max())
                              for t in (START, END)},
        boundary_original_jump={str(t):float(abs(b[round(t*audio.SR)]-b[round(t*audio.SR)-1]).max())
                                for t in (START, END)},
        pan_changes=[dict(at=e['at'], old=e['pan'], new=pans[e['at']]) for e in selected],
        inputs_sha256={p.relative_to(REPO).as_posix():h for p,h in hashes.items()},
        source_sha256=old['source_sha256'], output_sha256=sha(target),
        limitations=['No listening or ASR; no visual contact audit.',
                     'Projection uses actor root at event onset, matching study_contact_events.py.',
                     'No distance gain change or master renormalization.',
                     'Last 10 ms before window end crossfade to baseline; later tail remains original.',
                     'No renders, TTS, scene saves or MP4 changes.'])
    save(out/'report.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    if '--project' in sys.argv:
        i = sys.argv.index('--project')
        project(Path(sys.argv[i+1]), Path(sys.argv[i+2]), float(sys.argv[i+3]), float(sys.argv[i+4]))
    else:
        main()
