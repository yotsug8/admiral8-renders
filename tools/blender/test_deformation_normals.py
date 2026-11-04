"""CPU regression fixtures. Open the original fleet v2 scene before running.

Blender -b --factory-startup _game/skits/fleet_battle/v2/scene.blend
        --python-exit-code 2 -P tools/blender/test_deformation_normals.py
The original scene is read-only; all mutations use temporary mesh copies.
"""
import bpy,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'_game/study/deformation_normals';OUT.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(ROOT/'tools/blender'));sys.dont_write_bytecode=True
from deformation_normals import weld_compatible_uv_duplicates as weld
base=next(o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('Giant_') and o.name.endswith('.upper_body'))
results=[]
def clone():
 c=base.copy();c.data=base.data.copy();bpy.context.collection.objects.link(c);return c
def clean(c):
 m=c.data;bpy.data.objects.remove(c,do_unlink=True)
 if m.users==0:bpy.data.meshes.remove(m)
def sample(o):
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=ev.to_mesh()
 try:return [v.co.copy() for v in m.vertices]
 finally:ev.to_mesh_clear()
def mark(name,**kw):results.append(dict(test=name,passed=True,**kw));print('PASS',name,kw)
def refused(name,c,expected):
 before=c.data;coords=[tuple(v.co) for v in before.vertices];keys=before.shape_keys
 try:weld(c)
 except ValueError as e:
  assert expected in str(e),(expected,str(e));assert c.data is before and [tuple(v.co) for v in c.data.vertices]==coords and c.data.shape_keys is keys;mark(name,reason=str(e))
 else:raise AssertionError('Expected refusal '+name)
 clean(c)
c=clone();r=weld(c);group=r['groups'][0];clean(c)
# Compatible active, masked, chained relative morphs.
c=clone();basis=c.shape_key_add(name='Basis');a=c.shape_key_add(name='A');b=c.shape_key_add(name='B');b.relative_key=a
for i,p in enumerate(basis.data):
 delta=.03*p.co.y
 a.data[i].co.x+=delta;b.data[i].co.x+=delta;b.data[i].co.z+=.02*p.co.x
for k in (a,b):k.slider_min=-1;k.slider_max=2
b.vertex_group=c.vertex_groups[0].name;a.value=.35;b.value=.6
bpy.context.view_layer.update();before=sample(c);old=c.data;oldkey=c.data.shape_keys;r=weld(c);bpy.context.view_layer.update();after=sample(c)
err=max((v-after[r['old_to_new'][i]]).length for i,v in enumerate(before));assert err<1e-6;assert old.shape_keys is oldkey;assert len(oldkey.key_blocks['A'].data)==len(before)
mark('compatible_active_chained_masked_morphs',max_deformed_delta=err,keys=len(c.data.shape_keys.key_blocks));print('POST_ATTRS',[(x.name,x.data_type,x.domain) for x in c.data.attributes]);assert weld(c)['changed'] is False;mark('idempotent');clean(c)
c=clone();c.shape_key_add(name='Basis');a=c.shape_key_add(name='Bad');a.data[group[1]].co.x+=.01
refused('incompatible_inactive_morph_atomic',c,'Несовместимый morph')
c=clone();c.shape_key_add(name='Basis');c.shape_key_add(name='A');c.data.shape_keys.use_relative=False
refused('absolute_morph_atomic',c,'относительные shape keys')
c=clone();c.shape_key_add(name='Basis');c.shape_key_add(name='A');c.data.shape_keys.animation_data_create()
refused('animated_keys_atomic',c,'относительные shape keys')
c=clone();c.data.attributes.new('unsupported','FLOAT','POINT');refused('unknown_attribute_atomic',c,'Неизвестные')
# Same position but unequal weights must remain separate, with unchanged weights.
c=clone();v=group[1];wg=c.vertex_groups.new(name='Weld_negative_weight');wg.add([v],.125,'REPLACE');r=weld(c);assert r['old_to_new'][group[0]]!=r['old_to_new'][v];mark('weight_conflict_skipped',skipped=r['skipped']);clean(c)
c=clone();edge=next(e for e in c.data.edges if group[0] in e.vertices);edge.use_edge_sharp=True;r=weld(c);assert r['old_to_new'][group[0]]!=r['old_to_new'][group[1]];mark('explicit_sharp_preserved',skipped=r['skipped']);clean(c)
c=clone();face=next(p for p in c.data.polygons if group[0] in p.vertices);face.use_smooth=False;r=weld(c);assert r['old_to_new'][group[0]]!=r['old_to_new'][group[1]];mark('flat_face_preserved',skipped=r['skipped']);clean(c)
c=clone();ns=[n.vector.copy() for n in c.data.corner_normals]
for l in c.data.loops:
 if l.vertex_index==group[1]:ns[l.index]=ns[l.index].orthogonal().normalized()
c.data.normals_split_custom_set(ns);r=weld(c);assert r['old_to_new'][group[0]]!=r['old_to_new'][group[1]];mark('intentional_custom_split_preserved',skipped=r['skipped']);clean(c)
# Shared mesh stays untouched; helper operates in object mode without context operators.
c=base.copy();bpy.context.collection.objects.link(c);old=base.data;n=len(old.vertices);r=weld(c);assert base.data is old and len(old.vertices)==n and c.data is not old;mark('shared_source_unchanged');clean(c)
# A collapse and duplicate-face risk must be rejected before publication.
c=clone();m=bpy.data.meshes.new('DuplicateFaceFixture');m.from_pydata([(0,0,0),(1,0,0),(0,1,0)]*2,[],[(0,1,2),(3,4,5)]);m.uv_layers.new();c.data=m
for p in m.polygons:p.use_smooth=True
m.normals_split_custom_set([(0,0,1)]*6);refused('duplicate_faces_atomic',c,'дублированные грани')
(OUT/'compatible_weld_tests.json').write_text(json.dumps({'blender':bpy.app.version_string,'tests':results,'helper_sha256':hashlib.sha256((ROOT/'tools/blender/deformation_normals.py').read_bytes()).hexdigest()},indent=2))
print('TESTS_DONE',len(results))
