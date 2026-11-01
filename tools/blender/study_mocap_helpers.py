"""Isolate missing auxiliary-bone following on a copied, unaccepted Pudge study.

Two root-parented back-fat bones follow spine1's rigid delta. No skin weights,
source motion or production defaults change. Audit remains mandatory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import bpy
from bpy_extras import anim_utils

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_retarget_character as character
import study_retarget_smoke as api

FOLLOW = {'backfat5_0': 'spine1', 'backfat7_0': 'spine1'}


def build(source, output):
    path = source / 'character.blend'
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    arm = next(o for o in scene.objects if o.get('retarget_main'))
    scene.frame_set(1)
    bpy.context.view_layer.update()
    initial = {n: b.matrix.copy() for n, b in arm.pose.bones.items()}
    expected = []
    for frame in range(1, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        expected.append({n: arm.pose.bones[parent].matrix @ initial[parent].inverted() @ initial[n]
                         for n, parent in FOLLOW.items()})
    previous = {}
    for frame, matrices in enumerate(expected, 1):
        scene.frame_set(frame)
        for name, matrix in matrices.items():
            bone = arm.pose.bones[name]
            if bone.parent.name != 'root' or bone.constraints:
                raise ValueError('Expected unconstrained root-parented helper: ' + name)
            bone.rotation_mode = 'QUATERNION'
            bone.matrix = matrix
            if name in previous and bone.rotation_quaternion.dot(previous[name]) < 0:
                bone.rotation_quaternion.negate()
            previous[name] = bone.rotation_quaternion.copy()
            for channel in ('location', 'rotation_quaternion', 'scale'):
                bone.keyframe_insert(channel, frame=frame)
        bpy.context.view_layer.update()
    bag = anim_utils.action_get_channelbag_for_slot(arm.animation_data.action,
                                                  arm.animation_data.action_slot)
    for curve in bag.fcurves:
        if any(curve.data_path.startswith(f'pose.bones["{n}"]') for n in FOLLOW):
            for key in curve.keyframe_points:
                key.interpolation = 'LINEAR'
    error = 0.
    for frame, matrices in enumerate(expected, 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for name, matrix in matrices.items():
            error = max(error, max(abs(a-b) for ra, rb in zip(matrix, arm.pose.bones[name].matrix)
                                   for a, b in zip(ra, rb)))
    if error > 2e-5:
        raise ValueError('Helper keying failed: ' + str(error))
    scene.frame_set(1)
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'character.blend'))
    for name in ('live_matrices.json', 'source_motion.json'):
        shutil.copyfile(source / name, output / name)
    unchanged = hashlib.sha256(path.read_bytes()).hexdigest() == before
    report = {'source_sha256': before, 'source_unchanged': unchanged,
              'mapping': FOLLOW, 'keyed_matrix_error': error,
              'limits': 'Two helpers only. No skin or seam repair; not production-ready.'}
    (output / 'helpers.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not unchanged:
        raise ValueError('Source modified')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--mode', choices=('build', 'audit'), required=True)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.mode == 'build':
        build(args.source.resolve(), args.out.resolve())
    else:
        samples = json.loads((args.out / 'source_motion.json').read_text())['samples']
        api.FRAMES = [1+i/4 for i in range(4*(samples-1)+1)]
        character.audit(args.out.resolve(), moving_roots=('spine1', *FOLLOW))


if __name__ == '__main__':
    main()
