"""A reusable interior for dialogue with packed set assets."""

from pathlib import Path
import os

import bpy
from mathutils import Vector


RESOURCES = Path(os.environ.get("A8_RESOURCES", Path(__file__).resolve().parents[2] / "cache/resources"))
TAVERN = RESOURCES / "sets/tavern-crownfall.glb"


def surface(name, color):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = .7
    return material


def area(scene, name, origin, target, watts, size, color, *, shadows=True):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size, data.color = watts, "DISK", size, color
    data.use_shadow = shadows
    lamp = bpy.data.objects.new(name, data)
    scene.collection.objects.link(lamp)
    lamp.location = origin
    lamp.rotation_euler = (Vector(target) - lamp.location).to_track_quat("-Z", "Y").to_euler()


def dress(scene, ground, set_name, palette):
    tavern = set_name == "tavern"
    for light in tuple(scene.objects):
        if light.type == "LIGHT":
            bpy.data.objects.remove(light, do_unlink=True)
    for node in scene.world.node_tree.nodes:
        if node.type == "BACKGROUND":
            node.inputs["Strength"].default_value = .105 if tavern else .14
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast" if tavern else "None"
    scene.view_settings.exposure = -.52 if tavern else -.22
    scene.render.film_transparent = False
    if tavern:
        bpy.data.objects.remove(ground, do_unlink=True)
        bpy.ops.import_scene.gltf(filepath=str(TAVERN))
        area(scene, "Bar lantern bounce", (4.15, -16.71, 5.4), (3.39, -15.08, 1), 1000, 5, (1, .68, .39), shadows=False)
        area(scene, "Window bounce", (10.98, -17.16, 6), (8.05, -13.23, 1.7), 1600, 6, (.64, .8, 1), shadows=False)
        area(scene, "Back wall fill", (8.67, -15.04, 7.7), (11, -19.58, 4.3), 1250, 7, (1, .77, .53), shadows=False)
    else:
        ground.data.materials.clear()
        ground.data.materials.append(surface("Slate", (.075, .09, .115)))
        bpy.ops.mesh.primitive_cube_add(size=1, location=(7, 0, 4))
        wall = bpy.context.object
        wall.name, wall.dimensions = "Studio back", (.28, 75, 8)
        tone = tuple(max(.035, min(.32, channel)) for channel in palette[0]) if palette else (.14, .085, .065)
        wall.data.materials.append(surface("Studio wall", tone))
    fill = (.59, .74, 1)
    if palette and tavern:
        fill = tuple(.57 + .43 * max(0, min(1, channel)) ** .45 for channel in palette[0])
    area(scene, "Door bounce", (-4.2, -2.8, 5.3), (0, 0, 2.4), 1120 if tavern else 1850, 4.8, (1, .81, .64))
    area(scene, "Cold ambient", (-1.3, 4, 5.5), (0, 0, 2.9), 285 if tavern else 650, 4.2, fill)
