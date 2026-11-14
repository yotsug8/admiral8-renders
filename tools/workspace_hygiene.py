"""Read-only workspace audit. Findings are review candidates, never deletion approval."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCAL_AREAS = ('out', 'qa', 'cache', '_game', '_fv_work')
EXCLUDED = {'.git', 'vendor', '.venv', 'venv', 'env', 'node_modules',
            '.codex-attachments', '.codex-remote-attachments'}
GENERATED_SUFFIXES = {'.pyc', '.blend', '.blend1', '.mp4', '.exr', '.log'}


def directory_link(path):
    """Python 3.11 lacks Path.is_junction; reject Windows reparse points too."""
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) &
                                    getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def audit(root=ROOT, external=()):
    root = Path(root).resolve()
    if not (root / 'PROJECT_GUIDE.md').is_file() or not (root / 'tools/project_map.py').is_file():
        raise ValueError('Expected project root containing PROJECT_GUIDE.md and tools/project_map.py')
    findings, errors = [], []

    def add(kind, path, level='info'):
        findings.append({'kind': kind, 'path': str(path), 'level': level})

    def onerror(exc):
        errors.append(str(exc))

    # Do not traverse resource libraries, environments or directory links/junctions.
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        base = Path(folder)
        rel = base.relative_to(root)
        if not dirs and not files and base != root:
            add('empty_directory', rel.as_posix())
        kept = []
        for name in dirs:
            path = base / name
            if name in EXCLUDED or path == root / 'cache/resources':
                continue
            try:
                linked = directory_link(path)
            except OSError as exc:
                onerror(exc)
                continue
            if linked:
                add('directory_link_not_scanned', path.relative_to(root).as_posix())
                continue
            if name == '__pycache__':
                add('python_cache', path.relative_to(root).as_posix())
            else:
                kept.append(name)
        dirs[:] = kept
        for name in files:
            if name.endswith('.pyc'):
                add('python_bytecode', (rel / name).as_posix())

    tracked_status = 'unavailable'
    try:
        top = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], cwd=root,
                                      stderr=subprocess.DEVNULL).decode().strip()
        if Path(top).resolve() == root:
            tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8')
            tracked_status = 'checked'
            for name in filter(None, tracked.split('\0')):
                path = PurePosixPath(name)
                if path.parts[0] in LOCAL_AREAS or path.suffix.lower() in GENERATED_SUFFIXES:
                    add('tracked_production_or_generated_file', name, 'warning')
    except (OSError, subprocess.CalledProcessError) as exc:
        # A release archive can legitimately have no .git. This is not a passed Git audit.
        errors.append('Git index not checked: ' + str(exc))

    try:
        for candidate in root.parent.iterdir():
            if candidate == root or not candidate.is_dir() or directory_link(candidate):
                continue
            if re.search(r'(?:\d{8}|^\d{3,})', candidate.name) and (
                    (candidate / 'PROJECT_GUIDE.md').is_file() or
                    (candidate / 'video.py').is_file() and (candidate / 'tools/check.py').is_file()):
                add('numbered_sibling_project_review', candidate, 'warning')
    except OSError as exc:
        errors.append(str(exc))
    external_status = []
    for value in external:
        path = Path(value).expanduser().resolve()
        external_status.append({'path': str(path), 'exists': path.exists()})
        if path.exists():
            add('external_location_review', path, 'warning')
    return {'schema_version': 1, 'root': str(root), 'read_only': True,
            'local_areas': {name: (root / name).exists() for name in LOCAL_AREAS},
            'git_index': tracked_status, 'external': external_status,
            'findings': findings, 'errors': errors,
            'limits': 'No dependency/liveness proof; caches, empty directories and extra copies may be intentional.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--external', type=Path, action='append', default=[],
                        help='Explicit external location to check for leftover work; repeatable')
    parser.add_argument('--json', type=Path, help='Write report to a NEW file; never overwrite existing data')
    args = parser.parse_args()
    try:
        report = audit(args.root, args.external)
        if args.json:
            with args.json.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    counts = {}
    for item in report['findings']:
        counts[item['kind']] = counts.get(item['kind'], 0) + 1
    print(json.dumps({'root': report['root'], 'git_index': report['git_index'],
                      'counts': counts, 'errors': report['errors']}, ensure_ascii=False, indent=2))
    for item in report['findings'][:20]:
        print(f"{item['level']}: {item['kind']}: {item['path']}")
    if len(report['findings']) > 20:
        print('Only first 20 findings shown; --json saves the full report.')
    return 2 if report['errors'] else int(any(x['level'] == 'warning' for x in report['findings']))


if __name__ == '__main__':
    raise SystemExit(main())
