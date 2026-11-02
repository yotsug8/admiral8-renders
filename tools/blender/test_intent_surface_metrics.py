"""Regression: imported face meshes without an edge table must not bypass QA."""
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from study_character_intent import compare

data=SimpleNamespace(edges=[],loop_triangles=[SimpleNamespace(vertices=(0,1,2))],calc_loop_triangles=lambda:None)
mesh=SimpleNamespace(name='Imported_sleeve',data=data)
p=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]])
foot={'Imported_sleeve':np.array([0])};sole={'foot':foot}
q=p.copy();q[2,1]=.01
bad=compare([mesh],{mesh.name:p},{mesh.name:q},foot,sole,1.)
assert not bad['skin_pass'] and bad['meshes'][0]['contracted']==1,bad
good=compare([mesh],{mesh.name:p},{mesh.name:p.copy()},foot,sole,1.)
assert good['skin_pass'] and len(good['meshes'])==1,good
print('Face-only imported surfaces: collapse rejected, unchanged surface accepted')
