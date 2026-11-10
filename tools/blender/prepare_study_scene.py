"""Save a packed copy of an existing scene for the resumable renderer."""

import argparse
from pathlib import Path
import sys

import bpy


def localize_widget_meshes():
    shapes = {
        bone.custom_shape
        for obj in bpy.data.objects
        if obj.type == "ARMATURE"
        for bone in obj.pose.bones
        if bone.custom_shape and bone.custom_shape.type == "MESH"
    }
    meshes = {
        shape.data for shape in shapes
        if shape.data.library_weak_reference
        and shape.data.library is None
        and shape.data.override_library is None
    }
    users = bpy.data.user_map(subset=meshes)
    localized = []
    for mesh in sorted(meshes, key=lambda item: item.name):
        # Only replace data used exclusively as local rig widget geometry.
        if not users[mesh] <= shapes:
            continue
        name = mesh.name
        local = mesh.copy()
        mesh.user_remap(local)
        if mesh.users or local.library_weak_reference:
            raise RuntimeError(f"Could not localize widget mesh {name}")
        bpy.data.meshes.remove(mesh)
        local.name = name
        localized.append(name)
    return localized


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--picture-only", action="store_true",
                        help="Omit an audio-only sequencer from the copy. Export the mix as a separate WAV.")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    output = args.out.resolve()
    if not bpy.data.filepath or output.suffix.lower() != ".blend" or output.exists():
        parser.error("Open a saved .blend and choose a new .blend output path")
    if args.picture_only:
        for scene in bpy.data.scenes:
            editor = scene.sequence_editor
            if editor is None:
                continue
            strip_types = {strip.type for strip in editor.strips_all}
            if "SOUND" not in strip_types:
                continue
            # Pack All still leaves external paths on sequencer sound strips.
            if strip_types != {"SOUND"}:
                raise RuntimeError(f"Cannot omit sequencer audio from {scene.name}: the editor also has other strips")
            scene.sequence_editor_clear()
    localized = localize_widget_meshes()
    bpy.ops.file.pack_all()
    external = bpy.utils.blend_paths(absolute=True, packed=False)
    if external:
        raise RuntimeError(f"Scene still references an external file: {external[0]}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if bpy.ops.wm.save_as_mainfile(filepath=str(output), copy=True) != {"FINISHED"}:
        raise RuntimeError("Blender did not save the portable copy")
    print("Localized widget meshes:", ", ".join(localized) or "none")


if __name__ == "__main__":
    main()
