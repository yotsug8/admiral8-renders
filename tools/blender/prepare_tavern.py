"""Place and pack the original Crownfall tavern in the dialogue stage axes."""

import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.out.suffix.lower() != ".glb":
        parser.error("--out must name a self-contained .glb")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.shell.resolve(strict=True)))
    objects = bpy.context.scene.objects
    if not any(obj.type == "MESH" for obj in objects):
        raise ValueError("Crownfall tavern export contains no mesh")
    missing = [image.name for image in bpy.data.images if image.source == "FILE" and not all(image.size)]
    if missing:
        raise ValueError(f"Crownfall tavern export is missing textures: {', '.join(missing)}")

    # Angle the open aisle across the dialogue marks below the timber balcony.
    placement = Matrix.Rotation(math.radians(-155), 4, "Z") @ Matrix.Translation(Vector((-12.7, 9.6, -.045)))
    for obj in objects:
        if obj.parent is None:
            obj.matrix_world = placement @ obj.matrix_world
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(args.out.resolve()), export_format="GLB")


if __name__ == "__main__":
    main()
