"""Enable a verified local optional add-on for this Blender process only.

Set A8_BLENDER_ADDON=retarget and run this -P before the scene builder -P.
Does not save user preferences or change an existing scene.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import addon_utils

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resource_paths import RESOURCES

name = os.environ.get('A8_BLENDER_ADDON', 'retarget')
catalog = Path(__file__).resolve().parents[2] / 'docs/OPTIONAL_RESOURCES.json'
spec = json.loads(catalog.read_text(encoding='utf-8'))['blender_addons'][name]
folder = RESOURCES / 'blender-addons' / (name + '-' + spec['version'])
archive = folder / (name + '.zip')
if hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
    raise ValueError('Optional add-on checksum mismatch')
# Verify the extracted executable files against the pinned archive before importing.
import zipfile
with zipfile.ZipFile(archive) as source:
    for entry in source.infolist():
        if not entry.is_dir() and (folder / 'source' / entry.filename).read_bytes() != source.read(entry):
            raise ValueError('Modified add-on source: ' + entry.filename)
sys.path.insert(0, str(folder / 'source'))
module = addon_utils.enable(name, default_set=True, persistent=False)
if module is None:
    raise RuntimeError('Optional add-on could not be enabled: ' + name)
print('Optional add-on enabled:', name, spec['version'], flush=True)
