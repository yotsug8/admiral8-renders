"""Fixed, restrained finishing look; never adapts exposure frame by frame."""
import hashlib
from pathlib import Path
import numpy as np
from grade import Grade, data_hash, to_lab, to_rgb

class ChaseLook:
    def __init__(self,samples,profile='legacy', *, target_data=None, snapshot=None):
        if profile not in ('legacy', 'daylight'):
            raise ValueError('Unknown chase look: '+str(profile))
        self.profile=profile
        if snapshot is not None:
            state = snapshot['state']
            if data_hash(state) != snapshot['sha256']:
                raise ValueError('Look snapshot hash mismatch')
            if (state['version'] != 1 or state['profile'] != profile
                    or state['implementation'] != self.implementation()):
                raise ValueError('Look snapshot implementation/profile mismatch')
            self.grade = Grade.from_snapshot(state['grade']) if profile == 'legacy' else self.daylight
        else:
            if profile != 'legacy' and target_data is not None:
                raise ValueError('daylight does not use a grade target')
            self.grade=(Grade(samples,strength=.15,color=.25,warm_hue=-2.,contrast=.15,
                              target_data=target_data) if profile == 'legacy' else self.daylight)
        self._masks={}

    @staticmethod
    def implementation():
        return dict(numpy=np.__version__, files={name: hashlib.sha256(
            Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('grade.py', 'chase_look.py')})

    def snapshot(self):
        state = dict(version=1, profile=self.profile, implementation=self.implementation(),
                     grade=self.grade.snapshot() if self.profile == 'legacy' else None)
        return dict(state=state, sha256=data_hash(state))

    @staticmethod
    def daylight(rgb):
        """Fixed Lab curve, no exemplar matching, sharpening or local exposure."""
        lab=to_lab(rgb.astype(np.float32))
        light=lab[...,0].copy()
        lab[...,0]=np.interp(light,[0,5,15,30,50,70,85,100],
                                  [0,3,12,31,55,76,88,100])
        hue=np.degrees(np.arctan2(lab[...,2],lab[...,1]))
        chroma=np.hypot(lab[...,1],lab[...,2])
        # Keep foliage quieter; preserve saturated costume colours.
        green=np.clip(1-np.abs(hue-125)/35,0,1)*np.clip(chroma/12,0,1)
        lab[...,1:]*=(1.08-.16*green)[...,None]
        mid=np.clip(1-np.abs(light-55)/35,0,1)
        shadow=np.clip((35-light)/35,0,1)*np.clip(light/8,0,1)
        lab[...,1]+=.35*mid-.25*shadow
        lab[...,2]+=.8*mid-1.5*shadow
        return to_rgb(lab)

    def __call__(self,rgb):
        if not np.any(rgb):return rgb.copy()
        result=self.grade(rgb)
        h,w=result.shape[:2]
        if (h,w) not in self._masks:
            y,x=np.mgrid[-1:1:complex(0,h),-1:1:complex(0,w)]
            radius=np.sqrt((x*x+y*y)/2)
            t=np.clip((radius-.45)/.55,0,1)
            amount=.07 if self.profile == 'legacy' else .04
            self._masks[h,w]=(1-amount*t*t*(3-2*t))[...,None]
        return np.clip(result.astype(np.float32)*self._masks[h,w],0,255).astype(np.uint8)
