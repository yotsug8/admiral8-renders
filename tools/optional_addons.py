"""Install pinned optional Blender add-ons into the local resource library."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import urllib.request
import zipfile

if __package__:
    from .resource_paths import RESOURCES
else:
    from resource_paths import RESOURCES

CATALOG = Path(__file__).resolve().parents[1] / 'docs/OPTIONAL_RESOURCES.json'


def install(name):
    specs = json.loads(CATALOG.read_text(encoding='utf-8'))['blender_addons']
    if name not in specs:
        raise ValueError('Unknown add-on: ' + name)
    spec = specs[name]
    destination = RESOURCES / 'blender-addons' / (name + '-' + spec['version'])
    if destination.exists():
        raise ValueError('Destination already exists; inspect it instead of overwriting: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent, prefix='.addon-') as temporary:
        stage = Path(temporary)
        archive = stage / (name + '.zip')
        with urllib.request.urlopen(spec['url'], timeout=60) as source, archive.open('wb') as target:
            shutil.copyfileobj(source, target)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
            raise ValueError('Add-on archive checksum mismatch')
        extract(archive, stage / 'source')
        (stage / 'origin.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
        stage.rename(destination)
    return destination


def extract(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            path = (destination / entry.filename).resolve()
            if not path.is_relative_to(destination) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe add-on archive member: ' + entry.filename)
        source.extractall(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    args = parser.parse_args()
    try:
        print(install(args.name))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
