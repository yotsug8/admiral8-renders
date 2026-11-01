"""Measured CMU upper-body motion on a frozen Pudge stance, using verified Retarget.

Preserves the initial character pose, source timing and rotation amplitudes.
Only spine/neck/head are transferred; feet, arms' local poses and root stay put.
External data and its conditions: docs/studies/READY_MOTION_CLIP.md.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
import study_retarget_character as character
import study_retarget_smoke as api

ROOT=Path(__file__).resolve().parents[2]
CLIP=ROOT/'_game/study/ready_standing_received/ready_standing.blend'
CLIP_HASH='3f1de74d9f3d4cee2bc39ab2204dd5ec7a716a508c8468cfc43854ffca57c0ac'
MAPPING={'spine1':'LowerBack','spine2':'Spine','spine3':'Spine1',
         'neck1':'Neck1','head':'Head'}
def source_motion(donor, arm, local, source_start, output_frames, clip, clip_hash, amc_start, folder):
    if hashlib.sha256(clip.read_bytes()).hexdigest()!=clip_hash:
        raise ValueError('Unexpected source clip')
    with bpy.data.libraries.load(str(clip),link=False) as (src,dst):
        dst.objects=src.objects
    if len(dst.objects)!=1 or dst.objects[0].type!='ARMATURE':
        raise ValueError('Expected one data-only source armature')
    source=dst.objects[0];sc=bpy.context.scene;sc.collection.objects.link(source)
    if source.animation_data.drivers or bpy.data.texts:
        raise ValueError('Unexpected executable source data')
    sc.frame_set(source_start);bpy.context.view_layer.update()
    forward=sum((source.matrix_world.to_3x3()@(source.pose.bones[s+'ToeBase'].tail-
        source.pose.bones[s+'Foot'].head) for s in ('Left','Right')),Vector())
    forward.z=0;forward.normalize()
    alignment=Matrix.Rotation(-math.atan2(forward.y,forward.x),3,'Z')
    world=arm.matrix_world.to_quaternion().to_matrix()
    aligned=world.inverted()@alignment
    src0={n:(source.matrix_world@source.pose.bones[n].matrix).to_quaternion().to_matrix()
          for n in MAPPING.values()}
    base={n:arm.pose.bones[n].matrix.copy() for n in api.BONES}
    samples=[]
    for frame in range(1,output_frames+1):
        sf=source_start+2*(frame-1);sc.frame_set(sf);bpy.context.view_layer.update()
        samples.append({n:(source.matrix_world@source.pose.bones[n].matrix).to_quaternion().to_matrix()
                        for n in MAPPING.values()})
    # Store all source samples first: writing receiver keys must not drive its
    # parent from unrelated source-frame numbers while solving each hierarchy.
    previous={};max_angle={n:0. for n in MAPPING};max_step={n:0. for n in api.BONES}
    expected=[]
    for frame,sample in enumerate(samples,1):
        sc.frame_set(frame)
        expected_frame={}
        for name in api.BONES:
            b=donor.pose.bones['donor_'+name]
            b.rotation_mode='QUATERNION'
            initial=Matrix(local[name])
            loc,rot,scale=initial.decompose()
            if name in MAPPING:
                src_name=MAPPING[name]
                delta=aligned@sample[src_name]@src0[src_name].inverted()@aligned.inverted()
                desired=delta.to_4x4()@base[name]
                b.matrix=desired
                expected_frame[name]=desired.to_quaternion()
                rot=b.rotation_quaternion.copy()
                max_angle[name]=max(max_angle[name],math.degrees(delta.to_quaternion().angle))
            if name in previous and rot.dot(previous[name])<0:rot.negate()
            if name in previous:
                q=previous[name].rotation_difference(rot)
                max_step[name]=max(max_step[name],math.degrees(2*math.atan2(
                    math.sqrt(q.x*q.x+q.y*q.y+q.z*q.z),abs(q.w))))
            b.location=loc;b.rotation_quaternion=rot;b.scale=scale
            previous[name]=rot.copy()
            for channel in ('location','rotation_quaternion','scale'):b.keyframe_insert(channel,frame=frame)
            bpy.context.view_layer.update()
        expected.append(expected_frame)
    max_expected_error=0.
    for frame,reference in enumerate(expected,1):
        sc.frame_set(frame);bpy.context.view_layer.update()
        for name,q0 in reference.items():
            actual=donor.pose.bones['donor_'+name].matrix.to_quaternion()
            q=q0.rotation_difference(actual)
            max_expected_error=max(max_expected_error,math.degrees(2*math.atan2(
                math.sqrt(q.x*q.x+q.y*q.y+q.z*q.z),abs(q.w))))
    if max_expected_error>.01:
        raise ValueError('Keyed surrogate differs from original source rotations')
    bpy.data.objects.remove(source,do_unlink=True)
    sc.frame_set(1);bpy.context.view_layer.update()
    report={'clip_sha256':clip_hash,'source_amc_frames':[amc_start+source_start-1,amc_start+source_start-1+2*(output_frames-1)],
        'source_fps':60,'output_fps':30,'samples':output_frames,'duration_seconds':output_frames/30,
        'mapping':MAPPING,'source_forward':list(forward),
        'max_rotation_from_initial_deg':max_angle,'max_local_step_deg':max_step,
        'source_to_surrogate_max_rotation_error_deg':max_expected_error,
        'method':'World rotation delta since first sample; fixed horizontal heading alignment; initial pose retained. No root/leg/arm channels, no smoothing, no amplitude scaling.'}
    # Conservative admission filter for this frozen Pudge stance, not a general
    # anatomical limit. A passing source still needs mesh/contact and visual QA.
    report['preflight_pass']=max(max_angle.values())<=20 and max(max_step.values())<3
    api.write_json(folder/'source_motion.json',report)
    if not report['preflight_pass']:
        raise ValueError('Source needs a different reference pose or full-body staging; see source_motion.json')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--mode',choices=('build','audit','keys','video','diagnostic-keys'),required=True)
    p.add_argument('--source-start',type=int,default=1,help='First imported sample, 1-based')
    p.add_argument('--frames',type=int,default=90,help='Output samples at original 30 fps tempo')
    p.add_argument('--clip',type=Path,default=CLIP)
    p.add_argument('--clip-sha256',default=CLIP_HASH)
    p.add_argument('--amc-start',type=int,default=655,help='AMC sample corresponding to imported frame 1')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);folder=args.out.resolve()
    if args.source_start<1 or args.frames<2 or args.source_start+2*(args.frames-1)>180:
        raise ValueError('Requested interval lies outside the source clip')
    api.FRAMES=[1+i/4 for i in range(4*(args.frames-1)+1)]
    if args.mode=='build':
        character.build(folder,animate=lambda d,a,l:source_motion(d,a,l,args.source_start,args.frames,
            args.clip.resolve(),args.clip_sha256,args.amc_start,folder),frame_end=args.frames,
            limits='CMU upper-body only, original tempo. Initial Pudge stance and arm local poses retained; no leg/root/finger motion. Hidden cleaver excluded.')
    elif args.mode=='audit':character.audit(folder,moving_roots=('spine1',))
    elif args.mode=='diagnostic-keys':character.keys(folder,diagnostic=True,frames=(1,58,85))
    else:getattr(character,args.mode)(folder)
    print('MOCAP_LOOK_'+args.mode.upper()+'_OK')


if __name__=='__main__':main()
