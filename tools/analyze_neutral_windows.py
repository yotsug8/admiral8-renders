"""Analyze parent/pelvis rotations against an explicit neutral-matrix JSON."""
import argparse
import json
import math
from pathlib import Path

import numpy as np


def rotation(matrix):
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError('Expected a finite 4x4 matrix')
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-6, rtol=0):
        raise ValueError('Expected an affine matrix')
    if np.linalg.det(matrix[:3, :3]) <= 0:
        raise ValueError('Singular or reflected matrix is not a rotation basis')
    u, _, v = np.linalg.svd(matrix[:3, :3])
    return u @ v


def angle(a, b):
    return math.degrees(math.acos(float(np.clip((np.trace(a.T @ b)-1)/2, -1, 1))))


def analyze(data, neutral, window_size=60, pelvis='Hips', focus='Head', forward=(0., -1., 0.)):
    names = list(neutral)
    samples = data['samples']
    count = len(samples)
    if not 2 <= window_size <= count:
        raise ValueError('Window size must be between 2 and the sample count')
    if pelvis not in names or focus not in names or focus == pelvis:
        raise ValueError('Pelvis and a distinct focus bone must be present')
    for previous, current in zip(samples, samples[1:]):
        if current['frame'] != previous['frame']+1 or current['amc_sample'] != previous['amc_sample']+1:
            raise ValueError('Frame and source-sample labels must be consecutive')
    forward = np.asarray(forward, dtype=float)
    if forward.shape != (3,) or not np.isfinite(forward).all() or abs(forward[2]) > 1e-9 or np.linalg.norm(forward) < 1e-9:
        raise ValueError('Heading reference must be a nonzero horizontal vector')
    forward = forward / np.linalg.norm(forward)
    nr = {name: rotation(matrix) for name, matrix in neutral.items()}
    relative = {name: {space: [] for space in ('pelvis', 'parent')}
                for name in names if name != pelvis}
    for name in relative:
        if data['rest'][name]['parent'] not in names:
            raise ValueError('Neutral matrices must include each audited bone parent')
    rows = []
    for sample in samples:
        wr = {name: rotation(sample['bones'][name]['world_matrix']) for name in names}
        row = {'frame': sample['frame'], 'amc': sample['amc_sample'], 'bones': {}}
        for name in relative:
            parent = data['rest'][name]['parent']
            row['bones'][name] = {}
            for space, reference in (('pelvis', pelvis), ('parent', parent)):
                actual = wr[reference].T @ wr[name]
                neutral_relative = nr[reference].T @ nr[name]
                relative[name][space].append(actual)
                delta = nr[reference] @ actual @ neutral_relative.T @ nr[reference].T
                direction = delta @ forward
                if math.hypot(direction[0], direction[1]) < 1e-6:
                    raise ValueError('Heading projection is undefined near vertical')
                yaw = math.degrees(math.atan2(forward[0]*direction[1]-forward[1]*direction[0],
                                             forward[0]*direction[0]+forward[1]*direction[1]))
                row['bones'][name][space] = {
                    'angle_from_converter_tpose_deg': angle(neutral_relative, actual),
                    'heading_deg': yaw,
                }
        rows.append(row)
    windows = []
    for start in range(0, count-window_size+1, window_size):
        stop = start+window_size
        item = {'frames': [samples[start]['frame'], samples[stop-1]['frame']],
                'amc': [samples[start]['amc_sample'], samples[stop-1]['amc_sample']], 'bones': {}}
        for name in relative:
            item['bones'][name] = {}
            for space in ('pelvis', 'parent'):
                values = [row['bones'][name][space]['angle_from_converter_tpose_deg'] for row in rows[start:stop]]
                yaw = np.degrees(np.unwrap(np.radians([row['bones'][name][space]['heading_deg'] for row in rows[start:stop]])))
                matrices = relative[name][space][start:stop]
                item['bones'][name][space] = {
                    'absolute_range_deg': [min(values), max(values)],
                    'max_pairwise_excursion_deg': max(angle(a, b) for a in matrices for b in matrices),
                    'max_step_deg': max(angle(a, b) for a, b in zip(matrices, matrices[1:])),
                    'heading_start_end_deg': [float(yaw[0]), float(yaw[-1])],
                }
        windows.append(item)
    pairwise = {name: {} for name in relative}
    for name in relative:
        for space in ('pelvis', 'parent'):
            flat = np.array(relative[name][space]).reshape(count, 9)
            pairwise[name][space] = np.degrees(np.arccos(np.clip((flat @ flat.T-1)/2, -1, 1)))
    rolling = []
    for start in range(count-window_size+1):
        stop = start+window_size
        rolling.append({
            'frames': [samples[start]['frame'], samples[stop-1]['frame']],
            'max_pairwise_excursion_deg': {
                name: {space: float(array[start:stop, start:stop].max()) for space, array in spaces.items()}
                for name, spaces in pairwise.items()},
        })
    best = min(rolling, key=lambda window: window['max_pairwise_excursion_deg'][focus]['pelvis'])
    return {'neutral': 'Empirical converter T-pose, NOT calibrated anatomical neutral',
            'frames': count, 'window_size': window_size, 'windows': windows,
            'best_rolling_by_head_pelvis': best, 'rolling': rolling, 'per_frame': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rotations', required=True, type=Path)
    parser.add_argument('--neutral', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--window-size', type=int, default=60)
    parser.add_argument('--pelvis', default='Hips')
    parser.add_argument('--focus-bone', default='Head')
    parser.add_argument('--forward', type=float, nargs=3, default=(0., -1., 0.))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new file')
    data = json.loads(args.rotations.read_text(encoding='utf-8'))
    neutral = json.loads(args.neutral.read_text(encoding='utf-8'))
    result = analyze(data, neutral, args.window_size, args.pelvis, args.focus_bone, args.forward)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as file:
        json.dump(result, file, indent=2, allow_nan=False)
        file.write('\n')
    print(json.dumps({'frames': result['frames'], 'blocks': len(result['windows']),
                      'rolling_windows': len(result['rolling']),
                      'best_frames': result['best_rolling_by_head_pelvis']['frames']}))


if __name__ == '__main__':
    main()
