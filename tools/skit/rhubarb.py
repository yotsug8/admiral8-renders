"""Optional local speech-to-mouth cues. Does not animate or approve a Dota face.

Install: py -3.11 tools/skit/rhubarb.py --install
Run: py -3.11 tools/skit/rhubarb.py speech.wav --out out/WORK/audio/mouth.json
Non-English speech defaults to the less precise language-independent recognizer.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import urllib.request
import zipfile

if __package__:
    from ..resource_paths import RESOURCES, ROOT
    from ..optional_addons import extract
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from resource_paths import RESOURCES, ROOT
    from optional_addons import extract


def specification():
    return json.loads((ROOT / 'docs/OPTIONAL_RESOURCES.json').read_text(encoding='utf-8'))['lip_sync_tools']['rhubarb']


def verified_runtime():
    spec = specification()
    folder = RESOURCES / 'runtime' / ('rhubarb-' + spec['version'])
    archive = folder / 'release.zip'
    if not archive.is_file():
        raise ValueError('Rhubarb is absent; run with --install first')
    with archive.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != spec['sha256']:
            raise ValueError('Rhubarb archive checksum mismatch')
    # Check loaded binary/resources against the pinned archive, not an editable manifest.
    with zipfile.ZipFile(archive) as source:
        expected = set()
        for entry in source.infolist():
            path = (folder / entry.filename).resolve()
            if not path.is_relative_to(folder.resolve()):
                raise ValueError('Unsafe archive path')
            if entry.is_dir():
                continue
            expected.add(path)
            with source.open(entry) as packed, path.open('rb') as unpacked:
                if hashlib.file_digest(packed, 'sha256').digest() != hashlib.file_digest(unpacked, 'sha256').digest():
                    raise ValueError('Changed Rhubarb file: ' + entry.filename)
        actual = {p.resolve() for p in (folder / spec['directory']).rglob('*') if p.is_file()}
        if actual != expected:
            raise ValueError('Unexpected files in Rhubarb runtime directory')
    return folder / spec['directory'] / 'rhubarb.exe'


def install():
    spec = specification()
    folder = RESOURCES / 'runtime' / ('rhubarb-' + spec['version'])
    if folder.exists():
        return verified_runtime()
    folder.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=folder.parent, prefix='.rhubarb-') as temporary:
        stage = Path(temporary)
        archive = stage / 'release.zip'
        with urllib.request.urlopen(spec['url'], timeout=60) as source, archive.open('wb') as output:
            shutil.copyfileobj(source, output)
        with archive.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != spec['sha256']:
                raise ValueError('Downloaded Rhubarb archive checksum mismatch')
        extract(archive, stage)
        (stage / 'origin.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
        stage.rename(folder)
    return verified_runtime()


def validate_cues(data):
    duration = data['metadata']['duration']
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid duration in Rhubarb output')
    previous = 0
    for cue in data['mouthCues']:
        start, end = cue['start'], cue['end']
        if (not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end))
                or abs(start - previous) > .0001 or not start < end <= duration
                or cue['value'] not in tuple('ABCDEFGHX')):
            raise ValueError('Invalid or discontinuous Rhubarb mouth cue')
        previous = end
    if abs(previous - duration) > .0001:
        raise ValueError('Mouth cues do not cover the audio duration')


def generate(source, out, recognizer='phonetic', threads=2):
    source, out = Path(source).resolve(strict=True), Path(out).resolve()
    if out.exists():
        raise ValueError('Output already exists; choose a new path')
    if threads < 1 or recognizer not in ('phonetic', 'pocketSphinx'):
        raise ValueError('Invalid thread count or recognizer')
    binary = verified_runtime()
    with source.open('rb') as handle:
        source_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Only publish validated JSON; failed subprocesses leave no misleading final artifact.
    with TemporaryDirectory(dir=out.parent, prefix='.mouth-') as temporary:
        target = Path(temporary) / 'mouth.json'
        subprocess.run([str(binary), '--quiet', '-r', recognizer, '--threads', str(threads),
                        '-f', 'json', '-o', str(target), str(source)], check=True)
        data = json.loads(target.read_text(encoding='utf-8'))
        validate_cues(data)
        with source.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != source_hash:
                raise ValueError('Input audio changed during recognition')
        spec = specification()
        data['provenance'] = {'source_sha256': source_hash,
                              'rhubarb_version': spec['version'], 'runtime_archive_sha256': spec['sha256'],
                              'recognizer': recognizer,
                              'face_mapping': 'not performed', 'artistic_review': 'pending'}
        with out.open('x', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--recognizer', choices=('phonetic', 'pocketSphinx'), default='phonetic')
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args()
    try:
        if args.install:
            print(install())
        if args.source:
            if args.out is None:
                parser.error('--out is required with a source')
            print(generate(args.source, args.out, args.recognizer, args.threads))
        elif not args.install:
            parser.error('Provide a source or --install')
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
