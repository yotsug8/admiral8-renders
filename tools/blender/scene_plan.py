"""Build an editable local Blender scene from a declarative shot plan."""

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
from beacon_preview import aim, area, box, camera, finish, material, sphere


def validate(plan):
    required = {"schema_version", "request", "size", "fps", "frames", "materials",
                "objects", "shots", "lights"}
    if (not isinstance(plan, dict) or not required <= plan.keys()
            or plan.keys() - required - {"checks", "cues", "glows"}
            or type(plan["schema_version"]) is not int or plan["schema_version"] != 1
            or not isinstance(plan["request"], str) or not plan["request"].strip()):
        raise ValueError("Expected a version 1 plan with its original request")
    size, fps, count = plan["size"], plan["fps"], plan["frames"]
    if (len(size) != 2 or any(type(v) is not int or v % 2 or not 64 <= v <= 1920 for v in size)
            or type(fps) is not int or not 1 <= fps <= 60
            or type(count) is not int or not 2 <= count <= 600):
        raise ValueError("Expected an even draft size, 1–60 FPS and up to 600 frames")
    names = [row["name"] for row in plan["objects"]] + [row["name"] for row in plan["shots"]]
    if (len(names) != len(set(names)) or len(names) > 100
            or any(not isinstance(name, str) or not name.strip() or len(name.encode()) > 60 for name in names)):
        raise ValueError("Object and camera names must be unique and limited to 100")
    starts = [shot["frame"] for shot in plan["shots"]]
    if not starts or starts[0] != 1 or starts != sorted(set(starts)) or starts[-1] > count:
        raise ValueError("Shots must begin at frame 1 in increasing order")


def build_object(row, coats, count):
    kind, name = row["kind"], row["name"]
    pos, size = row["position"], row["size"]
    if (len(pos) != 3 or not all(math.isfinite(v) for v in pos)
            or len(size) != 3 or not all(math.isfinite(v) and v > 0 for v in size)):
        raise ValueError(f"Invalid position or size on {name}")
    coat = coats[row["material"]]
    if kind == "box":
        obj = box(name, pos, size, coat, bevel=row.get("bevel", .02))
    elif kind == "sphere":
        if size[0] != size[1] or size[0] != size[2]:
            raise ValueError(f"Sphere axes must be equal on {name}")
        obj = sphere(name, pos, size[0] / 2, coat)
    elif kind in ("cylinder", "ico"):
        if kind == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(vertices=48, location=pos)
        else:
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1, location=pos)
        obj = bpy.context.object
        obj.dimensions = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        finish(obj, name, coat)
    else:
        raise ValueError(f"Unsupported primitive: {kind}")
    obj.rotation_euler = [math.radians(angle) for angle in row.get("rotation", (0, 0, 0))]
    for channel, key, scale in (("location", "positions", 1), ("rotation_euler", "rotations", math.pi / 180)):
        keys = row.get(key, [])
        times = [f for f, _ in keys]
        if times and (times != sorted(set(times)) or not 1 <= times[0] <= times[-1] <= count):
            raise ValueError(f"Invalid key range on {name}")
        for frame, values in keys:
            setattr(obj, channel, [v * scale for v in values])
            obj.keyframe_insert(channel, frame=frame)
    return obj


def build(plan):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x, scene.render.resolution_y = plan["size"]
    scene.render.fps, scene.frame_end = plan["fps"], plan["frames"]
    scene.world = bpy.data.worlds.new("Studio")
    scene.world.color = (.07, .095, .13)
    coats = {}
    for name, row in plan["materials"].items():
        coat = material(name, row["rgb"], row.get("metal", 0), row.get("roughness", .4))
        if row.get("emission"):
            shader = coat.node_tree.nodes["Principled BSDF"]
            shader.inputs["Emission Color"].default_value = (*row["rgb"], 1)
            shader.inputs["Emission Strength"].default_value = row["emission"]
        coats[name] = coat
    for row in plan["objects"]:
        build_object(row, coats, plan["frames"])
    for shot in plan["shots"]:
        name, frame = shot["name"], shot["frame"]
        camera(scene, name, shot["position"], shot["target"], shot["lens"], frame)
        if "move" in shot:
            set_camera(scene.objects[name], shot, plan["frames"])
    for index, (position, target, power, size, color) in enumerate(plan["lights"], 1):
        area(f"Studio light {index}", position, target, power, size, color)
    for index, row in enumerate(plan.get("glows", []), 1):
        lamp = bpy.data.lights.new(f"Attached glow {index}", "POINT")
        lamp.energy, lamp.color = row["power"], row["rgb"]
        lamp.shadow_soft_size = row["radius"]
        obj = bpy.data.objects.new(lamp.name, lamp)
        scene.collection.objects.link(obj)
        obj.parent = scene.objects[row["object"]]
        obj.location = row["offset"]
    return scene


def set_camera(cam, shot, count):
    frame = shot["frame"]
    cam.location = shot["position"]
    aim(cam, shot["target"])
    if "move" not in shot:
        return
    cam.keyframe_insert("location", frame=frame)
    cam.keyframe_insert("rotation_euler", frame=frame)
    end, position = shot["move"]
    if not frame < end <= count:
        raise ValueError(f"Invalid camera move for {cam.name}")
    cam.location = position
    aim(cam, shot["target"])
    cam.keyframe_insert("location", frame=end)
    cam.keyframe_insert("rotation_euler", frame=end)


def check_saved_timeline(scene, plan):
    if (scene.frame_start != 1 or scene.frame_end != plan["frames"]
            or scene.render.fps != plan["fps"] or scene.render.fps_base != 1
            or [scene.render.resolution_x, scene.render.resolution_y] != plan["size"]
            or sorted((mark.frame, mark.camera.name) for mark in scene.timeline_markers if mark.camera)
            != [(shot["frame"], shot["name"]) for shot in plan["shots"]]):
        raise ValueError("Saved scene and edit plan have different timelines")


def edit_camera(scene, plan, name, factor):
    check_saved_timeline(scene, plan)
    shot = next(item for item in plan["shots"] if item["name"] == name)
    cam = scene.objects[name]
    if cam.type != "CAMERA" or abs(cam.data.lens - shot["lens"]) > .0001:
        raise ValueError("Saved camera differs from the plan")
    target = Vector(shot["target"])
    keys = [(shot["frame"], shot["position"])]
    if "move" in shot:
        keys.append(shot["move"])
    for frame, position in keys:
        scene.frame_set(frame)
        expected = target + (Vector(position) - target) / factor
        direction = (target - expected).to_track_quat("-Z", "Y")
        if (cam.location - expected).length > .0001 or abs(cam.rotation_euler.to_quaternion().dot(direction)) < .999999:
            raise ValueError(f"Saved camera position or target differs from the plan at frame {frame}")
    cam.animation_data_clear()
    set_camera(cam, shot, plan["frames"])
    return inspect(scene, plan)


def edit_light(scene, plan, name, index, factor):
    from contact_reaction import _curves

    check_saved_timeline(scene, plan)
    if not 1 <= index <= len(plan["lights"]):
        raise ValueError("Choose a studio light from the plan")
    light = scene.objects.get(f"Studio light {index}")
    position, target, original, size, color = plan["lights"][index - 1]
    direction = (Vector(target) - Vector(position)).to_track_quat("-Z", "Y")
    if (light is None or light.type != "LIGHT" or light.data.type != "AREA"
            or light.data.users != 1 or light.data.animation_data is not None
            or light.animation_data is not None or original <= 0
            or not math.isclose(light.data.energy, original, rel_tol=1e-6)
            or (light.location - Vector(position)).length > .0001
            or abs(light.rotation_euler.to_quaternion().dot(direction)) < .999999
            or abs(light.data.size - size) > .0001 or (Vector(light.data.color) - Vector(color)).length > .0001):
        raise ValueError("Saved studio light differs from the plan")
    starts = {shot["name"]: shot["frame"] for shot in plan["shots"]}
    first = starts[name]
    stop = min((frame for frame in starts.values() if frame > first), default=plan["frames"] + 1)
    adjusted = original * factor
    if first == 1 and stop == plan["frames"] + 1:
        light.data.energy = adjusted
    else:
        keys = [(1, original)] if first > 1 else []
        keys.append((first, adjusted))
        if stop <= plan["frames"]:
            keys.append((stop, original))
        for frame, energy in keys:
            light.data.energy = energy
            light.data.keyframe_insert("energy", frame=frame)
        for curve in _curves(light.data.animation_data.action):
            for point in curve.keyframe_points:
                point.interpolation = "CONSTANT"
    for tick in range(2, 2 * plan["frames"] + 1):
        scene.frame_set(tick // 2, subframe=(tick % 2) / 2)
        expected = adjusted if 2 * first <= tick < 2 * stop else original
        if not math.isclose(light.data.energy, expected, rel_tol=1e-6):
            raise ValueError("Light energy changed outside the selected shot")
    checks = inspect(scene, plan)
    checks.append(dict(kind="light_energy", light=light.name, frames=[first, stop],
                       before=original, after=adjusted, samples=2 * plan["frames"] - 1))
    return checks


def bounds(obj):
    return [obj.matrix_world @ Vector(vertex) for vertex in obj.bound_box]


def inspect(scene, plan):
    results = []
    for row in plan.get("checks", []):
        first, last = row["frames"]
        minimum_required = row["minimum"]
        if (type(first) is not int or type(last) is not int or not 1 <= first <= last <= plan["frames"]
                or not math.isfinite(minimum_required)):
            raise ValueError("A check is outside the timeline")
        a = scene.objects[row["object"]]
        kind = row["kind"]
        if kind not in ("in_frame", "separation", "axis_contact"):
            raise ValueError(f"Unsupported witness: {kind}")
        if kind != "in_frame" and row["axis"] not in ("x", "y", "z"):
            raise ValueError("A geometry check needs the x, y or z axis")
        measured = []
        for i in range(4 * first, 4 * last + 1):
            if kind == "in_frame" and i % 4:
                continue
            scene.frame_set(i // 4, subframe=(i % 4) / 4)
            vertices = bounds(a)
            if kind == "in_frame":
                coords = [world_to_camera_view(scene, scene.camera, v) for v in vertices]
                value = min(min(p.x, 1 - p.x, p.y, 1 - p.y, p.z) for p in coords)
            else:
                axis = "xyz".index(row["axis"])
                other = bounds(scene.objects[row["before"]])
                value = min(v[axis] for v in vertices) - max(v[axis] for v in other)
                if kind == "axis_contact":
                    value = -abs(value)
            measured.append(value)
        minimum = min(measured)
        if minimum + 1e-6 < minimum_required:
            raise ValueError(f"{kind} failed for {a.name}: {minimum:.4f}")
        results.append(dict(kind=kind, object=a.name, samples=len(measured), measured=minimum))
    return results


def write_sound(path, plan):
    rate = 48000
    fps = plan["fps"]
    samples = array("h", [0]) * (plan["frames"] * rate // fps)
    for frame, duration, frequency, gain in plan["cues"]:
        start, count = (frame - 1) * rate // fps, round(duration * rate)
        if not 0 <= start < start + count <= len(samples) or not 0 < gain <= .6 or not 20 <= frequency <= 5000:
            raise ValueError("Invalid sound cue")
        for i in range(count):
            tone = math.sin(math.tau * frequency * i / rate)
            envelope = math.sin(math.pi * i / count) ** 2
            value = samples[start + i] + round(32767 * tone * envelope * gain)
            if not -32768 <= value <= 32767:
                raise ValueError("Overlapping sound cues clip")
            samples[start + i] = value
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(samples.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    edits = parser.add_mutually_exclusive_group()
    edits.add_argument("--edit-camera", help="Edit one camera in the currently loaded packed scene")
    edits.add_argument("--edit-light", type=int, help="Edit one studio light in the loaded packed scene")
    edits.add_argument("--edit-size", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--distance-factor", type=float)
    parser.add_argument("--light-shot")
    parser.add_argument("--energy-factor", type=float)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    validate(plan)
    if args.edit_camera or args.edit_light is not None or args.edit_size:
        if not bpy.data.filepath or bpy.data.libraries or bpy.utils.blend_paths(absolute=True, packed=False):
            raise ValueError("Open a saved packed scene before editing a shot")
        scene = bpy.context.scene
        if args.edit_size:
            check_saved_timeline(scene, plan)
            width, height = plan["size"]
            plan["size"] = args.edit_size
            validate(plan)
            scene.render.resolution_x, scene.render.resolution_y = args.edit_size
            new_width, new_height = args.edit_size
            # AUTO fits the sensor to the longer side. Keep the vertical field of view.
            factor = max(1, width / height) / max(1, new_width / new_height)
            for shot in plan["shots"]:
                camera_data = scene.objects[shot["name"]].data
                if camera_data.sensor_fit != "AUTO" or abs(camera_data.lens - shot["lens"]) > .0001:
                    raise ValueError("Saved camera differs from the automatic sensor fit in the plan")
                shot["lens"] *= factor
                camera_data.lens = shot["lens"]
            checks = inspect(scene, plan)
            (args.out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
        elif args.edit_camera:
            if args.distance_factor is None or not .5 <= args.distance_factor <= 1.5:
                raise ValueError("Specify the distance factor from 0.5 to 1.5")
            checks = edit_camera(scene, plan, args.edit_camera, args.distance_factor)
        else:
            if (args.light_shot not in {shot["name"] for shot in plan["shots"]}
                    or args.energy_factor is None or not .5 <= args.energy_factor <= 1.5):
                raise ValueError("Specify a shot and the light energy factor from 0.5 to 1.5")
            checks = edit_light(scene, plan, args.light_shot, args.edit_light, args.energy_factor)
        scene.frame_set(1)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve() / "scene.blend"), copy=True)
        (args.out / "checks.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
        return
    scene = build(plan)
    checks = inspect(scene, plan)
    args.out.mkdir(parents=True)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve() / "scene.blend"))
    job = dict(schema_version=1, scene="scene.blend", out="draft", size=plan["size"],
               fps=plan["fps"], frames=[1, plan["frames"] + 1])
    if plan.get("cues"):
        write_sound(args.out / "mix.wav", plan)
        job["wav"] = "mix.wav"
    for name, data in (("plan.json", plan), ("checks.json", checks), ("job.json", job)):
        (args.out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
