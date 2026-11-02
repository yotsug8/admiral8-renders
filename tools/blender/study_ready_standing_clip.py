"""Select one unchanged 3 s window from CMU 77_02 using measured limits."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import bpy
import numpy as np

BONES = ['LowerBack','Spine','Spine1','Neck1','Head']
SOURCE_SHA = 'd6eef8f4ab182bef1bb5db0c46cbec0261b81a63ce1720b8a19777b7e79887a9'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def angle(a,b):
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    a=a/np.linalg.norm(a,axis=-1,keepdims=True)
    b=b/np.linalg.norm(b,axis=-1,keepdims=True)
    d=np.clip(np.abs(np.sum(a*b,axis=-1)),0,1)
    return np.degrees(2*np.arccos(d))


def import_bvh(path):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.render.fps=60
    bpy.context.scene.render.fps_base=1
    bpy.context.scene.unit_settings.system='METRIC'
    bpy.context.scene.unit_settings.scale_length=1
    result = bpy.ops.import_anim.bvh(filepath=str(path),target='ARMATURE',global_scale=0.0254/0.45,
        frame_start=1,use_fps_scale=False,update_scene_fps=False,update_scene_duration=False,
        rotate_mode='NATIVE',axis_forward='-Z',axis_up='Y')
    if result != {'FINISHED'}:
        raise RuntimeError(f'BVH import failed: {result}')
    return bpy.context.object


def observe(rig):
    world=rig.matrix_world
    return dict(q={n:list((world@rig.pose.bones[n].matrix).to_quaternion().normalized()) for n in BONES},
        root=list(world@rig.pose.bones['Hips'].head),
        feet={side:[list(world@p) for n in [side+'Foot',side+'ToeBase']
              for p in [rig.pose.bones[n].head,rig.pose.bones[n].tail]] for side in ['Left','Right']})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--reopen',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    out=args.out.resolve()
    assert sha(args.source)==SOURCE_SHA
    bpy.context.preferences.filepaths.file_preview_type='NONE'
    bpy.context.preferences.filepaths.save_version=0
    if args.reopen:
        prior=json.loads((out/'importreceipt.json').read_text())
        bpy.ops.wm.open_mainfile(filepath=str(out/'ready_standing.blend'),load_ui=False,use_scripts=False)
        rig=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
        errors=[]
        for i in range(180):
            bpy.context.scene.frame_set(i+1);new=observe(rig);old=prior['samples'][i]
            errors.extend(float(angle(new['q'][n],old['q'][n])) for n in BONES)
            assert new['root']==old['root'] and new['feet']==old['feet']
        result={'frames':180,'max_quaternion_error_deg':max(errors),'root_and_feet_exact':True,
                'blend_sha256':sha(out/'ready_standing.blend')}
        assert max(errors)<0.00001
        (out/'reopen.json').write_text(json.dumps(result,indent=2))
        print('REOPEN',json.dumps(result));return
    out.mkdir(parents=True,exist_ok=False)
    text=args.source.read_text();hier,motion=text.split('MOTION')
    rows=[line.strip() for line in motion.splitlines() if line.strip()][2:]
    assert len(rows)==938 and sum(map(int,re.findall(r'CHANNELS (\d+)',hier)))==96
    assert all(len(row.split())==96 and all(math.isfinite(float(v)) for v in row.split()) for row in rows)
    real=rows[1:]
    def write_bvh(path,selected):
        path.write_text(hier+'MOTION\nFrames: '+str(len(selected))+'\nFrame Time: 0.016666666666666667\n'+'\n'.join(selected)+'\n',encoding='ascii')
    full=out/'77_02.full_60fps.bvh';write_bvh(full,real)
    rig=import_bvh(full);all_samples=[]
    for frame in range(1,len(real)+1):
        bpy.context.scene.frame_set(frame);all_samples.append(observe(rig))
    quats={n:np.array([s['q'][n] for s in all_samples]) for n in BONES}
    root=np.array([s['root'] for s in all_samples])
    feet={side:np.array([s['feet'][side] for s in all_samples]) for side in ['Left','Right']}
    windows=[]
    for start in range(len(real)-179):
        stop=start+180
        metrics={n:{'max_from_first_deg':float(angle(q[start:stop],q[start]).max()),
                    'max_step_30fps_deg':float(angle(q[start:stop-2],q[start+2:stop]).max())}
                 for n,q in quats.items()}
        rotation_pass=all(m['max_from_first_deg']<=20 and m['max_step_30fps_deg']<3 for m in metrics.values())
        foot_displacements={s:float(np.linalg.norm(p[start:stop]-p[start],axis=-1).max()) for s,p in feet.items()}
        root_displacement=float(np.linalg.norm(root[start:stop]-root[start],axis=-1).max())
        # Conservative position screen, not a claim of sole contact.
        standing_pass=max(foot_displacements.values())<=0.05
        live=metrics['Head']['max_from_first_deg']>=0.5
        windows.append(dict(amc=[start+1,stop],rotation_pass=rotation_pass,standing_position_screen=standing_pass,
                            nonstatic=live,bones=metrics,foot_max_displacement_m=foot_displacements,
                            root_max_displacement_m=root_displacement))
    eligible=[w for w in windows if w['rotation_pass'] and w['standing_position_screen'] and w['nonstatic']]
    selected=min(eligible,key=lambda w:max(m['max_from_first_deg'] for m in w['bones'].values())) if eligible else None
    summary={'source_sha256':SOURCE_SHA,'source_frames_without_tpose':len(real),'tested_windows':len(windows),
             'rotation_passing_windows':sum(w['rotation_pass'] for w in windows),'eligible_windows':len(eligible),
             'selection':'Among qualifying windows, minimize the largest world delta across the five bones; root drift is reported, not treated as a step',
             'limits':{'max_world_from_first_deg':20,'max_world_step_30fps_deg_exclusive':3,
                       'foot_endpoint_max_displacement_m':0.05,
                       'head_min_excursion_deg_nonstatic':0.5},'selected':selected}
    (out/'selection.json').write_text(json.dumps(summary,indent=2))
    (out/'all_windows.json').write_text(json.dumps(windows,separators=(',',':')))
    if not eligible:
        best=min(windows,key=lambda w:max(m['max_from_first_deg']/20 for m in w['bones'].values())+max(m['max_step_30fps_deg']/3 for m in w['bones'].values()))
        print('NO_MATCH',json.dumps(summary),'BEST',json.dumps(best));return
    chosen=selected;start=chosen['amc'][0]-1
    clip=out/'77_02_standing_3s_60fps.bvh';write_bvh(clip,real[start:start+180])
    rig=import_bvh(clip);samples=[];poses=[]
    for frame in range(1,181):
        bpy.context.scene.frame_set(frame);samples.append(observe(rig))
        poses.append({b.name:[list(rig.matrix_world@b.head),list(rig.matrix_world@b.tail)] for b in rig.pose.bones})
    original=all_samples[start:start+180]
    rotation_error=max(float(angle(a['q'][n],b['q'][n])) for a,b in zip(samples,original) for n in BONES)
    point_error=max(float(np.linalg.norm(np.array(a[k])-b[k])) if k=='root' else
                    max(float(np.linalg.norm(np.array(a[k][s])-b[k][s],axis=-1).max()) for s in ['Left','Right'])
                    for a,b in zip(samples,original) for k in ['root','feet'])
    print('FULL_VS_EXCERPT',rotation_error,point_error)
    assert rotation_error<0.001 and point_error<0.000001
    bpy.context.scene.frame_start=1;bpy.context.scene.frame_end=180;bpy.context.scene.frame_set(1)
    assert len(rig.data.bones)==31
    assert not rig.animation_data.drivers and not bpy.data.texts and not bpy.data.libraries
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'ready_standing.blend'),compress=True)
    receipt={'blender':bpy.app.version_string,'build':bpy.app.build_hash.decode(),'source_sha256':SOURCE_SHA,
             'bvh_sha256':sha(clip),'blend_sha256':sha(out/'ready_standing.blend'),'fps':60,'frames':180,
             'duration_seconds':3,'meters_per_source_unit':0.0254/0.45,'amc':chosen['amc'],
             'source_sample_time_seconds':[start/60,(start+179)/60],'selected_metrics':chosen,
             'source_excerpt_pose_exact':samples==original,
             'source_excerpt_rotation_error_deg':rotation_error,'source_excerpt_point_error_m':point_error,
             'bones':[{'name':b.name,'parent':b.parent.name if b.parent else None} for b in rig.data.bones],
             'foot_endpoint_min_z_m':{s:min(p['feet'][s][i][2] for p in samples for i in range(4)) for s in ['Left','Right']},
             'root_end_minus_start_m':(np.array(samples[-1]['root'])-samples[0]['root']).tolist(),
             'root_axis_ranges_m':np.ptp(np.array([s['root'] for s in samples]),axis=0).tolist(),
             'samples':samples}
    (out/'importreceipt.json').write_text(json.dumps(receipt,separators=(',',':')))
    (out/'poses.json').write_text(json.dumps(poses,separators=(',',':')))
    print('SELECTED',json.dumps(summary))


if __name__=='__main__':
    main()
