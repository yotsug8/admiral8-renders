"""Narrow output-path protection for read-only Blender JSON diagnostics."""
from pathlib import Path


def json_output_path(path, inputs):
    """Reject scene names and aliases of inputs; do not create directories.

    samefile also detects existing hardlinks, which resolve alone cannot catch.
    This check assumes paths are not concurrently replaced by another process.
    """
    path = Path(path)
    output = path.resolve()
    if (not output.parent.is_dir() or path.suffix.lower() == '.blend'
            or output.suffix.lower() == '.blend'):
        raise ValueError('output must have an existing parent and cannot overwrite a scene')
    for source in inputs:
        if not source:  # bpy.data.filepath is empty for an unsaved scene.
            continue
        source = Path(source).resolve()
        if output == source or (output.exists() and source.exists()
                                and output.samefile(source)):
            raise ValueError('JSON output cannot overwrite an input file')
    return output


def write_json_report(path, payload, inputs):
    """Validate immediately before opening the report for writing."""
    json_output_path(path, inputs).write_text(payload, encoding='utf-8')
