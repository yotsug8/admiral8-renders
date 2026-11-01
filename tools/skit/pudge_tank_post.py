"""Fixed scene-specific finishing: restrained background and readable foreground."""
import numpy as np
from PIL import Image, ImageFilter
from grade import to_lab, to_rgb

BLUR=(2.2,.7,1.2,.6,1.8,.6,2.2)

def background(image,shot):
    lab=to_lab(np.asarray(image.convert('RGB'),dtype=np.float32))
    # Keep the forest green, but reduce competing yellow-green chroma.
    chroma=np.hypot(lab[...,1],lab[...,2])
    hue=np.arctan2(lab[...,2],lab[...,1])
    weight=np.clip(1-np.abs(np.degrees(hue)-115)/40,0,1)
    angle=np.radians(6)*weight
    lab[...,1]=chroma*np.cos(hue+angle)*.91
    lab[...,2]=chroma*np.sin(hue+angle)*.91
    lab[...,0]*=.97
    return Image.fromarray(to_rgb(lab)).filter(ImageFilter.GaussianBlur(BLUR[shot])).convert('RGBA')

def finish(image):
    lab=to_lab(np.asarray(image.convert('RGB'),dtype=np.float32))
    lab[...,0]=np.interp(lab[...,0],(0,12,28,45,65,82,100),(0,8,24,47,72,88,100))
    lab[...,1:]*=1.05
    chroma=np.hypot(lab[...,1],lab[...,2])
    # Only compress highly saturated pixels; leave skin and painted armor intact.
    cap=68+10*np.tanh(np.maximum(0,chroma-68)/10)
    lab[...,1:]*=np.minimum(1,cap/np.maximum(chroma,1e-6))[...,None]
    rgb=to_rgb(lab)
    h,w=rgb.shape[:2]
    y,x=np.mgrid[:h,:w]
    radius=((x-w*.5)/(w*.68))**2+((y-h*.48)/(h*.72))**2
    vignette=1-.065*np.clip(radius-.22,0,1)
    rgb=np.clip(rgb*vignette[...,None],0,255).astype(np.uint8)
    return Image.fromarray(rgb).filter(ImageFilter.UnsharpMask(radius=.65,percent=30,threshold=3))

def composite(plate,actor,shot):
    return finish(Image.alpha_composite(background(plate,shot),actor.convert('RGBA')))
