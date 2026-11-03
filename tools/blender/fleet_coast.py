"""Берег флота: вызвать environment() ВМЕСТО старого environment() при сборке.

Импорт не обращается к bpy, не меняет сцену, пути поиска или файлы.
Повторный вызов в той же сцене запрещён: пересобирать из assets.blend.
Камеры, актёры, следы кораблей, рендер и сохранение принадлежат сборщику.
Проверено в Blender 5.2 на рабочих камерах флота; художественный статус
всей постановки хранится в docs/productions/FLEET_BATTLE.md.
"""

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROCK = ROOT / '_game/models/render/models_props_rock_riveredge_rock001a.glb'
PREFIX = 'FleetCoast'


def _smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _edge(x):
    """Линия среднего уровня воды; всегда мористее свободной площадки."""
    return -7.2 + .9 * math.sin(x * .13) + .45 * math.sin(x * .31 + .8)


def _height(x, y):
    edge = _edge(x)
    if y < -5:
        return -.7 + .7 * _smooth((y - edge) / (-5 - edge)) if y >= edge else -.7 + (y - edge) * .32
    # Весь прямоугольник боя, включая границы, строго z=0.
    outside = max(abs(x) - 14, y - 22, 0)
    weight = _smooth(outside / 12) * _smooth((y + 5) / 8)
    return weight * (.45 + .6 * math.sin(x * .11 + y * .08)**2
                     + .22 * math.sin(y * .23 - x * .18)
                     + 7 * math.exp(-((y-72)/35)**2) * (1+.3*math.sin(x*.05)))


def _mesh(name, vertices, faces, material):
    import bpy
    mesh = bpy.data.meshes.new(PREFIX + ' ' + name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(material)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def _faces(nx, ny):
    return [(j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1,
             (j + 1) * nx + i) for j in range(ny - 1) for i in range(nx - 1)]


def _attribute(mesh, name, values):
    attr = mesh.attributes.new(name, 'FLOAT', 'POINT')
    attr.data.foreach_set('value', values)


def _ramp(nt, source, stops):
    node = nt.nodes.new('ShaderNodeValToRGB')
    ramp = node.color_ramp
    ramp.interpolation = 'EASE'
    for index, (position, color) in enumerate(stops):
        item = ramp.elements[index] if index < 2 else ramp.elements.new(position)
        item.position = position
        item.color = (*color, 1)
    nt.links.new(source, node.inputs['Fac'])
    return node.outputs['Color']


def _math(nt, operation, a, b):
    node = nt.nodes.new('ShaderNodeMath')
    node.operation = operation
    for index, value in enumerate((a, b)):
        if isinstance(value, (int, float)):
            node.inputs[index].default_value = value
        else:
            nt.links.new(value, node.inputs[index])
    return node.outputs[0]


def _noise(nt, vector, scale, detail=3):
    node = nt.nodes.new('ShaderNodeTexNoise')
    node.inputs['Scale'].default_value = scale
    node.inputs['Detail'].default_value = detail
    nt.links.new(vector, node.inputs['Vector'])
    return node.outputs['Fac']


def _mix(nt, factor, a, b):
    node = nt.nodes.new('ShaderNodeMixRGB')
    nt.links.new(factor, node.inputs[0])
    for socket, value in zip(node.inputs[1:], (a, b)):
        if isinstance(value, tuple):
            socket.default_value = (*value, 1)
        else:
            nt.links.new(value, socket)
    return node.outputs[0]


def _field(nt, name):
    node = nt.nodes.new('ShaderNodeAttribute')
    node.attribute_name = name
    return node.outputs['Fac']


def _materials(surface, linear_keys, start, end):
    sand = surface(PREFIX + ' wet sand and gravel', (.18, .16, .12), .65)
    nt = sand.node_tree
    bsdf = nt.nodes['Principled BSDF']
    coord = nt.nodes.new('ShaderNodeTexCoord').outputs['Object']
    patch = _noise(nt, coord, .43)
    gravel = _ramp(nt, patch, [(.58, (0, 0, 0)), (.8, (.6, .6, .6))])
    sand_color = _ramp(nt, _noise(nt, coord, 4), [(.18, (.16, .12, .065)), (.8, (.36, .27, .14))])
    stones = nt.nodes.new('ShaderNodeTexVoronoi')
    stones.inputs['Scale'].default_value = 17
    nt.links.new(coord, stones.inputs['Vector'])
    stone_color = _ramp(nt, stones.outputs['Distance'], [(.10, (.28, .30, .27)), (.65, (.065, .078, .075))])
    dry = _mix(nt, gravel, sand_color, stone_color)
    scrub=_ramp(nt,_noise(nt,coord,.32),[(.2,(.018,.036,.012)),(.8,(.09,.12,.035))])
    terrain_color=nt.nodes.new('ShaderNodeMixRGB')
    nt.links.new(_field(nt,'coast_scrub'),terrain_color.inputs[0]);nt.links.new(dry,terrain_color.inputs[1]);nt.links.new(scrub,terrain_color.inputs[2])
    dry=terrain_color.outputs[0]
    wet = _field(nt, 'coast_wet')
    nt.links.new(_mix(nt, wet, dry, (.045, .060, .055)), bsdf.inputs['Base Color'])
    nt.links.new(_math(nt, 'SUBTRACT', .82, _math(nt, 'MULTIPLY', wet, .56)), bsdf.inputs['Roughness'])
    fine = nt.nodes.new('ShaderNodeBump')
    fine.inputs['Strength'].default_value = .28
    fine.inputs['Distance'].default_value = .018
    nt.links.new(_noise(nt, coord, 110, 2), fine.inputs['Height'])
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .5
    bump.inputs['Distance'].default_value = .075
    nt.links.new(_math(nt, 'MULTIPLY', stones.outputs['Distance'], gravel), bump.inputs['Height'])
    nt.links.new(fine.outputs['Normal'], bump.inputs['Normal'])
    nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

    sea = surface(PREFIX + ' sea and broken surf', (.014, .065, .085), .24, .08)
    nt = sea.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['IOR'].default_value = 1.333
    coord = nt.nodes.new('ShaderNodeTexCoord').outputs['Object']
    mapping = nt.nodes.new('ShaderNodeMapping')
    nt.links.new(coord, mapping.inputs['Vector'])
    for frame, location in ((start, (0, 0, 0)), (end, (2.4, -3.8, 0))):
        mapping.inputs['Location'].default_value = location
        mapping.inputs['Location'].keyframe_insert('default_value', frame=frame)
    linear_keys(nt.animation_data.action)
    flowing = mapping.outputs['Vector']
    broad = _noise(nt, flowing, .8)
    fine = _noise(nt, flowing, 7, 2)
    distance = _field(nt, 'coast_distance')
    # Мягкий, искривлённый фронт прибоя внутри самого материала воды.
    # Ни отдельных белых полос, ни альфа-плоскостей, ни корабельных следов.
    shifted = _math(nt, 'ADD', distance, _math(nt, 'MULTIPLY', broad, 1.2))
    band = _ramp(nt, _math(nt, 'MULTIPLY', _math(nt, 'ABSOLUTE', shifted, 0), .65),
                 [(0, (1, 1, 1)), (.75, (0, 0, 0))])
    islands = _ramp(nt, _math(nt, 'MULTIPLY', broad, fine),
                    [(.17, (0, 0, 0)), (.39, (.85, .85, .85))])
    foam = _math(nt, 'MULTIPLY', band, islands)
    shallows = _ramp(nt, _math(nt, 'ADD', _math(nt, 'MULTIPLY', distance, .12), 1),
                     [(0, (.009, .036, .055)), (1, (.038, .16, .17))])
    nt.links.new(_mix(nt, foam, shallows, (.52, .66, .63)), bsdf.inputs['Base Color'])
    nt.links.new(_math(nt, 'ADD', .23, _math(nt, 'MULTIPLY', foam, .46)), bsdf.inputs['Roughness'])
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .38
    bump.inputs['Distance'].default_value = .09
    nt.links.new(_math(nt, 'ADD', broad, _math(nt, 'MULTIPLY', fine, .18)), bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    return sand, sea


def _terrain(sand, sea, start, fps):
    # Неравномерная сетка: плотная у воды и боя, редкая за рабочими планами.
    xs = sorted(set([-240, -180, -130, -100, -80] + list(range(-64, 65)) + [80, 100, 130, 180, 240]))
    rows = [-15, -10, -6, -4, -2, -1, -.5, 0, .2, .4, .6, .8, 1]
    land_y = [-5 + j * .5 for j in range(61)] + list(range(27, 81, 2)) + [90, 110, 140, 180, 240]
    vertices, wet = [], []
    for row in range(len(rows) + len(land_y)):
        for x in xs:
            edge = _edge(x)
            if row < len(rows):
                u = rows[row]
                y = edge + u if u <= 0 else edge + u * (-5 - edge)
            else:
                y = land_y[row - len(rows)]
            vertices.append((x, y, _height(x, y)))
            wet.append(1 - _smooth((y - edge - .15) / 3.4))
    # Последняя интерполированная строка уже y=-5; убрать дубликат.
    offset = len(rows) * len(xs)
    del vertices[offset:offset + len(xs)]
    del wet[offset:offset + len(xs)]
    shore = _mesh('Shore', vertices, _faces(len(xs), len(vertices) // len(xs)), sand)
    _attribute(shore.data, 'coast_wet', wet)
    _attribute(shore.data, 'coast_scrub', [_smooth((y-19+2*math.sin(x*.19))/18) for x,y,z in vertices])

    offsets = [-320, -240, -180, -140, -110, -90, -75]
    offsets += [-65 + j * .65 for j in range(96)]
    offsets += [-2.6 + j * .13 for j in range(33)]
    offsets = sorted(set(offsets))
    vertices = [(x, _edge(x) + d, -.7) for d in offsets for x in xs]
    ocean = _mesh('Ocean', vertices, _faces(len(xs), len(offsets)), sea)
    _attribute(ocean.data, 'coast_distance', [d for d in offsets for _ in xs])
    ocean.shape_key_add(name='Basis')
    # Четыре независимых базиса дают бегущие волны, а не вертикальный пульс.
    # Значения ключей 0..1: базис содержит противоположный полусдвиг.
    for index, (kx, ky, amplitude, period) in enumerate(((.38, .68, .055, 4.8), (-.61, .32, .032, 3.1))):
        for trig, phase in ((math.sin, 0), (math.cos, math.pi / 2)):
            key = ocean.shape_key_add(name=f'Swell {index} {trig.__name__}')
            for i, (x, y, _) in enumerate(vertices):
                taper = .35 + .65 * _smooth((_edge(x) - y) / 5)
                delta = amplitude * taper * trig(kx * x + ky * y)
                key.data[i].co.z += 2 * delta
                # Каждый ключ относителен к исходной плоскости; общий базис
                # вычитается ниже, после построения всех ключей.
            key.driver_add('value').driver.expression = (
                f'0.5+0.5*sin((frame-{start})*{2 * math.pi / (fps * period):.12f}+{phase:.12f})')
    basis = ocean.data.shape_keys.key_blocks[0]
    for i in range(len(vertices)):
        shift = sum((key.data[i].co.z + .7) / 2 for key in ocean.data.shape_keys.key_blocks[1:])
        for key in ocean.data.shape_keys.key_blocks:
            key.data[i].co.z -= shift
    return shore, ocean


def _rocks(helpers):
    import bpy
    from mathutils import Matrix, Vector
    imp, fix = helpers()
    imported, _ = imp(str(ROCK))
    fix(imported)
    sources = [obj for obj in imported if obj.type == 'MESH']
    if not sources:
        raise ValueError('Rock GLB contains no mesh')
    bpy.context.view_layer.update()
    points = [obj.matrix_world @ vertex.co for obj in sources for vertex in obj.data.vertices]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low + high) / 2
    width = max(high.x - low.x, high.y - low.y)
    if width < .001:
        raise ValueError('Rock GLB has degenerate bounds')
    meshes = []
    for obj in sources:
        mesh = obj.data.copy()
        mesh.transform(Matrix.Translation(-center) @ obj.matrix_world)
        meshes.append(mesh)
    # Силуэты групп: низкая передняя кромка, средние выступы, дальние мысы.
    # Центральный коридор моря |x|<36 и вся площадка остаются свободными.
    groups = [(-48, -13, 9, .15), (53, -5, 12, -.6),
              (-32, 30, 14, .4), (37, 34, 17, -.3),
              (-62, 58, 29, .2), (-29, 77, 23, -.7),
              (30, 88, 32, .6), (78, 72, 38, -.2), (-104, 115, 44, .35)]
    result = []
    for group, (gx, gy, span, angle) in enumerate(groups):
        for part, (dx, dy, size, turn, flatten) in enumerate(((0, 0, 1, 0, .92), (-.42, -.19, .46, 1.9, .63), (.37, .22, .61, -1.1, .8))):
            root = bpy.data.objects.new(f'{PREFIX} Rock {group:02d}-{part}', None)
            bpy.context.scene.collection.objects.link(root)
            scale = span * size / width
            root.scale = (scale, scale, scale * flatten * .43)
            root.rotation_euler = (.06 * math.sin(group + part), .08 * math.cos(group - part), angle + turn)
            x, y = gx + dx * span, gy + dy * span
            local_points = [root.rotation_euler.to_matrix() @ Vector((p.x * scale, p.y * scale, p.z * scale * flatten * .43)) for mesh in meshes for p in (v.co for v in mesh.vertices)]
            # Разместить по реальному низу, затем слегка заглубить в склон.
            min_z = min(p.z for p in local_points)
            root.location = (x, y, _height(x, y) - min_z - span * .045)
            for mesh in meshes:
                obj = bpy.data.objects.new(root.name + ' mesh', mesh)
                bpy.context.scene.collection.objects.link(obj)
                obj.parent = root
                result.append(obj)
            if y < 24:
                if not all(abs(x + p.x) > 36 for p in local_points):
                    raise ValueError(f'Rock intrudes into fleet corridor: group={group}, part={part}, x={x}, range={[min(p.x for p in local_points),max(p.x for p in local_points)]}, bounds={tuple(high-low)}')
    # Удаляются только объекты этого импорта, не чужие коллекции/материалы.
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    return result


def _trees(helpers):
    """Dota coastal forest ties the distant terrain together and supplies a scale cue."""
    import bpy
    import random
    from mathutils import Matrix,Vector
    imp,fix=helpers();rng=random.Random(630)
    models=['models_props_tree_tree_pine_01_sfm.glb','models_props_tree_tree_oak_01_sfm.glb']
    for kind,name in enumerate(models):
        imported,_=imp(str(ROOT/'_game/models/render'/name));fix(imported)
        objects=[o for o in imported if o.type=='MESH'];bpy.context.view_layer.update()
        points=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
        lo=Vector([min(p[i] for p in points) for i in range(3)]);hi=Vector([max(p[i] for p in points) for i in range(3)])
        origin=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));meshes=[]
        for o in objects:
            mesh=o.data.copy();mesh.transform(Matrix.Translation(-origin)@o.matrix_world);meshes.append(mesh)
        for i in range(15):
            x=-72+i*10+rng.uniform(-4,4);y=44+kind*19+rng.uniform(-7,7)
            height=rng.uniform(13,23);scale=height/(hi.z-lo.z)
            root=bpy.data.objects.new(f'{PREFIX} Tree {kind}-{i}',None);bpy.context.scene.collection.objects.link(root)
            root.location=(x,y,_height(x,y)-.1);root.scale=(scale,)*3;root.rotation_euler.z=rng.random()*math.tau
            for mesh in meshes:
                o=bpy.data.objects.new(root.name+' mesh',mesh);bpy.context.scene.collection.objects.link(o);o.parent=root
        for o in imported:bpy.data.objects.remove(o,do_unlink=True)


def environment():
    """Создать берег один раз в сцене сборщика; вернуть объекты для проверки.

    Не удаляет прежнее окружение: заменить вызов при чистой сборке.
    При смене постановки проверить камеры, мокрый край, силуэт скал и свет кожи.
    """
    import bpy
    import importlib.util
    if bpy.data.objects.get(PREFIX + ' Shore'):
        raise RuntimeError('FleetCoast already exists; rebuild from the asset scene')
    if not ROCK.is_file():
        raise FileNotFoundError(ROCK)
    spec = importlib.util.spec_from_file_location('_fleet_coast_helpers', ROOT / 'tools/blender/kunkka_ghostship.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    scene = bpy.context.scene
    start, end = scene.frame_start, max(scene.frame_start + 1, scene.frame_end)
    fps = scene.render.fps / scene.render.fps_base
    sand, sea = _materials(helper.surface, helper.linear_keys, start, end)
    shore, ocean = _terrain(sand, sea, start, fps)
    rocks = _rocks(helper.helpers)
    _trees(helper.helpers)
    world = bpy.data.worlds.new(PREFIX + ' cool sky')
    world.use_nodes = True
    # Same dome projection used by render_scene.py for the accepted Dota sky.
    nt=world.node_tree
    direction=nt.nodes.new('ShaderNodeTexCoord').outputs['Generated']
    split=nt.nodes.new('ShaderNodeSeparateXYZ');nt.links.new(direction,split.inputs[0])
    denominator=_math(nt,'ADD',split.outputs['Z'],.35)
    uv=nt.nodes.new('ShaderNodeCombineXYZ')
    for axis in ('X','Y'):
        nt.links.new(_math(nt,'ADD',_math(nt,'MULTIPLY',_math(nt,'DIVIDE',split.outputs[axis],denominator),.32),.5),uv.inputs[axis])
    sky=ROOT/'_game/sky/sky_dota_002_psd_8ad2c9bb_up.png'
    if not sky.is_file():raise FileNotFoundError(sky)
    tex=nt.nodes.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(sky),check_existing=True);tex.extension='MIRROR'
    nt.links.new(uv.outputs[0],tex.inputs['Vector'])
    gradient=_ramp(nt,split.outputs['Z'],[(0,(.12,.22,.30)),(.45,(.035,.09,.18))])
    blend=nt.nodes.new('ShaderNodeMapRange');blend.inputs['From Min'].default_value=.015;blend.inputs['From Max'].default_value=.18
    nt.links.new(split.outputs['Z'],blend.inputs['Value'])
    mix=nt.nodes.new('ShaderNodeMixRGB');nt.links.new(blend.outputs['Result'],mix.inputs[0]);nt.links.new(gradient,mix.inputs[1]);nt.links.new(tex.outputs['Color'],mix.inputs[2])
    nt.links.new(mix.outputs[0],nt.nodes['Background'].inputs['Color'])
    nt.nodes['Background'].inputs['Strength'].default_value=.7
    scene.world = world
    data = bpy.data.lights.new(PREFIX + ' warm side sun', 'SUN')
    data.energy = 2.1
    data.angle = .12
    data.color = (1, .86, .68)
    sun = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(sun)
    sun.location = (-65, -20, 34)
    helper.aim(sun, (0, 8, 0))
    helper.light(PREFIX + ' cool sky fill', (20, -12, 32), 14500, (.55, .73, 1), 38, (0, 7, 3))
    helper.light(PREFIX + ' fleet fill', (0, -55, 25), 10500, (.62, .8, 1), 40, (0, -35, 2))
    helper.light(PREFIX + ' pale back edge', (-16, 40, 25), 6500, (.72, .86, 1), 22, (0, 10, 4))
    return {'shore': shore, 'ocean': ocean, 'rocks': rocks, 'world': world}
