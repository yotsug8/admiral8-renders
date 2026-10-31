"""Surface-based vertical clearance for the chase's audited flat corridor.

Preserves the native gait and horizontal route; not foot IK or arbitrary terrain.
The sampled lower paw envelope drives a smooth, conservative whole-root lift.
"""
import math
import bpy
import numpy as np


def clear_paws(actor, scene, start, end, floor_z, clearance=.01):
    root=actor['root']; selection={}
    for obj in actor['objs']:
        if obj.type!='MESH':continue
        groups={g.index for g in obj.vertex_groups if any(s in g.name.lower() for s in ('hand_', 'finger', 'ankle_', 'foot_', 'ball_', 'toe_'))}
        surface={i for p in obj.data.polygons for i in p.vertices}
        ids=[v.index for v in obj.data.vertices if v.index in surface and sum(g.weight for g in v.groups if g.group in groups)>.5]
        if ids:selection[obj]=ids
    if not selection:raise ValueError('No weighted paw surfaces')
    frames=np.arange(start,end+.001,.25); gaps=[]; bases=[]
    for frame in frames:
        scene.frame_set(math.floor(frame),subframe=float(frame%1))
        dg=bpy.context.evaluated_depsgraph_get(); low=float('inf')
        for obj,ids in selection.items():
            ev=obj.evaluated_get(dg); mesh=ev.to_mesh()
            try:low=min(low,min((ev.matrix_world@mesh.vertices[i].co).z for i in ids))
            finally:ev.to_mesh_clear()
        gaps.append(low-floor_z);bases.append(root.location.copy())
    raw=np.maximum(0,clearance-np.asarray(gaps))
    radius=8
    upper=np.array([max(raw[max(0,i-radius):min(len(raw),i+radius+1)]) for i in range(len(raw))])
    kernel=np.exp(-.5*(np.arange(-radius,radius+1)/3)**2);kernel/=sum(kernel)
    lifts=np.convolve(np.pad(upper,radius,mode='edge'),kernel,mode='valid')
    for frame,base,lift in zip(frames,bases,lifts):
        root.location=base;root.location.z+=float(lift)
        root.keyframe_insert('location',index=2,frame=float(frame))
    for layer in root.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    if curve.data_path=='location' and curve.array_index==2:
                        for key in curve.keyframe_points:key.interpolation='LINEAR'
    return dict(samples=len(frames),raw_min_gap_m=min(gaps),max_lift_m=float(max(lifts)),
                sampled_min_corrected_gap_m=float(min(np.asarray(gaps)+lifts)),
                limits='Flat audited floor; quarter-frame vertices, not contact IK.')
