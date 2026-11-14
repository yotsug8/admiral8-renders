"""Print a compact, live source index; no model, network or dependencies required."""
import argparse
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
AREAS = {
    'render': ['tools/blender/run_render_job.py', 'tools/blender/export_render_job.py',
               'tools/blender/assemble_shots.py', 'tools/render_storage.py'],
    'scene': ['tools/scene_request_3d.py', 'tools/scene_revision.py',
              'tools/blender/scene_plan.py', 'tools/blender/contact_metrics.py'],
    'dota': ['tools/dota_engine/project.py', 'tools/dota_engine/hero_parts.py',
             'tools/blender/dota_map.py', 'tools/blender/render_scene.py'],
    'audio': ['tools/skit/mix.py', 'tools/skit/voices.py', 'tools/skit/character_voice.py',
              'tools/dialogue_request.py'],
    '2d': ['video.py', 'video.html', 'scene.js', 'scene_resources.js', 'scene_lottie.js'],
    'setup': ['requirements.txt', 'tools/paths.py', 'tools/resource_paths.py', 'tools/quickstart.py'],
    'qa': ['tools/check.py', 'tools/check_pipeline.py', 'tools/reference_review.py'],
}


def tracked_files():
    result = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT)
    return sorted(p for p in result.decode('utf-8').split('\0') if p and (ROOT / p).is_file())


def describe(path):
    file = ROOT / path
    print(path)
    if file.suffix != '.py':
        return
    tree = ast.parse(file.read_text(encoding='utf-8-sig'), filename=path)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            print('  ' + ast.unparse(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            print(f'  {node.lineno}: {node.name}({ast.unparse(node.args)})')
        elif isinstance(node, ast.ClassDef):
            print(f'  {node.lineno}: class {node.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area', choices=AREAS)
    parser.add_argument('--find', help='Case-insensitive fragment of a tracked path')
    parser.add_argument('--symbols', action='store_true', help='Top-level Python signatures and imports')
    parser.add_argument('--check', action='store_true', help='Fail if an indexed entry is missing')
    args = parser.parse_args()
    missing = [p for group in AREAS.values() for p in group if not (ROOT / p).is_file()]
    if missing:
        parser.error('Missing indexed files: ' + ', '.join(missing))
    if args.check:
        print(f'Index OK: {sum(map(len, AREAS.values()))} entry points')
        return
    if args.find:
        files = [p for p in tracked_files() if args.find.casefold() in p.casefold()]
    elif args.area:
        files = AREAS[args.area]
    else:
        for area, paths in AREAS.items():
            print(area + ': ' + ', '.join(paths))
        print('Rules/state/lessons: PROJECT_GUIDE.md; local assets: cache/resources/, _game/; work: out/, qa/')
        return
    for path in files:
        describe(path) if args.symbols else print(path)


if __name__ == '__main__':
    main()
