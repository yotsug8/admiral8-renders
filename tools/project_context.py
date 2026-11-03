"""Read a bounded repository handoff; no assistant service, network or packages."""
import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'docs/PROJECT_STATE.md'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', help='Part of an active section title, e.g. Лина')
    args = parser.parse_args()
    text = STATE.read_text(encoding='utf-8')
    sections = re.split(r'^## ', text, flags=re.MULTILINE)[1:]
    try:
        revision = subprocess.run(
            ['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = 'archive / Git unavailable'
    print(f'Revision: {revision}')
    print('Rules: AGENTS.md (read on first use; applies to any contributor).')
    print('Methods: docs/LEARNING.md; tools: docs/REPOSITORY_MAP.md.')
    print('Setup/resources: docs/SETUP.md, docs/LOCAL_FILES.md.')
    print('This summary is not a quality verdict or a replacement for task evidence.')
    if not args.task:
        print('\nActive sections (choose with --task):')
        for section in sections:
            print('- ' + section.splitlines()[0])
        return
    matches = [s for s in sections if args.task.casefold() in s.splitlines()[0].casefold()]
    if len(matches) != 1:
        parser.error(f'Expected one section, found {len(matches)}; run without --task for titles')
    print('\n## ' + matches[0].rstrip())


if __name__ == '__main__':
    main()
