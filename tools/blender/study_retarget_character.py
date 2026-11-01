"""Bounded Retarget API test on one frozen Pudge pose; never edits the source.

Requires the exact isolated package/profile described in RETARGET_SMOKE.md.
build -> reopen/audit without addon -> keys. No production defaults change.
"""
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import anim_utils
sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_retarget_smoke as api
from contact_metrics import resolve
from study_character_overlap import evaluated_vertices

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'_game/study/foundations/reach_witness/point_A.blend'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def meshes():
    return [o for o in bpy.context.scene.objects if o.get('retarget_mesh')]


def surfaces():
    graph = bpy.context.evaluated_depsgraph_get()
    return {o.name: evaluated_vertices(o, graph)[0] for o in meshes()}


def freeze(members, arm):
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    matrices = {o.name: o.matrix_world.copy() for o in members}
    pose = {o.name: {b.name: b.matrix_basis.copy() for b in o.pose.bones}
            for o in members if o.type == 'ARMATURE'}
    for o in members:
        o.animation_data_clear()
        if o.type == 'MESH' and o.data.shape_keys:
            o.data.shape_keys.animation_data_clear()
        if o.type == 'ARMATURE':
            for b in o.pose.bones:
                b.matrix_basis = pose[o.name][b.name]
    def depth(ob):
        result=0
        while ob.parent is not None:
            result+=1;ob=ob.parent
        return result
    for o in sorted(members, key=depth):
        o.matrix_world = matrices[o.name]
    bpy.context.view_layer.update()
    if any(b.constraints for b in arm.pose.bones):
        raise ValueError('Expected unconstrained source main rig')


def build(folder, animate=None, frame_end=60, limits=None):
    package = api.check_package(folder)
    api.guard(folder, folder/'journal.json')
    source_hash = digest(SOURCE)
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    sc = bpy.context.scene
    actor, arm, members = resolve('pudge', list(sc.objects))
    members = [o for o in members if 'blob' not in o.name]
    for ob in members:
        if ob.type == 'MESH' and not ob.hide_render:
            ob['retarget_mesh'] = True
    sc.frame_set(0)
    bpy.context.view_layer.update()
    original = surfaces()
    freeze(members, arm)
    frozen = surfaces()
    frozen_error = max(float(np.abs(frozen[n]-p).max()) for n,p in original.items())
    if frozen_error > 2e-5:
        raise ValueError(f'Freezing changed source surfaces: {frozen_error}')
    # Bake converts through world space. Keep this isolated actor near zero,
    # rather than carrying the map's ~100m translation into float32 matrices.
    layout_translation=actor.matrix_world.translation.copy()
    if actor.parent is not None:raise ValueError('Expected unparented actor root')
    actor.location-=layout_translation
    bpy.context.view_layer.update()
    frozen=surfaces()
    for ob in list(sc.objects):
        if ob not in members:
            bpy.data.objects.remove(ob, do_unlink=True)
    sc.frame_start, sc.frame_end, sc.render.fps = 1,frame_end,30
    arm['retarget_main'] = True
    initial = {b.name: [list(r) for r in b.matrix] for b in arm.pose.bones}
    local = {b.name: [list(r) for r in b.matrix_basis] for b in arm.pose.bones}
    sys.path.insert(0,str(package))
    module = importlib.import_module('retarget')
    entry = bpy.context.preferences.addons.new(); entry.module = 'retarget'
    module.register()
    report = dict(source_sha256=source_hash, package_sha256=api.PACKAGE_HASH,
                  blender_version=bpy.app.version_string, frozen_surface_error=frozen_error,
                  removed_layout_translation=list(layout_translation))
    try:
        data = bpy.data.armatures.new('DonorData')
        donor = bpy.data.objects.new('Donor', data)
        sc.collection.objects.link(donor)
        donor.matrix_world = arm.matrix_world.copy()
        api.select_only(donor); bpy.ops.object.mode_set(mode='EDIT')
        for name in api.BONES:
            b = data.edit_bones.new('donor_'+name)
            b.length = arm.data.bones[name].length
            b.matrix = arm.data.bones[name].matrix_local.copy()
            parent = arm.data.bones[name].parent
            b.parent = data.edit_bones.get('donor_'+parent.name) if parent else None
        bpy.ops.object.mode_set(mode='OBJECT')
        report['donor_rest_error']=max(float(np.abs(np.array(data.bones['donor_'+n].matrix_local)-np.array(arm.data.bones[n].matrix_local)).max()) for n in api.BONES)
        if report['donor_rest_error']>2e-6:raise ValueError('Donor rest orientation mismatch')
        for obj,prefix in [(donor,'donor_'),(arm,'')]:
            mapping = obj.data.retarget_retarget
            mapping.root = prefix+'root'
            for field,name in zip(api.FIELDS[1:],api.BONES[1:]):
                setattr(mapping.spine,field,prefix+name)
            mapping.deform_preset = '--'
        if animate is not None:
            report['source_motion']=animate(donor, arm, local)
        else:
            for f in range(sc.frame_start,sc.frame_end+1):
                for name in api.BONES:
                    b = donor.pose.bones['donor_'+name]
                    b.rotation_mode = 'QUATERNION'
                    base = Matrix(local[name])
                    angle = math.sin(2*math.pi*(f-1)/60)
                    if name == 'spine2': base = base @ Quaternion((1,0,0),math.radians(4)*angle).to_matrix().to_4x4()
                    if name == 'neck1': base = base @ Quaternion((0,0,1),math.radians(3)*angle).to_matrix().to_4x4()
                    b.location,b.rotation_quaternion,b.scale = base.decompose()
                    for channel in ('location','rotation_quaternion','scale'): b.keyframe_insert(channel,frame=f)
        action = donor.animation_data.action
        bag = anim_utils.action_get_channelbag_for_slot(action,donor.animation_data.action_slot)
        for c in bag.fcurves:
            for k in c.keyframe_points: k.interpolation='LINEAR'
        sc.frame_set(1);api.select_only(donor);arm.select_set(True)
        report['prebind_initial_pose']=api.compare([api.snapshot(donor,'donor_')[0]]*len(api.FRAMES),[api.snapshot(arm)[0]]*len(api.FRAMES))
        sc.frame_set(1);api.select_only(donor);arm.select_set(True)
        options = api.binding_options()
        report['binding_options']=options
        report['bind_result']=sorted(api.invoke_binding(module,options,report))
        added=[(b,c) for b in arm.pose.bones for c in b.constraints]
        if len(added)!=6 or any(c.type!='COPY_ROTATION' for _,c in added):
            raise ValueError('Unexpected binding scope')
        live=api.snapshot(arm)
        report['donor_to_live']=api.compare(api.snapshot(donor,'donor_'),live)
        try: api.compare(live,[live[0]]*len(live))
        except ValueError: report['static_negative_control']='caught'
        else: raise ValueError('No visible motion transferred')
        api.write_json(folder/'live_matrices.json',live)
        api.select_only(arm)
        module.bone_utils.bake_anim(frame_start=1,frame_end=frame_end,only_selected=False,
            bake_bones=True,bake_object=False,use_current_action=False,
            suffix=module.bone_utils.cp_suffix,step=1,interpolation='LINEAR',inverse=False)
        for _,c in added:c.mute=True
        arm.update_tag()
        report['live_to_baked']=api.compare(live,api.snapshot(arm))
        sc.frame_set(1);bpy.context.view_layer.update()
        current=surfaces()
        report['initial_surface_error']=max(float(np.abs(current[n]-p).max()) for n,p in frozen.items())
        if report['initial_surface_error']>2e-5: raise ValueError('Transfer changed initial skin pose')
        sc['retarget_initial']=json.dumps(initial)
        sc['retarget_source_sha256']=source_hash
        sc['retarget_limits']=limits or 'Frozen Pudge frame0; matched rest pose, spine2 +/-4deg, neck1 +/-3deg. Hidden cleaver excluded.'
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'character.blend'))
        report['source_unchanged']=digest(SOURCE)==source_hash
        if not report['source_unchanged']:raise ValueError('Source changed')
    finally:
        module.unregister();bpy.context.preferences.addons.remove(entry)
        api.write_json(folder/'build.json',report)


def audit(folder, moving_roots=('spine2','neck1')):
    if any(n=='retarget' or n.startswith('retarget.') for n in sys.modules):
        raise ValueError('Audit must run without addon')
    bpy.ops.wm.open_mainfile(filepath=str(folder/'character.blend'))
    sc=bpy.context.scene;arm=next(o for o in sc.objects if o.get('retarget_main'))
    report=dict(reopen=api.compare(json.loads((folder/'live_matrices.json').read_text()),api.snapshot(arm)))
    sc.frame_set(1);bpy.context.view_layer.update()
    graph=bpy.context.evaluated_depsgraph_get()
    base={o.name:evaluated_vertices(o,graph) for o in meshes()}
    initial=json.loads(sc['retarget_initial'])
    moving={b.name for n in moving_roots for b in [arm.pose.bones[n],*arm.pose.bones[n].children_recursive]}
    report.update(protected_bone_error=0.,max_edge_ratio=1.,max_sole_drift=0.,meshes={})
    weapon=next(o for o in meshes() if 'righthook_model' in o.name)
    bodies=[o for o in meshes() if any(n in o.name for n in ('upper_body','lower_body','.head','leftarm_model'))]
    def tree(ob, exclude_grip=False):
        ev=ob.evaluated_get(graph);mesh=ev.to_mesh()
        try:
            mesh.calc_loop_triangles()
            grip=set()
            if exclude_grip:
                groups={g.index:g.name.lower() for g in ob.vertex_groups}
                grip={v.index for v in ob.data.vertices if sum(g.weight for g in v.groups if
                    'wrist_r' in groups[g.group] or ('finger' in groups[g.group] and '_r' in groups[g.group]))>.5}
            tris=[tuple(t.vertices) for t in mesh.loop_triangles if not all(i in grip for i in t.vertices)]
            return BVHTree.FromPolygons([ev.matrix_world@v.co for v in mesh.vertices],tris,all_triangles=True)
        finally:ev.to_mesh_clear()
    def crossings():
        hook=tree(weapon)
        return {ob.name:set(hook.overlap(tree(ob,True))) for ob in bodies}
    original_crossings=crossings()
    report['weapon_crossings']={'baseline':{n:len(p) for n,p in original_crossings.items()},'max_new':0,'frames':[]}
    feet={}
    for o in meshes():
        if 'lower_body' in o.name:
            feet[o.name]=np.where(base[o.name][0][:,2]<base[o.name][0][:,2].min()+.045)[0]
    for f in range(sc.frame_start,sc.frame_end+1):
        sc.frame_set(f);bpy.context.view_layer.update()
        new_pairs={n:len(p-original_crossings[n]) for n,p in crossings().items()}
        report['weapon_crossings']['frames'].append({'frame':f,'new_pairs':new_pairs})
        report['weapon_crossings']['max_new']=max(report['weapon_crossings']['max_new'],sum(new_pairs.values()))
        for b in arm.pose.bones:
            if b.name not in moving:
                report['protected_bone_error']=max(report['protected_bone_error'],float(np.abs(np.array(b.matrix)-initial[b.name]).max()))
        for o in meshes():
            p,e=evaluated_vertices(o,graph);bp,be=base[o.name]
            if not np.array_equal(e,be):raise ValueError('Topology changed')
            a=np.linalg.norm(bp[e[:,0]]-bp[e[:,1]],axis=1);v=np.linalg.norm(p[e[:,0]]-p[e[:,1]],axis=1)
            valid=a>1e-6
            ratio=float(np.maximum(v[valid]/a[valid],a[valid]/np.maximum(v[valid],1e-12)).max())
            report['meshes'][o.name]=max(report['meshes'].get(o.name,1),ratio)
            report['max_edge_ratio']=max(report['max_edge_ratio'],ratio)
            if o.name in feet:
                ids=feet[o.name];report['max_sole_drift']=max(report['max_sole_drift'],float(np.linalg.norm(p[ids]-bp[ids],axis=1).max()))
    report['technical_pass']=report['max_edge_ratio']<1.35 and report['max_sole_drift']<.0002 and report['protected_bone_error']<2e-5 and report['weapon_crossings']['max_new']==0
    report['source_unchanged']=digest(SOURCE)==sc['retarget_source_sha256']
    report['limits']='Edge deformation, selected lowest sole band, hook/skin triangle crossings excluding weighted grip. Not containment, cloth simulation or valid grasp certification; visual QA required.'
    api.write_json(folder/'audit.json',report)
    if not report['technical_pass'] or not report['source_unchanged']: raise ValueError(json.dumps(report))


def keys(folder, diagnostic=False, frames=None):
    if not json.loads((folder/'audit.json').read_text())['technical_pass'] and not diagnostic:
        raise ValueError('Audit required before render')
    bpy.ops.wm.open_mainfile(filepath=str(folder/'character.blend'))
    sc=bpy.context.scene;sc.frame_set(1);bpy.context.view_layer.update()
    points=np.concatenate(list(surfaces().values()))
    low,high=points.min(axis=0),points.max(axis=0);center=Vector((low+high)/2)
    sc.render.engine='BLENDER_EEVEE';sc.eevee.taa_render_samples=32
    sc.render.resolution_x,sc.render.resolution_y=640,640;sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG';sc.render.film_transparent=False
    sc.view_settings.view_transform='Standard';sc.view_settings.look='None';sc.view_settings.exposure=0
    world=bpy.data.worlds.new('StudyWorld');sc.world=world;world.use_nodes=True
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(.055,.07,.085,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=.8
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,float(low[2])-.0001))
    floor=bpy.context.object;floor.name='StudyFloor'
    mat=bpy.data.materials.new('StudyFloor');mat.diffuse_color=(.12,.15,.18,1);floor.data.materials.append(mat)
    light=bpy.data.objects.new('StudyKey',bpy.data.lights.new('StudyKey','AREA'));sc.collection.objects.link(light)
    light.location=center+Vector((4,-3,7));light.data.energy=900;light.data.shape='DISK';light.data.size=5
    light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()
    for name,offset in [('front',(10,-3,1.5)),('side',(0,-10,1.5))]:
        cam=bpy.data.objects.new(name,bpy.data.cameras.new(name));sc.collection.objects.link(cam)
        cam.location=center+Vector(offset);cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type='ORTHO';cam.data.ortho_scale=float(max(high-low)*1.45);sc.camera=cam
        for frame in frames or (1,1+sc.frame_end//4,1+3*sc.frame_end//4):
            prefix='diagnostic_' if diagnostic else ''
            sc.frame_set(frame);sc.render.filepath=str(folder/f'{prefix}{name}_{frame:03d}.png')
            bpy.ops.render.render(write_still=True)
    bpy.context.preferences.filepaths.file_preview_type='NONE';bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/('diagnostic_preview.blend' if diagnostic else 'preview.blend')))


def video(folder):
    """Render the already audited copy at native frame rate from both witnesses."""
    report=json.loads((folder/'audit.json').read_text())
    if not report['technical_pass'] or not report['source_unchanged']:
        raise ValueError('Passing audit required')
    bpy.ops.wm.open_mainfile(filepath=str(folder/'preview.blend'))
    sc=bpy.context.scene
    for name in ('front','side'):
        target=folder/('frames_'+name)
        if target.exists():raise ValueError('Fresh frame directory required: '+str(target))
        target.mkdir()
        sc.camera=bpy.data.objects[name]
        for frame in range(sc.frame_start,sc.frame_end+1):
            sc.frame_set(frame);sc.render.filepath=str(target/f'{frame:04d}.png')
            bpy.ops.render.render(write_still=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--mode',choices=('build','audit','keys','video'),required=True)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);folder=args.out.resolve()
    globals()[args.mode](folder)
    print('RETARGET_CHARACTER_'+args.mode.upper()+'_OK')


if __name__=='__main__':main()
