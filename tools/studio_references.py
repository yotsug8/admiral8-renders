"""Snapshot user references and derive visual properties for the local scene builders."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageOps


IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MOVIES = {".mp4", ".mov", ".mkv", ".webm"}
TEXT = {".txt", ".md"}
EXTENSIONS = IMAGES | MOVIES | TEXT
MAX_FILES = 4


def poster(path, target):
    if path.suffix.lower() not in MOVIES:
        return path
    probe = os.environ.get("FFPROBE") or "ffprobe"
    result = subprocess.check_output([probe, "-v", "error", "-select_streams", "v:0",
                                      "-show_entries", "format=duration", "-of", "json", str(path)])
    seconds = float(json.loads(result)["format"]["duration"])
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-ss", str(seconds*.45),
                    "-i", str(path), "-frames:v", "1", "-vf", "scale=640:640:force_original_aspect_ratio=decrease",
                    str(target)], check=True, timeout=30)
    return target


def palette_of(image):
    image = image.copy()
    image.thumbnail((180, 180))
    quantized = image.quantize(colors=7)
    values = quantized.getpalette()
    frequencies = sorted(quantized.getcolors(), reverse=True)
    return [values[index*3:index*3+3] for _, index in frequencies[:3]]


def prepare_references(folder, paths):
    folder.mkdir()
    texts, palettes, aspects, files = [], [], [], []
    for index, source in enumerate(paths, 1):
        if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
            raise ValueError(f"Не удалось открыть референс «{source.name}».")
        if source.stat().st_size > (2 << 30):
            raise ValueError(f"Референс «{source.name}» должен занимать до 2 ГБ.")
        target = folder / f"{index:02d}-{source.name}"
        shutil.copy2(source, target)
        files.append(target.name)
        if target.suffix.lower() in TEXT:
            with target.open(encoding="utf-8-sig") as stream:
                texts.append(stream.read(601).strip())
            continue
        with Image.open(poster(target, folder / f"{index:02d}-frame.png")) as source_image:
            img = ImageOps.exif_transpose(source_image).convert("RGB")
            palettes.append(palette_of(img))
            aspects.append("portrait" if img.height > img.width else "landscape")
    profile = dict(files=files)
    if palettes:
        # Each file has equal weight, regardless of size or duration.
        averages = [list(map(lambda values: round(sum(values)/len(values)), zip(*colors)))
                    for colors in zip(*palettes)]
        profile["palette"] = [[round((value / 255)**2.2, 4) for value in color] for color in averages]
        if len(set(aspects)) == 1:
            profile["aspect"] = aspects[0]
    return texts, profile
