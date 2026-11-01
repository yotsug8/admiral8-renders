"""Render fixed diagnostic cameras around measured bad edges; never save the scene."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    folder, output = args.folder.resolve(), args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = folder / 'diagnostic_preview.blend'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    details = json.loads((folder / 'skin_details.json').read_text())
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    arm = next(o for o in scene.objects if o.get('retarget_main'))
    scene.render.resolution_x = scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    report = {'source_sha256': digest, 'diagnostic_only': True, 'parts': {}}
    for suffix, distance, offsets in (
        ('.head', .85, ((4, 2, 1), (0, 4, .5))),
        ('.upper_body', 1.2, ((-4, 2, 1), (-4, -2, 1))),
    ):
        name = next(n for n in details if n.endswith(suffix))
        ob = bpy.data.objects[name]
        worst = details[name]['worst']
        center = sum((Vector(p) for p in worst['original_world']), Vector()) / 2
        part = {'edge': worst, 'bones': {}, 'modifiers': [
            {'type': m.type, 'name': m.name, 'viewport': m.show_viewport,
             'render': m.show_render,
             'preserve_volume': getattr(m, 'use_deform_preserve_volume', None)}
            for m in ob.modifiers],
            'shape_keys': len(ob.data.shape_keys.key_blocks) if ob.data.shape_keys else 0}
        names = set().union(*(set(w) for w in worst['weights']))
        for frame in (1, worst['frame']):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            part['bones'][str(frame)] = {
                n: {'parent': arm.pose.bones[n].parent.name if arm.pose.bones[n].parent else None,
                    'world_matrix': [list(r) for r in arm.matrix_world @ arm.pose.bones[n].matrix],
                    'basis': [list(r) for r in arm.pose.bones[n].matrix_basis]}
                for n in sorted(names)}
        for side, offset in enumerate(offsets):
            cam = bpy.data.objects.new('SkinWitness', bpy.data.cameras.new('SkinWitness'))
            scene.collection.objects.link(cam)
            cam.location = center + Vector(offset)
            cam.rotation_euler = (center-cam.location).to_track_quat('-Z', 'Y').to_euler()
            cam.data.type = 'ORTHO'
            cam.data.ortho_scale = distance
            scene.camera = cam
            for frame in (1, worst['frame']):
                scene.frame_set(frame)
                scene.render.filepath = str(output / f'{suffix[1:]}_{side}_{frame:03d}.png')
                bpy.ops.render.render(write_still=True)
        report['parts'][name] = part
    report['source_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == digest
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['source_unchanged']:
        raise RuntimeError('Source changed')
    print('SKIN_CLOSEUPS_OK')


if __name__ == '__main__':
    main()
