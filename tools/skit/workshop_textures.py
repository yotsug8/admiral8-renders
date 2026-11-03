"""Prepare Valve's original Workshop textures without resizing the source art.

Only the declared archive members are read. Assets remain local; their original
terms apply. Compare source colour/normal layouts with the installed game export
before using these files on that mesh. Run with --out to reuse an existing cache.
"""
import argparse
from contextlib import ExitStack
import hashlib
import io
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
    'lina':{
        'lina_base':('base/__lina_base','lina_base'),
        'lina_base_dress':('lina_belt','lina_base_dress'),
        'lina_hair':('lina_head','lina_hair'),
        'lina_jewelry':('lina_neck','lina_jewelry'),
        'lina_sleeve':('lina_arms','lina_sleeve'),
    },
    'kunkka':{
        'kunkka2_body':('kunkka2_body','kunkka2_body'),
        'kunkka2_boots':('kunkka2_boots','kunkka2_boots'),
        'kunkka2_hair':('kunkka2_hair','kunkka2_hair'),
        'kunkka2_hands':('kunkka2_hands','kunkka2_hands'),
        'kunkka2_shoulders':('kunkka2_shoulders','kunkka2_shoulders'),
        'kunkka2_belt':('kunkka2_belt','kunkka2_belt'),
        'kunkka2_tidebringer':('kunkka2_tidebringer','kunkka2_tidebringer'),
    },
    'pudge':{
        'pudge2_body':('base/__pudge_base','pudge2_body'),
        'pudge2_bracer':('pudge_arms','pudge2_bracer'),
        'pudge2_apron':('pudge_back','pudge2_apron'),
        'pudge2_waist':('pudge_belt','pudge2_waist'),
        'pudge2_hair':('pudge_head','pudge2_hair'),
        'pudge2_chopper':('pudge_offhand','pudge2_chopper'),
        'pudge2_armleft':('pudge_shoulder','pudge2_armleft'),
        'pudge2_hook':('pudge_weapon','pudge2_hook'),
    },
}

# Exact archive paths only: no recursive search, persona fallback or extraction.
# Unlisted heroes retain the original materials/ layout and manifest schema.
ARCHIVE_LAYOUT={
    'kunkka':('materialsrc/models/heroes/kunkka',None),
    'pudge':('materials','pudge_base.zip'),
}


def prepare(out,heroes=('axe','rubick'),game_dir=None):
    out.mkdir(parents=True,exist_ok=True)
    manifest=out/'textures.json'
    report=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {'archives':{},'materials':{}}
    game_dir=game_dir or ROOT/'_game/models/render'
    for hero in heroes:
        mapping=MAP[hero]
        url=f'https://media.steampowered.com/apps/dota2/workshop/{hero}.zip?v=11161272'
        archive=out/f'{hero}.zip'
        if not archive.exists():
            partial=archive.with_suffix('.partial')
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=60) as source,partial.open('wb') as target:
                while chunk:=source.read(1024*1024):target.write(chunk)
            partial.replace(archive)
        report['archives'][hero]={'url':url,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'terms':'Valve Dota 2 Workshop resources; not CC0. Keep source assets outside the code repository.'}
        prefix,container=ARCHIVE_LAYOUT.get(hero,('materials',None))
        with ExitStack() as stack:
            z=stack.enter_context(zipfile.ZipFile(archive))
            if hero in ARCHIVE_LAYOUT:
                report['archives'][hero].update(bytes=archive.stat().st_size,
                    official_page=f'https://www.dota2.com/workshop/requirements/{hero}?l=english')
            if container:
                nested=z.read(container)
                report['archives'][hero]['nested_archive']={'member':container,
                    'sha256':hashlib.sha256(nested).hexdigest(),'bytes':len(nested)}
                z=stack.enter_context(zipfile.ZipFile(io.BytesIO(nested)))
            for material,(stem,game) in mapping.items():
                entry={}
                for kind in ('color','normal'):
                    member=f'{prefix}/{stem}_{kind}.tga'
                    with z.open(member) as stream:
                        if hero in ARCHIVE_LAYOUT:
                            raw=stream.read();stream=io.BytesIO(raw)
                        source=Image.open(stream);source.load();source=source.convert('RGB')
                    originals=sorted(game_dir.glob(f'{game}_{kind}_*.png'))
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
                    if hero in ARCHIVE_LAYOUT:
                        entry[kind].update(source_member_sha256=hashlib.sha256(raw).hexdigest(),
                            game_file=originals[0].resolve().relative_to(ROOT).as_posix()
                                if originals[0].resolve().is_relative_to(ROOT) else originals[0].name,
                            game_sha256=hashlib.sha256(originals[0].read_bytes()).hexdigest())
                    if container:entry[kind]['archive_container']=container
                report['materials'][material]=entry
                print(material,entry['color']['game_size'],'->',entry['color']['size'],flush=True)
    (out/'textures.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=ROOT/'_game/models/workshop')
    parser.add_argument('--heroes',nargs='+',choices=sorted(MAP),default=['axe','rubick'])
    parser.add_argument('--game-dir',type=Path,help='Original exported textures for layout comparison')
    args=parser.parse_args();prepare(args.out.resolve(),args.heroes,args.game_dir)
