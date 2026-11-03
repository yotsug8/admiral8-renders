"""Сохранённый кандидат двуручного хвата, а не универсальный rig или принятая сцена.

Нужна внешняя база _game/skits/doomsday/v12/effort_complete_pose_revised.blend
на кадре 318 с исходными игровыми мешами. В JSON только авторские дельты,
позы пальцев относительно wrist и отпечатки ресурсов; сами ресурсы не включены.

API: apply_geometry(weapon, skin), затем apply_pose(world_pose) перед bake.
Корректирующий shape key предназначен ТОЛЬКО для сжатого хвата. Отпускание,
изменение wrist относительно оружия и перенос во времени требуют новой проверки.
Остаточные sampled проникновения: L 0.01396, R 0.00782 мировых единиц.
Нулевые strict digit pairs на кадре 318 не подтверждают всю кожу или анимацию.

CPU-воспроизведение без рендера, сохранение только по явному --output:
blender -b --python tools/blender/doomsday_grip.py -- --source BASE.blend
  --verify-reference CANDIDATE.blend --report REPORT.json [--output NEW.blend]
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import bpy
from mathutils import Matrix, Vector

RECIPE_PATH = Path(__file__).with_suffix('.json')


def load_recipe():
    return json.loads(RECIPE_PATH.read_text(encoding='utf-8'))


def mesh_fingerprint(mesh):
    """Проверка порядка вершин и полигонов без публикации исходной геометрии."""
    digest = hashlib.sha256()
    for vertex in mesh.vertices:
        digest.update(struct.pack('<3f', *vertex.co))
    for polygon in mesh.polygons:
        digest.update(struct.pack('<I', len(polygon.vertices)))
        digest.update(struct.pack('<' + 'I' * len(polygon.vertices), *polygon.vertices))
    return digest.hexdigest()


def apply_pose(pose, recipe=None):
    """Меняет только пальцы; wrists, тело и оружие берутся из входной world pose."""
    recipe = recipe or load_recipe()
    result = {name: matrix.copy() for name, matrix in pose.items()}
    for name, relative in recipe['fingers_relative_wrist'].items():
        if name not in pose:
            raise ValueError(f'Нет нужной кости: {name}')
        result[name] = pose['wrist_' + name[-1]] @ Matrix(relative)
    return result


def apply_geometry(weapon, skin, recipe=None):
    """Постоянная рукоять и обратимый closed-only skin key; повторный вызов безопасен."""
    recipe = recipe or load_recipe()
    assets = recipe['asset_fingerprints']
    weapon_hash = mesh_fingerprint(weapon.data)
    if mesh_fingerprint(skin.data) != assets['skin_basis']:
        raise ValueError('Кожа или порядок её вершин отличаются от внешней базы.')
    applied_hashes = {assets['weapon_candidate'], assets['weapon_replayed']}
    if weapon_hash not in applied_hashes | {assets['weapon_base']}:
        raise ValueError('Оружие или порядок его вершин отличаются от внешней базы.')
    # Все проверки сделаны до изменения datablocks.
    if weapon_hash == assets['weapon_base']:
        weapon.data = weapon.data.copy()
        for vertex, delta in recipe['weapon_vertex_deltas']:
            weapon.data.vertices[vertex].co += Vector(delta)
        weapon.data.update()
    if skin.data.users > 1:
        skin.data = skin.data.copy()
    for modifier in list(skin.modifiers):
        if (modifier.name in recipe['remove_study_modifiers']
                and modifier.type in ('SUBSURF', 'SHRINKWRAP')):
            skin.modifiers.remove(modifier)
    if skin.data.shape_keys is None:
        skin.shape_key_add(name='Basis', from_mix=False)
    name = recipe['skin_corrective']['name']
    key = skin.data.shape_keys.key_blocks.get(name)
    if key is None:
        key = skin.shape_key_add(name=name, from_mix=False)
    basis = skin.data.shape_keys.key_blocks[0]
    for original, corrected in zip(basis.data, key.data):
        corrected.co = original.co
    for vertex, delta in recipe['skin_corrective']['vertex_deltas']:
        key.data[vertex].co += Vector(delta)
    key.value = 1.0
    return key


def _actors():
    from doomsday_weapon_clearance import select_meshes
    arm = next(o for o in bpy.context.scene.objects
               if o.type == 'ARMATURE' and o.parent and o.parent.name == 'axe_root')
    weapons, bodies, _ = select_meshes(bpy.context.scene, arm)
    skin = next(o for o in bodies if 'axe_model' in o.data.name.lower())
    return arm, weapons[0], skin


def _evaluated_points(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    result = []
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        result.append([evaluated.matrix_world @ v.co for v in mesh.vertices])
        evaluated.to_mesh_clear()
    return result


def main():
    if not bpy.app.background:
        raise RuntimeError('CLI рассчитан на отдельный background Blender, не live-сцену.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--frame', type=int, default=318)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-reference', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.output and args.output.resolve() in {
        args.source.resolve(),
        args.verify_reference.resolve() if args.verify_reference else args.source.resolve(),
    }:
        raise ValueError('Выход должен отличаться от исходника и проверяемого кандидата.')
    from doomsday_performance import snapshot, _basis
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    scene = bpy.context.scene
    if scene.frame_current != args.frame:
        scene.frame_set(args.frame)
    arm, weapon, skin = _actors()
    recipe = load_recipe()
    before = snapshot(arm)
    desired = apply_pose(before, recipe)
    apply_geometry(weapon, skin, recipe)
    inverse = arm.matrix_world.inverted()
    for name in recipe['fingers_relative_wrist']:
        bone = arm.pose.bones[name]
        local = _basis(bone, inverse @ desired[name], inverse @ desired[bone.parent.name])
        bone.location, bone.rotation_quaternion, bone.scale = local.decompose()
        bone.rotation_mode = 'QUATERNION'
        for channel in ('location', 'rotation_quaternion', 'scale'):
            bone.keyframe_insert(channel, frame=args.frame)
    bpy.context.view_layer.update()
    after = snapshot(arm)
    untouched = set(before) - set(recipe['fingers_relative_wrist'])
    unchanged_error = max(abs(before[n][i][j] - after[n][i][j])
                          for n in untouched for i in range(4) for j in range(4))
    replay = _evaluated_points((weapon, skin))
    apply_geometry(weapon, skin, recipe)
    bpy.context.view_layer.update()
    twice = _evaluated_points((weapon, skin))
    report = {'frame': args.frame, 'nonfinger_matrix_max_error': unchanged_error,
              'geometry_second_apply_max_error': max((a-b).length for xs, ys in zip(replay, twice)
                                                     for a, b in zip(xs, ys)),
              'scope': 'CPU reproduction only; no new visual or motion acceptance'}
    if args.output:
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True)
    if args.verify_reference:
        bpy.ops.wm.open_mainfile(filepath=str(args.verify_reference.resolve()))
        if bpy.context.scene.frame_current != args.frame:
            bpy.context.scene.frame_set(args.frame)
        _, ref_weapon, ref_skin = _actors()
        reference = _evaluated_points((ref_weapon, ref_skin))
        for label, expected, actual in zip(('weapon', 'skin'), reference, replay):
            if len(expected) != len(actual):
                raise ValueError(f'Разная evaluated-топология: {label}')
            report[label + '_evaluated_max_error'] = max((a-b).length for a, b in zip(expected, actual))
    report['reproduction_pass'] = all(v <= 1e-4 for k, v in report.items() if k.endswith('_error'))
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    if not report['reproduction_pass']:
        raise RuntimeError('CPU-воспроизведение отличается от сохранённого кандидата.')


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
