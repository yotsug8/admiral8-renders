"""CPU-only audit of the exact legacy close_neck function; never imports its module."""
import argparse
import ast
import hashlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from json_output import json_output_path, write_json_report

EXPECTED = '3ebd652e2dd38bdc133290c421691520e9592e9c184d20b5dbc2feff93bbd659'


def fixture(split, weighted):
    n = 18
    vertices = [(.3 * math.cos(2 * math.pi * i / n),
                 .3 * math.sin(2 * math.pi * i / n), z)
                for z in (0, 1) for i in range(n)] + [(0, 0, 1)]
    faces = [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    faces += [(n + i, n + (i + 1) % n, 2 * n) for i in range(n)]
    if split:
        expanded, expanded_faces = [], []
        for face in faces:
            expanded_faces.append(list(range(len(expanded), len(expanded) + len(face))))
            expanded.extend(vertices[i] for i in face)
        vertices, faces = expanded, expanded_faces
    mesh = bpy.data.meshes.new('audit_head')
    mesh.from_pydata(vertices, [], faces)
    head = bpy.data.objects.new('audit_head', mesh)
    bpy.context.collection.objects.link(head)
    basis = head.shape_key_add(name='Basis')
    a = head.shape_key_add(name='A')
    b = head.shape_key_add(name='B')
    b.relative_key = a
    for i, p in enumerate(basis.data):
        a.data[i].co = p.co + Vector((.02 * p.co.x, .03 * p.co.y, .02))
        b.data[i].co = a.data[i].co + Vector((.01, 0, .01 * p.co.z))
    body_mesh = bpy.data.meshes.new('audit_body')
    body_mesh.from_pydata([(.22 * math.cos(2 * math.pi * i / n),
                           .22 * math.sin(2 * math.pi * i / n), -.4 - j * .1)
                          for j in range(3) for i in range(n)], [], [])
    body = bpy.data.objects.new('audit_body', body_mesh)
    bpy.context.collection.objects.link(body)
    if weighted:
        for obj in (head, body):
            obj.vertex_groups.new(name='neck').add(
                list(range(len(obj.data.vertices))), 1.0, 'REPLACE')
    return head, body


def audit(fn, split, weighted):
    head, body = fixture(split, weighted)
    before = len(head.data.vertices)
    keys = head.data.shape_keys.key_blocks
    original = [(p.co.copy(), [k.data[i].co.copy() for k in keys])
                for i, p in enumerate(head.data.vertices)]
    bm = bmesh.new()
    bm.from_mesh(head.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=.0003)
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    indexes = [e.index for e in edges]
    assert len(bm.verts) == 37 and len(edges) == 18
    assert len(set(indexes)) == 18 and min(indexes) >= 0
    refs = [v for v in bm.verts]
    deform_existed = bm.verts.layers.deform.active is not None
    bm.verts.layers.deform.verify()
    invalidated = sum(not v.is_valid for v in refs)
    bm.free()
    assert deform_existed == weighted
    assert invalidated == (0 if weighted else 37)
    failure = None
    try:
        fn(head, [head, body])
    except ReferenceError as exc:
        failure = str(exc)
    assert (failure is None) == weighted
    if failure:
        assert failure == 'BMesh data of type BMVert has been removed'
    keys = head.data.shape_keys.key_blocks
    count = len(head.data.vertices)
    assert count == (55 if weighted else before)
    assert all(len(k.data) == count for k in keys)
    assert keys['B'].relative_key == keys['A']
    mesh_basis_error = max((p.co - keys['Basis'].data[i].co).length
                           for i, p in enumerate(head.data.vertices))
    existing_error = 0.0
    new_error = 0.0
    for i, p in enumerate(head.data.vertices):
        if weighted and p.co.z < -.1:
            new_error = max(new_error, *( (k.data[i].co - p.co).length for k in keys))
            assert len(p.groups) == 1 and p.groups[0].weight == 1.0
        else:
            closest, coords = min(original, key=lambda item: (item[0] - p.co).length)
            assert (closest - p.co).length < 1e-6
            existing_error = max(existing_error, *((k.data[i].co - co).length
                                                    for k, co in zip(keys, coords)))
    assert max(mesh_basis_error, existing_error, new_error) < 1e-6
    bm = bmesh.new()
    bm.from_mesh(head.data)
    bm.normal_update()
    new_faces = [f for f in bm.faces if any(v.co.z < -.1 for v in f.verts)]
    radial = [f.normal.dot(Vector((f.calc_center_median().x,
                                  f.calc_center_median().y, 0))) for f in new_faces]
    inconsistent = sum(not e.is_contiguous for e in bm.edges if e.is_manifold)
    assert inconsistent == 0
    assert len(new_faces) == (18 if weighted else 0)
    if weighted:
        assert min(radial) > 0 and min(f.calc_area() for f in new_faces) > 0
        assert sum(e.is_boundary for e in bm.edges) == 18
    bm.free()
    return dict(split=split, weighted=weighted, vertices_before=before,
                vertices_after=count, key_lengths=[len(k.data) for k in keys],
                boundary_indexes_after_weld=indexes, invalidated_by_deform_verify=invalidated,
                exception=failure, mesh_basis_error=mesh_basis_error,
                existing_keys_error=existing_error, new_keys_error=new_error,
                new_faces=len(new_faces), min_radial_normal=min(radial) if radial else None,
                inconsistent_manifold_edges=inconsistent)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('tools/blender/render_scene.py'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    protected = (args.source, bpy.data.filepath, __file__)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out = json_output_path(args.out, protected)
    source = args.source.read_text(encoding='utf-8')
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == 'close_neck')
    digest = hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
    assert digest == EXPECTED, 'Function changed: review fixture expectations before running'
    namespace = {'bpy': bpy, 'Vector': Vector}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'close_neck_only', 'exec'), namespace)
    results = [audit(namespace['close_neck'], split, weighted)
               for weighted in (False, True) for split in (False, True)]
    report = dict(blender=bpy.app.version_string, build=bpy.app.build_hash.decode(),
                  function_sha256=digest, cases=results, assertions_passed=True,
                  scope='Four synthetic meshes; no real character, render, or production change')
    write_json_report(args.out, json.dumps(report, indent=2) + '\n', protected)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
