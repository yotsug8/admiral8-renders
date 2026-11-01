"""Inspect replacement props and the native Pudge hand before staging."""
import bpy
import json
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'_game/skits/pudge_tank/revision'
OUT.mkdir(parents=True, exist_ok=True)
report = {}
for label, path in [('tank', ROOT/'_game/external/pudge_tank/scene.gltf'),
                    ('launcher', ROOT/'_game/external/pudge_tank/launcher.glb')]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = set(bpy.data.objects)-before
    report[label] = []
    for o in objects:
        points = [o.matrix_world @ Vector(v) for v in o.bound_box] if o.type == 'MESH' else []
        report[label].append(dict(name=o.name, type=o.type, parent=o.parent.name if o.parent else None,
            lo=[min(v[i] for v in points) for i in range(3)] if points else [],
            hi=[max(v[i] for v in points) for i in range(3)] if points else [],
            materials=[s.material.name for s in o.material_slots if s.material]))
    for o in objects: bpy.data.objects.remove(o, do_unlink=True)
hero = bpy.data.objects['pudge_root']
arm = max((o for o in hero.children_recursive if o.type == 'ARMATURE'), key=lambda o: len(o.pose.bones))
report['hand'] = {b.name: dict(head=list(arm.matrix_world@b.head), tail=list(arm.matrix_world@b.tail),
    matrix=[list(row) for row in (arm.matrix_world@b.matrix)])
    for b in arm.pose.bones if any(s in b.name.lower() for s in ('wrist', 'finger', 'thumb', 'index', 'middle', 'pinky'))}
report['bones'] = [b.name for b in arm.pose.bones]
report['wrist_children'] = {b.name: list(arm.matrix_world@b.head)
    for b in arm.pose.bones['wrist_R'].children_recursive}
(OUT/'assets_probe.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
