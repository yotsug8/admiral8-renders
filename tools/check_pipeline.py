"""Run the local 2D, 3D, text edit and recovery checks without game assets."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

from scene_revision import digest, write_json


ROOT = Path(__file__).resolve().parents[1]


def run(out, report, name, *command, expected=0, env=None):
    log = out / f"{name}.log"
    started = perf_counter()
    with log.open("wb") as output:
        result = subprocess.run([sys.executable, "-X", "utf8", *map(str, command)], cwd=ROOT,
                                stdout=output, stderr=subprocess.STDOUT, env=env)
    step = dict(name=name, exit_code=result.returncode, log=log.name, seconds=round(perf_counter() - started, 3))
    if expected:
        step["expected_exit_code"] = expected
    report["steps"].append(step)
    write_json(out / "report.json", report)
    if result.returncode != expected:
        raise RuntimeError(f"Проверка {name} завершилась ошибкой. Отчёт в {log}")


def local_recovery(out, report, runtime, model, probe):
    root = out / "local-text"
    scene = root / "scene"
    cache = scene / "draft"
    preview = cache / "preview.mp4"
    request = "Красный шар поднимается. Горизонтальный ролик на 2 секунды. Со звуковым сигналом."
    run(out, report, "local-encoder-failure", "tools/quickstart.py", "3d", "--planner", "objects",
        "--runtime", runtime, "--model", model, "--request", request, "--out", root,
        expected=1, env=dict(os.environ, IMAGEIO_FFMPEG_EXE=probe))
    first = json.loads((cache / "render_report.json").read_text(encoding="utf-8"))
    frames = list(range(1, 49))
    if preview.exists() or first["rendered"] != frames or first["reused"]:
        raise ValueError("Сбой кодировщика не сохранил полный кэш нового задания")
    files = [root / "plan.json", scene / "input_plan.json", scene / "scene.blend", scene / "job.json",
             *(cache / f"f{frame:04d}.png" for frame in frames)]
    before = [(file.stat().st_mtime_ns, digest(file)) for file in files]
    if before[0][1] != before[1][1]:
        raise ValueError("Сохранённый план отличается от входа сборки")
    run(out, report, "local-resume", "tools/quickstart.py", "3d", "--resume", "--out", root)
    after = json.loads((cache / "render_report.json").read_text(encoding="utf-8"))
    if after["reused"] != frames or after["rendered"] or before != [
        (file.stat().st_mtime_ns, digest(file)) for file in files
    ]:
        raise ValueError("Продолжение изменило план, сцену или проверенные кадры")
    return dict(expected_encoder_failure=True, reused_frames=len(frames), rebuilt_frames=0,
                plan_sha256=before[0][1], preserved_scene=True)


def verify_local_clip(path, ffmpeg, plan):
    import numpy as np

    raw = subprocess.check_output([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-an",
                                   "-vf", "scale=160:90", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    red, green, blue = np.frombuffer(raw, np.uint8).reshape(48, 90, 160, 3).transpose(3, 0, 1, 2).astype(float)
    ball = (red > 75) & (red > 1.35 * green) & (red > 1.35 * blue)
    areas = ball.sum(axis=(1, 2))
    if np.min(areas) < 10:
        raise ValueError("Красный шар не виден во всех кадрах")
    height = (ball * np.arange(90)[None, :, None]).sum(axis=(1, 2)) / areas
    rise = float(height[0] - height[-1])
    deltas = np.diff(height)
    if rise < 6 or np.max(np.abs(deltas)) > 2 or np.count_nonzero(deltas < -.15) < 12:
        raise ValueError("Движение красного шара не соответствует запросу")
    if len(plan["cues"]) != 1:
        raise ValueError("План должен содержать один звуковой сигнал")
    cue = (plan["cues"][0][0] - 1) / plan["fps"]
    raw = subprocess.check_output([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-vn",
                                   "-ac", "1", "-ar", "48000", "-f", "f32le", "-"])
    active = np.flatnonzero(np.abs(np.frombuffer(raw, np.float32)) > .02)
    if not len(active) or not cue - .01 <= active[0] / 48000 <= cue + .05:
        raise ValueError("Звуковой сигнал не совпадает с планом")
    return dict(rise_px_at_160x90=round(rise, 3), sound_cue_s=cue,
                decoded_sound_onset_s=round(float(active[0] / 48000), 6))


def sequence_edits(out, report):
    from local_scene_planner import compile_sequence

    root = out / "sequence"
    root.mkdir()
    request = ("Горизонтально. Сцена 1: красный шар поднимается, 2 секунды, со звуковым сигналом. "
               "Сцена 2: синий куб опускается, 3 секунды, со звуковым сигналом.")
    intent = dict(status="plan", aspect="landscape", scenes=[
        dict(shape="ball", color="red", motion="up", seconds=2, sound=True),
        dict(shape="cube", color="blue", motion="down", seconds=3, sound=True),
    ])
    write_json(root / "plan.json", compile_sequence(request, intent))
    write_json(root / "local_job.json", dict(schema_version=1, profile="sequence", source=None))
    command = ("tools/quickstart.py", "3d")
    run(out, report, "sequence-build", *command, "--resume", "--out", root)
    source = root / "scene/preview.mp4"
    movies = [source]
    original = digest(source)
    no_blender = dict(os.environ, BLENDER=str(root / "unavailable-blender.exe"))
    requests = (
        ("camera", "Приблизь камеру в первой сцене на 10%.", None),
        ("duration", "Сделай первую сцену длительностью 4 секунды.", None),
        ("portrait", "Сделай 9:16.", None),
        ("swap", "Поменяй местами первую и вторую сцены.", no_blender),
        ("mute", "Убери звуковой сигнал в первой сцене.", no_blender),
    )
    for name, text, env in requests:
        target = root / name
        run(out, report, f"sequence-{name}", *command, "--base", movies[-1], "--request", text,
            "--out", target, env=env)
        movies.append(target / "revision.mp4")
    rejected = root / "rejected"
    run(out, report, "sequence-repeat-mute", *command, "--base", movies[-1], "--request", requests[-1][1],
        "--out", rejected, expected=1, env=no_blender)
    log = (out / "sequence-repeat-mute.log").read_text(encoding="utf-8")
    if rejected.exists() or digest(source) != original or "В этой сцене нет звукового сигнала" not in log:
        raise ValueError("Правка изменила исходный ролик или сохранила отклонённую версию")
    return verify_sequence(movies)


def verify_sequence(movies):
    import numpy as np
    from blender.assemble_shots import cut_mp4_timing, decode_pcm, picture_hashes, same_audio
    from blender.export_render_job import AUDIO_RATE

    probe = os.environ.get("FFPROBE") or shutil.which("ffprobe")
    hashes = [picture_hashes(path) for path in movies]
    if (hashes[0][:48] == hashes[1][:48] or hashes[0][48:] != hashes[1][48:]
            or hashes[1][48:] != hashes[2][96:] or hashes[3][96:] + hashes[3][:96] != hashes[4]
            or hashes[4] != hashes[5]):
        raise ValueError("Цепочка правок изменила кадры вне заданного действия")
    if not same_audio(probe, movies[0], movies[1]) or not same_audio(probe, movies[2], movies[3]):
        raise ValueError("Правка камеры или формата изменила звук")

    cut_frames = (48, 48, 96, 96, 72, 72)
    frame_counts = (120, 120, 168, 168, 168, 168)
    evidence = []
    for index, (path, cut, count) in enumerate(zip(movies, cut_frames, frame_counts, strict=True)):
        timing = cut_mp4_timing(path)
        size = (640, 360) if index < 3 else (432, 768)
        if (timing["size"], timing["fps"], timing["count"]) != (size, 24, count):
            raise ValueError(f"Неожиданный размер или таймлайн в {path}")
        channels = timing["audio_channels"]
        pcm = np.frombuffer(decode_pcm(path, channels), dtype="<i2").reshape(-1, channels)
        samples_per_frame = AUDIO_RATE // 24
        begins = []
        for scene, (start, stop) in enumerate(((0, cut), (cut, count)), 1):
            block = pcm[start * samples_per_frame:stop * samples_per_frame]
            active = np.flatnonzero(np.any(np.abs(block.astype(np.int32)) > 655, axis=1))
            begin = int(active[0]) if len(active) else None
            folder = path.parent / f"scene-{scene:02d}"
            plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
            cues = plan["cues"]
            if cues:
                expected = (cues[0][0] - 1) * samples_per_frame
                if begin is None or not expected - 480 <= begin <= expected + 2400:
                    raise ValueError(f"Звуковой сигнал не совпадает с планом в {folder}")
            elif begin is not None:
                raise ValueError(f"В немой сцене найден сигнал в {folder}")
            if json.loads((folder / "job.json").read_text(encoding="utf-8"))["frames"] != [1, stop - start + 1]:
                raise ValueError(f"Сохранён неверный диапазон сцены в {folder}")
            begins.append(begin)
        fingerprint = digest(path)
        if index:
            manifest = json.loads((path.parent / "sequence-state.json").read_text(encoding="utf-8"))
            if manifest["parent_sha256"] != evidence[-1]["sha256"] or manifest["movie_sha256"] != fingerprint:
                raise ValueError(f"Нарушена цепочка ревизий в {path}")
        evidence.append(dict(file=path.relative_to(movies[0].parents[2]).as_posix(), sha256=fingerprint,
                             size=list(size), fps=24, frames=count, cut_frame=cut, onsets_in_scene_samples=begins))
    onset = [item["onsets_in_scene_samples"] for item in evidence]
    if (any(value is None for pair in onset[:-1] for value in pair)
            or abs(onset[1][1] - onset[2][1]) > 4
            or any(abs(a - b) > 4 for a, b in zip(onset[3], reversed(onset[4]), strict=True))
            or onset[5][0] is not None or onset[5][1] is None or abs(onset[5][1] - onset[4][1]) > 4):
        raise ValueError("Звуковые сигналы не следуют за сценами")
    return dict(planner="saved deterministic plan", movies=evidence, rejected_repeat_mute=True)


def verify(out, *, local=False):
    from blender.assemble_shots import FF, audio_packets, picture_hashes, same_audio, video_timing

    probe = shutil.which(os.environ.get("FFPROBE") or "ffprobe")
    if not probe:
        raise ValueError("Нужен ffprobe в PATH или явный FFPROBE")
    profiles = (
        ("2d/eclipse.mp4", (540, 960), 15, 105),
        ("3d/draft/preview.mp4", (640, 360), 24, 80),
        ("light/revision.mp4", (640, 360), 24, 80),
        ("recovery/delivery/preview.mp4", (320, 180), 24, 16),
    )
    if local:
        profiles += (("local-text/scene/draft/preview.mp4", (640, 360), 24, 48),)
    movies = {}
    for name, size, fps, count in profiles:
        path = out / name
        timing = video_timing(path)
        if (timing["size"], timing["fps"], timing["count"]) != (size, fps, count):
            raise ValueError(f"Неожиданные параметры {name}")
        subprocess.run([FF, "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                       check=True)
        movies[name] = dict(size=list(size), fps=fps, frames=count, sha256=digest(path))
    before, after = out / profiles[1][0], out / profiles[2][0]
    original, edited = picture_hashes(before), picture_hashes(after)
    changed = [i for i, (old, new) in enumerate(zip(original, edited, strict=True)) if old != new]
    if changed != list(range(34, 80)) or not audio_packets(probe, before) or not same_audio(probe, before, after):
        raise ValueError("Правка света изменила соседние кадры или звук")
    recovery = json.loads((out / "recovery/recovery-report.json").read_text(encoding="utf-8"))
    report = dict(movies=movies, light_changed_frames=len(changed), preserved_frames=34,
                  preserved_audio=True, recovery=recovery)
    if local:
        movie = out / profiles[-1][0]
        if not audio_packets(probe, movie):
            raise ValueError("В ролике из запроса отсутствует звуковой сигнал")
        plan = json.loads((out / "local-text/plan.json").read_text(encoding="utf-8"))
        report["local_text_clip"] = verify_local_clip(movie, FF, plan)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New folder for logs and MP4 evidence")
    parser.add_argument("--runtime", type=Path, help="Local llama-server for the optional text and recovery check")
    parser.add_argument("--model", type=Path, help="Local GGUF for the optional text and recovery check")
    parser.add_argument("--sequence-edits", action="store_true", help="Build and verify a chain of multi-scene edits")
    args = parser.parse_args()
    if bool(args.runtime) != bool(args.model):
        parser.error("Для проверки текста укажите одновременно --runtime и --model")
    out = args.out.resolve()
    report = dict(schema_version=1, game_folder_present=(ROOT / "_game").exists(), steps=[])
    try:
        if args.runtime:
            if not args.runtime.is_file() or not args.model.is_file():
                raise ValueError("Нужны существующие файлы llama-server и GGUF")
            probe = shutil.which(os.environ.get("FFPROBE") or "ffprobe")
            if not probe:
                raise ValueError("Нужен ffprobe в PATH или явный FFPROBE")
        out.mkdir(parents=True)
        run(out, report, "2d", "tools/quickstart.py", "2d", "--out", out / "2d")
        run(out, report, "3d", "tools/blender/run_render_job.py", out / "3d/job.json", "--build",
            "tools/blender/scene_plan.py", "--build-arg=--plan", "--build-arg=scenes/crystal_lift.json")
        run(out, report, "light", "tools/quickstart.py", "3d", "--base", out / "3d/draft/preview.mp4",
            "--out", out / "light", "--request", "Усиль второй источник света во втором плане на 40%.")
        run(out, report, "recovery", "tools/test_blender_resume.py", "--out", out / "recovery")
        if args.runtime:
            report["local_text"] = local_recovery(out, report, args.runtime.resolve(), args.model.resolve(), probe)
        report.update(verify(out, local=bool(args.runtime)))
        if args.sequence_edits:
            report["sequence_edits"] = sequence_edits(out, report)
        report["passed"] = True
        write_json(out / "report.json", report)
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Переносимая проверка не пройдена. {exc}") from None
    print(out / "report.json")


if __name__ == "__main__":
    main()
