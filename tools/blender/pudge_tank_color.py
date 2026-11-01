"""Give the tank opaque, denser camouflage with restrained specular light."""
import json
from pathlib import Path
import bpy

def apply_color(tank):
    changed = []
    materials = {s.material for o in tank.children_recursive if o.type == 'MESH'
                 for s in o.material_slots if s.material}
    for mat in materials:
        if not mat.name.startswith('tank matte paint ') or mat.get('dense_paint_v1'):
            continue
        nt = mat.node_tree
        old = next((n for n in nt.nodes if n.type == 'BSDF_DIFFUSE'), None)
        if old is None:
            continue
        paint = nt.nodes.new('ShaderNodeBsdfPrincipled')
        paint.name = 'Dense opaque paint'
        paint.inputs['Metallic'].default_value = .05
        paint.inputs['Roughness'].default_value = .73
        paint.inputs['Specular IOR Level'].default_value = .25
        paint.inputs['Alpha'].default_value = 1
        paint.inputs['Transmission Weight'].default_value = 0
        paint.inputs['Coat Weight'].default_value = 0
        color = nt.nodes.new('ShaderNodeRGBCurve')
        curve = color.mapping.curves[3]
        curve.points.new(.06, .025)
        curve.points.new(.25, .17)
        curve.points.new(.65, .62)
        color.mapping.update()
        if old.inputs['Color'].links:
            nt.links.new(old.inputs['Color'].links[0].from_socket, color.inputs['Color'])
        else:
            color.inputs['Color'].default_value = old.inputs['Color'].default_value
        saturation = nt.nodes.new('ShaderNodeHueSaturation')
        saturation.inputs['Saturation'].default_value = 1.3
        saturation.inputs['Hue'].default_value = .51
        nt.links.new(color.outputs['Color'], saturation.inputs['Color'])
        tint = nt.nodes.new('ShaderNodeMixRGB')
        tint.blend_type = 'MULTIPLY'
        tint.inputs[0].default_value = 1
        tint.inputs[2].default_value = (.78, 1, .68, 1)
        nt.links.new(saturation.outputs['Color'], tint.inputs[1])
        nt.links.new(tint.outputs[0], paint.inputs['Base Color'])
        if old.inputs['Normal'].links:
            nt.links.new(old.inputs['Normal'].links[0].from_socket, paint.inputs['Normal'])
        output = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
        nt.links.new(paint.outputs[0], output.inputs['Surface'])
        mat['dense_paint_v1'] = True
        changed.append(mat.name)
    fill = bpy.data.objects.get('soft production fill')
    if fill:
        fill.data.energy = .45
    rim = bpy.data.materials.get('painted commander collar')
    if rim:
        shader = next((n for n in rim.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if shader:
            shader.inputs['Base Color'].default_value = (.045, .075, .027, 1)
    return {'materials': changed, 'fill_energy': .45, 'roughness': .73, 'saturation': 1.3}

if __name__ == '__main__':
    out = Path(bpy.data.filepath).parent
    scene = bpy.context.scene
    scene.frame_set(150)
    report = apply_color(bpy.data.objects['detailed_tank'])
    (out / 'color_review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'color_candidate.blend'), compress=True)
    for frame in (91, 150):
        scene.frame_set(frame)
        scene.render.filepath = str(out / f'color_{frame:05d}.png')
        bpy.ops.render.render(write_still=True)
