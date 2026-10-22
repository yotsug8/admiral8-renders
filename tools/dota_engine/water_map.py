import json, numpy as np
from PIL import Image
g=json.load(open('world/world.gltf',encoding='utf-8')); nodes=g['nodes']; acc=g['accessors']; bv=g['bufferViews']
buf=open('world/world.bin','rb').read()
def qm(q):
    x,y,z,w=q; return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def loc(n):
    if 'matrix' in n: return np.array(n['matrix']).reshape(4,4).T
    M=np.eye(4); M[:3,:3]=qm(n.get('rotation',[0,0,0,1]))@np.diag(n.get('scale',[1,1,1])); M[:3,3]=n.get('translation',[0,0,0]); return M
par={c:i for i,n in enumerate(nodes) for c in n.get('children',[])}
def W(i):
    M=loc(nodes[i])
    while i in par: i=par[i]; M=loc(nodes[i])@M
    return M
def read(ai):
    a=acc[ai]; v=bv[a['bufferView']]; off=v.get('byteOffset',0)+a.get('byteOffset',0)
    n={'SCALAR':1,'VEC3':3}[a['type']]; dt={5126:np.float32,5125:np.uint32,5123:np.uint16}[a['componentType']]
    r=np.frombuffer(buf,dtype=dt,count=a['count']*n,offset=off); return r.reshape(-1,n) if n>1 else r
mats=g['materials']; S=10; R=3000; N=2*R//S
img=Image.new('L',(N,N),0)
from PIL import ImageDraw
d=ImageDraw.Draw(img)
for i,n in enumerate(nodes):
    if 'mesh' not in n: continue
    for p in g['meshes'][n['mesh']]['primitives']:
        if 'material' not in p or not mats[p['material']]['name'].startswith('water_generic'): continue
        P=read(p['attributes']['POSITION']); P=(np.c_[P,np.ones(len(P))]@W(i).T)[:,:3]
        G=np.c_[P[:,2]*39.37, P[:,0]*39.37]
        for t in read(p['indices']).reshape(-1,3):
            d.polygon([((G[k,0]+R)/S,(R-G[k,1])/S) for k in t],fill=255)
a=np.asarray(img)>0
# расстояние до края воды (простое: многократное сужение)
dist=np.zeros(a.shape,int); cur=a.copy(); k=0
while cur.any():
    k+=1; dist[cur]=k
    sh=cur.copy(); sh[1:]&=cur[:-1]; sh[:-1]&=cur[1:]; sh[:,1:]&=cur[:,:-1]; sh[:,:-1]&=cur[:,1:]; cur=sh
ys,xs=np.nonzero(dist>=1)
best=sorted(zip(dist[ys,xs],xs,ys),reverse=True)
seen=[]
for dd,x,y in best:
    gx,gy=x*S-R,R-y*S
    if any(abs(gx-a_)<600 and abs(gy-b_)<600 for a_,b_ in seen): continue
    seen.append((gx,gy)); print(f"WATER центр игры ({gx},{gy}) до берега {dd*S} ед.")
    if len(seen)>=8: break
im=Image.fromarray((np.clip(dist*6,0,255)).astype('uint8')); im.save('water_dist.png')
