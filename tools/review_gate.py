"""Check review records against current files; this cannot judge artistic quality.

Paths in review.artifacts and requirements[].evidence_files are relative to the
project.json directory. Each record has path and sha256. Artifacts must include
roles video and source (the scene or authored input). Read-only by default;
--mark-ready records readiness after validation. Neither mode produces evidence
or certifies that all applicable rules were found.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def guide_anchors(text):
    anchors = set(re.findall(r'<a\s+id=[\"\']([^\"\']+)[\"\']', text))
    counts = {}
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.MULTILINE):
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        anchors.add(slug if not count else f'{slug}-{count}')
        counts[slug] = count + 1
    return anchors


def validate(project_file, guide=None):
    """Return all metadata errors without editing the project or its evidence."""
    project_file = Path(project_file).resolve()
    guide = Path(guide) if guide is not None else ROOT / 'PROJECT_GUIDE.md'
    errors, hashes = [], {}
    try:
        project = json.loads(project_file.read_text(encoding='utf-8-sig'))
        guide_text = guide.read_text(encoding='utf-8-sig')
    except (OSError, ValueError) as exc:
        return [f'Cannot read project/guide: {exc}']
    if not isinstance(project, dict):
        return ['Project must be a JSON object']
    anchors = guide_anchors(guide_text)

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def file_record(record, label):
        if not isinstance(record, dict):
            errors.append(f'{label}: expected path/sha256 object')
            return
        relative = record.get('path')
        if not text(relative):
            errors.append(f'{label}: file path is required')
            return
        win = PureWindowsPath(relative)
        path = Path(relative)
        if path.is_absolute() or win.drive or win.root or ':' in relative or '..' in win.parts:
            errors.append(f'{label}: path must stay inside the work directory')
            return
        target = (project_file.parent / path).resolve()
        if not target.is_relative_to(project_file.parent):
            errors.append(f'{label}: path resolves outside the work directory')
            return
        expected = record.get('sha256')
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            errors.append(f'{label}: valid SHA-256 is required')
            return
        try:
            if target not in hashes:
                hashes[target] = sha256(target)
            if hashes[target] != expected:
                errors.append(f'{label}: stale or changed file: {relative}')
        except OSError as exc:
            errors.append(f'{label}: cannot read {relative}: {exc}')

    review = project.get('review')
    if not isinstance(review, dict):
        errors.append('review must be an object')
        review = {}
    if review.get('guide_sha256') != sha256(guide):
        errors.append('review: guide SHA-256 missing or stale; reassess current instructions')
    if not text(review.get('coverage_note')):
        errors.append('review: coverage_note explaining applicability review is required')
    try:
        when = datetime.fromisoformat(review.get('reviewed_at', '').replace('Z', '+00:00'))
        if when.utcoffset() is None:
            raise ValueError('timezone is required')
    except (ValueError, TypeError, AttributeError):
        errors.append('review: reviewed_at must be an ISO timestamp with timezone')
    artifacts = review.get('artifacts')
    roles = set()
    if not isinstance(artifacts, list) or not artifacts:
        errors.append('review: current video and source artifacts are required')
    else:
        for index, record in enumerate(artifacts):
            if isinstance(record, dict) and text(record.get('role')):
                roles.add(record['role'])
            else:
                errors.append(f'artifacts[{index}]: role is required')
            file_record(record, f'artifacts[{index}]')
        if not {'video', 'source'}.issubset(roles):
            errors.append('review: artifacts must include both video and source roles')

    requirements = project.get('requirements')
    if not isinstance(requirements, list) or not requirements:
        errors.append('requirements must be a nonempty applicability checklist')
        return errors
    seen = set()
    for index, requirement in enumerate(requirements):
        label = f'requirements[{index}]'
        if not isinstance(requirement, dict):
            errors.append(f'{label}: expected an object')
            continue
        identifier = requirement.get('id')
        if not text(identifier) or identifier in seen:
            errors.append(f'{label}: id must be nonempty and unique')
        else:
            seen.add(identifier)
            label = identifier
        source = requirement.get('source', '')
        if not isinstance(source, str) or not source.startswith('PROJECT_GUIDE.md#') or source.split('#', 1)[1] not in anchors:
            errors.append(f'{label}: source must reference an existing PROJECT_GUIDE.md anchor')
        if not text(requirement.get('criterion')):
            errors.append(f'{label}: criterion is required')
        status = requirement.get('status')
        if status == 'not_applicable':
            if not text(requirement.get('reason')):
                errors.append(f'{label}: not_applicable requires a reason')
        elif status == 'verified':
            if not text(requirement.get('method')):
                errors.append(f'{label}: verified requires a verification method')
            evidence = requirement.get('evidence_files')
            if not isinstance(evidence, list) or not evidence:
                errors.append(f'{label}: verified requires hashed evidence_files')
            else:
                for index, record in enumerate(evidence):
                    file_record(record, f'{label}.evidence_files[{index}]')
        else:
            errors.append(f'{label}: unresolved status {status!r}')
    return errors


def mark_ready(project_file, guide=None):
    """Explicitly mark reviewed metadata ready; preserve the file on validation failure."""
    project_file = Path(project_file).resolve()
    try:
        before = project_file.read_bytes()
        errors = validate(project_file, guide)
        if errors:
            return errors
        if project_file.read_bytes() != before:
            return ['Project changed during verification; retry after the writer finishes']
        project = json.loads(before.decode('utf-8-sig'))
        project['status'] = 'ready_for_user_review'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=project_file.parent,
                                             prefix='.review-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(project, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            if project_file.read_bytes() != before:
                return ['Project changed before readiness write; no changes applied']
            os.replace(temporary, project_file)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return []
    except (OSError, ValueError) as exc:
        return [f'Cannot mark project ready: {exc}']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='Path to the work project.json')
    parser.add_argument('--mark-ready', action='store_true',
                        help='Atomically set ready_for_user_review only after validation passes')
    args = parser.parse_args(argv)
    errors = mark_ready(args.project) if args.mark_ready else validate(args.project)
    print(json.dumps({'status': 'blocked' if errors else 'metadata_ready', 'errors': errors,
                     'limits': 'Checks current review records and hashes only; does not certify artistic quality or completeness of instruction coverage.'},
                    ensure_ascii=True, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
