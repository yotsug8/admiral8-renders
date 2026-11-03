"""Replace verified matching texture images, preserving the existing shader graph."""
import hashlib
import json
from pathlib import Path

import bpy


def apply_verified(folder, heroes):
    folder=Path(folder)
    manifest=json.loads((folder/'textures.json').read_text(encoding='utf-8'))
    changes=[]
    for material,entry in manifest['materials'].items():
        if not any(material.startswith(hero+'_') for hero in heroes):continue
        for kind in ('color','normal'):
            info=entry[kind];path=folder/info['file']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:
                raise ValueError(f'Workshop texture provenance changed: {material}/{kind}')
            prefix=material+'_'+kind
            # Match image identity, including suffixed material instances. Keep
            # alpha, roughness, masks and the normal-map convention unchanged.
            for mat in bpy.data.materials:
                if not mat.use_nodes:continue
                for node in mat.node_tree.nodes:
                    if node.type!='TEX_IMAGE' or not node.image:continue
                    if not node.image.name.startswith(prefix):continue
                    old=node.image
                    image=bpy.data.images.load(str(path),check_existing=True)
                    image.colorspace_settings.name=old.colorspace_settings.name
                    image.alpha_mode=old.alpha_mode;image.pack();node.image=image
                    changes.append(dict(material=mat.name,kind=kind,before=list(old.size),after=list(image.size)))
    if not changes:raise ValueError('No matching source image nodes; do not claim an upgrade')
    return changes
