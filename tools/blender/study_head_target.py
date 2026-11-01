"""One static head-to-cube study; outputs only under _game/study/head_target.

Uses the existing look_motion helper without invoking its FACS planner.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/study/head_target'
SOURCE = ROOT / '_game/study/face_staging/b/face_staging.blend'
sys.path.insert(0,str(ROOT/'tools/blender'))


def dump(name,value):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect():
    import bpy
    import numpy as np
    from mathutils import Vector
    from study_face_staging import actor,head,evaluated,islands
    sc = bpy.context.scene
    sc.frame_set(51)
    obj = head()
    p = evaluated(obj)
    ids = set(json.loads(sc['face_hold_eye_ids']))
    eyes = [p[g].mean(axis=0) for g in islands(obj.data) if len(g)==15 and set(g)<=ids]
    arms = []
    for arm in actor():
        if arm.type!='ARMATURE':
            continue
        arms.append(dict(name=arm.name,matrix=[list(r) for r in arm.matrix_world],
            bones=[dict(name=b.name,parent=b.parent.name if b.parent else None,
                matrix=[list(r) for r in arm.matrix_world@b.matrix],
                basis=[list(r) for r in b.matrix_basis],
                constraints=[dict(type=c.type,target=getattr(c,'target',None).name if getattr(c,'target',None) else None,
                                  subtarget=getattr(c,'subtarget',None),influence=c.influence,mute=c.mute) for c in b.constraints])
                for b in arm.pose.bones if 'head' in b.name.lower() or 'neck' in b.name.lower() or b.constraints]))
    dump('axes.json',dict(source_sha256=digest(SOURCE),eye_centers=[e.tolist() for e in eyes],
        target=list(bpy.data.objects['face_staging_target'].location),
        root_matrix=[list(r) for r in bpy.data.objects['lina_root'].matrix_world],armatures=arms,
        mesh_modifiers={o.name:[dict(type=m.type,object=getattr(m,'object',None).name if getattr(m,'object',None) else None)
                              for m in o.modifiers] for o in actor() if o.type=='MESH'}))
    print('HEAD_TARGET_INSPECT_OK',flush=True)


def surfaces():
    import bpy
    from study_face_staging import actor
    result={}
    for o in actor():
        if o.type!='MESH' or o.name=='lina_blob':
            continue
        ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh=ev.to_mesh()
        try:
            mesh.calc_loop_triangles()
            result[o.name]=dict(points=[ev.matrix_world@v.co for v in mesh.vertices],
                edges=[tuple(e.vertices) for e in mesh.edges],polygons=[tuple(p.vertices) for p in mesh.polygons],
                triangles=[tuple(t.vertices) for t in mesh.loop_triangles],world_matrix=[list(r) for r in ev.matrix_world])
        finally:
            ev.to_mesh_clear()
    return result


def invariants():
    """Raw meshes/morphs and existing animation; no pose fingerprint."""
    import bpy
    import numpy as np
    from study_face_staging import actor,curves
    data=hashlib.sha256()
    for o in sorted(actor(),key=lambda o:o.name):
        if o.type!='MESH':
            continue
        data.update(o.name.encode())
        data.update(np.array([v.co[:] for v in o.data.vertices]).tobytes())
        data.update(str([list(p.vertices) for p in o.data.polygons]).encode())
        if o.data.shape_keys:
            for k in o.data.shape_keys.key_blocks:
                data.update(k.name.encode())
                data.update(np.array([v.co[:] for v in k.data]).tobytes())
    actions=[(a.name,[(c.data_path,c.array_index,[(list(k.co),list(k.handle_left),list(k.handle_right),k.interpolation)
              for k in c.keyframe_points]) for c in curves(a)]) for a in bpy.data.actions]
    face=[]
    for f in range(108):
        bpy.context.scene.frame_set(f)
        face.append([(o.name,[(k.name,k.value) for k in o.data.shape_keys.key_blocks])
                     for o in actor() if o.type=='MESH' and o.data.shape_keys])
    bpy.context.scene.frame_set(51)
    return dict(raw_mesh_morph_hash=data.hexdigest(),actions_hash=hashlib.sha256(json.dumps(actions).encode()).hexdigest(),
                face_values_hash=hashlib.sha256(json.dumps(face).encode()).hexdigest(),face_samples=108)


def contacts(geometry):
    from mathutils.bvhtree import BVHTree
    trees={n:BVHTree.FromPolygons(s['points'],s['polygons']) for n,s in geometry.items()}
    names=list(trees)
    pairs={}
    for i,a in enumerate(names):
        for b in names[i+1:]:
            if any('lina_head' in n or 'lina_neck' in n for n in (a,b)):
                pairs[a+' | '+b]=set(trees[a].overlap(trees[b]))
    return pairs


def skin_check(base,current):
    from types import SimpleNamespace
    from mathutils.kdtree import KDTree
    from deformation_metrics import compare
    params=SimpleNamespace(edge_epsilon=1e-9,area_epsilon=1e-8,stretch_ratio=1.3,
        growth_m=.002,contraction_ratio=.7,top=5)
    report={}
    for n in base:
        r=compare(base[n],current[n],51,params)
        # Shared spatial seams can use duplicate vertices, invisible to edge tests.
        kd=KDTree(len(base[n]['points']))
        for i,p in enumerate(base[n]['points']):
            kd.insert(p,i)
        kd.balance()
        gaps=[]
        for i,p in enumerate(base[n]['points']):
            for _,j,d in kd.find_range(p,.0001):
                if j>i:
                    gaps.append(((current[n]['points'][i]-current[n]['points'][j]).length-d,i,j))
        r['coincident_seam_pairs']=len(gaps)
        r['largest_seam_growth']=sorted(gaps,reverse=True)[:5]
        report[n]=r
    before,after=contacts(base),contacts(current)
    return dict(meshes=report,contacts={k:dict(before=len(before[k]),after=len(after[k]),
                new=sorted(after[k]-before[k]),removed_count=len(before[k]-after[k])) for k in before},
                limitation='Surface intersections count polygon pairs; existing overlaps and tangency are not a penetration-depth measurement.')


def pose(yaw,pitch):
    import bpy
    from look_motion import apply_looks
    from study_face_staging import head
    sc=bpy.context.scene
    arm=next(m.object for m in head().modifiers if m.type=='ARMATURE')
    root=bpy.data.objects['lina_root']
    actions_before=set(bpy.data.actions)
    before={b.name:b.matrix.copy() for b in arm.pose.bones}
    result=apply_looks(dict(actors={'lina':{}},frames=108,fps=30,looks=[dict(who='lina',
        start=50/30,end=52/30,yaw_deg=yaw,pitch_deg=pitch,attack=1/30,release=1/30,eye_lead=0)]),
        {'lina':dict(arm=arm,root=root,info=dict(head_bone='Head_1'))},sc,30)
    sc.frame_set(51)
    bpy.context.view_layer.update()
    # Extract just the helper's static pose. Remove its temporary NLA window.
    bone=arm.pose.bones['Head_1']
    basis=bone.matrix_basis.copy()
    target=bone.matrix.copy()
    for tr in list(arm.animation_data.nla_tracks):
        if tr.name.startswith('look_motion_'):
            arm.animation_data.nla_tracks.remove(tr)
    for action in set(bpy.data.actions)-actions_before:
        assert action.users==0
        bpy.data.actions.remove(action)
    bone.matrix_basis=basis
    bpy.context.view_layer.update()
    err=max(abs(bone.matrix[i][j]-target[i][j]) for i in range(4) for j in range(4))
    assert err<2e-5
    unchanged={b.name:max(abs(b.matrix[i][j]-before[b.name][i][j]) for i in range(4) for j in range(4))
               for b in arm.pose.bones if b.name!='Head_1' and b not in bone.children_recursive}
    assert max(unchanged.values(),default=0)<2e-5
    return dict(helper=result,static_matrix_error=err,other_bone_max_error=max(unchanged.values(),default=0),
                head_world=[list(r) for r in arm.matrix_world@bone.matrix],yaw_deg=yaw,pitch_deg=pitch,
                temporary_overlay_removed=True)


def gpu_guard():
    import os
    import subprocess
    # Guard against another background Blender; interactive/other processes are
    # left untouched. GPU utilization is sampled immediately before each still.
    ps="Get-CimInstance Win32_Process -Filter \"Name='blender.exe'\" | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    raw=subprocess.check_output(['powershell.exe','-NoProfile','-Command',ps],text=True).strip()
    processes=json.loads(raw) if raw else []
    if isinstance(processes,dict):
        processes=[processes]
    others=[p for p in processes if p['ProcessId']!=os.getpid() and
            any(x in (p.get('CommandLine') or '') for x in (' -b ',' --background '))]
    if others:
        raise RuntimeError('Another background Blender is active; retry render later.')
    load=int(subprocess.check_output(['nvidia-smi','--query-gpu=utilization.gpu','--format=csv,noheader,nounits'],text=True).strip())
    if load>25:
        raise RuntimeError(f'GPU busy ({load}%); retry render later.')
    return dict(other_background_blender_count=len(others),gpu_utilization_percent=load)


def build(correction=False):
    import bpy
    import numpy as np
    from study_face_staging import geometry_check
    label='correction' if correction else 'turned'
    destination=OUT/(label+'.blend')
    assert not destination.exists(),'Preserve earlier attempt'
    baseline_invariants=invariants()
    base=surfaces()
    sc=bpy.context.scene
    # Same comparison camera and cube as FACE_STAGING B. Larger stills permit
    # actual eyelid/neck inspection, not upscaled miniature renders.
    sc.render.resolution_x,sc.render.resolution_y=1920,1080
    # Baseline rendering reads SOURCE directly; avoid a redundant packed copy.
    yaw,pitch=(6,-6) if not correction else (6,-3)
    helper=pose(yaw,pitch)
    assert invariants()==baseline_invariants
    current=surfaces()
    checks=skin_check(base,current)
    checks['framing']=geometry_check(sc.camera,bpy.data.objects['face_staging_target'],bpy.data.objects['face_staging_support'])
    checks['helper']=helper
    checks['invariants']=baseline_invariants
    checks['source_sha256']=digest(SOURCE)
    dump(label+'_qa_presave.json',checks)
    bpy.ops.wm.save_as_mainfile(filepath=str(destination),compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(destination))
    assert invariants()==baseline_invariants
    reopened=surfaces()
    errors={n:max((a-b).length for a,b in zip(current[n]['points'],reopened[n]['points'])) for n in current}
    assert max(errors.values())<1e-6
    checks['reopen_max_coordinate_error']=max(errors.values())
    checks['blend_sha256']=digest(destination)
    dump(label+'_qa.json',checks)
    print('HEAD_TARGET_BUILD_OK',label,flush=True)


def render(label):
    import bpy
    path=SOURCE if label=='baseline' else OUT/(label+'.blend')
    destination=OUT/(label+'.png')
    assert not destination.exists(),'Do not overwrite a rendered attempt'
    ledger_path=OUT/'renders.json'
    ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    assert len(ledger)<3,'Two comparison images and one correction maximum'
    if label!='baseline':
        approved=json.loads((OUT/(label+'_integrity.json')).read_text())
        assert approved['source_sha256']==digest(SOURCE)
        assert approved['blend_sha256']==digest(path)
    availability=gpu_guard()
    bpy.ops.wm.open_mainfile(filepath=str(path))
    sc=bpy.context.scene
    sc.frame_set(51)
    sc.render.resolution_x,sc.render.resolution_y=1920,1080
    sc.render.filepath=str(destination)
    ledger.append(dict(label=label,status='started',availability=availability))
    dump('renders.json',ledger)
    bpy.ops.render.render(write_still=True)
    decoded=bpy.data.images.load(str(destination),check_existing=False)
    assert tuple(decoded.size)==(1920,1080),'Saved PNG did not decode at the requested size'
    bpy.data.images.remove(decoded)
    ledger[-1].update(status='finished',sha256=digest(destination),size=[1920,1080])
    dump('renders.json',ledger)
    print('HEAD_TARGET_RENDER_OK',label,flush=True)


def verify_saved(label):
    """Rebuild in memory and compare saved pose; never overwrites a blend."""
    import bpy
    from study_face_staging import head
    assert label in ('turned','correction')
    path=OUT/(label+'.blend')
    qa=json.loads((OUT/(label+'_qa.json')).read_text())
    source_hash=digest(SOURCE)
    file_hash=digest(path)
    assert source_hash==qa['source_sha256'] and file_hash==qa['blend_sha256']
    original=invariants()
    def packed():
        return {i.name:dict(size=list(i.size),bytes=len(i.packed_file.data),
                    sha256=hashlib.sha256(bytes(i.packed_file.data)).hexdigest())
                for i in bpy.data.images if i.packed_file}
    def stage_data():
        sc=bpy.context.scene
        return dict(objects={n:[list(r) for r in bpy.data.objects[n].matrix_world]
            for n in (sc.camera.name,'face_staging_target','face_staging_support')},
            lens=sc.camera.data.lens,frame_range=[sc.frame_start,sc.frame_end],fps=sc.render.fps)
    images=packed()
    stage_before=stage_data()
    baseline_geometry=surfaces()
    face=head()
    face_name=face.name
    blocks=face.data.shape_keys.key_blocks
    eye_ids=set(json.loads(bpy.context.scene['face_hold_eye_ids']))
    for key in ('eyeClosed','upperLidRaiser','squint'):
        eye_ids.update(i for i,(v,b) in enumerate(zip(blocks[key].data,blocks[0].data)) if (v.co-b.co).length>1e-7)
    pose(qa['helper']['yaw_deg'],qa['helper']['pitch_deg'])
    reconstructed=surfaces()
    bpy.ops.wm.open_mainfile(filepath=str(path))
    assert invariants()==original==qa['invariants']
    assert packed()==images
    assert stage_data()==stage_before
    saved=surfaces()
    errors={n:max((a-b).length for a,b in zip(reconstructed[n]['points'],saved[n]['points'])) for n in reconstructed}
    assert max(errors.values())<1e-6
    for n in reconstructed:
        assert reconstructed[n]['polygons']==saved[n]['polygons']
        assert reconstructed[n]['edges']==saved[n]['edges']
    p,q=baseline_geometry[face_name]['points'],saved[face_name]['points']
    ratios=[]
    for tri in baseline_geometry[face_name]['triangles']:
        if not eye_ids.intersection(tri):
            continue
        a,b,c=tri
        original_area=(p[b]-p[a]).cross(p[c]-p[a]).length
        if original_area>1e-8:
            ratios.append((q[b]-q[a]).cross(q[c]-q[a]).length/original_area)
    assert head().data.shape_keys.key_blocks['eyeClosed'].value==0
    assert digest(path)==file_hash and digest(SOURCE)==source_hash
    dump(label+'_integrity.json',dict(source_sha256=source_hash,blend_sha256=file_hash,
        reconstructed_pose_max_error=max(errors.values()),mesh_errors=errors,packed_images=images,
        invariants=original,stage_identical=True,eye_region=dict(triangles=len(ratios),
            min_area_ratio=min(ratios),max_area_ratio=max(ratios),
            limitation='Morph-displacement mask around eyes, not a complete eyelid contact test.'),
        status='integrity_pass_not_artistic_acceptance'))
    print('HEAD_TARGET_INTEGRITY_OK',label,max(errors.values()),flush=True)


def analyze_saved():
    """Read-only localization; no rendering, deletion, or scene writes."""
    import bpy
    import numpy as np
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from study_face_staging import evaluated,head
    report=json.loads((OUT/'turned_qa.json').read_text(encoding='utf-8'))
    rows={}
    for label,path in [('baseline',SOURCE),('turned',OUT/'turned.blend')]:
        bpy.ops.wm.open_mainfile(filepath=str(path))
        sc=bpy.context.scene
        sc.frame_set(51)
        obj=head()
        points=evaluated(obj)
        def location(o,ids):
            p=evaluated(o)[ids]
            q=world_to_camera_view(sc,sc.camera,Vector(p.mean(axis=0)))
            return dict(center=p.mean(axis=0).tolist(),pixel1920=[q.x*1920,(1-q.y)*1080],
                        vertices=ids)
        triangle=location(obj,[1201,1200,1214])
        triangle['weights']={str(i):{obj.vertex_groups[g.group].name:g.weight for g in obj.data.vertices[i].groups}
                             for i in (1201,1200,1214)}
        pairs=[]
        for key,value in report['contacts'].items():
            if not value['new']:
                continue
            a,b=[bpy.data.objects[n] for n in key.split(' | ')]
            for ia,ib in value['new']:
                pairs.append(dict(objects=[a.name,b.name],polygons=[ia,ib],
                    locations=[location(a,list(a.data.polygons[ia].vertices)),location(b,list(b.data.polygons[ib].vertices))]))
        packed={i.name:hashlib.sha256(bytes(i.packed_file.data)).hexdigest()
                for i in bpy.data.images if i.packed_file}
        rows[label]=dict(contracted_triangle=triangle,new_pair_localizations=pairs,packed_images=packed)
    rows['packed_images_identical']=rows['baseline']['packed_images']==rows['turned']['packed_images']
    rows['baseline'].pop('packed_images')
    rows['turned'].pop('packed_images')
    print('HEAD_TARGET_LOCALIZATION '+json.dumps(rows,ensure_ascii=False),flush=True)


def main():
    import bpy
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['inspect','build','correction','render','analyze-saved','verify'])
    parser.add_argument('--image',choices=['baseline','turned','correction'])
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    if args.mode=='inspect':
        inspect()
    elif args.mode=='render':
        assert args.image
        render(args.image)
    elif args.mode=='analyze-saved':
        analyze_saved()
    elif args.mode=='verify':
        verify_saved(args.image or 'turned')
    else:
        build(args.mode=='correction')


if __name__=='__main__':
    main()
