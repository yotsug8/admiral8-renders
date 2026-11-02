"""Render an inspected saved scene without rebuilding it; resume exact caches.

Blender -b --python this.py -- --blend scene.blend --output frames
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import bpy


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blend',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--width',type=int,default=1280)
    parser.add_argument('--height',type=int,default=720)
    parser.add_argument('--samples',type=int,default=48)
    parser.add_argument('--reuse-higher-samples',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.output.mkdir(exist_ok=True,parents=True)
    signature={'blend_sha256':hashlib.sha256(args.blend.read_bytes()).hexdigest(),
               'width':args.width,'height':args.height,'samples':args.samples,
               'fps':30,'shutter':.25,'cuts':[0,45,120,195,243,277,330,360]}
    manifest=args.output/'manifest.json'
    cached=json.loads(manifest.read_text()) if manifest.exists() else {}
    if cached and cached.get('settings') != signature:
        old=cached.get('settings',{})
        compatible=(args.reuse_higher_samples and old.get('samples',0)>args.samples and
                    {k:v for k,v in old.items() if k!='samples'}==
                    {k:v for k,v in signature.items() if k!='samples'})
        if not compatible:
            raise ValueError('Output cache belongs to another scene or render configuration')
    hashes={int(f):digest for f,digest in zip(cached.get('source_frames',[]),cached.get('frame_sha256',[]))}
    sample_counts={int(f):n for f,n in cached.get('frame_samples',{}).items()}
    for frame in hashes:sample_counts.setdefault(frame,cached['settings']['samples'])
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()))
    scene=bpy.context.scene;scene.render.engine='CYCLES'
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='OPTIX';prefs.get_devices()
    for device in prefs.devices:device.use=device.type=='OPTIX'
    if not any(d.use for d in prefs.devices):raise RuntimeError('No OPTIX device')
    scene.cycles.device='GPU';scene.cycles.samples=args.samples
    scene.cycles.use_denoising=True;scene.cycles.denoising_use_gpu=True
    scene.cycles.adaptive_threshold=.015
    scene.render.resolution_x=args.width;scene.render.resolution_y=args.height
    scene.render.resolution_percentage=100;scene.render.use_persistent_data=True
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB'
    scene.render.motion_blur_shutter=.25
    started=time.time()
    for frame in range(420):
        target=args.output/f'{frame:04d}.png'
        if frame in hashes:
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=hashes[frame]:
                raise ValueError(f'Cached frame differs: {frame}')
            continue
        scene.frame_set(frame)
        # Cut boundaries must not sample the previous camera during shutter time.
        scene.render.use_motion_blur=frame not in signature['cuts']
        scene.render.filepath=str(target)
        bpy.ops.render.render(write_still=True)
        hashes[frame]=hashlib.sha256(target.read_bytes()).hexdigest()
        sample_counts[frame]=args.samples
        numbers=sorted(hashes)
        manifest.write_text(json.dumps({'settings':signature,'source_frames':numbers,
            'frame_sha256':[hashes[f] for f in numbers],'fps':30,
            'frame_samples':sample_counts,
            'elapsed_seconds':time.time()-started},indent=2))
        print(f'DELIVERY_FRAME {frame+1}/420 elapsed={time.time()-started:.1f}',flush=True)


if __name__=='__main__':main()
