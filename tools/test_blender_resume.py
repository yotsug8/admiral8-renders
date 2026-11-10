"""Integration check for Blender resume. Run explicitly with Python 3.11."""

from array import array
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from textwrap import dedent
from uuid import uuid4
import wave

from paths import BLENDER
from skit.grade import FF


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='New folder for the recovery evidence')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = (args.out or root / 'qa' / ('resume-proof-' + uuid4().hex[:8])).resolve()
    out.mkdir(parents=True)
    blend = out / 'demo.blend'
    blender = BLENDER
    base = [blender, '-b', '--factory-startup', '--disable-autoexec', '-t', '4', '--python-exit-code', '2']
    builder = out / 'build.py'
    builder.write_text(dedent(f'''
    import bpy
    from mathutils import Vector
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.render.engine = 'BLENDER_EEVEE'
    s.eevee.taa_render_samples = 8
    s.render.fps = 24
    s.frame_start, s.frame_end = 1, 16
    bpy.ops.mesh.primitive_cube_add(size=1.3, location=(-1.5, 0, 0.65))
    cube = bpy.context.object
    m = bpy.data.materials.new('Amber'); m.diffuse_color = (0.8, 0.24, 0.02, 1)
    cube.data.materials.append(m)
    cube.keyframe_insert('location', frame=1)
    cube.location.x = 1.5; cube.rotation_euler.z = 1.1
    cube.keyframe_insert('location', frame=16); cube.keyframe_insert('rotation_euler', frame=16)
    cube.rotation_euler.z = 0; cube.keyframe_insert('rotation_euler', frame=1)
    bpy.ops.mesh.primitive_plane_add(size=200)
    floor = bpy.data.materials.new('Slate'); floor.diffuse_color = (0.055, 0.13, 0.18, 1)
    bpy.context.object.data.materials.append(floor)
    bpy.ops.object.camera_add(location=(0,-7,4))
    s.camera = bpy.context.object
    s.camera.rotation_euler = (Vector((0,0,0.5))-s.camera.location).to_track_quat('-Z','Y').to_euler()
    s.camera.data.lens = 42
    for name, pos, power in [('Key',(-3,-4,6),1800),('Fill',(3,1,4),1100)]:
        bpy.ops.object.light_add(type='AREA',location=pos)
        obj=bpy.context.object; obj.name=name; obj.data.energy=power; obj.data.size=4
        obj.rotation_euler=(-obj.location).to_track_quat('-Z','Y').to_euler()
    s.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})
    '''), encoding='utf-8')

    elapsed = {}

    def run(name, cmd, expected=0, env=None):
        started = time.perf_counter()
        with (out / name).open('w', encoding='utf-8') as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=90, env=env)
        elapsed[name.removesuffix('.log')] = round(time.perf_counter() - started, 3)
        if result.returncode != expected:
            raise RuntimeError((out / name).read_text(encoding='utf-8', errors='replace')[-2200:])

    run('build.log', base + ['-P', str(builder)])
    frames = out / 'frames'
    cmd = base + [str(blend), '-P', str(root / 'tools/blender/render_study_frames.py'), '--', '--out', str(frames),
                  '--range', '1:17', '--size', '320', '180', '--fps', '24', '--resume']
    with (out / 'interrupted.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            until = time.monotonic() + 45
            while len(list(frames.glob('f*.sha256'))) < 3 and process.poll() is None:
                if time.monotonic() >= until:
                    raise RuntimeError('First frames timed out')
                time.sleep(0.03)
            assert process.poll() is None, 'Render finished or failed before interruption'
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
    finished = sorted(frames.glob('f*.sha256'))
    assert 3 <= len(finished) < 16
    kept = finished[0].with_suffix('.png')
    previous = kept.read_bytes(), kept.stat().st_mtime_ns
    broken = finished[1].with_suffix('.png')
    broken.write_bytes(b'broken PNG')
    run('resumed.log', cmd)
    report = json.loads((frames / 'render_report.json').read_text(encoding='utf-8'))
    assert int(broken.stem[1:]) in report['rendered']
    assert len(report['reused']) == len(finished) - 1
    assert len(report['rendered']) + len(report['reused']) == 16
    assert (kept.read_bytes(), kept.stat().st_mtime_ns) == previous
    export_cmd = [sys.executable, '-X', 'utf8', str(root / 'tools/blender/export_render_job.py'),
                  str(blend), str(frames), '--range']
    run('encode_short.log', export_cmd + ['1:9'])
    movie = frames / 'preview.mp4'
    old_movie = movie.read_bytes(), movie.stat().st_mtime_ns
    saved_frames = {frame.name: frame.stat().st_mtime_ns for frame in frames.glob('f*.png')}
    stamp = frames / 'f0016.sha256'
    held_stamp = stamp.with_suffix('.held')
    stamp.rename(held_stamp)
    try:
        run('encode_incomplete.log', export_cmd + ['1:17'], expected=1)
        assert 'Нет проверенного кадра 16' in (out / 'encode_incomplete.log').read_text(encoding='utf-8')
        assert (movie.read_bytes(), movie.stat().st_mtime_ns) == old_movie
    finally:
        held_stamp.rename(stamp)
    probe = shutil.which(os.environ.get('FFPROBE') or 'ffprobe')
    if not probe:
        raise RuntimeError('ffprobe is required')
    # Run an actual process that rejects encoder options, without invoking Blender again.
    run('encode_failed.log', export_cmd + ['1:17'], expected=1,
        env=dict(os.environ, IMAGEIO_FFMPEG_EXE=probe))
    assert (movie.read_bytes(), movie.stat().st_mtime_ns) == old_movie
    run('encode_retry.log', export_cmd + ['1:17'])
    assert movie.read_bytes() != old_movie[0]
    assert {frame.name: frame.stat().st_mtime_ns for frame in frames.glob('f*.png')} == saved_frames
    wav = out / 'cue.wav'
    rate = 24_000
    with wave.open(str(wav), 'wb') as audio:
        audio.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        tone = array('h', (int(10_000 * math.sin(2 * math.pi * 440 * i / rate))
                           if 3000 <= i < 6000 else 0 for i in range(12_000)))
        stereo = array('h', (value for sample in tone for value in (sample, sample)))
        if sys.byteorder == 'big':
            stereo.byteswap()
        audio.writeframes(stereo.tobytes())
    job = out / 'job.json'
    job_data = dict(schema_version=1, scene=blend.name, out='delivery', frames=[1, 17],
                    size=[320, 180], fps=24, wav=wav.name)
    job_cmd = [sys.executable, '-X', 'utf8', str(root / 'tools/blender/run_render_job.py'), str(job)]
    job.write_text(json.dumps(dict(job_data, fps=True)), encoding='utf-8')
    run('job_invalid.log', job_cmd, expected=1)
    delivery = out / 'delivery'
    assert not delivery.exists()
    job.write_text(json.dumps(job_data, indent=2), encoding='utf-8')
    run('job_failed.log', job_cmd, expected=1, env=dict(os.environ, IMAGEIO_FFMPEG_EXE=probe))
    job_movie = delivery / 'preview.mp4'
    assert not job_movie.exists()
    job_report = delivery / 'render_report.json'
    assert json.loads(job_report.read_text(encoding='utf-8'))['rendered'] == list(range(1, 17))
    delivery_frames = {frame.name: frame.stat().st_mtime_ns for frame in delivery.glob('f*.png')}
    run('job_retry.log', job_cmd)
    retried = json.loads(job_report.read_text(encoding='utf-8'))
    assert retried['reused'] == list(range(1, 17)) and not retried['rendered']
    assert {frame.name: frame.stat().st_mtime_ns for frame in delivery.glob('f*.png')} == delivery_frames
    run('encode_wav.log', export_cmd + ['1:17', '--wav', str(wav)])
    def decode_audio(source):
        return subprocess.check_output([FF, '-v', 'error', '-xerror', '-i', str(source),
                                        '-map', '0:a:0', '-ac', '1', '-f', 's16le', '-'])

    decoded = decode_audio(movie)
    assert decoded == decode_audio(job_movie)
    pcm = array('h', decoded)
    if sys.byteorder == 'big':
        pcm.byteswap()
    onset = next(i for i, sample in enumerate(pcm) if abs(sample) > 3000)
    assert abs(onset - 6000) <= 240, onset
    assert len(pcm) >= 32_000 and max(map(abs, pcm[25_000:32_000])) < 100
    voiced_movie = movie.read_bytes(), movie.stat().st_mtime_ns
    long_wav = out / 'too_long.wav'
    with wave.open(str(long_wav), 'wb') as audio:
        audio.setparams((1, 2, 48_000, 0, 'NONE', 'not compressed'))
        audio.writeframes(bytes(2 * 32_001))
    run('wav_rejected.log', export_cmd + ['1:17', '--wav', str(long_wav)], expected=1)
    assert 'WAV длиннее' in (out / 'wav_rejected.log').read_text(encoding='utf-8')
    assert (movie.read_bytes(), movie.stat().st_mtime_ns) == voiced_movie
    assert {frame.name: frame.stat().st_mtime_ns for frame in frames.glob('f*.png')} == saved_frames
    changed = out / 'changed.blend'
    edit = f'import bpy; bpy.context.scene.camera.data.lens += 2; bpy.ops.wm.save_as_mainfile(filepath={str(changed)!r})'
    run('changed.log', base + [str(blend), '--python-expr', edit])
    run('rejected.log', [str(changed) if arg == str(blend) else arg for arg in cmd], expected=2)
    assert 'настройки изменились' in (out / 'rejected.log').read_text(encoding='utf-8', errors='replace')
    run('export_rejected.log', [str(changed) if arg == str(blend) else arg for arg in export_cmd] + ['1:17'], expected=1)
    assert 'отличается от версии' in (out / 'export_rejected.log').read_text(encoding='utf-8', errors='replace')
    assert (kept.read_bytes(), kept.stat().st_mtime_ns) == previous
    print(out)
    outcome = {'interrupted_after': len(finished), 'resumed': report,
               'incomplete_range_rejected': True, 'encoder_retry_preserved_frames': True,
               'audio_onset_at_48000': onset, 'audio_matches_between_commands': True,
               'long_wav_rejected': True, 'job_retry_reused': len(retried['reused']),
               'changed_scene_rejected': True, 'elapsed_seconds': elapsed}
    summary = json.dumps(outcome, ensure_ascii=False, indent=2)
    (out / 'recovery-report.json').write_text(summary + '\n', encoding='utf-8')
    print(summary)


if __name__ == '__main__':
    main()
