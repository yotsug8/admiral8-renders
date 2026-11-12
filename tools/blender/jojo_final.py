"""Finish approved JoJo v12 at native 1080p; one Blender process at a time.
Run on v12 with -- prepare, then on saved final scene with -- render.
"""
import bpy,hashlib,json,sys,time
from pathlib import Path
s=bpy.context.scene
root=Path('out/dota-jojo/v12/final').resolve();root.mkdir(parents=True,exist_ok=True)
frames=root/'frames';frames.mkdir(exist_ok=True)
manifest=root/'render-manifest.json'
mode=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'prepare'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
if mode=='prepare':
 source=sha(bpy.data.filepath)
 s.render.resolution_x=1080;s.render.resolution_y=1920;s.render.resolution_percentage=100
 s.eevee.taa_render_samples=96;s.eevee.shadow_pool_size='1024'
 s.frame_start=1;s.frame_end=504;s.frame_set(1)
 s.render.filepath=str(frames/'frame_')
 bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(root/'jojo-final.blend'))
 data={'scene_sha256':sha(root/'jojo-final.blend'),'source_scene_sha256':source,'size':[1080,1920],'samples':96,'shadow_pool_mb':1024,'fps':30,'new_frames':[70,244],'reused_v7_frames':[[1,69],[245,504]],'reuse_reason':'Same native v7 source frames used by the approved v12 preview outside 70-244; accepted actors/environment/cameras unchanged there.','rendered':{},'status':'probes'}
 targets=[87,140,216]
else:
 data=json.loads(manifest.read_text());assert sha(bpy.data.filepath)==data['scene_sha256'],'Scene changed; cannot resume'
 targets=range(70,245);data['status']='rendering'
for f in targets:
 p=frames/f'frame_{f:04d}.png'
 if str(f) in data['rendered'] and p.exists() and sha(p)==data['rendered'][str(f)]['sha256']:continue
 start=time.monotonic();s.frame_set(f);s.render.filepath=str(p);bpy.ops.render.render(write_still=True)
 # Blender has completed writing; the assembler later fully decodes each PNG.
 data['rendered'][str(f)]={'sha256':sha(p),'seconds':round(time.monotonic()-start,3)}
 manifest.write_text(json.dumps(data,indent=2));print('FRAME_COMPLETE',f,data['rendered'][str(f)]['seconds'],flush=True)
data['status']='probes_complete' if mode=='prepare' else 'render_complete'
manifest.write_text(json.dumps(data,indent=2))
