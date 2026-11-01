"""Camera-only continuity study on a prepared reach, original frames 0..83.

blender -b attention_small.blend --disable-autoexec --python-exit-code 2
        -P tools/blender/study_blocking.py -- --out NEW_DIRECTORY
Render separately with render_study_frames.py; camera markers make a hard cut.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


def digest(values):
    h = hashlib.sha256()
    for value in values:
        h.update(struct.pack('<d', value))
    return h.hexdigest()


def rig_state(scene):
    """All evaluated rig world matrices and shape values at every output frame."""
    result = []
    rigs = sorted((o for o in scene.objects if o.type == 'ARMATURE'), key=lambda o: o.name)
    meshes = sorted((o for o in scene.objects if o.type == 'MESH'), key=lambda o: o.name)
    for frame in range(84):
        scene.frame_set(frame)
        deps = bpy.context.evaluated_depsgraph_get()
        values = []
        for obj in rigs:
            rig = obj.evaluated_get(deps)
            for bone in rig.pose.bones:
                matrix = rig.matrix_world @ bone.matrix
                values.extend(v for row in matrix for v in row)
        for obj in meshes:
            values.extend(v for row in obj.matrix_world for v in row)
            if obj.data.shape_keys:
                values.extend(k.value for k in obj.data.shape_keys.key_blocks)
        result.append(digest(values))
    return result


def surface_state(scene):
    """Raw mesh coordinates, topology and all morph coordinates (no skin edits)."""
    result = {}
    for obj in scene.objects:
        if obj.type != 'MESH':
            continue
        mesh = obj.data
        values = [v for vertex in mesh.vertices for v in vertex.co]
        values.extend(v for poly in mesh.polygons for v in (len(poly.vertices), *poly.vertices))
        if mesh.shape_keys:
            values.extend(v for key in mesh.shape_keys.key_blocks for p in key.data for v in p.co)
        values.extend(v for vertex in mesh.vertices for group in vertex.groups
                      for v in (group.group, group.weight))
        result[obj.name] = digest(values)
    return result


def camera(scene, name, target, offset, scale):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    data.type = 'ORTHO'
    data.ortho_scale = scale
    obj.location = target + offset
    obj.rotation_euler = (-offset).to_track_quat('-Z', 'Y').to_euler()
    data.clip_start, data.clip_end = .1, 300.
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = args.out.resolve()
    source = Path(bpy.data.filepath).resolve()
    if not source.is_file() or out.exists():
        raise ValueError('Open the source scene and use a new output directory')
    scene = bpy.context.scene
    if abs(scene.render.fps / scene.render.fps_base - 30) > 1e-8:
        raise ValueError('Source must already use 30 fps')
    if scene.frame_start > 0 or scene.frame_end < 83:
        raise ValueError('Source must cover frames 0..83')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from contact_metrics import resolve
    _, arm, _ = resolve('pudge', list(scene.objects))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    before = rig_state(scene)
    surfaces = surface_state(scene)
    scene.frame_set(30)
    wrist = (arm.matrix_world @ arm.pose.bones['wrist_L'].matrix).translation
    head = (arm.matrix_world @ arm.pose.bones['head'].matrix).translation
    # Parallel fixed views: enlargement without reversing screen direction.
    offset = Vector((30., 9., 6.))
    wide_target = Vector((head.x, head.y - .25, 2.35))
    close_target = wrist + Vector((-.05, 0., .18))
    wide = camera(scene, 'blocking_establish', wide_target, offset, 11.5)
    close = camera(scene, 'blocking_hand', close_target, offset, 2.6)
    for marker in list(scene.timeline_markers):
        if marker.camera:
            scene.timeline_markers.remove(marker)
    for frame, cam in ((0, wide), (30, close)):
        scene.timeline_markers.new(cam.name, frame=frame).camera = cam
    scene.camera = wide
    scene.frame_start, scene.frame_end = 0, 83
    scene.render.resolution_x, scene.render.resolution_y = 360, 640
    scene.render.resolution_percentage = 100
    scene.render.use_motion_blur = False
    projection = []
    for frame in range(84):
        scene.frame_set(frame)
        cam = wide if frame < 30 else close
        row = {'frame': frame, 'camera': cam.name}
        for name in ('head', 'elbow_L', 'wrist_L'):
            p = (arm.matrix_world @ arm.pose.bones[name].matrix).translation
            row[name] = list(world_to_camera_view(scene, cam, p))
        projection.append(row)
    # Axis = outward stroke between preparation and final extension, in XY.
    positions = []
    for frame in (21, 39):
        scene.frame_set(frame)
        positions.append((arm.matrix_world @ arm.pose.bones['wrist_L'].matrix).translation.copy())
    axis = positions[1] - positions[0]
    sides = {cam.name: axis.x * (cam.location.y - positions[0].y)
             - axis.y * (cam.location.x - positions[0].x) for cam in (wide, close)}
    if sides[wide.name] * sides[close.name] <= 0:
        raise ValueError('Cameras cross the action axis')
    out.mkdir(parents=True)
    scene.frame_set(0)
    dest = out / 'blocking_matchcut.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(dest))
    # Re-open the saved result: verify actual delivery, not only live state.
    bpy.ops.wm.open_mainfile(filepath=str(dest))
    after = rig_state(bpy.context.scene)
    mesh_equal = surfaces == surface_state(bpy.context.scene)
    source_equal = source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    report = dict(frames=list(range(84)), fps=30, duration=2.8, cut_frame=30,
                  source_sha256=source_hash, source_unchanged=source_equal,
                  rig_and_shapes_equal=before == after, raw_meshes_equal=mesh_equal,
                  reference_hashes=before, saved_hashes=after, axis_sides=sides,
                  projection=projection,
                  limits='Bone projections are not surface visibility or collision tests. '
                         'Original holds retained. No grasp or object contact is claimed.')
    (out / 'continuity.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not (before == after and mesh_equal and source_equal):
        raise RuntimeError('Source/rig/surface preservation failed; inspect continuity.json')
    print('PASS: 84 saved rig states, mesh/shape coordinates, source hash, same-side cameras')


if __name__ == '__main__':
    main()
