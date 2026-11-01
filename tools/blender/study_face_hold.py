"""Bounded Lina face study using existing FACS helpers; all output stays local.

Blender: --background --python tools/blender/study_face_hold.py -- build|verify|keys|detail|render
Python: tools/blender/study_face_hold.py assemble
No TTS, source blend edits, production rendering, or shared cache writes.
"""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '_game/study/face_hold'
SOURCE = ROOT / '_game/skits/probe19/gaze_head.blend'
FPS, COUNT = 30, 108
KEYS = (0, 24, 51, 17, 19)  # Three storytelling poses, plus native blink extrema.
STRENGTH = .45


def dump(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emotion():
    """Read the existing literal preset without importing the production CLI."""
    tree = ast.parse((ROOT / 'tools/skit/skit.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == 'EMO' and node.value.func.attr == 'update'
                and node.value.args and isinstance(node.value.args[0], ast.Dict)):
            for key, value in zip(node.value.args[0].keys, node.value.args[0].values):
                if isinstance(key, ast.Constant) and key.value == 'скепсис':
                    return ast.literal_eval(value)
    raise RuntimeError('Existing skepticism preset not found')


def head_object():
    import bpy
    root = bpy.data.objects['lina_root']
    return next(o for o in root.children_recursive if o.type == 'MESH' and o.data.shape_keys)


def coords(obj):
    import bpy
    import numpy as np
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    try:
        a = np.empty(len(mesh.vertices)*3, dtype=np.float64)
        mesh.vertices.foreach_get('co', a)
        m = np.array(ev.matrix_world)
        return a.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
    finally:
        ev.to_mesh_clear()


def build():
    import bpy
    import numpy as np
    from mathutils import Vector, Matrix
    sys.path.insert(0, str(ROOT / 'tools/blender'))
    import face
    from gaze import EYE_CHANNELS
    from contact_reaction import _curves

    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    sc = bpy.context.scene
    sc.frame_set(0)
    bpy.context.view_layer.update()
    root = bpy.data.objects['lina_root']
    members = [root, *root.children_recursive]
    head = head_object()
    kb = head.data.shape_keys.key_blocks
    preset = emotion()
    probe = json.loads((ROOT / '_game/skits/probe15/scene.json').read_text(encoding='utf-8'))
    assert any(e[3] == preset for e in probe['faces']), 'Preset changed since source probe'
    needed = {*EYE_CHANNELS, 'eyeClosed', *(k[:-2] if k.endswith(('_L', '_R')) else k for k in preset)}
    assert needed <= set(kb.keys()), 'No synthetic substitute for missing morphs'
    inventory = {k.name: int(sum((v.co-b.co).length > 1e-7 for v, b in zip(k.data, kb[0].data))) for k in kb}
    assert all(inventory[k] for k in needed), 'Required morph has no displacement'
    # Freeze the source pose and its equipment before replacing the face action.
    matrices = {o.name: o.matrix_world.copy() for o in members}
    bases = {o.name: {b.name: b.matrix_basis.copy() for b in o.pose.bones}
             for o in members if o.type == 'ARMATURE'}
    for o in members:
        o.animation_data_clear()
        o.matrix_world = matrices[o.name]
        if o.type == 'ARMATURE':
            for b in o.pose.bones:
                b.matrix_basis = bases[o.name][b.name]
        if o.type == 'MESH' and o.data.shape_keys:
            o.data.shape_keys.animation_data_clear()
            for k in o.data.shape_keys.key_blocks:
                k.value = 0.
    for o in sc.objects:
        if o not in members and o.type in {'MESH', 'ARMATURE'}:
            o.hide_render = True
    # Resolve images before relocation: retain source materials, pack only used images.
    materials = {slot.material for o in members if o.type == 'MESH' for slot in o.material_slots if slot.material}
    images = {n.image for mat in materials if mat.use_nodes for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image}
    for img in images:
        img.filepath = bpy.path.abspath(img.filepath)
        if not Path(img.filepath).is_file() and not img.packed_file:
            raise FileNotFoundError(img.name)
        img.pack()
    sc.frame_start, sc.frame_end, sc.render.fps = 0, COUNT-1, FPS
    config = dict(actors={'lina': {}}, voices={}, talk={},
                  faces=[[.9, 4.6, 'lina', {k: v*STRENGTH for k, v in preset.items()}, {'attack': .6}]],
                  gazes=[dict(who='lina', start=0., end=5., x=0., y=0., attack=1/FPS, release=.2),
                         dict(who='lina', start=.35, end=5., x=-.35, y=0., attack=.3, release=.2)])
    face.animate(head, 'lina', config, {}, FPS, COUNT, seed=1)
    blink_path = kb['eyeClosed'].path_from_id('value')
    for curve in _curves(head.data.shape_keys.animation_data.action):
        for k in curve.keyframe_points:
            k.interpolation = 'LINEAR'
            if curve.data_path == blink_path:
                # Attempt 2: native full blink exposes a bright slit at the lash.
                # This short study deliberately omits it; do not claim a blink fix.
                k.co.y = 0.
    kb['eyeClosed'].value = 0.
    sc.frame_set(0)
    bpy.context.view_layer.update()
    points = coords(head)
    eye_ids = sorted({i for name in EYE_CHANNELS for i, (v, b) in enumerate(zip(kb[name].data, kb[0].data)) if (v.co-b.co).length > 1e-7})
    eye_center = Vector(points[eye_ids].mean(axis=0))
    cam = sc.camera
    front = cam.matrix_world.translation-eye_center
    front.z = 0.
    front.normalize()
    target = eye_center-Vector((0, 0, .10))
    cam.animation_data_clear()
    cam.data.animation_data_clear()
    cam.data.dof.use_dof = False
    cam.data.sensor_fit = 'VERTICAL'
    cam.data.angle_y = math.radians(34)
    cam.data.clip_start = .02
    # Full facial silhouette and upper hair; chest may exit the portrait frame.
    distance = .84 / (2*math.tan(cam.data.angle_y/2))
    cam.name = 'face_hold_front'
    cam.location = target+front*distance
    cam.rotation_euler = (target-cam.location).to_track_quat('-Z', 'Y').to_euler()
    other = cam.copy()
    other.data = cam.data.copy()
    other.name = 'face_hold_oblique'
    sc.collection.objects.link(other)
    other.location = target + (Matrix.Rotation(math.radians(23), 3, 'Z') @ front)*distance
    other.rotation_euler = (target-other.location).to_track_quat('-Z', 'Y').to_euler()
    marker = bpy.data.objects.new('attention_direction_reference_not_solved', None)
    sc.collection.objects.link(marker)
    marker.location = eye_center + Matrix.Rotation(math.radians(12.25), 3, 'Z') @ front * 2
    marker['limitation'] = 'Direction reference only: eye FACS are not a calibrated binocular target solver.'
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = 320, 360
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.use_file_extension = True
    sc.render.use_compositing = False
    sc.render.use_sequencer = False
    # Existing EEVEE materials; no render-engine or geometry substitutes.
    sc['face_hold_config'] = json.dumps(config)
    sc['face_hold_eye_ids'] = json.dumps(eye_ids)
    sc['face_hold_source_sha256'] = digest(SOURCE)
    dump('inventory.json', dict(source=str(SOURCE.relative_to(ROOT)), source_sha256=digest(SOURCE),
         actor='lina', head=head.name, native_morph_vertices=inventory, required=sorted(needed),
         emotion_source='tools/skit/skit.py:EMO[скепсис]', strength=STRENGTH,
         source_probe15_matches=True, config=config, cameras=[cam.name, other.name],
         attempt=2, blink='omitted; native blink rejected after close-up inspection',
         packed_images=sorted(i.name for i in images), fps=FPS, frames=COUNT))
    witness('before')
    sc.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'face_hold.blend'))
    print('FACE_HOLD_BUILD_OK', flush=True)


def witness(stage):
    import bpy
    import numpy as np
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    head = head_object()
    kb = head.data.shape_keys.key_blocks
    eye_ids = json.loads(sc['face_hold_eye_ids'])
    cams = [bpy.data.objects[n] for n in ('face_hold_front', 'face_hold_oblique')]
    head.data.calc_loop_triangles()
    tri = np.array([t.vertices[:] for t in head.data.loop_triangles])
    edges = np.array([e.vertices[:] for e in head.data.edges])
    def normals(p):
        n = np.cross(p[tri[:,1]]-p[tri[:,0]], p[tri[:,2]]-p[tri[:,0]])
        a = np.linalg.norm(n, axis=1)
        return n/np.maximum(a[:,None], 1e-12), a
    sc.frame_set(0)
    base = coords(head)
    n0, a0 = normals(base)
    local = np.array([v.co[:] for v in kb[0].data])
    ln0, la0 = normals(local)
    legit = np.zeros(len(tri))
    for k in kb[1:]:
        nk, _ = normals(np.array([v.co[:] for v in k.data]))
        legit = np.maximum(legit, np.degrees(np.arccos(np.clip((nk*ln0).sum(axis=1), -1, 1))))
    _, jaw_area = normals(np.array([v.co[:] for v in kb['jawOpen'].data]))
    skin = (legit < 90) & (jaw_area < 2*np.maximum(la0, 1e-12)) & (a0 > 1e-10)
    e0 = np.linalg.norm(base[edges[:,0]]-base[edges[:,1]], axis=1)
    # Native lipPressor has submillimetre tails on the neck/upper chest.
    # Frame the meaningful facial region, but audit skin over the whole mesh.
    moving = np.zeros(len(base), dtype=bool)
    for name in ('eyeClosed', 'outerBrowRaiser', 'chinRaiser', 'lipPressor'):
        moving |= np.linalg.norm(np.array([x.co[:] for x in kb[name].data])-local, axis=1)>.001
    moving[eye_ids] = True
    ids = np.flatnonzero(moving)
    values, vertices, per_frame = [], [], []
    max_skin_angle, max_stretch, max_speed = 0., 1., 0.
    min_area = 1.
    extremes = {}
    failures = []
    for sample in range((COUNT-1)*4+1):
        f = sample/4
        sc.frame_set(int(f), subframe=f%1)
        bpy.context.view_layer.update()
        p = coords(head)
        assert np.isfinite(p).all()
        v = np.array([k.value for k in kb])
        if vertices:
            max_speed = max(max_speed, float(np.linalg.norm(p-vertices[-1], axis=1).max()*4*FPS))
        vertices.append(p)
        values.append(v)
        nn, aa = normals(p)
        angle = np.degrees(np.arccos(np.clip((nn*n0).sum(axis=1), -1, 1)))
        if float(angle[skin].max()) > max_skin_angle:
            i = int(np.argmax(np.where(skin, angle, -1)))
            extremes['skin_normal'] = dict(frame=f, triangle=i, vertices=tri[i].tolist(),
                  neutral_center=base[tri[i]].mean(axis=0).tolist(), active_center=p[tri[i]].mean(axis=0).tolist())
        max_skin_angle = max(max_skin_angle, float(angle[skin].max()))
        min_area = min(min_area, float((aa[skin]/a0[skin]).min()))
        ratios = np.linalg.norm(p[edges[:,0]]-p[edges[:,1]],axis=1)/np.maximum(e0,1e-9)
        if float(ratios.max()) > max_stretch:
            i = int(np.argmax(ratios))
            extremes['edge_stretch'] = dict(frame=f, vertices=edges[i].tolist(), neutral_length_m=float(e0[i]),
                  neutral_center=base[edges[i]].mean(axis=0).tolist(), active_length_m=float(e0[i]*ratios[i]))
        max_stretch = max(max_stretch, float(ratios.max()))
        if np.any(skin & (angle > 90)):
            failures.append(f'skin_fold:{f}')
        if float(ratios.max()) > 3:
            failures.append(f'edge_stretch_over_3:{f}')
        # Facial FACS vertices include eyes, lips and brows; hair assessed in images.
        boxes = []
        for cam in cams:
            q = [world_to_camera_view(sc,cam,Vector(x)) for x in p[ids]]
            box = [min(x.x for x in q),min(x.y for x in q),max(x.x for x in q),max(x.y for x in q)]
            boxes.append(box)
            if not all(.025 < x.x < .975 and .025 < x.y < .975 and x.z > 0 for x in q):
                failures.append(f'face_crop:{cam.name}:{f}')
        if sample % 4 == 0:
            per_frame.append(dict(frame=f, face_boxes=boxes, eye_centroid=p[eye_ids].mean(axis=0).tolist()))
    vertices, values = np.array(vertices), np.array(values)
    hold = vertices[51*4:]
    hold_drift = float(np.abs(hold-hold[0]).max())
    assert hold_drift < 1e-7, 'Hold drift or cyclic motion'
    if failures:
        dump(stage+'_failed.json', dict(failures=failures, per_frame=per_frame))
    assert not failures, failures[:8]
    blink_max = float(values[:,list(kb.keys()).index('eyeClosed')].max())
    assert blink_max == 0., 'Final bounded study must not include the rejected native blink'
    per_frame_step = np.linalg.norm(vertices[4::4]-vertices[:-4:4],axis=2).max(axis=1)
    report = dict(stage=stage, samples=len(values), frames=COUNT, fps=FPS,
                  total_triangles=len(tri), skin_triangles=int(skin.sum()),
                  excluded_triangles=int((~skin).sum()), max_skin_normal_deg=max_skin_angle,
                  min_skin_area_ratio=min_area, max_edge_stretch=max_stretch,
                  max_vertex_speed_m_s=max_speed, hold_max_coordinate_drift_m=hold_drift,
                  blink_max=blink_max, max_adjacent_frame_vertex_delta_m=float(per_frame_step.max()),
                  framing_vertices=len(ids), framing_mask_native_displacement_m=.001,
                  extremes=extremes,
                  failures=failures, per_frame=per_frame,
                  limitations=['Finite quarter-frame samples, not a proof over continuous time.',
                               'No exhaustive eyelid/eyeball or lip collision solver; inspect rendered frames.',
                               'Gaze weights express direction, not precise binocular fixation.',
                               'Skin excludes native eyelid/lip flips and jaw interior as in face.unfold.'])
    if stage == 'before':
        np.savez_compressed(OUT/'before.npz', vertices=vertices, values=values)
    else:
        with np.load(OUT/'before.npz') as before:
            report['reopen_vertex_error_m'] = float(np.abs(vertices-before['vertices']).max())
            report['reopen_channel_error'] = float(np.abs(values-before['values']).max())
        assert report['reopen_vertex_error_m'] < 1e-7 and report['reopen_channel_error'] < 1e-7
    dump(stage+'_qa.json', report)
    print('FACE_HOLD_WITNESS', json.dumps({k:v for k,v in report.items() if k!='per_frame'}), flush=True)


def render(keys_only):
    import bpy
    sc = bpy.context.scene
    if not keys_only:
        assert (OUT/'keys_approved.json').exists(), 'Review keys before animation rendering'
        approval = json.loads((OUT/'keys_approved.json').read_text(encoding='utf-8'))
        assert approval['blend_sha256'] == digest(OUT/'face_hold.blend'), 'Review belongs to a different blend'
        qa = json.loads((OUT/'after_qa.json').read_text())
        assert qa['reopen_vertex_error_m'] < 1e-7 and not qa['failures']
        assert qa['max_skin_normal_deg'] < 90 and qa['max_edge_stretch'] < 3
    frames = KEYS if keys_only else range(COUNT)
    folder = OUT/('keys' if keys_only else 'frames')
    folder.mkdir(exist_ok=True)
    if not keys_only and any(folder.glob('*.png')):
        raise RuntimeError('Animation frames already exist; do not silently repeat the one authorized render')
    for f in frames:
        sc.frame_set(f)
        for view, name in [('front','face_hold_front'),('oblique','face_hold_oblique')]:
            sc.camera = bpy.data.objects[name]
            sc.render.filepath = str(folder/f'{view}_{f:04d}.png')
            bpy.ops.render.render(write_still=True)
    print('FACE_HOLD_RENDER_OK', flush=True)


def diagnostic():
    """Isolate native blink/gaze contributions at the recorded worst eye patch."""
    import bpy
    import numpy as np
    from mathutils import Vector
    sc = bpy.context.scene
    head = head_object()
    kb = head.data.shape_keys.key_blocks
    sc.frame_set(18)
    actual = {k.name: float(k.value) for k in kb[1:] if k.value}
    sc.frame_set(51)
    final = {k.name: float(k.value) for k in kb[1:] if k.value}
    final['eyeClosed'] = 1.
    head.data.shape_keys.animation_data_clear()
    cases = [('neutral', {}), ('blink_only', {'eyeClosed': 1.}),
             ('gaze_only', {k:v for k,v in actual.items() if k!='eyeClosed'}),
             ('saved_frame18', actual), ('stress_hold_blink', final)]
    cameras = [bpy.data.objects[n] for n in ('face_hold_front','face_hold_oblique')]
    folder = OUT/'diagnostic'
    folder.mkdir(exist_ok=True)
    report = {}
    base = None
    original = {c.name: c.matrix_world.copy() for c in cameras}
    for label, weights in cases:
        for k in kb[1:]:
            k.value = weights.get(k.name,0.)
        bpy.context.view_layer.update()
        p = coords(head)
        if base is None:
            base = p.copy()
        edge = [359,360]
        triangle = [386,388,360]
        def normal(a):
            n = np.cross(a[1]-a[0],a[2]-a[0])
            return n/np.linalg.norm(n)
        length = float(np.linalg.norm(p[edge[0]]-p[edge[1]]))
        report[label] = dict(weights=weights, edge_vertices=edge, triangle_vertices=triangle,
                            edge_length_m=length, neutral_edge_length_m=float(np.linalg.norm(base[359]-base[360])),
                            normal_deg=float(np.degrees(np.arccos(np.clip(normal(p[triangle])@normal(base[triangle]),-1,1)))),
                            triangle_points_world_m=p[triangle].tolist())
        # Render native pixels around both eyes; no enlargement of old thumbnails.
        center = Vector(base[json.loads(sc['face_hold_eye_ids'])].mean(axis=0))
        for cam in cameras:
            sc.camera = cam
            forward = original[cam.name].translation-center
            forward.z = 0.
            forward.normalize()
            cam.location = center + forward*(.27/(2*math.tan(cam.data.angle_y/2)))
            cam.rotation_euler = (center-cam.location).to_track_quat('-Z','Y').to_euler()
            sc.render.resolution_x, sc.render.resolution_y = 640,360
            sc.render.filepath = str(folder/f'{label}_{cam.name}.png')
            bpy.ops.render.render(write_still=True)
    dump('diagnostic.json',report)
    print('FACE_HOLD_DIAGNOSTIC',json.dumps(report),flush=True)


def detail():
    """Native-resolution close-ups of final animation eyes and lips at extrema."""
    import bpy
    import numpy as np
    from mathutils import Vector
    sc = bpy.context.scene
    h = head_object()
    cams = [bpy.data.objects[n] for n in ('face_hold_front','face_hold_oblique')]
    originals = {c.name: c.matrix_world.copy() for c in cams}
    sc.frame_set(0)
    neutral = coords(h)
    center = Vector(neutral[json.loads(sc['face_hold_eye_ids'])].mean(axis=0))
    kb = h.data.shape_keys.key_blocks
    delta = np.linalg.norm(np.array([v.co[:] for v in kb['upperLipsPart'].data])-
                           np.array([v.co[:] for v in kb[0].data]),axis=1)
    mouth = Vector(neutral[delta > .002].mean(axis=0))
    sc.render.resolution_x,sc.render.resolution_y = 640,360
    folder = OUT/'final_detail'
    folder.mkdir(exist_ok=True)
    for f in (0,20,45):
        sc.frame_set(f)
        for region, target, height in [('eyes',center,.27),('lips',mouth,.26)]:
            for cam in cams:
                sc.camera = cam
                front = originals[cam.name].translation-center
                front.z = 0.
                front.normalize()
                cam.location = target+front*(height/(2*math.tan(cam.data.angle_y/2)))
                cam.rotation_euler = (target-cam.location).to_track_quat('-Z','Y').to_euler()
                sc.render.resolution_x,sc.render.resolution_y = 640,360
                sc.render.filepath = str(folder/f'{region}_{f:04d}_{cam.name}.png')
                bpy.ops.render.render(write_still=True)


def assemble():
    from PIL import Image, ImageDraw
    import numpy as np
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('ffmpeg and ffprobe are required')
    folder = OUT/'frames'
    for view in ('front','oblique'):
        assert len(list(folder.glob(view+'_*.png'))) == COUNT, 'Missing or stale frames'
    result = OUT/'face_hold.mp4'
    subprocess.run([ffmpeg,'-v','error','-y','-framerate',str(FPS),'-start_number','0','-i',str(folder/'front_%04d.png'),
                    '-framerate',str(FPS),'-start_number','0','-i',str(folder/'oblique_%04d.png'),
                    '-filter_complex','hstack=inputs=2','-frames:v',str(COUNT),'-an','-c:v','libx264',
                    '-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(result)],check=True)
    decoded = OUT/'decoded'
    decoded.mkdir(exist_ok=True)
    subprocess.run([ffmpeg,'-v','error','-y','-i',str(result),'-vsync','0',str(decoded/'%04d.png')],check=True)
    files = sorted(decoded.glob('*.png'))
    assert len(files) == COUNT
    diffs = []
    prev = None
    for start in range(0,COUNT,12):
        for j,path in enumerate(files[start:start+12]):
            im = Image.open(path).convert('RGB')
            assert im.size == (640,360)
            a = np.asarray(im).astype(float)
            if prev is not None:
                diffs.append(float(np.abs(a-prev).mean()))
            prev = a
            # Three columns would reduce each face; use two full-size columns.
            # Six rows preserve every decoded pixel in the review sheets.
        sheet = Image.new('RGB',(1280,6*382),(24,25,27))
        draw = ImageDraw.Draw(sheet)
        for j,path in enumerate(files[start:start+12]):
            x,y = (j%2)*640,(j//2)*382
            sheet.paste(Image.open(path),(x,y))
            draw.text((x+8,y+361),f'frame {start+j:03d}  {(start+j)/FPS:.3f}s',fill='white')
        sheet.save(OUT/f'review_{start//12:02d}.jpg',quality=95)
    meta = json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-show_format','-of','json',str(result)]))
    assert len(meta['streams']) == 1 and meta['streams'][0]['codec_type'] == 'video'
    assert meta['streams'][0]['avg_frame_rate'] == '30/1'
    dump('video_qa.json',dict(frames=len(files),size=[640,360],fps=FPS,duration=float(meta['format']['duration']),
         audio_streams=0,decoded_mean_abs_differences=diffs,sha256=digest(result),
         visual_review='pending: review_00.jpg through review_08.jpg'))
    print('FACE_HOLD_ASSEMBLY_OK',result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['build','verify','keys','diagnostic','detail','render','assemble'])
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:])
    if args.mode == 'assemble':
        assemble()
        return
    import bpy
    if args.mode == 'build':
        build()
    else:
        bpy.ops.wm.open_mainfile(filepath=str(OUT/'face_hold.blend'))
        if args.mode == 'verify':
            witness('after')
        elif args.mode == 'diagnostic':
            diagnostic()
        elif args.mode == 'detail':
            detail()
        else:
            render(args.mode == 'keys')


if __name__ == '__main__':
    main()
