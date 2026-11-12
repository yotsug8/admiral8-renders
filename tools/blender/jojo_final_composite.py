"""Assemble the full native 1080p JoJo v12 delivery without altering timing."""
from pathlib import Path
import hashlib,json,subprocess
from PIL import Image,ImageFilter,ImageStat
from jojo_impact_composite import impact

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
root=Path('out/dota-jojo/v12/final');manifest=json.loads((root/'render-manifest.json').read_text())
assert manifest['status']=='render_complete'
assert sha(root/'jojo-final.blend')==manifest['scene_sha256']
frames=root/'composite';frames.mkdir(exist_ok=True)
source_hashes={}
for f in range(1,505):
 source=(root/'frames' if 70<=f<=244 else Path('out/dota-jojo/v7/final/frames'))/f'frame_{f:04d}.png'
 digest=sha(source)
 if 70<=f<=244:assert digest==manifest['rendered'][str(f)]['sha256']
 source_hashes[str(f)]=digest
 with Image.open(source) as image:
  image.load();assert image.size==(1080,1920),(f,image.size)
  im=image.convert('RGB');assert max(ImageStat.Stat(im).mean)>1,('black',f)
 im=im.filter(ImageFilter.UnsharpMask(radius=.9,percent=35,threshold=3))
 impact(im,f).save(frames/f'frame_{f:04d}.png')
output=root/'jojo-final.mp4'
subprocess.run(['ffmpeg','-y','-v','error','-framerate','30','-start_number','1','-i',str(frames/'frame_%04d.png'),'-i','out/dota-jojo/v12/preview.mp4','-map','0:v:0','-map','1:a:0','-frames:v','504','-c:v','libx264','-preset','slow','-crf','16','-pix_fmt','yuv420p','-c:a','copy','-t','16.8','-movflags','+faststart',str(output)],check=True)
subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],check=True)
info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]));video=next(s for s in info['streams'] if s['codec_type']=='video')
assert (video['width'],video['height'],int(video['nb_frames']),video['r_frame_rate'])==(1080,1920,504,'30/1')
report={'sha256':sha(output),'scene_sha256':manifest['scene_sha256'],'compositor_sha256':sha(__file__),'effects_sha256':sha('tools/blender/jojo_impact_composite.py'),'source_frame_sha256':source_hashes,'size':[1080,1920],'fps':30,'frames':504,'duration':info['format']['duration'],'new_render':[70,244],'reused_v7':[[1,69],[245,504]],'audio':'bitstream copy from approved v12 preview; listening not verified','visual_review':'pending','decode_errors':False}
(root/'verification.json').write_text(json.dumps(report,indent=2))
print('FINAL_ASSEMBLED',output,report['sha256'])
