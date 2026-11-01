"""Locate worst changing edges in an unaccepted transfer; no render or edits."""
import argparse
import json
from pathlib import Path
import sys
import bpy
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from study_retarget_character import meshes
from study_character_overlap import evaluated_vertices

p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);folder=a.folder.resolve()
bpy.ops.wm.open_mainfile(filepath=str(folder/'character.blend'))
sc=bpy.context.scene;sc.frame_set(1);graph=bpy.context.evaluated_depsgraph_get()
base={o.name:evaluated_vertices(o,graph) for o in meshes()}
report={}
for ob in meshes():
    points,edges=base[ob.name]
    original=np.linalg.norm(points[edges[:,0]]-points[edges[:,1]],axis=1)
    largest=None;peak_absolute=0.;count=0
    for frame in range(1,sc.frame_end+1):
        sc.frame_set(frame);bpy.context.view_layer.update()
        current,_=evaluated_vertices(ob,graph)
        length=np.linalg.norm(current[edges[:,0]]-current[edges[:,1]],axis=1)
        ratio=np.maximum(length/np.maximum(original,1e-12),original/np.maximum(length,1e-12))
        ratio[original<=1e-6]=1
        idx=int(np.argmax(ratio));absolute=np.abs(length-original)
        peak_absolute=max(peak_absolute,float(absolute.max()))
        count=max(count,int(np.sum((ratio>1.35)&(absolute>.002))))
        if largest is None or ratio[idx]>largest['ratio']:
            ends=[int(v) for v in edges[idx]]
            groups={g.index:g.name for g in ob.vertex_groups}
            largest=dict(frame=frame,ratio=float(ratio[idx]),original_m=float(original[idx]),
                changed_m=float(length[idx]),vertices=ends,original_world=points[ends].tolist(),
                current_world=current[ends].tolist(),weights=[{groups[g.group]:g.weight for g in ob.data.vertices[v].groups} for v in ends])
    report[ob.name]=dict(worst=largest,max_absolute_edge_change_m=peak_absolute,
        max_edges_over_ratio_and_2mm=count,edges=len(edges))
(folder/'skin_details.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('SKIN_DETAILS_SAVED')
