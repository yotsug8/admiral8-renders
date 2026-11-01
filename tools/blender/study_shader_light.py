"""Compare the existing Dota emission shader's key/ambient balance.

Only supports the known half-Lambert node topology; unknown layouts fail.
Never saves the source blend or changes animation/cameras/background materials.
"""
import argparse
import json
from pathlib import Path
import sys
import bpy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--frames', nargs='+', type=int, default=[30,90,360])
    p.add_argument('--key', type=float, default=.65)
    p.add_argument('--ambient', type=float, default=.95)
    p.add_argument('--candidate-only', action='store_true',
                   help='Render only candidate when baseline frames already exist')
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not 0 <= args.key <= 2 or not 0 <= args.ambient <= 2:
        raise ValueError('Study parameters must be within 0..2')
    scene = bpy.context.scene
    if any(not scene.frame_start <= f <= scene.frame_end for f in args.frames):
        raise ValueError('Frame outside source scene')
    targets = []
    for mat in bpy.data.materials:
        if not mat.get('_dota') or not mat.use_nodes:
            continue
        candidates = []
        for n in mat.node_tree.nodes:
            if n.type != 'MATH' or n.operation != 'MULTIPLY_ADD' or not n.inputs[0].is_linked:
                continue
            source = n.inputs[0].links[0].from_node
            if source.type == 'MATH' and source.operation == 'POWER' and source.inputs[1].default_value == 2:
                candidates.append(n)
        if len(candidates) != 1:
            raise ValueError('Unknown Dota lighting layout: '+mat.name)
        n = candidates[0]
        if n.inputs[1].is_linked or n.inputs[2].is_linked:
            raise ValueError('Animated/linked light strengths unsupported')
        targets.append((mat.name, n, n.inputs[1].default_value, n.inputs[2].default_value))
    if not targets:
        raise ValueError('No supported Dota shaders')
    out = args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    scene.render.resolution_x, scene.render.resolution_y = 360,640
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    try:
        for f in args.frames:
            scene.frame_set(f)
            for variant in (['candidate'] if args.candidate_only else ['before','candidate']):
                for name,n,key,ambient in targets:
                    n.inputs[1].default_value = key if variant == 'before' else args.key
                    n.inputs[2].default_value = ambient if variant == 'before' else args.ambient
                scene.render.filepath=str(out/f'{variant}_{f:04d}.png')
                bpy.ops.render.render(write_still=True)
    finally:
        for name,n,key,ambient in targets:
            n.inputs[1].default_value,n.inputs[2].default_value=key,ambient
    (out/'report.json').write_text(json.dumps(dict(frames=args.frames,key=args.key,
        ambient=args.ambient,materials=[dict(name=name,key=key,ambient=ambient) for name,n,key,ambient in targets],
        candidate_only=args.candidate_only,
        limits='Only requested frames checked; no whole-film or artistic acceptance.'),indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
