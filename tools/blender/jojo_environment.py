"""JoJo v7: textured Dota ruins and closer, mostly frontal storytelling cameras.

Input: corrected v6 scene. Local game-derived assets stay outside Git.
"""
import bpy
import math
import random
import bmesh
from pathlib import Path
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'out/dota-jojo/v7'
OUT.mkdir(parents=True, exist_ok=True)
s = bpy.context.scene
s.frame_set(1)


def aim(obj, target):
    obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z', 'Y').to_euler()


def imported_ruin(asset, name, location, scale, rotation=0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/'out/dota-jojo/environment'/(asset+'.glb')))
    obs = list(set(bpy.data.objects)-before)
    meshes = [o for o in obs if o.type == 'MESH' and 'physics' not in o.name.lower()]
    points = [o.matrix_world @ Vector(v) for o in meshes for v in o.bound_box]
    pivot = Vector(((min(v.x for v in points)+max(v.x for v in points))/2,
                    (min(v.y for v in points)+max(v.y for v in points))/2,
                    min(v.z for v in points)))
    dg = bpy.context.evaluated_depsgraph_get()
    result = []
    for source in meshes:
        mesh = bpy.data.meshes.new_from_object(source.evaluated_get(dg),
                                              preserve_all_data_layers=True, depsgraph=dg)
        for vertex in mesh.vertices:
            vertex.co = (source.matrix_world @ vertex.co-pivot)*scale
        obj = bpy.data.objects.new(name, mesh)
        s.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler.z = rotation
        for material in mesh.materials:
            if not material or not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    for key, value in [('Alpha', 1), ('Metallic', 0), ('Roughness', .88)]:
                        for link in list(node.inputs[key].links):
                            material.node_tree.links.remove(link)
                        node.inputs[key].default_value = value
        result.append(obj)
    for obj in obs:
        bpy.data.objects.remove(obj, do_unlink=True)
    return result


# Replace repeated cubes with game-authored masonry, original UVs and normals.
for obj in list(s.objects):
    if obj.name.startswith(('Rear masonry', 'Landing masonry')):
        bpy.data.objects.remove(obj, do_unlink=True)
imported_ruin('hoodwink_debut_ruins_wall_02', 'DOTA rear tall broken wall',
              (-4.4, 4.6, -.02), .82)
imported_ruin('hoodwink_debut_ruins_wall_02', 'DOTA landing ruined masonry',
              (0, -11.4, 1.15), 1.05, math.pi)
imported_ruin('hoodwink_debut_ruins_arch_l', 'DOTA rear arch', (-6.3, 4.0, 0), .56, math.pi/2)
imported_ruin('hoodwink_debut_ruins_roots', 'DOTA roots at rear wall', (-4.5, 3.6, 0), .40)
imported_ruin('hoodwink_debut_ruins_roots', 'DOTA roots at landing edge', (5.4, -8.8, 1.2), .30, math.pi)

# A distant backing closes irregular gaps without introducing foreground walls.
backmat = bpy.data.materials.new('Deep stone recess')
backmat.diffuse_color = (.028, .035, .04, 1)
backmat.use_nodes = True
backbs = backmat.node_tree.nodes.get('Principled BSDF')
backbs.inputs['Base Color'].default_value = (.012, .018, .025, 1)
backbs.inputs['Roughness'].default_value = 1
bn, bl = backmat.node_tree.nodes, backmat.node_tree.links
bg = bn.new('ShaderNodeNewGeometry')
bm = bn.new('ShaderNodeVectorMath')
bm.operation = 'SCALE'
bm.inputs[3].default_value = .30
bl.new(bg.outputs['Position'], bm.inputs[0])
bt = bn.new('ShaderNodeTexImage')
bt.image = bpy.data.images.load(str(ROOT/'out/kunkka-last-stand/map/tile_stone_000_75_tga_6031593f.png'), check_existing=True)
bt.projection = 'BOX'
bt.projection_blend = .2
bl.new(bm.outputs[0], bt.inputs['Vector'])
neutral=bn.new('ShaderNodeHueSaturation');neutral.inputs['Saturation'].default_value=0
neutral.inputs['Value'].default_value=.20;bl.new(bt.outputs['Color'],neutral.inputs['Color'])
warm=bn.new('ShaderNodeMixRGB');warm.blend_type='MULTIPLY';warm.inputs[0].default_value=1
warm.inputs[2].default_value=(1,.92,.82,1);bl.new(neutral.outputs[0],warm.inputs[1])
height=bn.new('ShaderNodeSeparateXYZ');bl.new(bg.outputs['Position'],height.inputs[0])
base=bn.new('ShaderNodeMapRange');base.inputs['From Min'].default_value=.15;base.inputs['From Max'].default_value=1.3
base.inputs['To Min'].default_value=.35;base.inputs['To Max'].default_value=0
bl.new(height.outputs['Z'],base.inputs['Value'])
moss_noise=bn.new('ShaderNodeTexNoise');moss_noise.inputs['Scale'].default_value=2.5
bl.new(bg.outputs['Position'],moss_noise.inputs['Vector'])
patch=bn.new('ShaderNodeMath');patch.operation='GREATER_THAN';patch.inputs[1].default_value=.57
bl.new(moss_noise.outputs['Fac'],patch.inputs[0])
mask=bn.new('ShaderNodeMath');mask.operation='MULTIPLY';bl.new(patch.outputs[0],mask.inputs[0]);bl.new(base.outputs[0],mask.inputs[1])
blend=bn.new('ShaderNodeMixRGB');bl.new(mask.outputs[0],blend.inputs[0]);bl.new(warm.outputs[0],blend.inputs[1]);bl.new(bt.outputs['Color'],blend.inputs[2])
bl.new(blend.outputs[0],backbs.inputs['Base Color'])
bb = bn.new('ShaderNodeBump')
bb.inputs['Strength'].default_value = .25
bb.inputs['Distance'].default_value = .04
bl.new(bt.outputs['Color'], bb.inputs['Height'])
bl.new(bb.outputs[0], backbs.inputs['Normal'])
def curved_apse(name, cy, radius, direction, base):
    vertices, faces = [], []
    count = 42
    for i in range(count+1):
        angle = math.pi*i/count
        if direction > 0:
            x=radius*math.cos(angle)
            height=5.8+3.2*math.sqrt(max(0,1-(x/7.2)**2))+.15
        else:
            height=7.4+.18*math.sin(i*1.7)+.12*math.cos(i*.7)
        for r,z in [(radius,base),(radius,base+height),(radius+.45,base+height),(radius+.45,base)]:
            vertices.append((r*math.cos(angle),cy+direction*r*math.sin(angle),z))
    for i in range(count):
        a,b=4*i,4*(i+1)
        for j in range(4):faces.append((a+j,b+j,b+(j+1)%4,a+(j+1)%4))
    faces.extend([(0,3,2,1),(4*count,4*count+1,4*count+2,4*count+3)])
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.materials.append(backmat)
    obj=bpy.data.objects.new(name,mesh);s.collection.objects.link(obj)
    bevel=obj.modifiers.new('Eroded apse joins','BEVEL');bevel.width=.045;bevel.segments=2
    return obj


curved_apse('Curved landing recess',-7.0,5.2,-1,1.2)
light_data = bpy.data.lights.new('Deep masonry grazing light', 'POINT')
light_obj = bpy.data.objects.new('Deep masonry grazing light', light_data)
s.collection.objects.link(light_obj)
light_obj.location = (0, 6.5, 5.8)
light_data.energy = 200
light_data.shadow_soft_size = 2
light_data.color = (.78, .81, .85)
aim(light_obj, (0, 8.8, 3.7))

# Retain exact tread heights/contact geometry, improve surfaces with game stone.
stone = bpy.data.materials.new('DOTA worn limestone paving')
stone.use_nodes = True
nodes, links = stone.node_tree.nodes, stone.node_tree.links
bs = nodes.get('Principled BSDF')
bs.inputs['Roughness'].default_value = .86
geometry = nodes.new('ShaderNodeNewGeometry')
mapping = nodes.new('ShaderNodeVectorMath')
mapping.operation = 'SCALE'
mapping.inputs[3].default_value = .27
links.new(geometry.outputs['Position'], mapping.inputs[0])
image = nodes.new('ShaderNodeTexImage')
image.image = bpy.data.images.load(str(ROOT/'out/kunkka-last-stand/map/tile_stone_000_75_tga_6031593f.png'), check_existing=True)
image.projection = 'BOX'
image.projection_blend = .12
links.new(mapping.outputs[0], image.inputs['Vector'])
tint = nodes.new('ShaderNodeMixRGB')
tint.blend_type = 'MULTIPLY'
tint.inputs[0].default_value = 1
tint.inputs[2].default_value = (.34, .36, .34, 1)
links.new(image.outputs['Color'], tint.inputs[1])
links.new(tint.outputs[0], bs.inputs['Base Color'])
bump = nodes.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = .35
bump.inputs['Distance'].default_value = .045
links.new(image.outputs['Color'], bump.inputs['Height'])
links.new(bump.outputs['Normal'], bs.inputs['Normal'])
for obj in s.objects:
    if obj.type == 'MESH' and obj.name.startswith(('Foundation', 'STAIR tread',
                    'Upper landing', 'Stair side masonry', 'Continuous architrave')):
        obj.data.materials.clear()
        obj.data.materials.append(stone)

# Match the silhouettes as well as the textures. Remove manufactured-perfect
# corners from the structural union; keep every established foot contact plane.
rng = random.Random(782)


def chip(obj, location, radius):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=radius, location=location)
    cutter = bpy.context.object
    cutter.rotation_euler = tuple(rng.uniform(0, math.pi) for _ in range(3))
    cutter.scale = (rng.uniform(.8, 1.3), rng.uniform(.8, 1.2), rng.uniform(.65, 1.1))
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new('Cut weathered corner', 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'
    mod.object = cutter
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


bpy.data.objects.remove(bpy.data.objects['Continuous architrave'], do_unlink=True)

# Distinct structural stone, without the clean floor-tile pattern on the roof.
aged = bpy.data.materials.new('Aged structural limestone')
aged.use_nodes = True
an, al = aged.node_tree.nodes, aged.node_tree.links
aged_bs = an.get('Principled BSDF')
aged_bs.inputs['Roughness'].default_value = .93
ag = an.new('ShaderNodeNewGeometry')
noise = an.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 2.8
noise.inputs['Detail'].default_value = 5
al.new(ag.outputs['Position'],noise.inputs['Vector'])
ramp = an.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].color = (.028,.032,.023,1)
ramp.color_ramp.elements[1].color = (.19,.175,.14,1)
al.new(noise.outputs['Fac'],ramp.inputs[0])
at=an.new('ShaderNodeTexImage')
at.image=bt.image
at.projection='BOX'
at.projection_blend=.2
am=an.new('ShaderNodeVectorMath');am.operation='SCALE';am.inputs[3].default_value=.55
al.new(ag.outputs['Position'],am.inputs[0]);al.new(am.outputs[0],at.inputs['Vector'])
mix=an.new('ShaderNodeMixRGB');mix.blend_type='MIX';mix.inputs[0].default_value=.12
aneutral=an.new('ShaderNodeHueSaturation');aneutral.inputs['Saturation'].default_value=.12
al.new(at.outputs['Color'],aneutral.inputs['Color'])
al.new(ramp.outputs['Color'],mix.inputs[1]);al.new(aneutral.outputs[0],mix.inputs[2])
al.new(mix.outputs[0],aged_bs.inputs['Base Color'])
fine = an.new('ShaderNodeTexNoise')
fine.inputs['Scale'].default_value = 34
fine.inputs['Detail'].default_value = 3
al.new(ag.outputs['Position'],fine.inputs['Vector'])
ab = an.new('ShaderNodeBump')
ab.inputs['Strength'].default_value = .3
ab.inputs['Distance'].default_value = .035
al.new(fine.outputs['Fac'],ab.inputs['Height'])
al.new(ab.outputs[0],aged_bs.inputs['Normal'])
def vault_underside(x, y):
    # Same analytic surface as the welded shell below. The extra overlap covers
    # its polygonal approximation and subtle stone displacement.
    radius_sq = x*x + max(0, y-2)**2
    return 5.8 + 3.2*math.sqrt(max(0, 1-radius_sq/49))


# Each capital meets the actual vault, without freestanding lintels or ribs.
# Preserve the lower shaft and all actor/prop clearances; extend only its upper
# part. A fitted top on the capital follows the curved soffit across its width.
column_supports = []
for obj in list(s.objects):
    if obj.type != 'MESH' or 'hoodwink_debut_pillar.vmdl_c' not in obj.name:
        continue
    points = [obj.matrix_world@Vector(v) for v in obj.bound_box]
    cx = (min(v.x for v in points)+max(v.x for v in points))/2
    cy = (min(v.y for v in points)+max(v.y for v in points))/2
    old_top = max(v.z for v in points)
    if abs(cx)>7:
        bpy.data.objects.remove(obj, do_unlink=True)
        continue
    radius = .72
    segments = 16
    rim = [(cx+radius*math.cos(2*math.pi*i/segments),
            cy+radius*math.sin(2*math.pi*i/segments)) for i in range(segments)]
    minimum_roof = min(vault_underside(x,y) for x,y in rim)
    cap_bottom = minimum_roof-.22
    shaft_top = cap_bottom+.10
    inverse = obj.matrix_world.inverted()
    obj.data = obj.data.copy()
    for vertex in obj.data.vertices:
        point = obj.matrix_world@vertex.co
        if point.z>3.0:
            point.z = 3.0+(point.z-3.0)*(shaft_top-3.0)/(old_top-3.0)
            vertex.co = inverse@point
    vertices, faces = [], []
    # Rounded bell-shaped springing stone, not a rectangular infill block.
    for fraction, ring_radius in [(0,.43),(.15,.48),(.55,.65),(1,radius)]:
        for i in range(segments):
            angle = 2*math.pi*i/segments
            x, y = cx+ring_radius*math.cos(angle), cy+ring_radius*math.sin(angle)
            roof = vault_underside(x,y)+.10
            vertices.append((x,y,cap_bottom+(roof-cap_bottom)*fraction))
    for j in range(3):
        for i in range(segments):
            k=(i+1)%segments
            faces.append((j*segments+i,j*segments+k,(j+1)*segments+k,(j+1)*segments+i))
    faces.append(tuple(reversed(range(segments))))
    vertices.append((cx,cy,vault_underside(cx,cy)+.10))
    for i in range(segments):
        faces.append((3*segments+i,3*segments+(i+1)%segments,len(vertices)-1))
    mesh = bpy.data.meshes.new('Vault fitted capital')
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(aged)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    cap = bpy.data.objects.new('Vault fitted column capital', mesh)
    s.collection.objects.link(cap)
    bevel = cap.modifiers.new('Worn capital edges', 'BEVEL')
    bevel.width = .035
    bevel.segments = 3
    column_supports.append({'column': obj.name, 'capital': cap.name,
                            'shaft_top': shaft_top, 'capital_bottom': cap_bottom})

# One welded, tangent-continuous shell: curved wall, half-dome, front vault.
# A shared material and world-space mapping avoid a wall/ceiling texture seam.
vertices,faces=[],[]
na,nlat,nx,ny=42,20,40,6
rings=[(7,z) for z in (0,2.9,5.8)]
for j in range(1,nlat+1):
    angle=math.pi*.5*j/nlat
    rings.append((7*math.cos(angle),5.8+3.2*math.sin(angle)))
for radius,z in rings:
    for i in range(na+1):
        a=math.pi*i/na
        vertices.append((radius*math.cos(a),2+radius*math.sin(a),z))
for j in range(len(rings)-1):
    for i in range(na):
        a=j*(na+1)+i;b=a+na+1
        faces.append((b,b+1,a+1,a))
offset=len(vertices)
for j in range(ny+1):
    y=-3.2+j*5.2/ny
    for i in range(nx+1):
        angle=math.pi*i/nx
        vertices.append((7*math.cos(angle),y,5.8+3.2*math.sin(angle)))
for j in range(ny):
    for i in range(nx):
        a=offset+j*(nx+1)+i;b=a+nx+1
        faces.append((a,a+1,b+1,b))
mesh=bpy.data.meshes.new('Continuous sanctuary shell');mesh.from_pydata(vertices,[],faces)
bm=bmesh.new();bm.from_mesh(mesh)
bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.00001)
bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=.00001)
bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
mesh.materials.append(backmat)
vault=bpy.data.objects.new('Continuous sanctuary shell',mesh);s.collection.objects.link(vault)
for poly in mesh.polygons:poly.use_smooth=True
solid=vault.modifiers.new('Vault thickness','SOLIDIFY');solid.thickness=.4
tex=bpy.data.textures.new('Vault stone irregularity',type='CLOUDS');tex.noise_scale=.55;tex.noise_depth=2
disp=vault.modifiers.new('Vault stone wear','DISPLACE');disp.texture=tex;disp.texture_coords='GLOBAL';disp.strength=.045
ld=bpy.data.lights.new('Vault soft bounce','AREA');lo=bpy.data.objects.new('Vault soft bounce',ld);s.collection.objects.link(lo)
lo.location=(0,-1,4.5);ld.energy=260;ld.size=5;ld.color=(.72,.78,.85);aim(lo,(0,4,8.4))
for name,location,target,power in [
        ('Upper apse soft fill',(-1,4.4,6.5),(0,8.8,8.1),180),
        ('Near vault soft fill',(2,-2,6.2),(1,2,8.9),140)]:
    ld=bpy.data.lights.new(name,'AREA');lo=bpy.data.objects.new(name,ld);s.collection.objects.link(lo)
    lo.location=location;ld.energy=power;ld.size=5;ld.color=(.88,.87,.84);aim(lo,target)
for obj in list(s.objects):
    if obj.name.startswith('Stair side masonry'):
        obj.data.materials.clear()
        obj.data.materials.append(aged)
    if obj.name.startswith('STAIR tread'):
        obj.modifiers.clear()
        # Chip only the nosing away from the walking corridor x=.7..3.5.
        front = obj.location.y-obj.dimensions.y/2
        top = obj.location.z+obj.dimensions.z/2
        for x in (-4.4,-2.6,-.65,4.3):
            chip(obj, (x+rng.uniform(-.25,.25),front,top-.015),rng.uniform(.055,.095))
        bevel = obj.modifiers.new('Worn stair edges', 'BEVEL')
        bevel.width = .025
        bevel.segments = 3

# The landing and last tread were coplanar overlapping boxes with separate
# bevels. Union before beveling removes the false lip while retaining all levels.
floor=bpy.data.objects['Foundation']
floor.modifiers.clear()
floor.location.z += .02  # Match the authored ground and imported ruin bases at z=0.
parts=[o for o in list(s.objects) if o.name.startswith(('STAIR tread','Upper landing'))]
for obj in parts:
    obj.modifiers.clear()
    bpy.context.view_layer.objects.active=floor
    mod=floor.modifiers.new('Continuous landing and stair','BOOLEAN')
    mod.operation='UNION';mod.solver='EXACT';mod.object=obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(obj,do_unlink=True)
floor.name='Continuous stone floor and stair'
bevel=floor.modifiers.new('Continuous worn stair edges','BEVEL');bevel.width=.018;bevel.segments=3

# Keep textured ruin surfaces readable behind faces, subordinate to the actors.
for name, location, target, energy in [
        ('Rear wall wash', (-3, 1.2, 4.7), (0, 4.6, 3), 130),
        ('Landing wall wash', (-3, -8.8, 4.4), (0, -11.4, 3.2), 100)]:
    obj = bpy.data.objects[name]
    obj.location = location
    obj.data.energy = energy
    obj.data.size = 4
    aim(obj, target)


def camera(name, start, end, first, last, target0, target1, lens, aperture=6.3):
    obj = bpy.data.objects[name]
    obj.animation_data_clear()
    obj.data.animation_data_clear()
    obj.data.lens = lens
    obj.data.dof.aperture_fstop = aperture
    for frame, location, target in [(start, first, target0), (end, last, target1)]:
        obj.location = location
        aim(obj, target)
        obj.data.dof.focus_distance = (Vector(target)-obj.location).length
        obj.keyframe_insert('location', frame=frame)
        obj.keyframe_insert('rotation_euler', frame=frame)
        obj.data.keyframe_insert('dof.focus_distance', frame=frame)
    return obj


c1 = camera('01_Shadow_identity', 1, 90, (-3.0,-6.1,2.8), (-2.95,-5.9,2.8),
            (-2.5,-.55,2.0), (-2.5,-.55,2.05), 40)
c2 = camera('02_Time_erasure', 91, 154, (-2.9,-7.0,3.1), (-2.8,-6.8,3.1),
            (-2.5,-.55,2.1), (-2.5,-.55,2.1), 42)
# The transformation cuts to a frontal medium shot instead of a distant tableau.
marker = s.timeline_markers.new('Transformation close view', frame=155)
marker.camera = bpy.data.objects['03_Diavolo_glimpse']
camera('03_Diavolo_glimpse', 155, 244, (2.8,-6.3,3.0), (2.75,-6.1,3.0),
       (2.65,-.4,2.25), (2.65,-.4,2.25), 38)
camera('05_Column_reveal', 316, 407, (2.75,-8.8,3.5), (2.75,-10,3.8),
       (2.45,-.4,1.95), (2.75,-3.1,2.15), 36, 8)
c5 = bpy.data.objects['05_Column_reveal'].data
for frame, lens in [(316,36),(377,36),(394,29),(424,29)]:
    c5.lens = lens
    c5.keyframe_insert('lens', frame=frame)

# Fit the complete ward silhouettes with a real margin over their entire motion.
wards = [o for name in ('observer','sentry')
         for o in bpy.data.objects['ITEM / '+name].children if o.type == 'MESH']
for cam, frames in ((c1,range(1,91)), (c2,range(91,155))):
    factor = 1.0
    for frame in frames:
        s.frame_set(frame)
        points = [world_to_camera_view(s,cam,o.matrix_world@v.co) for o in wards for v in o.data.vertices]
        factor = max(factor, max(abs(p.x-.5)/.455 for p in points))
    cam.data.lens /= factor

s.frame_set(1)
s.render.filepath = str(OUT/'frames/frame_')
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'jojo-v7.blend'))
print('JOJO_ENVIRONMENT_READY', flush=True)
