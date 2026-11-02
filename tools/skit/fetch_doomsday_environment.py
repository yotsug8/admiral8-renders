"""Fetch the explicitly selected CC0 environment assets from Poly Haven.

Binary assets and API responses stay in the ignored local production directory.
"""
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'_game/skits/doomsday/v2/external'
ASSETS={
    'kloppenheim_06_puresky':[('hdri','4k','hdr')],
    'rocks_ground_02':[('Diffuse','4k','jpg'),('nor_gl','4k','jpg'),('Rough','4k','jpg')],
    'rocky_terrain_02':[('Diffuse','4k','jpg')],
}


def get(url):
    request=urllib.request.Request(url,headers={'User-Agent':'Local animation asset preparation'})
    with urllib.request.urlopen(request,timeout=90) as response:return response.read()


def main():
    OUT.mkdir(parents=True,exist_ok=True);manifest=[]
    for name,variants in ASSETS.items():
        metadata=json.loads(get(f'https://api.polyhaven.com/files/{name}'))
        (OUT/f'{name}_files.json').write_text(json.dumps(metadata,indent=2))
        for kind,size,fmt in variants:
            aliases={'Diffuse':('diff','Diffuse'),'Displacement':('disp','Displacement'),'Rough':('rough','Rough')}
            key=next(k for k in aliases.get(kind,(kind,)) if k in metadata)
            spec=metadata[key][size][fmt];url=spec['url'];parsed=urllib.parse.urlparse(url)
            if parsed.scheme!='https' or parsed.hostname!='dl.polyhaven.org':raise ValueError('Unexpected asset host')
            path=OUT/Path(parsed.path).name
            if not path.exists() or hashlib.md5(path.read_bytes()).hexdigest()!=spec['md5']:
                payload=get(url)
                if hashlib.md5(payload).hexdigest()!=spec['md5']:raise ValueError(f'Checksum mismatch: {name}/{kind}')
                path.write_bytes(payload)
            manifest.append({'asset':name,'page':f'https://polyhaven.com/a/{name}','license':'CC0',
                'kind':kind,'file':path.name,'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            print(path.name,flush=True)
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')


def boulder():
    """Highest supplied texture set; the original mesh is shared by all sizes."""
    folder=OUT.parent.parent/'v3/external/boulder_01';folder.mkdir(parents=True,exist_ok=True)
    metadata=json.loads(get('https://api.polyhaven.com/files/boulder_01'))
    spec=metadata['gltf']['8k']['gltf'];files={Path(urllib.parse.urlparse(spec['url']).path).name:spec,**spec['include']}
    entries=[]
    for name,entry in files.items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()):raise ValueError('Unsafe asset dependency path')
        url=entry['url'];parsed=urllib.parse.urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!='dl.polyhaven.org':raise ValueError('Unexpected model host')
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists() or hashlib.md5(path.read_bytes()).hexdigest()!=entry['md5']:
            data=get(url)
            if hashlib.md5(data).hexdigest()!=entry['md5']:raise ValueError('Model dependency checksum mismatch')
            path.write_bytes(data)
        entries.append({'file':name,'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (folder/'manifest.json').write_text(json.dumps({'asset':'boulder_01','page':'https://polyhaven.com/a/boulder_01',
        'credit':'Powered by Poly Haven','license':'CC0','files':entries},indent=2))
    print('Boulder 01: native mesh and 8K texture dependencies verified',flush=True)


if __name__=='__main__':
    if '--boulder' in sys.argv:boulder()
    else:main()
