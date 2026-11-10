"""Inspect evaluated Rain skin against the side of a local cylindrical handle."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from doomsday_weapon_clearance import _surface


REGIONS = ("Hand", "Index", "Middle", "Ring", "Pinky", "Thumb")


def hand_groups(skin, side):
    return {
        group.index: next((name for name in REGIONS if group.name[4:].startswith(name)), None)
        for group in skin.vertex_groups
        if group.name.startswith("DEF-") and group.name.endswith(f".{side}")
    }


def handle_size(handle):
    return (max(math.hypot(v.co.x, v.co.y) for v in handle.data.vertices),
            max(abs(v.co.z) for v in handle.data.vertices))


def inspect_sample(frame, surface, groups, inverse, shaft, size):
    radius, half_length = size
    nearest = {}
    minimum = math.inf
    for vertex, weights in zip(surface["points"], surface["weights"], strict=True):
        hand = [(weight, group) for group, weight in weights if groups.get(group) and weight >= .35]
        if not hand:
            continue
        region = groups[max(hand, key=lambda pair: pair[0])[1]]
        point = inverse @ vertex
        if abs(point.z) >= half_length - .003:
            continue
        gap = math.hypot(point.x, point.y) - radius
        minimum = min(minimum, gap)
        if region not in nearest or gap < nearest[region]["gap_m"]:
            nearest[region] = dict(gap_m=gap, angle_deg=math.degrees(math.atan2(point.y, point.x)))
    row = dict(frame=frame, regions=nearest, min_side_gap_m=minimum, failures=[],
               surface_pairs=len(shaft.overlap(surface["tree"])))
    if row["surface_pairs"]:
        row["failures"].append("skin and shaft surfaces intersect")
    if any(name not in nearest or nearest[name]["gap_m"] > .002 for name in REGIONS):
        row["failures"].append("missing palm or finger contact")
    if minimum < -.0005:
        row["failures"].append("skin enters the shaft")
    if all(name in nearest for name in ("Thumb", "Index", "Middle", "Ring")):
        thumb = nearest["Thumb"]["angle_deg"]
        opposition = min(abs((thumb - nearest[name]["angle_deg"] + 180) % 360 - 180)
                         for name in ("Index", "Middle", "Ring"))
        row["opposition_deg"] = opposition
        if opposition < 85:
            row["failures"].append("thumb and fingers touch the same side")
    return row


def inspect(scene, skin, handle, frames, side):
    size = handle_size(handle)
    groups = hand_groups(skin, side)
    rows = []
    for frame in frames:
        scene.frame_set(int(frame), subframe=frame % 1)
        graph = bpy.context.evaluated_depsgraph_get()
        inverse = handle.evaluated_get(graph).matrix_world.inverted()
        shaft = _surface(handle, graph, False, False)["tree"]
        rows.append(inspect_sample(frame, _surface(skin, graph, False, False), groups, inverse, shaft, size))
    return dict(rows=rows, passed=all(not row["failures"] for row in rows))


def hand_tree(surface, groups):
    vertices = {i for i, weights in enumerate(surface["weights"])
                if any(groups.get(group) and weight >= .35 for group, weight in weights)}
    faces = [face for face in surface["triangles"] if all(vertex in vertices for vertex in face)]
    if not faces:
        raise ValueError("No evaluated hand surface")
    indices = sorted({vertex for face in faces for vertex in face})
    remap = {vertex: index for index, vertex in enumerate(indices)}
    points = [surface["points"][index] for index in indices]
    return BVHTree.FromPolygons(points, [tuple(remap[v] for v in face) for face in faces], all_triangles=True)


def transfer_phases(giver, receiver):
    phases = []
    labels = {(True, False): "giver", (True, True): "both", (False, True): "receiver", (False, False): "none"}
    for a, b in zip(giver, receiver, strict=True):
        phase = labels[not a["failures"], not b["failures"]]
        if not phases or phases[-1]["phase"] != phase:
            phases.append(dict(frame=a["frame"], phase=phase))
    return phases


def inspect_transfer(scene, frames):
    baton = scene.objects["Light baton"]
    giver_skin, receiver_skin = (scene.objects[name] for name in ("GEO-rain-body", "GEO-rain-body.001"))
    size = handle_size(baton)
    groups = hand_groups(giver_skin, "R"), hand_groups(receiver_skin, "L")
    giver, receiver, crossing = [], [], []
    for frame in frames:
        scene.frame_set(int(frame), subframe=frame % 1)
        graph = bpy.context.evaluated_depsgraph_get()
        inverse = baton.evaluated_get(graph).matrix_world.inverted()
        shaft = _surface(baton, graph, False, False)["tree"]
        a, b = (_surface(skin, graph, False, False) for skin in (giver_skin, receiver_skin))
        giver.append(inspect_sample(frame, a, groups[0], inverse, shaft, size))
        receiver.append(inspect_sample(frame, b, groups[1], inverse, shaft, size))
        pairs = hand_tree(a, groups[0]).overlap(hand_tree(b, groups[1]))
        if pairs:
            crossing.append(dict(frame=frame, surface_pairs=len(pairs)))
    phases = transfer_phases(giver, receiver)
    unsupported = [a["frame"] for a, b in zip(giver, receiver) if a["failures"] and b["failures"]]
    dual = [a["frame"] for a, b in zip(giver, receiver) if not a["failures"] and not b["failures"]]
    collisions = [
        (name, row["frame"]) for name, rows in (("giver", giver), ("receiver", receiver))
        for row in rows if row["surface_pairs"] or row["min_side_gap_m"] < -.0005
    ]
    starts_with_giver = not giver[0]["failures"] and bool(receiver[0]["failures"])
    ends_with_receiver = bool(giver[-1]["failures"]) and not receiver[-1]["failures"]
    ordered = [row["phase"] for row in phases] == ["giver", "both", "receiver"]
    passed = not collisions and not crossing and ordered
    return dict(giver=giver, receiver=receiver, unsupported=unsupported, dual=dual,
                collisions=collisions, starts_with_giver=starts_with_giver,
                ends_with_receiver=ends_with_receiver, phases=phases, ordered=ordered,
                hand_collisions=crossing, passed=passed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handle", default="Case handle")
    parser.add_argument("--body", default="GEO-rain-body")
    parser.add_argument("--frames", required=True, help="Inclusive start and exclusive end, e.g. 53:180")
    parser.add_argument("--side", choices=("L", "R"), default="R")
    parser.add_argument("--transfer", action="store_true",
                        help="Check continuous support in the Rain baton handoff, including half frames")
    parser.add_argument("--substeps", choices=(2, 4), default=2, type=int, help="Samples per frame for --transfer")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    first, stop = map(int, args.frames.split(":"))
    if first >= stop:
        parser.error("Empty frame range")
    scene = bpy.context.scene
    if args.transfer:
        if first < scene.frame_start or stop - 1 > scene.frame_end:
            parser.error("Transfer range is outside the scene")
        step = args.substeps
        frames = [index / step for index in range(first * step, (stop - 1) * step + 1)]
        report = inspect_transfer(scene, frames)
        print(f"Baton transfer: {len(frames)} samples, {len(report['unsupported'])} unsupported, "
              f"{len(report['collisions'])} shaft collisions, {len(report['hand_collisions'])} hand collisions, "
              f"{len(report['dual'])} dual support, ordered: {report['ordered']}.")
    else:
        report = inspect(scene, bpy.data.objects[args.body],
                         bpy.data.objects[args.handle], range(first, stop), args.side)
        failures = sum(bool(row["failures"]) for row in report["rows"])
        print(f"Handle contact: {stop-first} frames, {failures} failed.")
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["passed"]:
        raise RuntimeError("Handle contact did not pass")


if __name__ == "__main__":
    main()
