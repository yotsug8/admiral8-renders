"""Ground the boarding shadow and render a separate revision of actor layers."""
import json
import os
from pathlib import Path
import bpy
from mathutils import Matrix, Vector


def ground_actor_shadow(scene):
    """Bake a flat support shadow; the actor has non-unit scale and boards a vehicle."""
    hero=bpy.data.objects['pudge_root']
    blob=bpy.data.objects['pudge_blob']
    scene.frame_set(0)
    ground=float(hero.matrix_world.translation.z)
    blob.animation_data_clear()
    blob.parent=None
    blob.matrix_parent_inverse=Matrix.Identity(4)
    blob.rotation_euler=(0,0,0)
    mat=blob.active_material.copy()
    blob.data=blob.data.copy()
    blob.data.materials.clear();blob.data.materials.append(mat)
    mat.node_tree.animation_data_clear()
    gain=next(n for n in mat.node_tree.nodes if n.type=='MATH' and n.operation=='MULTIPLY').inputs[1]
    records=[]
    for frame in range(300):
        scene.frame_set(frame)
        root=hero.matrix_world.translation
        height=max(0.,root.z-ground)
        blob.location=(root.x,root.y,ground+.012)
        blob.dimensions=(2.0*(1+.13*height),1.7*(1+.13*height),0)
        blob.hide_render=frame>=66
        gain.default_value=.28/(1+2.5*height)
        for prop in ('location','scale','hide_render'):
            blob.keyframe_insert(prop,frame=frame)
        gain.keyframe_insert('default_value',frame=frame)
    # Reopen-compatible audit of actual vertices, not only parent transforms.
    for frame in range(300):
        scene.frame_set(frame)
        world=[blob.matrix_world@v.co for v in blob.data.vertices]
        low,high=min(v.z for v in world),max(v.z for v in world)
        assert abs(low-ground-.012)<1e-4 and abs(high-low)<1e-4,(frame,low,high)
        records.append({'frame':frame,'z':low,'visible':not blob.hide_render,
                        'width':blob.dimensions.x,'opacity_gain':gain.default_value})
    scene.frame_set(0)
    return {'ground':ground,'samples':records,
            'limits':'Flat ground already measured; vehicle occlusion replaces the blob after boarding.'}


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]
    out=root/'_game/skits/pudge_tank/polish_v2'
    out.mkdir(parents=True,exist_ok=True)
    scene=bpy.context.scene
    report=ground_actor_shadow(scene)
    (out/'shadow_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    scene.render.filepath=str(out/'layers/f#####')
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'layers.blend'),compress=True)
    if not os.environ.get('PT_NO_RENDER'):
        scene.frame_start,scene.frame_end=0,299
        bpy.ops.render.render(animation=True)
