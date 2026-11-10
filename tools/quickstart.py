"""Проверить программы и собрать локальный предпросмотр."""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from paths import BLENDER
from scene_revision import DRAFT_FPS, plan_revision, write_json, write_preview


ROOT = Path(__file__).resolve().parents[1]
LOCAL_BUILDERS = {"objects": "scene_plan.py", "rain": "rain_action_plan.py",
                  "contact": "console_reaction.py", "push": "study_robot_push.py",
                  "lift": "rain_unexpected_weight.py", "sequence": "scene_plan.py"}


def check(mode):
    if sys.version_info[:2] != (3, 11):
        raise ValueError("Запустите команду с Python 3.11")
    packages = ("numpy", "PIL", "imageio_ffmpeg", "playwright") if mode == "2d" else (
        "numpy", "imageio_ffmpeg"
    )
    for package in packages:
        try:
            importlib.import_module(package)
        except ImportError as exc:
            raise ValueError(f"Не загружается {package}. Установите зависимости по docs/SETUP.md: {exc}") from exc
    ffmpeg = importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe()
    if mode == "2d":
        ffmpeg = shutil.which("ffmpeg") or ffmpeg
    subprocess.run([ffmpeg, "-version"], check=True, capture_output=True, timeout=15)
    probe = shutil.which(os.environ.get("FFPROBE") or "ffprobe")
    if not probe:
        raise ValueError("Не найден ffprobe. Добавьте его в PATH или укажите FFPROBE")
    subprocess.run([probe, "-version"], check=True, capture_output=True, timeout=15)

    if mode == "2d":
        from playwright.sync_api import Error, sync_playwright

        try:
            with sync_playwright() as session:
                browser = session.chromium.launch(args=["--disable-gpu"], timeout=15_000)
                browser.close()
        except Error as exc:
            raise ValueError("Не запустился Chromium. Выполните python -m playwright install chromium") from exc
        print("2D: Python, FFmpeg, ffprobe и Chromium готовы.", flush=True)
    else:
        blender = shutil.which(BLENDER)
        if not blender:
            raise ValueError("Не найден Blender. Укажите путь к установленному blender.exe через BLENDER")
        result = subprocess.run([blender, "--version"], check=True, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=15)
        version = result.stdout.partition("\n")[0]
        if not version.startswith("Blender "):
            raise ValueError("BLENDER должен указывать на исполняемый файл Blender")
        print(f"3D: {version}, FFmpeg и ffprobe готовы.", flush=True)
    return probe


def render(mode, out, probe, scene=None, frames=None, *, local_voice=False, full=False):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if mode == "2d":
        out.mkdir(parents=True)
        for key in ("FV_QA_ONLY", "FV_QA_DIR", "FV_BADGE"):
            env.pop(key, None)
        env.update(FV_SILENT="1", FV_WORKERS="2")
        if full:
            env.pop("FV_DRAFT", None)
        else:
            env["FV_DRAFT"] = "1"
        if local_voice:
            env.pop("FV_SILENT")
            env.pop("FV_BEAT", None)
        filename = "preview.mp4" if scene else "eclipse.mp4"
        if frames:
            filename = "insert.mp4"
        target = out / filename
        command = ["video.py"]
        if local_voice:
            command.append("--local-preview")
        if frames:
            first, stop = frames
            command.extend(["--picture-range", f"{first}:{stop}"])
        elif scene:
            snapshot = out / "source.json"
            shutil.copyfile(scene, snapshot)
            scene = snapshot
        command.extend([str(scene or "episodes/study_eclipse.json"), str(target)])
    else:
        target = out / "draft" / "preview.mp4"
        command = ["tools/blender/run_render_job.py", str(out / "job.json"),
                   "--build", "tools/blender/paper_lock.py"]
    subprocess.run([sys.executable, *command], cwd=ROOT, env=env, check=True)
    streams = subprocess.check_output([
        probe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames",
        "-of", "csv=p=0", str(target),
    ], text=True).strip()
    expected, count = {"2d": (f"540,960,{DRAFT_FPS}/1", 105), "3d": ("640,360,30/1", 156)}[mode]
    if full:
        expected = "1080,1920,30/1"
    if scene:
        count = frames[1] - frames[0] if frames else None
    parameters, _, actual = streams.rpartition(",")
    if (parameters != expected or not actual.isdigit()
            or int(actual) < 1 or (count is not None and int(actual) != count)):
        raise RuntimeError(f"Неожиданные параметры ролика: {streams}")
    if scene and not frames and not full:
        write_preview(scene, target, int(actual), wav=target.with_suffix(".wav") if local_voice else None)
    print(f"Проверенный ролик: {target}")


def describe_plan(plan):
    if plan["operation"] == "accent":
        first, stop = plan["frames"]
        effect = plan["effect"]
        return (f"Акцент на {effect['target']} в {effect['at']:g} с. "
                f"Кадры {first}–{stop - 1} при {DRAFT_FPS} кадрах/с.")
    return (f"Пауза с {plan['at']:g} с продлится на {plan['extra_seconds']:g} с. "
            f"Сдвинутся эффекты: {len(plan['shifted_effects'])}. Новый полный предпросмотр сцены.")


def apply_revision(out, episode, plan, manifest, probe):
    out.mkdir(parents=True)
    edited = out / "scene.json"
    write_json(edited, episode)
    write_json(out / "plan.json", plan)
    if manifest is None:
        render("2d", out / "edit", probe, edited)
        return out / "edit/preview.mp4"
    revision = out / "revision.json"
    write_json(revision, manifest)
    render("2d", out / "edit", probe, edited, plan["frames"])
    subprocess.run([sys.executable, "-X", "utf8", "tools/blender/run_render_job.py",
                    "--revision", str(revision)], cwd=ROOT, check=True)
    return out / manifest["out"]


def run_3d_request(args, out):
    from scene_request_3d import (build, camera_plan, creation_plan, cut_plan, dolly_plan, light_plan,
                                  revise, revise_cut, revise_planned, revision_plan, sequence_revision_plan)

    base = args.base.resolve() if args.base else None
    cut = cut_plan(args.request, base)
    if cut is not None:
        plan, timing = cut
        print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
        if not args.plan_only:
            print(f"Проверенный ролик: {revise_cut(out, base, plan, timing)}")
        return
    sequence = sequence_revision_plan(args.request, base) if base else None
    if sequence is not None:
        plan, insert, hashes, edited, source, history = sequence
        print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
        if not args.plan_only:
            if plan["operation"] not in {"scene_mute", "scene_swap"}:
                check("3d")
            print(f"Проверенный ролик: {revise_planned(out, base, plan, insert, hashes, edited, source=source, history=history)}")
        return
    edited = camera_plan(base) if base else None
    if edited is not None:
        plan, insert, hashes = light_plan(args.request, base, edited) or dolly_plan(args.request, base, edited)
    elif base:
        plan, insert, hashes = revision_plan(args.request, base)
    else:
        plan = creation_plan(args.request)
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if args.plan_only:
        return
    check("3d")
    if edited is not None:
        result = revise_planned(out, base, plan, insert, hashes, edited)
    else:
        result = revise(out, base, plan, insert, hashes) if base else build(out, plan)
    print(f"Проверенный ролик: {result}")


def build_local_sequence(snapshot, staged, builder):
    from run_render_job import build_job, read_job

    plan = json.loads(snapshot.read_text(encoding="utf-8"))
    if (not isinstance(plan, dict) or plan.get("schema_version") != 1
            or not isinstance(plan.get("scenes"), list) or len(plan["scenes"]) not in (2, 3)):
        raise ValueError("План монтажа версии 1 требует две или три сцены")
    shots = []
    has_audio = False
    profile = None
    for i, scene in enumerate(plan["scenes"], 1):
        item = f"scene-{i:02d}"
        plan_path = staged.parent / f"{item}.json"
        write_json(plan_path, scene)
        shot = staged / item / "job.json"
        build_job(shot, builder, ["--plan", str(plan_path)])
        job, _, _, wav = read_job(shot)
        timing = (job["size"], job["fps"])
        if profile is not None and timing != profile:
            raise ValueError("Задания проекта должны совпадать по размеру и FPS")
        profile = timing
        has_audio |= wav is not None
        shots.append(shot.relative_to(staged).as_posix())
    project = dict(schema_version=1, shots=shots, out="preview.mp4")
    if has_audio:
        project["audio"] = "shots"
    write_json(staged / "project.json", project)


def run_local_3d(args, out):
    from render_storage import file_lock
    from scene_revision import digest

    plan_path, receipt_path = out / "plan.json", out / "local_job.json"
    scene_folder = out / "scene"
    with file_lock(out.with_name(out.name + ".local-plan.lock")):
        if args.resume:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int
                    or receipt["schema_version"] != 1 or receipt.get("profile") not in LOCAL_BUILDERS
                    or "source" not in receipt or (receipt["source"] is not None and not isinstance(receipt["source"], str))):
                raise ValueError("Неизвестный формат локального задания")
        else:
            if out.exists():
                raise ValueError("Выберите новую папку или используйте --resume")
            from local_scene_planner import plan_request

            source = args.source.resolve(strict=True) if args.source else None
            request = args.request
            if args.reference_look:
                from dialogue_request import LANDSCAPE, PORTRAIT

                look = json.loads(args.reference_look.read_text(encoding="utf-8"))
                if look.get("aspect") and not (LANDSCAPE.search(request) or PORTRAIT.search(request)):
                    request = ("Вертикально. " if look["aspect"] == "portrait" else "Горизонтально. ") + request
            plan = plan_request(request, args.runtime, args.model, args.planner)
            if args.reference_look:
                for shot in plan.get("scenes", [plan]):
                    shot["materials"]["Floor"]["rgb"] = [max(.025, min(.38, v)) for v in look["palette"][0]]
                    if len(look["palette"]) > 1:
                        shot["materials"]["Pedestal"]["rgb"] = [
                            max(.035, min(.48, v)) for v in look["palette"][1]
                        ]
            receipt = dict(schema_version=1, profile=args.planner, source=str(source) if source else None)
            with TemporaryDirectory(prefix=".local-plan-", dir=out.parent) as directory:
                prepared = Path(directory) / "result"
                prepared.mkdir()
                write_json(prepared / plan_path.name, plan)
                write_json(prepared / receipt_path.name, receipt)
                prepared.rename(out)
        print(f"План: {plan_path}", flush=True)
        if args.plan_only:
            return

        check("3d")
        builder = ROOT / "tools" / "blender" / LOCAL_BUILDERS[receipt["profile"]]
        sys.path.insert(0, str(builder.parent))
        from run_render_job import build_job, read_job, run_job, run_project

        fingerprint = digest(plan_path)
        snapshot_name = "input_plan.json"
        sequence = receipt["profile"] == "sequence"
        config = scene_folder / ("project.json" if sequence else "job.json")
        if scene_folder.exists():
            if digest(scene_folder / snapshot_name) != fingerprint:
                raise ValueError("План изменился после сборки. Для новой версии выберите другую папку")
        else:
            with TemporaryDirectory(prefix=".local-scene-", dir=out) as directory:
                work = Path(directory)
                snapshot = work / "plan.json"
                shutil.copyfile(plan_path, snapshot)
                if digest(snapshot) != fingerprint:
                    raise ValueError("План изменился во время чтения")
                staged = work / scene_folder.name
                if sequence:
                    build_local_sequence(snapshot, staged, builder)
                else:
                    builder_args = ["--plan", str(snapshot)]
                    if receipt["source"]:
                        builder_args.extend(("--source", receipt["source"]))
                    build_job(staged / config.name, builder, builder_args)
                    read_job(staged / config.name)
                if digest(plan_path) != fingerprint:
                    raise ValueError("План изменился во время подготовки сцены")
                snapshot.rename(staged / snapshot_name)
                staged.rename(scene_folder)
        render_result = run_project if sequence else run_job
        print(f"Проверенный ролик: {render_result(config)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("2d", "3d"))
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--check", action="store_true", help="Проверить программы без рендера")
    options.add_argument("--out", type=Path, help="Новая папка для результата")
    parser.add_argument("--scene", type=Path, help="Свой JSON-сценарий для черновика 2D без озвучки")
    parser.add_argument("--local-voice", action="store_true", help="Озвучить полный черновик через Windows SAPI")
    parser.add_argument("--full", action="store_true", help="Экспортировать 2D в 1080×1920 при 30 кадрах/с")
    parser.add_argument("--frames", metavar="НАЧАЛО:КОНЕЦ", help="Собрать немую вставку из своего сценария")
    parser.add_argument("--request", help="Создание 3D или правка предпросмотра по тексту")
    parser.add_argument("--base", type=Path, help="Исходный preview.mp4 для текстовой правки")
    parser.add_argument("--plan-only", action="store_true", help="Показать план текстовой правки без рендера")
    parser.add_argument("--planner", choices=LOCAL_BUILDERS, help="Профиль локального 3D-планировщика")
    parser.add_argument("--runtime", type=Path, help="Локальный llama-server для --planner")
    parser.add_argument("--model", type=Path, help="Локальный GGUF для --planner")
    parser.add_argument("--source", type=Path, help="Исходный Rain Rig для профилей rain и lift")
    parser.add_argument("--reference-look", type=Path, help="Палитра и формат из визуальных референсов")
    parser.add_argument("--resume", action="store_true", help="Продолжить локальное 3D-задание по сохранённому плану")
    args = parser.parse_args()
    if args.reference_look and args.planner not in ("objects", "sequence"):
        parser.error("--reference-look требует локальный планировщик предметов или монтажа")
    if args.planner or args.resume:
        if args.mode != "3d" or not args.out or any((args.scene, args.local_voice, args.full, args.frames, args.base, args.check)):
            parser.error("Для локального планировщика используйте 3d и --out без других режимов")
        if args.resume:
            if any((args.planner, args.request, args.runtime, args.model, args.source, args.plan_only)):
                parser.error("Для продолжения нужны только 3d, --resume и --out")
        elif not all((args.request, args.runtime, args.model)):
            parser.error("Для --planner нужны --request, --runtime и --model")
        if args.source and (args.planner not in ("rain", "lift") or args.source.suffix.lower() != ".blend"):
            parser.error("--source принимает .blend только для rain и lift")
        try:
            run_local_3d(args, args.out.resolve())
        except (TypeError, ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            raise SystemExit(f"Локальная сборка не завершена. {exc}") from None
        return
    if any((args.runtime, args.model, args.source)):
        parser.error("--runtime, --model и --source требуют --planner")
    scene = args.scene.resolve() if args.scene else None
    if scene and (args.mode != "2d" or not args.out):
        parser.error("--scene доступен для 2d вместе с --out")
    if scene and (scene.suffix.lower() != ".json" or not scene.is_file()):
        parser.error("--scene должен указывать на существующий JSON-файл")
    if args.local_voice and (not scene or args.frames is not None or args.request is not None):
        parser.error("--local-voice требует полный предпросмотр своего 2D-сценария")
    if args.full and (not scene or args.frames is not None or args.request is not None):
        parser.error("--full требует 2d, --scene и --out без правки или диапазона")
    if args.request is not None:
        if args.mode == "3d":
            if args.check or args.frames is not None or (not args.plan_only and not args.out):
                parser.error("Для текстового 3D-запроса нужен --out или --plan-only")
        elif not scene or not args.base or args.frames is not None:
            parser.error("--request требует --scene и --base вместо --frames")
    elif args.base or args.plan_only:
        parser.error("--base и --plan-only требуют --request")
    frames = None
    if args.frames is not None:
        if scene is None:
            parser.error("--frames требует --scene")
        try:
            first, stop = map(int, args.frames.split(":"))
        except ValueError:
            parser.error("Укажите два целых номера кадров через двоеточие")
        if not 0 <= first < stop:
            parser.error("Нужен непустой диапазон с началом от нуля")
        frames = (first, stop)
    try:
        out = (args.out or ROOT / "qa" / "quickstart" / args.mode).resolve()
        if args.mode == "3d" and args.request is not None:
            run_3d_request(args, out)
            return
        if args.request is not None:
            episode, plan, manifest = plan_revision(scene, args.base.resolve(), out, args.request)
            print(describe_plan(plan), flush=True)
            if args.plan_only:
                return
        probe = check(args.mode)
        if not args.check:
            if args.request is None:
                render(args.mode, out, probe, scene, frames, local_voice=args.local_voice, full=args.full)
                return
            apply_revision(out, episode, plan, manifest, probe)
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Быстрый запуск не завершён. {exc}") from None


if __name__ == "__main__":
    main()
