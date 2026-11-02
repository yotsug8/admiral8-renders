"""Negative acting fixture: hesitation/reach exceeds the Pudge sleeve's range.

No grasp, production integration or universal action generator is implied.
Writes checks and seven diagnostic pose cards; the known defect must reject it.
This is retained to reproduce the limitation, not as a ready action template.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contact_reaction import _rig, _solve_leg
from study_character_intent import apply_pose, surfaces, inspect_pose
from study_character_overlap import material
from study_neck_corrective import snapshot

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'_game/study/intent_decision'
SOURCE = ROOT/'_game/study/neck_methods/delivery01/scene.blend'
FPS, COUNT = 30, 168


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def channel(frame, keys):
    if frame <= keys[0][0]:
        return np.asarray(keys[0][1], dtype=float)
    for (a, va), (b, vb) in zip(keys, keys[1:]):
        if a <= frame <= b:
            t=(frame-a)/(b-a)
            t=t*t*t*(10+t*(-15+6*t))
            return np.asarray(va)+(np.asarray(vb)-np.asarray(va))*t
    return np.asarray(keys[-1][1], dtype=float)


def cube(name, center, scale, color):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    ob=bpy.context.object;ob.name=name;ob.scale=scale
    ob.data.materials.append(material(name,color))
    bevel=ob.modifiers.new('Soft edges','BEVEL');bevel.width=.025;bevel.segments=3
    ob.modifiers.new('Normals','WEIGHTED_NORMAL')
    return ob


def linear(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation='LINEAR'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    out=args.out.resolve()
    if not out.is_relative_to(BASE.resolve()) or out==BASE.resolve():
        raise ValueError('Use a child of _game/study/intent_decision')
    out.mkdir(parents=True,exist_ok=False)
    source_hash=digest(SOURCE)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
    sc=bpy.context.scene;sc.frame_set(0)
    arm=next(o for o in sc.objects if o.type=='ARMATURE')
    basis={b.name:b.matrix_basis.copy() for b in arm.pose.bones}
    arm.animation_data_clear()
    for bone in arm.pose.bones:
        bone.matrix_basis=basis[bone.name]
        bone.rotation_mode='QUATERNION'
    meshes=[o for o in sc.objects if o.type=='MESH' and not o.hide_render
            and any(m.type=='ARMATURE' for m in o.modifiers)]
    for ob in meshes:
        if ob.data.shape_keys:ob.data.shape_keys.animation_data_clear()
    bpy.context.view_layer.update()
    sleeve=next(o for o in meshes if o.name.endswith('leftarm_model'))
    baseline=surfaces(meshes)
    pts=np.concatenate(list(baseline.values()))
    height=float(np.ptp(pts[:,2]))
    base={b.name:arm.matrix_world@b.matrix for b in arm.pose.bones}
    pelvis,legs,_,_=_rig(arm,())
    sole_ids={};foot_ids={}
    for leg in legs:
        ankle=arm.pose.bones[leg[2]]
        names={b.name for b in [ankle,*ankle.children_recursive]}
        candidates={}
        for ob in meshes:
            groups={g.index for g in ob.vertex_groups if g.name in names}
            ids=np.array([v.index for v in ob.data.vertices
                          if sum(g.weight for g in v.groups if g.group in groups)>.95],dtype=int)
            if len(ids):candidates[ob.name]=ids
        if not candidates:raise ValueError('Missing sole selection')
        z=min(baseline[n][ids,2].min() for n,ids in candidates.items())
        band={n:ids[baseline[n][ids,2]<=z+height*.003] for n,ids in candidates.items()}
        band={n:ids for n,ids in band.items() if len(ids)}
        if sum(map(len,band.values()))<3:raise ValueError('Insufficient support')
        sole_ids[ankle.name]=band
        for n,ids in band.items():foot_ids[n]=np.union1d(foot_ids.get(n,np.array([],dtype=int)),ids)
    # Small ordinary fruit: no glow or movement supplies the character's intention.
    fruit_center=Vector((1.65,2.10,2.20));radius=.18
    cube('Decision_stand',(1.65,2.10,.965),(.55,.55,1.93),(.23,.14,.065))
    cube('Decision_top',(1.65,2.10,1.97),(.90,.75,.10),(.34,.23,.12))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=radius,location=fruit_center)
    fruit=bpy.context.object;fruit.name='Decision_fruit'
    fruit.data.materials.append(material('Fruit red',(.55,.045,.025)))
    for p in fruit.data.polygons:p.use_smooth=True
    cube('Fruit_stem',(1.65,2.10,2.40),(.035,.035,.09),(.12,.07,.025))
    # Three-quarter camera on the free-hand side, unchanged throughout the action.
    cam=bpy.data.objects.new('Decision_camera',bpy.data.cameras.new('Decision_camera'))
    sc.collection.objects.link(cam)
    target=Vector((.35,.85,2.05));cam.location=target+Vector((9,8,4.5))
    cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.type='ORTHO';cam.data.ortho_scale=7.0
    sc.camera=cam
    sc.render.resolution_x,sc.render.resolution_y=720,600
    sc.render.resolution_percentage=100;sc.eevee.taa_render_samples=32
    sc.frame_start,sc.frame_end,sc.render.fps,sc.render.fps_base=0,COUNT-1,FPS,1.
    wrist_start=base['wrist_L'].translation.copy()
    # The hand makes a small aborted impulse, draws back, then reaches visibly.
    hand_keys=[(0,wrist_start),(22,wrist_start),(39,wrist_start+Vector((.24,0,.24))),
               (53,wrist_start+Vector((-.07,-.08,.20))),
               (89,wrist_start+Vector((-.07,-.08,.20))),
               (137,Vector((.72,2.15,2.72))),(167,Vector((.72,2.15,2.72)))]
    face=bpy.data.objects['Study_joined_head_torso'].data.shape_keys
    last={};kinematic_error=0.
    for frame in range(COUNT):
        pitch=float(channel(frame,[(0,0),(40,0),(56,-5),(88,-5),(124,8),(167,8)]))
        shift=channel(frame,[(0,(0,0,0)),(40,(0,0,0)),(56,(-.025,0,-.006)),
                             (88,(-.025,0,-.006)),(124,(.025,0,-.008)),(167,(.025,0,-.008))])
        apply_pose(arm,base,basis,pelvis,legs,height,dict(shift=shift,pitch=pitch,shoulder=(0,0,0),elbow=(0,0,0)))
        current={b.name:arm.matrix_world@b.matrix for b in arm.pose.bones}
        desired={};target_wrist=current['wrist_L'].copy();target_wrist.translation=Vector(channel(frame,hand_keys))
        wrist_angle=float(channel(frame,[(0,0),(89,0),(137,-25),(167,-25)]))
        target_wrist=Matrix.Translation(target_wrist.translation)@Matrix.Rotation(math.radians(wrist_angle),4,'Y')@target_wrist.to_3x3().to_4x4()
        _solve_leg(current,desired,('bicep_L','elbow_L','wrist_L'),Vector(),None,Vector((1,0,0)),target_wrist)
        for n in ('bicep_L','elbow_L','wrist_L'):
            arm.pose.bones[n].matrix=arm.matrix_world.inverted()@desired[n]
            bpy.context.view_layer.update()
        kinematic_error=max(kinematic_error,((arm.matrix_world@arm.pose.bones['wrist_L'].matrix).translation-target_wrist.translation).length)
        yaw=float(channel(frame,[(0,0),(9,0),(24,10),(167,10)]))
        nod=float(channel(frame,[(0,0),(14,0),(29,4),(89,4),(109,7),(125,4),(167,4)]))
        # Keep the source's tested modest head range; stronger turns failed QA.
        for name,share in [('head',1.)]:
            head=arm.pose.bones[name];hm=arm.matrix_world@head.matrix;p=hm.translation
            transform=Matrix.Translation(p)@Matrix.Rotation(math.radians(yaw*share),4,'Z')@Matrix.Rotation(math.radians(nod*share),4,'Y')@Matrix.Translation(-p)
            head.matrix=arm.matrix_world.inverted()@transform@hm
            bpy.context.view_layer.update()
        for name,value in [('eyeLeft',.5),('eyeDown',.4)]:
            key=face.key_blocks[name]
            key.value=float(channel(frame,[(0,0),(5,0),(12,value),(167,value)]))
            key.keyframe_insert('value',frame=frame)
        bpy.context.view_layer.update()
        for bone in arm.pose.bones:
            if bone.name in last and bone.rotation_quaternion.dot(last[bone.name])<0:bone.rotation_quaternion.negate()
            last[bone.name]=bone.rotation_quaternion.copy()
            for prop in ('location','rotation_quaternion','scale'):bone.keyframe_insert(prop,frame=frame)
    linear(arm.animation_data.action)
    linear(face.animation_data.action)
    sc.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    names=[o.name for o in meshes];arm_name=arm.name;sleeve_name=sleeve.name
    bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),use_scripts=False)
    sc=bpy.context.scene;arm=bpy.data.objects[arm_name]
    meshes=[bpy.data.objects[n] for n in names];cam=bpy.data.objects['Decision_camera']
    checks=[]
    for i in range((COUNT-1)*4+1):
        frame=i/4;sc.frame_set(int(frame),subframe=frame%1)
        bpy.context.view_layer.update()
        row=inspect_pose(sc,arm,meshes,baseline,foot_ids,sole_ids,height,[cam])
        hand=snapshot(bpy.data.objects[sleeve_name])
        tree=BVHTree.FromPolygons(hand['points'],hand['triangles'],all_triangles=True)
        nearest=tree.find_nearest(fruit_center)
        row['fruit_surface_gap']=float(nearest[3]-radius)
        row['passed']=row['passed'] and row['fruit_surface_gap']>.05
        row['frame']=frame;checks.append(row)
    report=dict(passed=all(r['passed'] for r in checks) and kinematic_error<height*.001,
        frames=COUNT,fps=FPS,samples=len(checks),kinematic_error=kinematic_error,
        source_sha256=source_hash,scene_sha256=digest(out/'scene.blend'),checks=checks,
        limits='No grasp; fixed supports, skin and framing only. No exhaustive collisions, gaze or physical COM proof.')
    report['source_unchanged']=digest(SOURCE)==source_hash
    report['passed']=report['passed'] and report['source_unchanged']
    (out/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('DECISION',json.dumps({k:v for k,v in report.items() if k!='checks'}),flush=True)
    # Diagnostic pose cards also show rejected results, never publish them as passed.
    for frame in (0,24,53,89,124,137,167):
        sc.frame_set(frame);sc.camera=cam;sc.render.filepath=str(out/f'pose_{frame:04d}.png')
        bpy.ops.render.render(write_still=True)
    if not report['passed']:raise ValueError('Pose or transition failed: inspect audit before motion render')


if __name__=='__main__':main()
