"""Prepare Valve's original Workshop textures without resizing the source art.

Only the declared archive members are read. Assets remain local; their original
terms apply. Compare source colour/normal layouts with the installed game export
before using these files on that mesh. Run with --out to reuse an existing cache.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
MAP={
    'axe':{
        'axe_body_color':('base/__axe_base','axe_body'),
        'axe_armor_color':('axe_armor','axe_armor'),
        'axe_belt_color':('axe_belt','axe_belt'),
        'axe_hair_color':('axe_hair','axe_hair'),
        'axe_weapon_color':('axe_weapon','axe_weapon'),
    },
    'rubick':{
        'rubick_body':('base/__rubick_base','rubick_base'),
        'rubick_head_color':('rubick_head','rubick_head'),
        'rubick_robe':('rubick_back','rubick_robe'),
        'rubick_shoulder':('rubick_shoulder','rubick_shoulder'),
        'rubick_staff':('rubick_weapon','rubick_staff'),
    },
}


def prepare(out):
    out.mkdir(parents=True,exist_ok=True);report={'archives':{},'materials':{}}
    for hero,mapping in MAP.items():
        url=f'https://media.steampowered.com/apps/dota2/workshop/{hero}.zip?v=11161272'
        archive=out/f'{hero}.zip'
        if not archive.exists():
            partial=archive.with_suffix('.partial')
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=60) as source,partial.open('wb') as target:
                while chunk:=source.read(1024*1024):target.write(chunk)
            partial.replace(archive)
        report['archives'][hero]={'url':url,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'terms':'Valve Dota 2 Workshop resources; not CC0. Keep source assets outside the code repository.'}
        with zipfile.ZipFile(archive) as z:
            for material,(stem,game) in mapping.items():
                entry={}
                for kind in ('color','normal'):
                    member=f'materials/{stem}_{kind}.tga'
                    with z.open(member) as stream:
                        source=Image.open(stream);source.load();source=source.convert('RGB')
                    originals=sorted((ROOT/'_game/models/render').glob(f'{game}_{kind}_*.png'))
                    if len(originals)!=1:raise ValueError(f'Ambiguous game texture {game}/{kind}: {originals}')
                    with Image.open(originals[0]) as image:original=image.convert('RGB')
                    a=np.asarray(source.resize(original.size,Image.Resampling.LANCZOS)).astype(float)
                    b=np.asarray(original).astype(float);mask=np.ones(a.shape[:2],bool)
                    flipped=False
                    if kind=='normal':
                        mask=(a[:,:,2]>128)&(b[:,:,2]>128)
                        # Unused atlas background is not a UV correspondence sample.
                        inverse=a.copy();inverse[:,:,1]=255-inverse[:,:,1]
                        if abs(inverse[mask]-b[mask]).mean()<.8*abs(a[mask]-b[mask]).mean():
                            pixels=np.array(source);pixels[:,:,1]=255-pixels[:,:,1];source=Image.fromarray(pixels);a=inverse;flipped=True
                    error=float(abs(a[mask]-b[mask]).mean())
                    if error>12:raise ValueError(f'Source layout mismatch: {material}/{kind}, MAE {error:.2f}')
                    path=out/f'{material}_{kind}.png';source.save(path)
                    entry[kind]={'file':path.name,'archive_member':member,'size':source.size,'game_size':original.size,
                        'comparison_mae_255':error,'green_flipped':flipped,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                report['materials'][material]=entry
                print(material,entry['color']['game_size'],'->',entry['color']['size'],flush=True)
    (out/'textures.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=ROOT/'_game/models/workshop')
    prepare(parser.parse_args().out.resolve())
