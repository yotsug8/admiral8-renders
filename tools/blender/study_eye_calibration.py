"""Bounded eye-FACS calibration on an in-memory copy; never saves the source.

Blender --python this_file -- inspect / audit / render.
Ordinary Python -- texture / review (Pillow and NumPy already installed).
All generated evidence stays in _game/study/eye_calibration.
"""
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/study/eye_calibration'
SOURCE = ROOT / '_game/study/face_staging/b/face_staging.blend'
VALUES = (0.0, 0.175, 0.35)
# Original 640x360 camera, enlarged six times, fixed pixel crop.
CROP = (175, 100, 345, 170)
sys.path.insert(0, str(ROOT / 'tools/blender'))


def dump(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def inspect():
    import bpy
    import numpy as np
    from study_face_staging import head, islands, evaluated
    obj = head()
    kb = obj.data.shape_keys.key_blocks
    base = np.array([v.co[:] for v in kb[0].data])
    groups = [g for g in islands(obj.data) if len(g) == 15]
    eye_ids = set(sum(groups, []))
    keys = []
    for k in kb:
        delta = np.array([v.co[:] for v in k.data])-base
        moved = np.linalg.norm(delta, axis=1)>1e-8
        keys.append(dict(name=k.name, value=k.value, slider=[k.slider_min,k.slider_max],
            relative=k.relative_key.name, moved=int(moved.sum()),
            eye_vertices_moved=int(moved[list(eye_ids)].sum()), max_delta=float(np.linalg.norm(delta,axis=1).max())))
    materials = []
    for mat in obj.data.materials:
        images = []
        for node in mat.node_tree.nodes:
            if node.type != 'TEX_IMAGE' or not node.image:
                continue
            im = node.image
            images.append(dict(name=im.name, size=list(im.size), colorspace=im.colorspace_settings.name,
                vector_links=[(l.from_node.type,l.from_socket.name) for l in node.inputs['Vector'].links]))
            if 'color' in im.name.lower():
                copy = im.copy()
                copy.filepath_raw = str(OUT / 'head_color.png')
                copy.file_format = 'PNG'
                copy.save()
                bpy.data.images.remove(copy)
        materials.append(dict(name=mat.name,images=images))
    mesh=obj.data
    mesh.calc_loop_triangles()
    uv=mesh.uv_layers.active.data
    dump('inventory.json',dict(source_sha256=digest(SOURCE),frame=51,head=obj.name,keys=keys,
        materials=materials,uv_layer=mesh.uv_layers.active.name,
        eye_groups=[dict(ids=g,points=evaluated(obj)[g].tolist(),
            triangles=[dict(vertices=list(t.vertices),uv=[list(uv[i].uv) for i in t.loops])
                       for t in mesh.loop_triangles if set(t.vertices)<=set(g)]) for g in groups]))
    print('EYE_CALIBRATION_INSPECT_OK',flush=True)


def texture():
    """Select the painted dark pupil, excluding its white painted highlight."""
    import numpy as np
    from PIL import Image, ImageDraw
    im=Image.open(OUT/'head_color.png').convert('RGB')
    a=np.array(im)
    y,x=np.where(a[283:301,435:460].max(axis=2)<65)
    pixels=np.stack((x+435,y+283),axis=1)
    assert len(pixels)>100
    center=pixels.mean(axis=0)
    dump('texture_landmark.json',dict(texture_sha256=digest(OUT/'head_color.png'),
        method='Dark pixels max(R,G,B)<65 in hand-localized pupil ROI [435,283,460,301]; texel centers, top-left origin.',
        pixels=pixels.tolist(),center_pixel=center.tolist(),
        uv=[float((center[0]+.5)/512),float(1-(center[1]+.5)/512)],
        limitation='Painted-pupil landmark, not an optical axis; ROI/painted highlight make center approximate.'))
    crop=im.crop((410,265,490,325)).resize((800,600))
    d=ImageDraw.Draw(crop)
    cx,cy=(center[0]-410)*10,(center[1]-265)*10
    d.line((cx-12,cy,cx+12,cy),fill='cyan',width=2)
    d.line((cx,cy-12,cx,cy+12),fill='cyan',width=2)
    crop.save(OUT/'iris_texture.png')
    print('EYE_CALIBRATION_TEXTURE_OK')


def setup():
    import bpy
    from study_face_staging import head
    sc=bpy.context.scene
    obj=head()
    keys=obj.data.shape_keys
    values={k.name:k.value for k in keys.key_blocks}
    keys.animation_data_clear()
    for k in keys.key_blocks:
        k.value=values[k.name]
    assert keys.key_blocks['eyeClosed'].value==0
    assert all(keys.key_blocks[n].value==0 for n in ('eyeRight','eyeUp','eyeDown'))
    sc.render.resolution_x,sc.render.resolution_y=3840,2160
    sc.render.resolution_percentage=100
    sc.render.use_border=True
    sc.render.use_crop_to_border=True
    x0,y0,x1,y1=CROP
    sc.render.border_min_x,sc.render.border_max_x=x0/640,x1/640
    sc.render.border_min_y,sc.render.border_max_y=1-y1/360,1-y0/360
    sc.render.image_settings.file_format='PNG'
    return obj,values


def sample(value):
    import bpy
    import numpy as np
    from study_face_staging import head, evaluated
    obj=head()
    obj.data.shape_keys.key_blocks['eyeLeft'].value=value
    obj.data.update()
    bpy.context.view_layer.update()
    return evaluated(obj)


def uv_binding(mesh, group, uv_point):
    """Barycentric binding of an actual texture landmark to a mesh triangle."""
    import numpy as np
    uv=mesh.uv_layers.active.data
    for tri in mesh.loop_triangles:
        if not set(tri.vertices)<=set(group):
            continue
        coords=np.array([uv[i].uv[:] for i in tri.loops])
        q=np.array(uv_point)+[int(coords[:,0].mean()),0]
        try:
            w=np.linalg.solve(np.vstack((coords.T,np.ones(3))),np.r_[q,1.])
        except np.linalg.LinAlgError:
            continue
        if min(w)>=-1e-7:
            return np.array(tri.vertices),w
    raise ValueError('Pupil texel is outside the eye UV triangles')


def pupil_measure(obj,p,groups):
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from bpy_extras.object_utils import world_to_camera_view
    sc=bpy.context.scene
    camera=sc.camera
    landmark=json.loads((OUT/'texture_landmark.json').read_text())
    deps=bpy.context.evaluated_depsgraph_get()
    trees=[]
    for o in sc.objects:
        if o.type!='MESH' or o.hide_render:
            continue
        ev=o.evaluated_get(deps)
        me=ev.to_mesh()
        try:
            trees.append(BVHTree.FromPolygons([ev.matrix_world@v.co for v in me.vertices],
                                             [list(f.vertices) for f in me.polygons]))
        finally:
            ev.to_mesh_clear()
    def project(point):
        q=world_to_camera_view(sc,camera,Vector(point))
        return np.array([q.x*3840-CROP[0]*6,(1-q.y)*2160-CROP[1]*6])
    results=[]
    for group in groups:
        vids,w=uv_binding(obj.data,group,landmark['uv'])
        center=w@p[vids]
        pixels=[]
        visible=[]
        for x,y in landmark['pixels']:
            ids,weights=uv_binding(obj.data,group,[(x+.5)/512,1-(y+.5)/512])
            point=weights@p[ids]
            ray=Vector(point)-camera.matrix_world.translation
            distance=ray.length
            hits=[t.ray_cast(camera.matrix_world.translation,ray.normalized(),distance+.001) for t in trees]
            nearest=min((hit[3] for hit in hits if hit[0] is not None),default=float('inf'))
            px=project(point)
            pixels.append(px)
            if abs(nearest-distance)<.00005:
                visible.append(px)
        results.append(dict(group_first_vertex=group[0],center_uv=landmark['uv'],
            center_binding=dict(vertices=vids.tolist(),weights=w.tolist()),
            center_world=center.tolist(),center_crop_px=project(center).tolist(),
            dark_pupil_samples=len(pixels),visible_samples=len(visible),
            visible_centroid_crop_px=np.mean(visible,axis=0).tolist() if visible else None,
            eye_bounds_crop_px=[np.min([project(v) for v in p[group]],axis=0).tolist(),
                                np.max([project(v) for v in p[group]],axis=0).tolist()]))
    return results


def audit():
    import bpy
    import numpy as np
    from mathutils.bvhtree import BVHTree
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from study_face_staging import actor, evaluated, islands
    obj,values=setup()
    mesh=obj.data
    mesh.calc_loop_triangles()
    tri=np.array([t.vertices[:] for t in mesh.loop_triangles])
    edges=np.array([e.vertices[:] for e in mesh.edges])
    groups=[g for g in islands(mesh) if len(g)==15]
    assert len(groups)==2
    eye_set=set(sum(groups,[]))
    eye_tri=np.array([i for i,t in enumerate(tri) if set(t)<=eye_set])
    rest_tri=np.array([i for i,t in enumerate(tri) if not set(t)<=eye_set])
    key=mesh.shape_keys.key_blocks
    lid_ids=set()
    for name in ('eyeLeft','eyeRight','eyeUp','eyeDown','eyeClosed','squint','upperLidRaiser'):
        lid_ids.update(i for i,(a,b) in enumerate(zip(key[name].data,key[0].data)) if (a.co-b.co).length>1e-7)
    lid_tri=np.array([i for i,t in enumerate(tri) if set(t)&lid_ids])
    changed=np.array([(a.co-b.co).length>1e-8 for a,b in zip(key['eyeLeft'].data,key[0].data)])
    other={o.name:evaluated(o) for o in actor() if o.type=='MESH' and o!=obj}
    def geometry(p):
        q=p[tri]
        cross=np.cross(q[:,1]-q[:,0],q[:,2]-q[:,0])
        return np.linalg.norm(p[edges[:,0]]-p[edges[:,1]],axis=1),np.linalg.norm(cross,axis=1),cross
    def contacts(p):
        a=BVHTree.FromPolygons(p.tolist(),tri[eye_tri].tolist(),all_triangles=True)
        b=BVHTree.FromPolygons(p.tolist(),tri[rest_tri].tolist(),all_triangles=True)
        return {(int(eye_tri[i]),int(rest_tri[j])) for i,j in a.overlap(b)}
    base=sample(0.)
    bl,ba,bn=geometry(base)
    bc=contacts(base)
    rows=[]
    for value in VALUES:
        p=sample(value)
        lengths,areas,normals=geometry(p)
        mask=ba>1e-10
        angles=np.degrees(np.arccos(np.clip(np.sum(bn*normals,axis=1)/np.maximum(ba*areas,1e-30),-1,1)))
        ratios=lengths/np.maximum(bl,1e-12)
        area_ratios=areas/np.maximum(ba,1e-30)
        lm=lid_tri[mask[lid_tri]]
        cc=contacts(p)
        fixed_error=float(np.abs(p[~changed]-base[~changed]).max())
        other_error=max(float(np.abs(evaluated(bpy.data.objects[n])-v).max()) for n,v in other.items())
        assert fixed_error<1e-7 and other_error<1e-7
        assert all(abs(k.value-values[k.name])<1e-7 for k in key if k.name!='eyeLeft')
        worst=int(np.argmax(ratios))
        normal_i=int(lm[np.argmax(angles[lm])])
        skin_lm=np.array([i for i in lm if i not in set(eye_tri)])
        def location(index):
            q=world_to_camera_view(bpy.context.scene,bpy.context.scene.camera,Vector(p[tri[index]].mean(axis=0)))
            return dict(triangle=index,vertices=tri[index].tolist(),
                centroid_crop_px=[q.x*3840-CROP[0]*6,(1-q.y)*2160-CROP[1]*6])
        row=dict(value=value,head_vertex_sha256=hashlib.sha256(p.tobytes()).hexdigest(),
            fixed_head_vertex_error=fixed_error,other_mesh_error=other_error,
            worst_edge=dict(vertices=edges[worst].tolist(),ratio=float(ratios[worst]),
                            before_mm=float(bl[worst]*1000),after_mm=float(lengths[worst]*1000)),
            eye_region_triangles=len(lm),degenerate_triangles_excluded=int((~mask).sum()),
            eye_region_min_area_ratio=float(area_ratios[lm].min()),
            eye_region_max_normal_degrees=float(angles[lm].max()),
            worst_normal_triangle=dict(index=normal_i,vertices=tri[normal_i].tolist()),
            skin_eye_region=dict(triangles=len(skin_lm),min_area_ratio=float(area_ratios[skin_lm].min()),
                max_normal_degrees=float(angles[skin_lm].max())),
            surface_flips_over_90=int((angles[mask]>90).sum()),
            eye_skin_intersections=dict(before=len(bc),after=len(cc),new=sorted(cc-bc),removed=sorted(bc-cc),
                new_locations=[[location(a),location(b)] for a,b in sorted(cc-bc)]),
            pupils=pupil_measure(obj,p,groups))
        row['gross_surface_gate']=bool(ratios.max()<3 and angles[mask].max()<90 and area_ratios[mask].min()>.15)
        rows.append(row)
    report=dict(source_sha256=digest(SOURCE),script_sha256=digest(Path(__file__)),
        frame=51,non_gaze_values={k:v for k,v in values.items() if k!='eyeLeft'},
        camera=dict(name=bpy.context.scene.camera.name,matrix=[list(r) for r in bpy.context.scene.camera.matrix_world],
                    lens=bpy.context.scene.camera.data.lens,original_pixel_crop=CROP,scale=6),
        values=rows,limitation='Finite three-value audit; area/normal/edge and triangle intersections are not a general eyelid collision or optical-axis solver.')
    dump('audit.json',report)
    assert all(r['gross_surface_gate'] for r in rows),'Gross surface defect: no render'
    print('EYE_CALIBRATION_AUDIT_OK',flush=True)


def guard():
    import os
    import subprocess
    raw=subprocess.check_output(['powershell.exe','-NoProfile','-Command',
        "Get-Process blender -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],text=True)
    others=[int(s) for s in raw.split() if int(s)!=os.getpid()]
    if others:
        raise RuntimeError('Another Blender is active; wait before retrying.')
    load=int(subprocess.check_output(['nvidia-smi','--query-gpu=utilization.gpu','--format=csv,noheader,nounits'],text=True).strip())
    if load>25:
        raise RuntimeError('GPU busy; wait before retrying.')
    return dict(other_blender_count=0,gpu_utilization_percent=load)


def render():
    import bpy
    import numpy as np
    report=json.loads((OUT/'audit.json').read_text())
    assert report['source_sha256']==digest(SOURCE)
    assert report['script_sha256']==digest(Path(__file__))
    obj,_=setup()
    ledger_path=OUT/'renders.json'
    ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    for row in report['values']:
        label=f"eyeLeft_{row['value']:.3f}"
        if any(r['label']==label and r['status']=='finished' for r in ledger):
            continue
        assert len(ledger)<3,'Three still attempts maximum'
        assert row['gross_surface_gate']
        p=sample(row['value'])
        assert hashlib.sha256(p.tobytes()).hexdigest()==row['head_vertex_sha256']
        destination=OUT/(label+'.png')
        assert not destination.exists()
        availability=guard()
        ledger.append(dict(label=label,status='started',availability=availability))
        dump('renders.json',ledger)
        bpy.context.scene.render.filepath=str(destination)
        bpy.ops.render.render(write_still=True)
        im=bpy.data.images.load(str(destination),check_existing=False)
        size=list(im.size)
        assert size[0]>=1019 and size[1]>=419
        bpy.data.images.remove(im)
        ledger[-1].update(status='finished',sha256=digest(destination),size=size)
        dump('renders.json',ledger)
        print('EYE_CALIBRATION_RENDER_OK',label,flush=True)


def review():
    """Decode originals; corroborate UV motion with local image translation."""
    import numpy as np
    from PIL import Image, ImageDraw
    report=json.loads((OUT/'audit.json').read_text())
    ledger=json.loads((OUT/'renders.json').read_text())
    assert len(ledger)==3 and all(r['status']=='finished' for r in ledger)
    assert digest(SOURCE)==report['source_sha256']
    images=[]
    for r in ledger:
        path=OUT/(r['label']+'.png')
        assert digest(path)==r['sha256']
        im=Image.open(path).convert('RGB')
        im.load()
        assert list(im.size)==r['size']==[1020,420]
        images.append(im)
    arrays=[np.array(im).astype(float) for im in images]
    base=report['values'][0]['pupils']
    matches=[]
    for index in (1,2):
        eyes=[]
        for j,pupil in enumerate(base):
            x,y=np.rint(pupil['center_crop_px']).astype(int)
            patch=arrays[0][y-18:y+19,x-18:x+19]
            errors=[]
            for dy in range(-3,4):
                for dx in range(-2,17):
                    candidate=arrays[index][y+dy-18:y+dy+19,x+dx-18:x+dx+19]
                    errors.append((float(np.mean((candidate-patch)**2)),dx,dy))
            errors.sort()
            target=report['values'][index]['pupils'][j]
            eyes.append(dict(group_first_vertex=pupil['group_first_vertex'],
                uv_displacement_px=(np.array(target['center_crop_px'])-pupil['center_crop_px']).tolist(),
                best_integer_translation_px=list(errors[0][1:]),best_mse=errors[0][0],second_mse=errors[1][0]))
        matches.append(dict(value=VALUES[index],eyes=eyes))
    sheet=Image.new('RGB',(1020,3*450),(25,25,25))
    draw=ImageDraw.Draw(sheet)
    for i,im in enumerate(images):
        draw.text((12,i*450+8),f'eyeLeft = {VALUES[i]:.3f} | same f51 emotion / camera / light',fill='white')
        sheet.paste(im,(0,i*450+30))
    sheet.save(OUT/'comparison.jpg',quality=94)
    dump('image_verification.json',dict(source_unchanged=True,decoded_stills=3,size=[1020,420],matches=matches,
        method='37x37 RGB patch around UV pupil center, exhaustive integer translation [-2,16] x [-3,3]; corroboration only, not optical-axis recovery.',
        generated_bytes=sum(p.stat().st_size for p in OUT.iterdir() if p.is_file())))
    print('EYE_CALIBRATION_REVIEW_OK')


def main():
    mode=sys.argv[sys.argv.index('--')+1]
    if mode in ('texture','review'):
        globals()[mode]()
        return
    import bpy
    OUT.mkdir(parents=True, exist_ok=True)
    before=digest(SOURCE)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    bpy.context.scene.frame_set(51)
    globals()[mode]()
    assert digest(SOURCE)==before, 'Source changed'


if __name__ == '__main__':
    main()
