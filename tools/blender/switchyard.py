"""Self-contained storyboard, geometry and sound for the switchyard exercise."""

import argparse
from array import array
import json
import math
from pathlib import Path
import sys
import wave

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from beacon_preview import area, box, camera, finish, material


FPS, END, CUT = 30, 61, 30
SIZE = (480, 270)
GAUGE, AXLE_Z = .46, .294
START, SPEED, BRANCH, HALF_AXLES = -2.85, .103, -.55, .25
SWITCH_START, SWITCH_OPEN = 14, 20
CUES = ((SWITCH_OPEN, .10, 370), (30, .075, 260), (35, .07, 195))


def route(x):
    u = min(1., max(0., (x - BRANCH) / 2.25))
    y = 1.12 * u * u * (3 - 2 * u)
    angle = math.atan(1.12 * 6 * u * (1 - u) / 2.25)
    return Vector((x, y, AXLE_Z)), angle


def offset(position, angle, distance):
    return position + Vector((-math.sin(angle) * distance, math.cos(angle) * distance, 0))


def rail(name, points, coat):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions, data.bevel_depth, data.bevel_resolution = "3D", .026, 2
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, position in zip(spline.points, points):
        point.co = (*position, 1)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    data.materials.append(coat)


def empty(name):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    return obj


def cylinder(name, radius, depth, coat, parent, position):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth)
    obj = finish(bpy.context.object, name, coat, .006)
    obj.parent, obj.location = parent, position
    obj.rotation_euler.x = math.pi / 2
    return obj


def part(name, parent, position, size, coat):
    obj = box(name, (0, 0, 0), size, coat)
    obj.parent, obj.location = parent, position
    return obj


def build(out):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.fps, scene.frame_end = FPS, END - 1
    scene.world = bpy.data.worlds.new("Depot")
    scene.world.color = (.09, .12, .16)
    steel = material("Polished rail", (.25, .34, .38), .68, .28)
    dark = material("Track hardware", (.07, .10, .13), .27)
    ground = material("Depot concrete", (.045, .07, .085), roughness=.77)
    copper = material("Safety orange", (.72, .22, .045), .28)
    ivory = material("Pale marking", (.73, .76, .66), roughness=.48)
    teal = material("Cart enamel", (.045, .36, .40), .23)
    box("Floor", (0, .4, -.09), (100, 100, .18), ground, bevel=0)
    for index in range(18):
        x = -3 + index * .35
        point, angle = route(x)
        sleeper = box(f"Branch sleeper {index}", (point.x, point.y, .07), (.15, .78, .14), dark)
        sleeper.rotation_euler.z = angle
        if x > .45:
            box(f"Main sleeper {index}", (x, 0, .07), (.15, .72, .14), dark)
    for side in (-1, 1):
        points = []
        for index in range(121):
            x = -3.25 + index * .058
            point, angle = route(x)
            point.z = .18
            points.append(offset(point, angle, side * GAUGE / 2))
        rail(f"Running rail {side}", points, steel)
        rail(f"Dead-end rail {side}", ((-.26, side * GAUGE / 2, .18),
                                      (2.45, side * GAUGE / 2, .18)), steel)
    box("Buffer body", (2.47, 0, .31), (.34, .72, .44), copper)
    for y in (-.22, 0, .22):
        slash = box("Buffer warning stripe", (2.285, y, .34), (.025, .08, .27), dark, .006)
        slash.rotation_euler.x = -.38

    blade = box("Switch blade", (-.48, .20, .182), (.55, .040, .045), copper, .008)
    lever = box("Throw lever", (-.46, -.63, .24), (.34, .068, .08), copper)
    linkage = box("Switch linkage", (-.48, -.20, .104), (.055, .89, .036), steel)
    box("Lever mount", (-.46, -.63, .10), (.43, .25, .20), dark)
    for frame, swing in ((1, 0), (SWITCH_START, 0), (SWITCH_OPEN, 1), (END - 1, 1)):
        blade.rotation_euler.z = .14 * swing
        blade.location.y = .20 + .035 * swing
        lever.rotation_euler.y = .43 - .86 * swing
        linkage.location.y = -.20 + .022 * swing
        for obj, channel in ((blade, "rotation_euler"), (blade, "location"),
                             (lever, "rotation_euler"), (linkage, "location")):
            obj.keyframe_insert(channel, frame=frame)

    body = empty("Cart deck control")
    part("Deck", body, (0, 0, .085), (.81, .62, .10), teal)
    part("Cargo crate", body, (-.035, 0, .26), (.60, .47, .25), ivory)
    for x in (-.24, .18):
        part("Crate strap", body, (x, 0, .385), (.055, .49, .032), dark)
    part("Front identification", body, (.415, 0, .095), (.026, .23, .055), ivory)
    bogies, wheels = [], []
    for label in ("Front", "Rear"):
        bogie = empty(f"{label} axle")
        bogies.append(bogie)
        for side in (-1, 1):
            wheel = empty(f"{label} wheel control {side}")
            wheel.parent, wheel.location = bogie, (0, side * GAUGE / 2, 0)
            cylinder(f"{label} wheel", .088, .064, dark, wheel, (0, 0, 0))
            cylinder(f"{label} hub", .041, .018, steel, wheel, (0, side * .040, 0))
            part("Wheel witness mark", wheel, (.055, side * .037, 0), (.018, .012, .018), ivory)
            wheels.append(wheel)
    previous = [None] * len(wheels)
    travel = [0.] * len(wheels)
    for frame in range(1, END):
        x = START + SPEED * (frame - 1)
        front, rear = (route(x + shift) for shift in (HALF_AXLES, -HALF_AXLES))
        body.location = (front[0] + rear[0]) / 2
        tangent = front[0] - rear[0]
        body.rotation_euler.z = math.atan2(tangent.y, tangent.x)
        for bogie, (point, angle) in zip(bogies, (front, rear)):
            bogie.location, bogie.rotation_euler.z = point, angle
        for index, wheel in enumerate(wheels):
            point, angle = (front, rear)[index // 2]
            world = offset(point, angle, wheel.location.y)
            if previous[index] is not None:
                travel[index] += (world - previous[index]).length
            previous[index] = world
            wheel.rotation_euler.y = travel[index] / .088
            wheel.keyframe_insert("rotation_euler", frame=frame)
        for obj in (body, *bogies):
            obj.keyframe_insert("location", frame=frame)
            obj.keyframe_insert("rotation_euler", frame=frame)

    camera(scene, "Overview", (-1.1, -6.0, 5.7), (-.24, .42, .16), 41, 1)
    camera(scene, "Turn", (1.1, -5.4, 4.4), (1.32, .42, .18), 40, CUT)
    camera(scene, "Low turn", (1.75, -5.6, 2.58), (1.34, .45, .27), 43, CUT)
    # The alternative is selected by the revision job, never by a timeline marker.
    scene.timeline_markers.remove(scene.timeline_markers.get("Low turn"))
    area("Key", (-3, -3, 6), (0, 0, 0), 920, 5, (1, .82, .68))
    area("Fill", (1, 4, 5), (0, .5, 0), 1250, 4, (.61, .81, 1))
    area("Rail rim", (4, -2, 3), (1, .5, .2), 420, 2, (1, .92, .76))
    extents = {}
    for name, frames in (("Overview", range(1, CUT)), ("Turn", range(CUT, END)),
                         ("Low turn", range(CUT, END))):
        border = 1.
        for frame in frames:
            scene.frame_set(frame)
            for vertex in bpy.data.objects["Cargo crate"].bound_box:
                world = bpy.data.objects["Cargo crate"].matrix_world @ Vector(vertex)
                p = world_to_camera_view(scene, bpy.data.objects[name], world)
                border = min(border, p.x, 1 - p.x, p.y, 1 - p.y)
        if border < .045:
            raise RuntimeError(f"Cargo leaves the safe composition of {name}: {border:.3f}")
        extents[name] = border
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "scene.blend"))
    return extents


def sound(path):
    rate = 48_000
    data = array("h")
    for index in range((END - 1) * rate // FPS):
        t = index / rate
        value = .021 * math.sin(2 * math.pi * 69 * t) * math.sin(math.pi * t / 2) ** 2
        for frame, duration, frequency in CUES:
            elapsed = t - (frame - 1) / FPS
            if 0 <= elapsed < duration:
                value += .34 * math.sin(2 * math.pi * frequency * elapsed) * math.sin(math.pi * elapsed / duration) ** 3
        data.append(round(value * 32767))
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(data.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    out = args.out.resolve()
    out.mkdir(parents=True)
    extents = build(out)
    sound(out / "sound.wav")
    entry = 1 + math.ceil((BRANCH - START - HALF_AXLES) / SPEED)
    if SWITCH_OPEN >= entry:
        raise RuntimeError("The front axle reaches the switch before it settles")
    job = dict(schema_version=1, scene="scene.blend", out="draft", size=list(SIZE), fps=FPS)
    files = {
        "job.json": dict(job, frames=[1, END], wav="sound.wav"),
        "insert.json": dict(job, out="insert", frames=[CUT, END], camera="Low turn"),
        "blocking.json": dict(cut_frame=CUT, switch_frames=[SWITCH_START, SWITCH_OPEN], front_axle_entry=entry,
                              cargo_minimum_frame_border=extents, sound_frames=[cue[0] for cue in CUES]),
    }
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
