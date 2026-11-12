"""Composite brief JoJo time-erasure accents from lossless rendered frames.
No continuous blur; the original audio remains at its original timestamps.
"""
from pathlib import Path
import argparse, hashlib, json, subprocess
from PIL import Image, ImageOps, ImageFilter


def impact(im, frame):
    # Two isolated story beats: entering erased time and changing identity.
    pulse={87:1.,119:1.,138:1.,139:1.,140:1.}
    if frame in pulse:
        inverted=ImageOps.invert(im)
        red,green,blue=inverted.split()
        inverted=Image.merge('RGB',(red,green.point(lambda x:int(x*.72)),blue.point(lambda x:int(x*.82))))
        im=Image.blend(im,inverted,pulse[frame])
    # The displacement is a six-frame impulse, not persistent camera wobble.
    kicks={85:(.018,-.008),86:(-.025,.004),87:(.035,0),88:(-.012,0),89:(.004,0),
           118:(-.025,0),119:(.04,0),120:(-.012,0),
           138:(-.035,0),139:(.06,0),140:(-.02,-.008),141:(.01,.004),142:(-.004,0)}
    if frame in kicks:
        dx,dy=kicks[frame];w,h=im.size
        # Overscan prevents black borders and wraps; bounded impulse keeps faces readable.
        scale=1+2.5*max(abs(dx),abs(dy))+.005
        im=im.transform((w,h),Image.Transform.AFFINE,(1/scale,0,w*(1-1/scale)/2+dx*w,0,1/scale,h*(1-1/scale)/2+dy*h),Image.Resampling.BICUBIC)
        if frame in (87,119,139):
            r,g,b=im.split();rs=round(8*w/720);bs=round(6*w/720)
            r=r.resize((w+rs,h),Image.Resampling.BICUBIC).crop((0,0,w,h));b=b.resize((w+bs,h),Image.Resampling.BICUBIC).crop((bs,0,w+bs,h));im=Image.merge('RGB',(r,g,b))
    return im


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--probe',action='store_true');args=parser.parse_args()
    root=Path('out/dota-jojo/v12');root.mkdir(exist_ok=True,parents=True)
    frames=Path('D:/Admiral8-temp/dota-jojo/v12-composite');frames.mkdir(exist_ok=True)
    first,last=(70,216) if args.probe else (1,504)
    for f in range(first,last+1):
        if args.probe:
            source=Path('D:/Admiral8-temp/dota-jojo/v11-erasure')/f'frame_{f:04d}.png'
        elif 70<=f<=244:
            source=Path('D:/Admiral8-temp/dota-jojo/v12-frames')/f'frame_{f:04d}.png'
        else:
            source=Path('out/dota-jojo/v7/final/frames')/f'frame_{f:04d}.png'
        with Image.open(source) as image:
            image.load()
            expected=(540,960) if args.probe else ((720,1280) if 70<=f<=244 else (1080,1920))
            assert image.size==expected,(f,image.size,expected)
            im=image.convert('RGB').resize((720,1280),Image.Resampling.LANCZOS)
        # Mild output sharpening; does not purport to restore absent source textures.
        im=im.filter(ImageFilter.UnsharpMask(radius=.6,percent=35,threshold=3))
        impact(im,f).save(frames/f'frame_{f:04d}.png')
    output=root/('impact-probe.mp4' if args.probe else 'preview.mp4')
    cmd=['ffmpeg','-y','-v','error','-framerate','30','-start_number',str(first),'-i',str(frames/'frame_%04d.png'),'-ss',str((first-1)/30),'-i','out/dota-jojo/v11/preview.mp4','-map','0:v:0','-map','1:a:0','-frames:v',str(last-first+1),'-c:v','libx264','-preset','slow','-crf','16','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-t',str((last-first+1)/30),'-movflags','+faststart',str(output)]
    subprocess.run(cmd,check=True)
    subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],check=True)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
    video=next(s for s in info['streams'] if s['codec_type']=='video');assert int(video['nb_frames'])==last-first+1
    report={'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'size':[720,1280],'frames':last-first+1,'visual_review':'pending','audio':'same original timeline; listening not verified','probe':args.probe,'source':'v11 PNG scaled for effect probe only' if args.probe else 'v12 new renders 70-244; native v7 1080 PNG outside; no MP4 generation chain'}
    if not args.probe:
        report['scene_sha256']=hashlib.sha256((root/'jojo-v12.blend').read_bytes()).hexdigest()
        report['compositor_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report['new_frame_sha256']={str(f):hashlib.sha256((Path('D:/Admiral8-temp/dota-jojo/v12-frames')/f'frame_{f:04d}.png').read_bytes()).hexdigest() for f in range(70,245)}
    (root/('probe-verification.json' if args.probe else 'verification.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
