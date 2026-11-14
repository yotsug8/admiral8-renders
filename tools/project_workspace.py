"""Create a clean production workspace from a prompt; this does not generate a video."""
import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def create(parent, name, prompt):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', name):
        raise ValueError('Project name must use lowercase letters, digits, _ or -')
    if not prompt.strip():
        raise ValueError('A nonempty prompt is required')
    parent = Path(parent).resolve()
    folder = parent / name
    folder.mkdir(parents=True, exist_ok=False)
    for child in ('source', 'scenes', 'audio', 'renders', 'qa'):
        (folder / child).mkdir()
    data = {
        'schema_version': 1, 'id': name, 'prompt': prompt.strip(), 'status': 'planning',
        'brief': {}, 'shots': [], 'assets': [], 'decisions': [], 'feedback': [],
        'checks': [], 'deliverables': [], 'next_step': 'Read PROJECT_GUIDE.md and prepare the brief',
    }
    (folder / 'project.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--parent', type=Path, default=ROOT / 'out')
    args = parser.parse_args()
    try:
        print(create(args.parent, args.name, args.prompt))
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
