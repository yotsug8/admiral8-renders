"""Bounded CPU gait diagnostics on evaluated polygon vertices, never a render.

blender -b scene.blend -P tools/blender/gait_metrics.py -- --metadata actors.json
    --actor hoodwink --start 144 --end 239.75 --floor-z 3.251190185546875
    --json gait.json

Distances respect scale_length; floor-z is in scene coordinates. Contact bands
are declared heuristics, not physical validation. Flight means all selected
paws clear the band; hidden/missing paws invalidate that inference. Cadence is
from geometric band entries, not NLA repeats or local height minima. It is
reported separately from low-slip candidate contacts. No scene is saved.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from json_output import write_json_report


def summarize(times, positions, roots, floor_m, *, near=.02, penetration=.01,
              slide=.15):
    """positions: time x fixed surface-vertex x xyz, in metres.

    Interval velocities use matching vertex IDs and actual elapsed seconds.
    Near-ground speeds require the SAME vertex in band at both endpoints.
    Root-relative speed removes translation only: it includes body turns and
    all installed pose layers, and is not isolated source-animation speed.
    """
    t=np.asarray(times,dtype=float); p=np.asarray(positions,dtype=float)
    r=np.asarray(roots,dtype=float)
    if (t.ndim!=1 or len(t)<3 or p.ndim!=3 or p.shape[0]!=len(t)
            or p.shape[1]<1 or p.shape[2]!=3 or r.shape!=(len(t),3)):
        raise ValueError('Expected >=3 times, fixed nonempty vertex set, and roots Nx3')
    if not all(np.isfinite(a).all() for a in (t,p,r)) or not math.isfinite(floor_m):
        raise ValueError('Nonfinite samples')
    if np.any(np.diff(t)<=0) or min(near,penetration,slide)<0:
        raise ValueError('Times must increase and thresholds must be nonnegative')
    dt=np.diff(t); gaps=p[:,:,2]-floor_m
    band=(gaps>=-penetration)&(gaps<=near)
    band_intersection=band.any(axis=1)
    penetrating=gaps.min(axis=1)<-penetration
    # A paw passing through the floor also intersects its thin surface band.
    # Those intersections cannot count as support or trigger footstep events.
    contact=band_intersection&~penetrating
    stable=band[:-1]&band[1:]&contact[:-1,None]&contact[1:,None]
    v=np.diff(p,axis=0)/dt[:,None,None]
    rv=np.diff(r,axis=0)/dt[:,None]
    speed=np.linalg.norm(v[:,:,:2],axis=2)
    relative=np.linalg.norm((v-rv[:,None,:])[:,:,:2],axis=2)
    def stats(a):
        return None if a.size==0 else dict(n=int(a.size),median=float(np.median(a)),
                  p95=float(np.percentile(a,95)),max=float(np.max(a)))
    # One event per outside -> inside transition; starting contact is censored.
    entries=np.flatnonzero(~contact[:-1]&contact[1:])+1
    entry_t=t[entries]
    intervals=np.diff(entry_t)
    duration=float(t[-1]-t[0])
    airborne=(gaps.min(axis=1)>near)
    low_slip=(stable&(speed<=slide)).any(axis=1)
    return dict(duration_s=duration,min_gap_m=float(gaps.min()),
        max_lowest_gap_m=float(gaps.min(axis=1).max()),
        root_horizontal_mps=stats(np.linalg.norm(rv[:,:2],axis=1)),
        near_ground_vertex_mps=stats(speed[stable]),
        near_ground_root_relative_mps=stats(relative[stable]),
        airborne_vertex_mps=stats(speed[airborne[:-1]&airborne[1:]]),
        near_ground_interval_s=float(dt[stable.any(axis=1)].sum()),
        low_slip_candidate_interval_s=float(dt[low_slip].sum()),
        airborne_interval_s=float(dt[airborne[:-1]&airborne[1:]].sum()),
        penetrating_sample_fraction=float(np.mean(penetrating)),
        rejected_penetrating_band_samples=int(np.sum(band_intersection&penetrating)),
        contact_entry_times_s=entry_t.tolist(),contact_entry_count=len(entries),
        left_censored_contact=bool(contact[0]),right_censored_contact=bool(contact[-1]),
        contact_entry_rate_hz=len(entries)/duration,
        same_paw_cycle_hz=None if len(intervals)<1 else float(1/np.median(intervals)),
        contact_time_uncertainty_s=float(dt.max()),
        near_mask=contact.tolist(),airborne_mask=airborne.tolist())


def select_surfaces(objects, bone_names, minimum_weight=.5):
    """Select only polygon vertices weighted to explicitly matched side bones.

    Selection stays fixed over time. Evaluated topology changes are refused.
    Visibility is checked separately on every sample, including ancestors.
    """
    selected=[]
    for obj in objects:
        if obj.type!='MESH':continue
        groups={g.index for g in obj.vertex_groups if g.name in bone_names}
        surface={i for poly in obj.data.polygons for i in poly.vertices}
        ids=[v.index for v in obj.data.vertices if v.index in surface and
             sum(g.weight for g in v.groups if g.group in groups)>minimum_weight]
        if ids:selected.append((obj,ids))
    if not selected:raise ValueError(f'No weighted polygon surface for {bone_names}')
    return selected


def main():
    import bpy
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata',required=True,type=Path)
    parser.add_argument('--actor',required=True)
    parser.add_argument('--start',type=float,required=True)
    parser.add_argument('--end',type=float,required=True)
    parser.add_argument('--step',type=float,default=.25)
    parser.add_argument('--floor-z',type=float,required=True)
    parser.add_argument('--near',type=float,default=.02)
    parser.add_argument('--penetration',type=float,default=.01)
    parser.add_argument('--slide',type=float,default=.15)
    parser.add_argument('--max-samples',type=int,default=2000)
    parser.add_argument('--json',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if (not all(math.isfinite(x) for x in (args.start,args.end,args.step,args.floor_z,
            args.near,args.penetration,args.slide)) or args.end<=args.start or args.step<=0
            or min(args.near,args.penetration,args.slide)<0):
        raise ValueError('Invalid range or threshold')
    count=math.ceil((args.end-args.start)/args.step)+1
    if not 3<=count<=args.max_samples:raise ValueError('Sampling budget exceeded or too few samples')
    scene=bpy.context.scene;scale=scene.unit_settings.scale_length
    source=Path(bpy.data.filepath)
    source_stat=source.stat()
    source_hash=hashlib.file_digest(source.open('rb'),'sha256').hexdigest()
    fps=scene.render.fps/scene.render.fps_base
    if scale<=0 or fps<=0:raise ValueError('Invalid units or FPS')
    meta=json.loads(args.metadata.read_text(encoding='utf-8'))[args.actor]
    root=bpy.data.objects[meta['root']];arm=bpy.data.objects[meta['arm']]
    objects=[bpy.data.objects[n] for n in meta['objs'] if n in bpy.data.objects]
    # Exact terminal side suffix prevents eyeball and opposite-side matches.
    paws={}
    for prefix in ('hand','ankle'):
        for side in ('L','R'):
            names=[b.name for b in arm.data.bones if re.fullmatch(
                (r'hand' if prefix=='hand' else r'(?:ankle|ball|toeBase|foot|toe)')
                +'_'+side,b.name,re.I)]
            if names:
                descendants={child.name for name in names for child in arm.data.bones[name].children_recursive
                             if child.name.lower().endswith('_'+side.lower())}
                paws[prefix+'_'+side]=select_surfaces(objects,set(names)|descendants)
    if not paws:raise ValueError('No supported side-specific paw bones; provide adapted selection')
    frames=np.minimum(args.start+np.arange(count)*args.step,args.end)
    data={k:[] for k in paws};roots=[];times=[]
    saved=scene.frame_current,scene.frame_subframe
    try:
        for f in frames:
            scene.frame_set(math.floor(f),subframe=float(f%1))
            dg=bpy.context.evaluated_depsgraph_get()
            roots.append(tuple(root.evaluated_get(dg).matrix_world.translation*scale))
            times.append(float(f/fps))
            # Evaluate each selected mesh once, never walk map geometry.
            cache={}
            for obj in {o for selections in paws.values() for o,_ in selections}:
                parent=obj
                while parent:
                    if parent.hide_render:raise ValueError(f'Hidden surface at {f}: {obj.name}')
                    parent=parent.parent
                ev=obj.evaluated_get(dg);mesh=ev.to_mesh()
                try:
                    if (len(mesh.vertices)!=len(obj.data.vertices) or
                            len(mesh.polygons)!=len(obj.data.polygons)):
                        raise ValueError(f'Topology changed: {obj.name}')
                    if any(m.show_render!=m.show_viewport for m in obj.modifiers):
                        raise ValueError(f'Render/viewport modifier mismatch: {obj.name}')
                    ids={i for selection in paws.values() for o,ix in selection if o==obj for i in ix}
                    cache[obj]={i:tuple((ev.matrix_world@mesh.vertices[i].co)*scale) for i in ids}
                finally:ev.to_mesh_clear()
            for key,selection in paws.items():
                data[key].append([cache[o][i] for o,ids in selection for i in ids])
    finally:scene.frame_set(saved[0],subframe=saved[1])
    results={k:summarize(times,p,roots,args.floor_z*scale,near=args.near,
               penetration=args.penetration,slide=args.slide) for k,p in data.items()}
    flight=np.all([v.pop('airborne_mask') for v in results.values()],axis=0)
    for v in results.values():v.pop('near_mask')
    if source.stat().st_mtime_ns!=source_stat.st_mtime_ns:
        raise ValueError('Scene file changed during sampling; rerun on stable input')
    report=dict(scene=source.name,actor=args.actor,source_sha256=source_hash,
        source_size_bytes=source_stat.st_size,
        source_mtime_ns=source_stat.st_mtime_ns,
        frames=[float(frames[0]),float(frames[-1])],samples=len(frames),fps=fps,
        thresholds=dict(near_ground_m=args.near,allowed_penetration_m=args.penetration,
                        low_slip_mps=args.slide,floor_scene_z=args.floor_z),
        all_selected_paws_airborne_interval_s=float(np.diff(times)[flight[:-1]&flight[1:]].sum()),
        selection={k:[dict(mesh=o.name,vertices=len(ids),bones=[g.name for g in o.vertex_groups
                   if any(g.name.lower().endswith('_'+s.lower()) for s in [k[-1]]) and
                   re.match(r'hand|finger|ankle|ball|toe|foot',g.name,re.I)]) for o,ids in sel]
                   for k,sel in paws.items()},paws=results,
        limits='Geometric band entries are contact candidates, not proof of planted feet. '
        'Flight requires all selected paws above band. Weighted vertices can miss surface interiors. '
        'Root-relative velocity includes turns and all installed pose layers; no isolated native action. '
        'Flat floor only; no balance, force, clothing, weapon or visual validation. '
        'Vertex statistics are pooled and sample-dependent; no pass/fail claim.')
    write_json_report(args.json,json.dumps(report,indent=2,allow_nan=False),
                      [source,args.metadata])
    print('GAIT_METRICS',args.json,flush=True)


if __name__=='__main__':main()
