"""Controlled A/B acting study: simultaneous greeting versus an answering partner.

Uses the existing local Rain rig and existing study helpers, not a Dota-rig claim.
Blender -b -P this_file -- --out NEW_FOLDER [--render]
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_rain_partner import Performer, SOURCE, duplicate_rain
from prepare_study_scene import localize_widget_meshes


def aim(obj, point):
    obj.rotation_euler = (Vector(point)-obj.location).to_track_quat('-Z', 'Y').to_euler()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    out = args.out.resolve()
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Local Rain rig required: {SOURCE}')
    out.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(out).free < 1024**3:
        raise RuntimeError('Need at least 1 GiB for the study')
    original_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report = {'fps': 30, 'frames_per_variant': 180, 'size': [480, 480],
              'control_sample_step': 6,
              'source_sha256': original_hash,
              'credit': 'Rain Rig, Blender Studio / Blender Foundation, CC BY 4.0',
              'variable': 'listener acting only; camera, lighting, initiator and duration identical',
              'limits': 'Silent acting experiment; no Dota-rig, lip-sync or full collision certification. '
                        'Source has a known Spine3 driver referencing missing STR-Spine4.',
              'visual_review': 'pending', 'variants': {}}
    for variant in ('simultaneous', 'response'):
        bpy.ops.wm.open_mainfile(filepath=str(SOURCE), use_scripts=False)
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        scene = bpy.context.scene
        first = bpy.data.objects['RIG-rain']
        second, originals, copies = duplicate_rain(first)
        a, b = Performer(first, -.62, 50), Performer(second, .62, -50)
        # Clear inherited actions so this experiment contains only authored poses.
        for rig in (first, second):
            if rig.animation_data:
                rig.animation_data.action = None
                for track in list(rig.animation_data.nla_tracks):
                    rig.animation_data.nla_tracks.remove(track)
        top = next(o for o in copies if o.name.startswith('GEO-rain-top'))
        mat = bpy.data.materials.new('Listener teal'); mat.use_nodes = True
        bsdf = mat.node_tree.nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (.06, .23, .22, 1)
        bsdf.inputs['Roughness'].default_value = .6
        top.data.materials.clear(); top.data.materials.append(mat)
        for obj in list(scene.objects):
            if obj.type in ('CAMERA', 'LIGHT'):
                bpy.data.objects.remove(obj, do_unlink=True)
        bpy.ops.object.camera_add(location=(0, -6, 2.1))
        scene.camera = bpy.context.object
        scene.camera.data.type = 'ORTHO'; scene.camera.data.ortho_scale = 2.35
        aim(scene.camera, (0, 0, .99))
        for location, energy, size in [((-3,-4,5),650,4),((3,-2,3),350,3),((0,3,4),600,3)]:
            bpy.ops.object.light_add(type='AREA', location=location)
            light = bpy.context.object; light.data.energy = energy; light.data.size = size
            aim(light, (0,0,1))
        bpy.ops.mesh.primitive_plane_add(size=200, location=(0,0,.00115))
        floor = bpy.data.materials.new('Floor'); floor.use_nodes = True
        floor.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.09,.115,.13,1)
        bpy.context.object.data.materials.append(floor)
        scene.world = bpy.data.worlds.new('World'); scene.world.use_nodes = True
        scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.18,.22,.28,1)
        scene.world.node_tree.nodes['Background'].inputs[1].default_value = .35
        scene.render.engine = 'BLENDER_EEVEE'; scene.eevee.taa_render_samples = 16
        scene.render.resolution_x = scene.render.resolution_y = 480
        scene.render.resolution_percentage = 100; scene.render.fps = 30
        scene.render.image_settings.file_format = 'PNG'; scene.view_settings.view_transform = 'AgX'
        scene.frame_start, scene.frame_end = 0, 179
        mesh_visibility = {o: o.hide_viewport for o in scene.objects if o.type == "MESH"}
        for obj in mesh_visibility:
            obj.hide_viewport = True
        for frame in [*range(0,180,6),179]:
            print("POSE",variant,frame,flush=True)
            scene.frame_set(frame)
            a.pose(frame/30, True, b)
            b.pose(frame/30, variant == 'simultaneous', a)
            for actor in (a,b):
                for name in actor.names:
                    bone = actor.p[name]
                    bone.keyframe_insert('location', frame=frame)
                    bone.keyframe_insert('rotation_quaternion' if bone.rotation_mode=='QUATERNION'
                                         else 'rotation_euler', frame=frame)
                    bone.keyframe_insert('scale', frame=frame)
        for obj, hidden in mesh_visibility.items():
            obj.hide_viewport = hidden
        bpy.context.view_layer.update()
        folder = out / variant; folder.mkdir()
        scene.frame_set(0)
        localize_widget_meshes(); bpy.ops.file.pack_all()
        scene.render.filepath = str(folder/'frame_')
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'study.blend'))
        (folder/'job.json').write_text(json.dumps({
            'schema_version': 1, 'scene': 'study.blend', 'out': 'motion',
            'frames': [0,180], 'size': [320,320], 'fps': 30}, indent=2), encoding='utf-8')
        frames = range(180) if args.render else (0,30,60,90,120,150,179)
        for frame in frames:
            scene.frame_set(frame); scene.render.filepath = str(folder/f'frame_{frame:04d}.png')
            bpy.ops.render.render(write_still=True)
        report['variants'][variant] = {'rendered': list(frames),
            'scene_sha256': hashlib.sha256((folder/'study.blend').read_bytes()).hexdigest()}
        (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != original_hash:
        raise RuntimeError('Source modified')
    report['source_unchanged'] = True
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
