# Замер средних цветов участков кадра (вода, трава, песок, весь кадр) — для сверки со скриншотами доты
import sys
from PIL import Image
import numpy as np
im=Image.open(sys.argv[1]).convert('RGB')
if im.width!=1080: im=im.resize((1080,1920))
a=np.asarray(im).astype(float)
def avg(x0,y0,x1,y1): return a[y0:y1,x0:x1].reshape(-1,3).mean(0).round().astype(int).tolist()
print("water_open", avg(560,1180,700,1300), "water_far", avg(700,450,1000,560), "grass", avg(0,330,120,400), "sand", avg(40,560,220,700), "whole", avg(0,0,a.shape[1],a.shape[0]))
