"""Ограниченная сварка совместимых экспортных дублей до Armature.

Проверено численно только на upper_body/leftarm Пуджа из fleet_battle v2.
Не применять автоматически ко всем моделям. Визуальная A/B обязательна.
Фиксированный targetmap BMesh сохраняет corner UV; живого Weld нет.
Исходный mesh заменяется отдельной копией только после проверки сохранности.
"""
import math
from collections import Counter, defaultdict
from itertools import combinations


def weld_compatible_uv_duplicates(obj, *, position_tolerance=1e-6,
                                 normal_tolerance=1e-3):
    """Вернуть соответствие индексов и установить проверенную копию mesh.

    position_tolerance — локальные единицы; normal_tolerance — расстояние
    единичных векторов (0,001 ≈ 0,0573°, допуск квантования custom normals).
    Веса должны совпадать точно, независимо от порядка записей групп.
    Несовместимые позиции/веса/нормали и явные hard edges пропускаются.
    Несовместимый morph у иначе подходящей группы отменяет всю операцию.
    Поддержаны относительные shape keys без animation_data; остальные
    режимы/неизвестные атрибуты отклоняются до изменения объекта.
    """
    import bpy
    import bmesh
    from mathutils.kdtree import KDTree

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(obj.type == 'MESH' and obj.mode == 'OBJECT', 'Нужен mesh в Object mode')
    require(math.isfinite(position_tolerance) and 0 < position_tolerance <= 1e-5,
            'Недопустимый допуск позиции')
    require(math.isfinite(normal_tolerance) and 0 <= normal_tolerance <= 1e-3,
            'Допуск нормалей не должен превышать 0,001')
    mods = list(obj.modifiers)
    require(len(mods) == 1 and mods[0].type == 'ARMATURE' and
            mods[0].object is not None and mods[0].show_render and mods[0].show_viewport,
            'Поддержан только один включённый Armature без других модификаторов')
    source = obj.data
    require(not source.library and not obj.library, 'Linked-ресурсы не поддержаны')
    require(source.has_custom_normals and source.uv_layers, 'Нужны custom normals и UV')
    allowed = {'position', '.edge_verts', '.corner_vert', '.corner_edge',
               '.select_vert', '.select_edge', '.select_poly', 'material_index',
               'sharp_face', 'sharp_edge', 'custom_normal', '.uv_seam',
               '.uv_select_vert', '.uv_select_edge', '.uv_select_face'}
    allowed.update(source.uv_layers.keys())
    require(all(a.name in allowed for a in source.attributes),
            'Неизвестные mesh-атрибуты: сварка не проверена для этих данных')
    keys = source.shape_keys
    if keys:
        require(keys.use_relative and keys.animation_data is None,
                'Поддержаны относительные shape keys без анимации/драйверов')
        require(all(len(k.data) == len(source.vertices) for k in keys.key_blocks),
                'Некорректное число точек shape key')

    points = [v.co.copy() for v in source.vertices]
    normals = [n.vector.copy() for n in source.corner_normals]
    require(all(math.isfinite(c) for p in points + normals for c in p),
            'Нефинитные координаты/нормали')
    require(all(n.length > .5 for n in normals), 'Нулевая нормаль')
    unit_normals = [n.normalized() for n in normals]
    weights = [tuple(sorted((g.group, g.weight) for g in v.groups))
               for v in source.vertices]
    vertex_loops = defaultdict(list)
    hard = set()
    for face in source.polygons:
        if not face.use_smooth:
            hard.update(face.vertices)
        for index in face.loop_indices:
            vertex_loops[source.loops[index].vertex_index].append(index)
    for edge in source.edges:
        if edge.use_edge_sharp:
            hard.update(edge.vertices)

    # Компоненты близости: затем обязательная попарная проверка, без цепочек.
    tree = KDTree(len(points))
    for i, p in enumerate(points):
        tree.insert(p, i)
    tree.balance()
    remaining = set(range(len(points)))
    groups, skipped = [], Counter()
    while remaining:
        seed = min(remaining)
        component, pending = set(), [seed]
        while pending:
            i = pending.pop()
            if i in component:
                continue
            component.add(i)
            pending.extend(j for _, j, _ in tree.find_range(points[i], position_tolerance)
                           if j not in component)
        remaining.difference_update(component)
        ids = sorted(component)
        if len(ids) < 2:
            continue
        if any((points[a] - points[b]).length > position_tolerance
               for a, b in combinations(ids, 2)):
            skipped['position_chain'] += 1
            continue
        if hard.intersection(ids) or any(not vertex_loops[i] for i in ids):
            skipped['explicit_hard_or_loose'] += 1
            continue
        if any(weights[i] != weights[ids[0]] for i in ids):
            skipped['weights'] += 1
            continue
        ns = [unit_normals[j] for i in ids for j in vertex_loops[i]]
        if any((a - b).length > normal_tolerance for a, b in combinations(ns, 2)):
            skipped['normals'] += 1
            continue
        if keys:
            for key in keys.key_blocks:
                require(all((key.data[a].co - key.data[b].co).length <= position_tolerance
                            for a, b in combinations(ids, 2)),
                        f'Несовместимый morph {key.name}: вершины {ids}')
        groups.append(ids)

    representative = list(range(len(points)))
    for ids in groups:
        for i in ids:
            representative[i] = ids[0]
    # Запрет схлопывания/дублирования граней и образования non-manifold ребра.
    faces, edge_faces, edge_flags = set(), Counter(), {}
    for face in source.polygons:
        ids = [representative[i] for i in face.vertices]
        require(len(set(ids)) == len(ids), 'Сварка схлопывает грань')
        signature = tuple(sorted(ids))
        require(signature not in faces, 'Сварка создаёт дублированные грани')
        faces.add(signature)
        for a, b in zip(ids, ids[1:] + ids[:1]):
            edge_faces[tuple(sorted((a, b)))] += 1
    require(all(n <= 2 for n in edge_faces.values()), 'Получается non-manifold ребро')
    for edge in source.edges:
        pair = tuple(sorted(representative[i] for i in edge.vertices))
        flags = (edge.use_edge_sharp, edge.use_seam)
        require(pair not in edge_flags or edge_flags[pair] == flags,
                'Конфликт sharp/seam флагов объединяемых рёбер')
        edge_flags[pair] = flags

    report = dict(groups=groups, skipped=dict(skipped), vertices_before=len(points),
                  position_tolerance=position_tolerance, normal_tolerance=normal_tolerance)
    if not groups:
        return dict(report, changed=False, vertices_after=len(points),
                    old_to_new=list(range(len(points))),
                    old_loop_to_new=list(range(len(source.loops))))

    # Все изменения — только в кандидате. Даже неудачный postcheck не меняет obj.
    candidate = source.copy()
    bm = bmesh.new()
    try:
        if keys:
            require(candidate.shape_keys is not keys, 'Shape keys остались общими')
        bm.from_mesh(candidate, use_shape_key=False)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        vertex_tag = bm.verts.layers.int.new('_dn_vertex')
        loop_tag = bm.loops.layers.int.new('_dn_loop')
        face_tag = bm.faces.layers.int.new('_dn_face')
        for v in bm.verts:
            v[vertex_tag] = v.index
        for face, old in zip(bm.faces, source.polygons):
            face[face_tag] = old.index
            for loop, index in zip(face.loops, old.loop_indices):
                loop[loop_tag] = index
        bmesh.ops.weld_verts(bm, targetmap={bm.verts[i]: bm.verts[ids[0]]
                                          for ids in groups for i in ids[1:]})
        bm.to_mesh(candidate)
        origins = [x.value for x in candidate.attributes['_dn_vertex'].data]
        loop_origins = [x.value for x in candidate.attributes['_dn_loop'].data]
        face_origins = [x.value for x in candidate.attributes['_dn_face'].data]
        require(sorted(loop_origins) == list(range(len(source.loops))), 'Потеря corner')
        require(sorted(face_origins) == list(range(len(source.polygons))), 'Потеря грани')
        index_of = {old: new for new, old in enumerate(origins)}
        mapping = [index_of[i] for i in representative]
        require(len(origins) == len(set(representative)), 'Неожиданное число вершин')
        inverse_loops = [0] * len(loop_origins)
        for new, old in enumerate(loop_origins):
            inverse_loops[old] = new
            require(candidate.loops[new].vertex_index == mapping[source.loops[old].vertex_index],
                    'Изменилось соответствие corner/vertex')
        for new, old in zip(candidate.polygons, face_origins):
            prior = source.polygons[old]
            require([loop_origins[i] for i in new.loop_indices] == list(prior.loop_indices),
                    'Изменился порядок углов грани')
            require(new.material_index == prior.material_index and new.use_smooth == prior.use_smooth,
                    'Изменились материал или smooth грани')
        require(list(candidate.uv_layers.keys()) == list(source.uv_layers.keys()), 'Потеря UV слоя')
        for layer in source.uv_layers:
            require(all(candidate.uv_layers[layer.name].data[new].uv == layer.data[old].uv
                        for new, old in enumerate(loop_origins)), 'Изменились corner UV')
        for new, old in enumerate(origins):
            require(candidate.vertices[new].co == points[old], 'Изменилась позиция target')
            require(tuple(sorted((g.group, g.weight) for g in candidate.vertices[new].groups))
                    == weights[old], 'Изменились skin weights')
        if keys:
            new_keys = candidate.shape_keys
            require(list(new_keys.key_blocks.keys()) == list(keys.key_blocks.keys()), 'Потеря morph')
            require(new_keys.use_relative == keys.use_relative, 'Изменился режим morph')
            for old, new in zip(keys.key_blocks, new_keys.key_blocks):
                require((new.relative_key.name, new.value, new.slider_min, new.slider_max,
                         new.mute, new.interpolation, new.vertex_group) ==
                        (old.relative_key.name, old.value, old.slider_min, old.slider_max,
                         old.mute, old.interpolation, old.vertex_group), 'Изменились параметры morph')
                require(all(new.data[i].co == old.data[j].co for i, j in enumerate(origins)),
                        'Изменились координаты morph')
        # Перекодировать исходные векторы в новую loop-normal space. Нельзя
        # копировать старые INT16 custom_normal после изменения топологии.
        candidate.normals_split_custom_set([normals[i] for i in loop_origins])
        candidate.update()
        normal_error = max((n.vector.normalized() - unit_normals[old]).length
                           for n, old in zip(candidate.corner_normals, loop_origins))
        require(normal_error <= 1e-3, 'Изменились исходные corner normals сверх квантования')
        for edge in candidate.edges:
            pair = tuple(sorted(origins[i] for i in edge.vertices))
            require((edge.use_edge_sharp, edge.use_seam) == edge_flags[pair],
                    'Изменились sharp/seam флаги')
        for name in ('_dn_vertex', '_dn_loop', '_dn_face'):
            candidate.attributes.remove(candidate.attributes[name])
        candidate.name = source.name + '_compatible_weld'
        obj.data = candidate
        return dict(report, changed=True, vertices_after=len(candidate.vertices),
                    old_to_new=mapping, old_loop_to_new=inverse_loops,
                    rest_normal_vector_error=normal_error,
                    shape_keys=len(keys.key_blocks) if keys else 0)
    except Exception:
        bpy.data.meshes.remove(candidate)
        raise
    finally:
        bm.free()
