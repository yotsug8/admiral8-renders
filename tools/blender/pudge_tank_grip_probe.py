"""Measure actual prop handle vertices and native glove before placement."""
import bpy
import json
from mathutils import Vector
from pathlib import Path
root = Path(__file__).resolve().parents[2]
sc = bpy.context.scene
body = bpy.data.objects['launcher-body']
launcher = bpy.data.objects['held_launcher']
inv = launcher.matrix_world.inverted()
points = [inv @ body.matrix_world @ v.co for v in body.data.vertices]
points = [p for p in points if p.z < .12]
report = dict(prop_low_vertices=[list(p) for p in points])
hero = bpy.data.objects['pudge_root']
arm = max((o for o in hero.children_recursive if o.type=='ARMATURE'), key=lambda o:len(o.pose.bones))
hand = arm.pose.bones['wrist_R']
report['bones'] = {n:list(arm.matrix_world@arm.pose.bones[n].head) for n in ('wrist_R','weapon_rt_1','thumb_0_R','thumb_2_R')}
dg = bpy.context.evaluated_depsgraph_get()
for o in hero.children_recursive:
    if o.type != 'MESH': continue
    vg = o.vertex_groups.get('wrist_R')
    if not vg: continue
    ev = o.evaluated_get(dg)
    vertices = [ev.matrix_world@ev.data.vertices[v.index].co for v in o.data.vertices
                if any(g.group==vg.index and g.weight>.6 for g in v.groups)]
    report[o.name] = [list(p) for p in vertices]
(root/'_game/skits/pudge_tank/revision/grip_geometry.json').write_text(json.dumps(report), encoding='utf-8')
