"""Read-only rig inventory in background Blender; JSON to stdout, no render/save.

Usage: blender -b --factory-startup --disable-autoexec -t 2
       --python-exit-code 1 -P tools/blender/inspect_pose_study.py -- scene.blend
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy


def vec(v):
    return [round(float(x), 6) for x in v]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("blend", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    source = args.blend.resolve(strict=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    if hasattr(scene, "cycles"):
        scene.cycles.device = "CPU"
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    frames = sorted({scene.frame_start, scene.frame_end,
                     (scene.frame_start + scene.frame_end) // 2})
    scene.frame_set(frames[0])
    rigs = [o for o in scene.objects if o.type == "ARMATURE"]
    report = {"source": source.name, "sha256": digest,
              "blender": bpy.app.version_string,
              "fps": scene.render.fps / scene.render.fps_base,
              "frames_sampled": frames,
              "unit_scale": scene.unit_settings.scale_length,
              "unit_system": scene.unit_settings.system,
              "objects": len(scene.objects), "rigs": [],
              "limits": "Bone positions at three frames only; no surface/contact/visual validation."}
    for rig in rigs:
        ad = rig.animation_data
        points = {b.name: (rig.matrix_world @ b.matrix).translation.copy()
                  for b in rig.pose.bones}
        item = {"name": rig.name, "parent": rig.parent.name if rig.parent else None,
                "bones": len(rig.pose.bones), "scale": vec(rig.scale),
                "bone_names": list(points),
                "world_axes": [vec(rig.matrix_world.to_3x3().col[i]) for i in range(3)],
                "action": ad.action.name if ad and ad.action else None,
                "nla": [{"name": t.name, "mute": t.mute,
                         "strips": [{"action": s.action.name if s.action else None,
                                     "range": [s.frame_start, s.frame_end],
                                     "blend": s.blend_type, "influence": s.influence,
                                     "use_animated_influence": s.use_animated_influence,
                                     "mute": s.mute}
                                    for s in t.strips]} for t in ad.nla_tracks] if ad else [],
                "constraints": [{"bone": b.name, "type": c.type, "mute": c.mute}
                                for b in rig.pose.bones for c in b.constraints],
                "chains": {}, "meshes": []}
        names = {b.name.lower(): b.name for b in rig.pose.bones}
        for side in ("l", "r"):
            chain = [names.get(f"{part}_{side}") for part in ("bicep", "elbow", "wrist")]
            if not all(chain):
                item["chains"][side] = {"missing": chain}
                continue
            a, b, c = [points[n] for n in chain]
            u, v = b - a, c - b
            item["chains"][side] = {
                "bones": chain, "positions_world": [vec(p) for p in (a, b, c)],
                "lengths_world": [u.length, v.length],
                "bend_degrees": math.degrees(u.angle(v)),
                "bend_axis_world": vec(u.cross(v).normalized()),
                "rotation_modes": [rig.pose.bones[n].rotation_mode for n in chain]}
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            attached = any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)
            if not attached and obj.parent != rig:
                continue
            hand_groups = {g.index: g.name for g in obj.vertex_groups
                           if any(token in g.name.lower() for token in
                                  ("wrist", "finger", "thumb", "hand"))}
            totals = {}
            for vertex in obj.data.vertices:
                for group in vertex.groups:
                    if group.group in hand_groups and group.weight > 0:
                        name = hand_groups[group.group]
                        totals[name] = totals.get(name, 0) + 1
            item["meshes"].append({"name": obj.name, "vertices": len(obj.data.vertices),
                                   "hidden_render": obj.hide_render,
                                   "hidden_viewport": obj.hide_viewport,
                                   "parent_bone": obj.parent_bone,
                                   "hand_weight_vertex_counts": totals})
        drift = 0.0
        for frame in frames:
            scene.frame_set(frame)
            for bone in rig.pose.bones:
                drift = max(drift, ((rig.matrix_world @ bone.matrix).translation - points[bone.name]).length)
        item["max_sampled_bone_origin_drift_world"] = drift
        report["rigs"].append(item)
        scene.frame_set(frames[0])
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Source file changed during inspection")
    report["source_hash_unchanged"] = True
    print("POSE_STUDY_REPORT " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
