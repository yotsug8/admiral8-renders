"""Fixed, restrained finishing look; never adapts exposure frame by frame."""
import numpy as np
from grade import Grade

class ChaseLook:
    def __init__(self,samples):
        self.grade=Grade(samples,strength=.15,color=.25,warm_hue=-2.,contrast=.15)
        self._masks={}

    def __call__(self,rgb):
        if not np.any(rgb):return rgb.copy()
        result=self.grade(rgb)
        h,w=result.shape[:2]
        if (h,w) not in self._masks:
            y,x=np.mgrid[-1:1:complex(0,h),-1:1:complex(0,w)]
            radius=np.sqrt((x*x+y*y)/2)
            t=np.clip((radius-.45)/.55,0,1)
            self._masks[h,w]=(1-.07*t*t*(3-2*t))[...,None]
        return np.clip(result.astype(np.float32)*self._masks[h,w],0,255).astype(np.uint8)
