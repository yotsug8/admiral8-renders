"""Turn the approved rail-barrier storyboard into an editable Blender job."""

import argparse
from array import array
import json
import math
from pathlib import Path
import sys
import wave

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from beacon_preview import area, box, camera, material
from switchyard import cylinder, empty, part, rail


def cart(steel, dark, teal, ivory):
    root = empty("Cart")
    deck = part("Cart deck", root, (0, 0, .28), (.94, .69, .14), teal)
    crate = part("Cargo", root, (-.03, 0, .54), (.67, .54, .40), ivory)
    for x in (-.21, .15):
        part("Cargo strap", root, (x, 0, .55), (.044, .56, .40), dark)
    wheels = []
    for x in (-.31, .31):
        for side in (-1, 1):
            wheel = empty("Wheel rotation")
            wheel.parent = root
            wheel.location = (x, side * .30, .174)
            cylinder("Tread", .116, .078, dark, wheel, (0, 0, 0))
            cylinder("Hub", .052, .018, steel, wheel, (0, side * .044, 0))
            part("Wheel pin", wheel, (.073, side * .048, 0), (.026, .017, .026), ivory)
            wheels.append(wheel)
    return root, deck, crate, wheels


def build(plan):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 12
    scene.render.fps = plan["fps"]
    scene.render.resolution_x, scene.render.resolution_y = plan["size"]
    scene.frame_start, scene.frame_end = 1, plan["stop"] - 1
    scene.world = bpy.data.worlds.new("Maintenance bay")
    scene.world.color = (.10, .13, .17)
    steel = material("Steel", (.24, .31, .35), .64, .33)
    dark = material("Fasteners", (.053, .072, .091), .30, .46)
    floor = material("Floor concrete", (.13, .17, .18), roughness=.75)
    copper = material("Barrier enamel", (.80, .26, .036), .13, .38)
    ivory = material("Cargo enamel", (.72, .70, .53), .06, .58)
    teal = material("Cart enamel", (.042, .32, .32), .27, .42)
    box("Floor", (0, 0, -.10), (22, 20, .20), floor, bevel=0)
    box("Back wall", (0, 2.20, 2.4), (24, .22, 4.9), floor)
    for x in range(-10, 11, 2):
        box("Wall seam", (x, 2.07, 2.4), (.048, .04, 4.9), dark)
    for x in range(-12, 13):
        box("Sleeper", (x * .34, 0, .016), (.18, .91, .032), dark)
    for side in (-1, 1):
        rail("Running rail", ((-5, side * .30, .032), (5, side * .30, .032)), steel)
    root, deck, crate, wheels = cart(steel, dark, teal, ivory)
    box("Barrier base", (0, .89, .06), (.41, .43, .12), dark)
    box("Barrier pedestal", (0, .89, .32), (.28, .27, .60), copper)
    arm = empty("Barrier hinge")
    arm.location = (0, .78, .60)
    beam = part("Barrier beam", arm, (0, -.80, 0), (.095, 1.63, .095), copper)
    for i in range(4):
        part("Reflective band", arm, (0, -.30 - .36 * i, .001), (.098, .113, .098), ivory)
    start, open_at, close_at, shut = plan["arm"]
    for f, angle in ((1, 0), (start, 0), (open_at, -61), (close_at, -61), (shut, 0)):
        arm.rotation_euler.x = math.radians(angle)
        arm.keyframe_insert("rotation_euler", frame=f)
    for f, x in ((1, -2.58), (scene.frame_end, 2.58)):
        root.location.x = x
        root.keyframe_insert("location", frame=f)
        for wheel in wheels:
            wheel.rotation_euler.y = (x + 2.58) / .116
            wheel.keyframe_insert("rotation_euler", frame=f)
    scene.frame_set(1)
    views = {
        "Approach": ((-3.35, -5.15, 3.70), (-.97, .13, .54), 38),
        "Crossing": ((2.9, -4.82, 3.07), (.04, .17, .78), 43),
        "Departure": ((4.2, -5.26, 3.37), (1.37, .15, .55), 40),
        "Wheel level": ((4.1, -3.1, .59), (.02, .21, .79), 35),
    }
    for shot in plan["shots"]:
        camera(scene, shot["camera"], *views[shot["camera"]], shot["start"])
    revision_camera = plan["revision"]["camera"]
    camera(scene, revision_camera, *views[revision_camera], 1)
    scene.timeline_markers.remove(scene.timeline_markers[revision_camera])
    area("Soft key", (-3, -4, 6), (0, 0, 0), 1150, 4.5, (1, .85, .70))
    area("Blue fill", (1, 1.4, 5), (0, 0, 0), 980, 3.6, (.66, .83, 1))
    area("Rail rim", (4, 1.2, 3.1), (0, 0, .1), 360, 2.4, (1, .94, .75))
    return scene, deck, crate, beam


def points(obj):
    return [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]


def surface(obj, vertices):
    return BVHTree.FromPolygons(vertices, [tuple(p.vertices) for p in obj.data.polygons])


def lowest_over_route(obj, vertices, y):
    heights = [p.z for p in vertices if p.y <= y]
    for edge in obj.data.edges:
        a, b = (vertices[i] for i in edge.vertices)
        if (a.y < y < b.y) or (b.y < y < a.y):
            heights.append(a.z + (b.z - a.z) * ((y - a.y) / (b.y - a.y)))
    if not heights:
        raise RuntimeError("The raised beam should remain above the cargo route")
    return min(heights)


def inspect(scene, plan, deck, crate, beam):
    minimum = 1.
    crossing = []
    for sample in range(4 * (scene.frame_end - 1) + 1):
        frame = 1 + sample / 4
        scene.frame_set(int(frame), subframe=frame % 1)
        payload, barrier = points(crate), points(beam)
        if surface(beam, barrier).overlap(surface(crate, payload)) or (
                surface(beam, barrier).overlap(surface(deck, points(deck)))):
            raise RuntimeError(f"Barrier intersects cart at frame {frame}")
        track_cart = points(deck)
        if min(p.x for p in track_cart) <= .05 and max(p.x for p in track_cart) >= -.05:
            crossing.append(frame)
            if not plan["arm"][1] <= frame <= plan["arm"][2]:
                raise RuntimeError(f"Barrier must stay open during crossing at frame {frame}")
            lowest = lowest_over_route(beam, barrier, max(p.y for p in track_cart))
            minimum = min(minimum, lowest - max(p.z for p in payload) - .01)
    if not crossing or minimum < .10:
        raise RuntimeError("Clearance must be visible above the passing cargo")

    shots = plan["shots"]
    edit = plan["revision"]
    spans = [(shot["camera"], shot["start"], following)
             for shot, following in zip(shots, [s["start"] for s in shots[1:]] + [plan["stop"]])]
    _, start, stop = spans[edit["shot"] - 1]
    spans.append((edit["camera"], start, stop))
    borders = {}
    for name, first, end in spans:
        view = scene.objects[name]
        border = 1.
        for frame in range(first, end):
            scene.frame_set(frame)
            for point in (*points(crate), *points(beam)):
                x, y, depth = world_to_camera_view(scene, view, point)
                border = min(border, x, 1 - x, y, 1 - y)
                if depth <= 0 or border < .015:
                    raise RuntimeError(f"Cargo or beam is clipped in {name} at frame {frame}: {border:.3f}")
        borders[name] = border
    return dict(crossing=[crossing[0], crossing[-1]], clearance_lower_bound=minimum,
                minimum_camera_borders=borders, geometry_samples=sample + 1)


def sound(path, plan):
    rate = 48_000
    fps = plan["fps"]
    duration = (plan["stop"] - 1) / fps
    start, opened, closing, closed = ((f - 1) / fps for f in plan["arm"])
    pcm = array("h")
    for sample in range(round(rate * duration)):
        t = sample / rate
        fade = min(1., t / .18, (duration - t) / .20)
        value = fade * .044 * (math.sin(2 * math.pi * 61 * t) + .28 * math.sin(2 * math.pi * 132 * t))
        for first, end in ((start, opened), (closing, closed)):
            if first <= t < end:
                value += .08 * math.sin(2 * math.pi * 154 * t) * math.sin(math.pi * (t - first) / (end - first))
        if 0 <= t - closed < .12:
            value += .20 * math.sin(2 * math.pi * 230 * (t - closed)) * (1 - (t - closed) / .12) ** 2
        pcm.append(round(value * 32767))
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(pcm.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True)
    scene, deck, crate, beam = build(plan)
    report = inspect(scene, plan, deck, crate, beam)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out / "scene.blend"))
    sound(args.out / "sound.wav", plan)
    shots, edit = plan["shots"], plan["revision"]
    first = shots[edit["shot"] - 1]["start"]
    stop = shots[edit["shot"]]["start"] if edit["shot"] < len(shots) else plan["stop"]
    job = dict(schema_version=1, scene="scene.blend", size=plan["size"], fps=plan["fps"])
    outputs = {
        "storyboard.json": plan,
        "checks.json": report,
        "job.json": dict(job, out="draft", frames=[1, plan["stop"]], wav="sound.wav"),
        "insert.json": dict(job, out="insert", frames=[first, stop], camera=edit["camera"]),
    }
    for name, value in outputs.items():
        (args.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
