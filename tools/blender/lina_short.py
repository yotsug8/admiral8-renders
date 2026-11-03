"""Finish the Lina forest short from its checked source; never overwrite it."""
import hashlib,json,math,sys,time
from pathlib import Path
import bpy
from mathutils import Vector,Quaternion
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/blender'))
from contact_reaction import _curves
from study_head_target import gpu_guard
SOURCE=ROOT/'_game/study/lina_threat/reaction_v2/look/scene.blend'
OUT=ROOT/'_game/study/lina_threat/final'
COUNT=270

def dump(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE),use_scripts=False)
    sc=bpy.context.scene;sc.frame_set(0);root=bpy.data.objects['lina_root']
    base=root.location.copy();rotation=root.rotation_quaternion.copy()
    root.rotation_mode='QUATERNION'
    # A flying character leaves along her heading; no running cycle is implied.
    axis=Vector((.84,-.54,0))
    for f,offset,tilt in [(0,(0,0,0),0),(100,(0,0,0),0),(140,(-.25,-.4,0),0),(165,(-.4,-.65,0),3),
                           (179,(-.6,-.95,.05),8),(195,(-1.4,-2.2,.18),14),
                           (220,(-4.8,-7.5,.5),18),(269,(-10,-16,1),18)]:
        root.location=base+Vector(offset);root.rotation_quaternion=Quaternion(axis,math.radians(tilt))@rotation
        root.keyframe_insert('location',frame=f);root.keyframe_insert('rotation_quaternion',frame=f)
    for c in _curves(root.animation_data.action):
        for k in c.keyframe_points:
            k.interpolation='BEZIER';k.handle_left_type=k.handle_right_type='AUTO_CLAMPED'
    # No repeated bob or neutral reset after fear; finish with the empty clearing.
    sc.frame_end=COUNT-1;sc.render.fps=30
    sc.render.resolution_x=1080;sc.render.resolution_y=1920;sc.render.resolution_percentage=100
    sc.camera=bpy.data.objects['story'];sc.camera.data.ortho_scale=9.6
    sc.eevee.taa_render_samples=64
    sc.render.use_motion_blur=True;sc.render.motion_blur_shutter=.25
    # The visible casting hand is R; the old L attachment put fire behind her.
    arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
    fire=bpy.data.objects['Fire in palm'];lamp=bpy.data.objects['Palm fire light']
    for f in range(70):
        sc.frame_set(f);bpy.context.view_layer.update()
        wrist=arm.matrix_world@arm.pose.bones['wrist_R'].matrix
        elbow=arm.matrix_world@arm.pose.bones['elbow_R'].matrix
        direction=(wrist.translation-elbow.translation).normalized()
        fire.location=wrist.translation+direction*.24+Vector((0,0,.28))
        fire.keyframe_insert('location',frame=f)
        lamp.location=fire.location+Vector((0,0,.2));lamp.keyframe_insert('location',frame=f)
    # Three curved tongues preserve a simple silhouette without a rigid diamond.
    outer=bpy.data.objects['flame outer']
    for v in outer.data.vertices:
        z=v.co.z;v.co.x+=.10*math.sin(z*8);v.co.y*=.75
    mod=outer.modifiers.new('Rounded flame','SUBSURF');mod.levels=mod.render_levels=2
    for i,(x,y,scale) in enumerate([(-.13,.03,.65),(.15,-.03,.48)]):
        ob=outer.copy();ob.data=outer.data.copy();ob.name=f'flame tongue {i}'
        sc.collection.objects.link(ob);ob.location=(x,y,.04);ob.scale=(scale,scale,scale)
    sc.render.film_transparent=False
    from doomsday_atmosphere import glow
    glow(sc)
    for ob in bpy.data.objects:
        if ob.name.startswith('flame ') and ob.type=='MESH':
            for mat in ob.data.materials:
                for n in mat.node_tree.nodes:
                    if n.type=='BSDF_PRINCIPLED':n.inputs['Emission Strength'].default_value=4
    sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGB'
    sc.render.use_overwrite=True;sc.render.use_placeholder=False
    sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
    dump('build.json',dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        scene_sha256=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest(),frames=COUNT,fps=30,
        resolution=[1080,1920],story='Fire, looming threat, fear, decision, flight out of frame, quiet clearing',
        limits='Stylized silhouette threat; Lina hovers. Prior collar candidate limits retained.'))

def probe():
    gpu_guard();sc=bpy.context.scene;sc.render.resolution_percentage=50
    for f in (0,37,72,150,190,220,269):
        sc.frame_set(f);sc.render.filepath=str(OUT/'probes'/f'{f:04}.png');bpy.ops.render.render(write_still=True)

def patch_framing():
    """Change only root travel after f100; prove the cached prefix unchanged."""
    sc=bpy.context.scene;root=bpy.data.objects['lina_root']
    old_sha=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest()
    def prefix():
        values=[]
        for f in range(100):
            sc.frame_set(f);bpy.context.view_layer.update()
            values.append([v for row in root.matrix_world for v in row])
        return values
    before=prefix();sc.frame_set(0);base=root.location.copy()
    for f,offset in [(100,(0,0,0)),(140,(-.25,-.4,0)),(165,(-.4,-.65,0)),(179,(-.6,-.95,.05))]:
        root.location=base+Vector(offset);root.keyframe_insert('location',frame=f)
    for c in _curves(root.animation_data.action):
        for k in c.keyframe_points:k.handle_left_type=k.handle_right_type='AUTO_CLAMPED'
    error=max(abs(a-b) for aa,bb in zip(before,prefix()) for a,b in zip(aa,bb))
    if error>1e-7:raise ValueError(f'Cached prefix changed: {error}')
    retained={f'frame_{f:04}.png':hashlib.sha256((OUT/'frames'/f'frame_{f:04}.png').read_bytes()).hexdigest() for f in range(100)}
    sc.frame_set(0);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
    metadata=json.loads((OUT/'build.json').read_text())
    metadata['scene_sha256']=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest();dump('build.json',metadata)
    dump('reuse.json',dict(previous_scene_sha256=old_sha,scene_sha256=metadata['scene_sha256'],
        unchanged_root_matrix_error=error,change='Only root location keys from frame 100; all other scene data preserved',frames=retained))


def render(start=0):
    gpu_guard();sc=bpy.context.scene
    expected=json.loads((OUT/'build.json').read_text())
    if expected['scene_sha256']!=hashlib.sha256((OUT/'scene.blend').read_bytes()).hexdigest():raise ValueError('Scene changed')
    reuse={}
    if start:
        reuse=json.loads((OUT/'reuse.json').read_text())
        if reuse['scene_sha256']!=expected['scene_sha256']:raise ValueError('Reuse scene mismatch')
        if any(hashlib.sha256((OUT/'frames'/n).read_bytes()).hexdigest()!=h for n,h in reuse['frames'].items()):raise ValueError('Cached frame changed')
    started=time.time();sc.render.filepath=str(OUT/'frames/frame_');sc.frame_start=start
    bpy.ops.render.render(animation=True)
    files=[OUT/'frames'/f'frame_{f:04}.png' for f in range(COUNT)]
    if not all(p.is_file() and p.stat().st_mtime>=started-1 for p in files[start:]):raise ValueError('Missing or stale frames')
    dump('manifest.json',dict(scene_sha256=expected['scene_sha256'],reuse= reuse,frames={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}))

if __name__=='__main__':
    mode=sys.argv[sys.argv.index('--')+1]
    if mode=='build':build()
    else:
        bpy.ops.wm.open_mainfile(filepath=str(OUT/'scene.blend'),use_scripts=False)
        if mode=='probe':probe()
        elif mode=='patch-framing':patch_framing()
        elif mode=='resume':render(100)
        elif mode=='render':render()
        else:raise ValueError(mode)
