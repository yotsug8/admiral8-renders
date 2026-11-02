"""Reframe the collision using the verified v3 scene; reuse unchanged frames.

Blender --background --python tools/blender/doomsday_composition.py -- probe|draft
"""
import hashlib
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '_game/skits/doomsday/v3'
OUT = ROOT / '_game/skits/doomsday/v4'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from doomsday_refine import gpu


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def camera(scene, position, lens, target):
    cam = scene.camera
    target = Vector(target)
    cam.location = position
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = lens
    cam.data.dof.focus_distance = (target - cam.location).length
    cam.data.dof.aperture_fstop = 7
    bpy.context.view_layer.update()


def main():
    mode = sys.argv[sys.argv.index('--') + 1]
    if mode not in ('probe', 'draft'):
        raise ValueError(mode)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / 'frames/manifest.json').read_text())
    if sha(SOURCE / 'scene.blend') != manifest['blend_sha256']:
        raise ValueError('Source scene no longer matches cached frames')
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE / 'scene.blend'))
    scene = bpy.context.scene
    gpu(scene)
    scene.cycles.samples = 48
    cam = scene.camera
    # Only the changed shot is rendered. Original camera keys remain untouched
    # in the source blend and all other shots retain their verified pixels.
    cam.animation_data_clear()
    cam.data.animation_data_clear()
    arms = [o for o in scene.objects if o.type == 'ARMATURE' and
            ('axe_1' in o.pose.bones or 'index_1_R' in o.pose.bones)]
    fits = [dict(position=(5,-7,2.0), lens=27, target=(-.5,-2.4,1.9))]
    axe_meshes = [o for o in scene.objects if o.type == 'MESH' and
                  any(m.type == 'ARMATURE' and m.object and 'axe_1' in m.object.pose.bones
                      for m in o.modifiers)]
    if not axe_meshes:
        raise ValueError('Missing attacker meshes for framing check')
    # Fit actual deformed vertices across the whole shot, not oversized world
    # bounding-box corners or just one landing pose. Keep a single fixed lens.
    fit = fits[0]
    maximum = 1.
    for frame in range(44, 68):
        scene.frame_set(frame)
        camera(scene, **fit)
        deps = bpy.context.evaluated_depsgraph_get()
        for ob in axe_meshes:
            evaluated = ob.evaluated_get(deps)
            for v in evaluated.data.vertices:
                p = world_to_camera_view(scene, cam, evaluated.matrix_world @ v.co)
                if p.z <= 0:
                    raise ValueError('Attacker behind camera')
                maximum = max(maximum, abs(p.x-.5)/.455, abs(p.y-.5)/.45)
    fit['lens'] /= maximum * 1.005
    projections = []
    for fit in fits:
        samples = []
        for frame in (44, 52, 60, 67):
            scene.frame_set(frame)
            camera(scene, **fit)
            points = {ob.name + ':' + bone: ob.matrix_world @ ob.pose.bones[bone].head
                      for ob in arms for bone in ('head', 'Head_0', 'wrist_L', 'wrist_R', 'index_1_R')
                      if bone in ob.pose.bones}
            samples.append({'frame':frame, 'points': {name:list(world_to_camera_view(scene,cam,p)) for name,p in points.items()}})
        projections.append(samples)
    (OUT / 'camera_candidates.json').write_text(json.dumps(fits, indent=2))
    (OUT / 'projection.json').write_text(json.dumps(projections, indent=2))
    if mode == 'probe':
        for index, fit in enumerate(fits):
            for frame in (44, 60):
                scene.frame_set(frame)
                camera(scene, **fit)
                scene.render.filepath = str(OUT / f'framed_{frame:04d}.png')
                bpy.ops.render.render(write_still=True)
        return
    chosen = fits[0]
    folder = OUT / 'frames'
    folder.mkdir(exist_ok=True)
    (folder / 'manifest.json').unlink(missing_ok=True)
    hashes, provenance = [], []
    for f, expected in zip(manifest['source_frames'], manifest['frame_sha256']):
        source = SOURCE / 'frames' / f'{f:04d}.png'
        dest = folder / source.name
        if 44 <= f < 68:
            scene.frame_set(f)
            camera(scene, **chosen)
            scene.render.filepath = str(dest)
            bpy.ops.render.render(write_still=True)
            provenance.append('reframed')
        else:
            if sha(source) != expected:
                raise ValueError('Cached frame hash mismatch')
            # Hard links avoid duplicating unchanged large render files.
            dest.unlink(missing_ok=True)
            dest.hardlink_to(source)
            provenance.append('v3 cache')
        hashes.append(sha(dest))
    report = {'source_frames': manifest['source_frames'], 'fps': manifest['fps'],
              'frame_sha256': hashes, 'source_blend_sha256': sha(SOURCE/'scene.blend'),
              'script_sha256': sha(Path(__file__)), 'camera': chosen,
              'provenance': provenance, 'scope': 'Only collision camera changed; no pose edits.'}
    (folder / 'manifest.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
