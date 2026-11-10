"""Map supported Russian requests to local 3D scene and shot recipes."""

import json
from fractions import Fraction
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from render_storage import file_lock
from paths import BLENDER
from scene_revision import SECONDS, digest, write_json


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/blender/run_render_job.py"
CREATE = re.compile(
    r"(?:сделай|создай|собери) (?:(вертикальный|горизонтальный) )?"
    r"3d[- ](?:ролик|черновик) про (бумажный кораблик и шлюз|шлагбаум и тележку)",
    re.IGNORECASE,
)
EDITS = {
    "paper_lock": re.compile(r"покажи выход кораблика сбоку (?:в третьем|в 3-м) плане", re.IGNORECASE),
    "rail_barrier": re.compile(r"покажи проезд с уровня колёс (?:во втором|во 2-м) плане", re.IGNORECASE),
}
PACKAGE = ("draft/preview.mp4", "scene.blend", "job.json", "insert.json")
ORDINALS = ("первом", "втором", "третьем", "четвертом", "пятом")
LIGHT_ORDINALS = ("первый", "второй", "третий", "четвертый", "пятый")
DOLLY = re.compile(
    r"(приблизь|отодвинь) камеру (?:в|во) "
    r"([1-9]-м|первом|втором|третьем|четв[её]ртом|пятом) плане на (\d{1,2}) ?%",
    re.IGNORECASE,
)
LIGHT = re.compile(
    r"(усиль|ослабь) ([1-9]-й|первый|второй|третий|четв[её]ртый|пятый) источник света (?:в|во) "
    r"([1-9]-м|первом|втором|третьем|четв[её]ртом|пятом) плане на (\d{1,2}) ?%",
    re.IGNORECASE,
)
SCENE_EDIT = re.compile(
    r"((?:приблизь|отодвинь) камеру|(?:усиль|ослабь) (?:[1-9]-й|первый|второй|третий|четв[её]ртый|пятый) источник света) "
    r"(?:в|во) ([1-9]-й|первой|второй|третьей) сцене на (\d{1,2}) ?%", re.IGNORECASE,
)
CUT = re.compile(
    rf"(?:вырежи|удали) (?:паузу|отрезок) с ({SECONDS})(?: с)? до ({SECONDS}) с",
    re.IGNORECASE,
)
SCENE_DURATION = re.compile(
    r"сделай ([1-9]-ю|первую|вторую|третью) сцену длительностью (\d+) секунд(?:у|ы)?", re.IGNORECASE,
)
SCENE_MUTE = re.compile(
    r"убери звуковой сигнал (?:в|во) ([1-9]-й|первой|второй|третьей) сцене", re.IGNORECASE,
)
SCENE_SWAP = re.compile(
    r"поменяй местами ([1-9]-ю|первую|вторую|третью) и ([1-9]-ю|первую|вторую|третью) сцены",
    re.IGNORECASE,
)
SEQUENCE_FORMAT = re.compile(r"сделай (?:ролик )?(9\s*:\s*16|16\s*:\s*9)", re.IGNORECASE)
SEQUENCE_SIZES = {"9:16": [432, 768], "16:9": [640, 360]}


def normalize(request):
    return " ".join(request.strip().removesuffix(".").split())


def cut_plan(request, base):
    match = CUT.fullmatch(normalize(request))
    if not match:
        return None
    if base is None:
        raise ValueError('Для удаления отрезка укажите исходный MP4 через --base')
    from blender.assemble_shots import cut_mp4_timing

    fingerprint = digest(base)
    timing = cut_mp4_timing(base)
    start, end = (Fraction(value.replace(',', '.')) for value in match.groups())
    fps, count = timing['fps'], timing['count']
    first, stop = round(start * fps), round(end * fps)
    if not 0 <= start < end <= count / fps or first >= stop or stop - first == count:
        raise ValueError('Выберите непустой отрезок внутри ролика, оставляющий кадры')
    audio = timing.get('audio_channels')
    plan = dict(schema_version=1, request=request, operation='cut_av' if audio else 'cut_silent', source_name=base.name,
                base_sha256=fingerprint, frames=[first, stop], fps=str(fps),
                source_frames=count, output_frames=count - (stop - first))
    if audio:
        plan['audio_channels'] = audio
    return plan, timing


def revise_cut(out, base, plan, timing):
    from blender.assemble_shots import cut_frames

    with file_lock(out.with_name(out.name + '.text-edit.lock')):
        if out.exists():
            raise FileExistsError('Выберите новую папку результата')
        with TemporaryDirectory(prefix='.text-cut-', dir=out.parent) as directory:
            work = Path(directory)
            snapshot = work / 'base.mp4'
            shutil.copyfile(base, snapshot)
            if digest(snapshot) != plan['base_sha256']:
                raise ValueError('Исходный MP4 изменился после составления плана')
            result = work / 'result'
            result.mkdir()
            movie = result / 'revision.mp4'
            cut_frames(snapshot, movie, *plan['frames'], timing)
            write_json(result / 'plan.json', dict(plan, result_sha256=digest(movie)))
            result.rename(out)
    return out / movie.name


def creation_plan(request):
    match = CREATE.fullmatch(normalize(request))
    if not match:
        raise ValueError("Поддерживаются запросы про бумажный кораблик и шлюз или про шлагбаум и тележку")
    orientation, subject = match.groups()
    portrait = orientation is not None and orientation.casefold() == "вертикальный"
    if subject.casefold() == "бумажный кораблик и шлюз":
        recipe, args = "paper_lock", ["--side-exit"]
        if portrait:
            args.append("--portrait")
        storyboard = ["Подход", "Подъём ворот", "Выход кораблика"]
    else:
        if portrait:
            raise ValueError("Для «Шлагбаума» подготовлен горизонтальный формат")
        recipe = "rail_barrier"
        story_path = ROOT / "scenes/rail_barrier.json"
        story = json.loads(story_path.read_text(encoding="utf-8"))
        args = ["--plan", str(story_path.relative_to(ROOT))]
        storyboard = [shot["action"] for shot in story["shots"]]
    return dict(request=request, operation="create", recipe=recipe, format="9:16" if portrait else "16:9",
                storyboard=storyboard, builder_args=args)


def run(*args):
    subprocess.run([sys.executable, "-X", "utf8", str(RUNNER), *map(str, args)], cwd=ROOT, check=True)


def build(out, plan):
    builder = RUNNER.with_name(plan["recipe"] + ".py")
    args = [f"--build-arg={arg}" for arg in plan["builder_args"]]
    run(out / "job.json", "--build", builder, *args)
    hashes = {name: digest(out / name) for name in PACKAGE}
    write_json(out / "request.json", dict(schema_version=1, plan=plan, sha256=hashes))
    return out / PACKAGE[0]


def revision_plan(request, base):
    root = base.parent.parent
    if base != root / PACKAGE[0]:
        raise ValueError("Укажите исходный draft/preview.mp4 из папки 3D-запроса")
    receipt = json.loads((root / "request.json").read_text(encoding="utf-8"))
    recipe = receipt["plan"]["recipe"]
    if receipt["schema_version"] != 1 or recipe not in EDITS:
        raise ValueError("Неизвестный пакет 3D-запроса")
    if not EDITS[recipe].fullmatch(normalize(request)):
        raise ValueError("Для этой сцены доступна только предусмотренная текстовая правка ракурса")
    hashes = receipt["sha256"]
    if any(digest(root / name) != hashes.get(name) for name in PACKAGE):
        raise ValueError("Исходный ролик, сцена или задание изменились после сборки")
    source = json.loads((root / "job.json").read_text(encoding="utf-8"))
    insert = json.loads((root / "insert.json").read_text(encoding="utf-8"))
    first, stop = insert["frames"]
    offset = first - source["frames"][0]
    plan = dict(request=request, operation="replace_shot", recipe=recipe, camera=insert["camera"],
                frames=[offset, offset + stop - first], fps=source["fps"])
    return plan, insert, hashes


def camera_plan(base):
    path = base.parent.parent / "plan.json"
    if path.is_file():
        plan = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(plan, dict) and plan.get("schema_version") == 1 and "objects" in plan:
            return plan
    return None


def shot_number(word, ordinals):
    word = word.casefold().replace("ё", "е")
    return int(word[0]) if word[0].isdigit() else ordinals.index(word) + 1


def checked_shot(base, source_plan, number, *, project_picture=False):
    shots = source_plan["shots"]
    if not 1 <= number <= len(shots):
        raise ValueError("Выберите существующий план")
    root = base.parent.parent
    source = json.loads((root / "job.json").read_text(encoding="utf-8-sig"))
    render = json.loads((base.parent / "render_job.json").read_text(encoding="utf-8-sig"))
    scene = root / "scene.blend"
    preview = "preview-project-picture.mp4" if project_picture else "preview.mp4"
    if (base != root / source["out"] / preview or source["scene"] != scene.name
            or digest(scene) != render["source"] or render["camera"] is not None
            or source["frames"] != [1, source_plan["frames"] + 1]
            or (source["fps"], source["size"]) != (source_plan["fps"], source_plan["size"])
            or (render["fps"], render["size"]) != (source["fps"], source["size"])):
        raise ValueError("Предпросмотр, исходная сцена и план должны относиться к одной сборке")
    shot = shots[number - 1]
    first = shot["frame"]
    stop = shots[number]["frame"] if number < len(shots) else source["frames"][1]
    insert = dict(schema_version=1, scene="scene.blend", out="insert", frames=[first, stop],
                  fps=source["fps"], size=source["size"], camera=shot["name"])
    return shot, insert, {PACKAGE[0]: digest(base), "scene.blend": render["source"]}


def dolly_plan(request, base, source_plan, *, project_picture=False):
    match = DOLLY.fullmatch(normalize(request))
    if not match:
        raise ValueError("Укажите «Приблизь камеру во втором плане на 10%» или «Усиль второй источник света во втором плане на 40%»")
    verb, ordinal, percentage = match.groups()
    number, percentage = shot_number(ordinal, ORDINALS), int(percentage)
    if not 1 <= percentage <= 50:
        raise ValueError("Выберите величину перемещения от 1 до 50%")
    shot, insert, hashes = checked_shot(base, source_plan, number, project_picture=project_picture)
    verb = verb.casefold()
    factor = 1 + (percentage / 100 if verb == "отодвинь" else -percentage / 100)
    target = shot["target"]

    def scaled(position):
        return [center + (value - center) * factor for value, center in zip(position, target, strict=True)]

    shot["position"] = scaled(shot["position"])
    if "move" in shot:
        shot["move"][1] = scaled(shot["move"][1])
    plan = dict(request=request, operation="dolly", shot=number, camera=shot["name"], distance_factor=factor,
                frames=[frame - 1 for frame in insert["frames"]], fps=insert["fps"])
    return plan, insert, hashes


def light_plan(request, base, source_plan, *, project_picture=False):
    match = LIGHT.fullmatch(normalize(request))
    if not match:
        return None
    verb, light, ordinal, percentage = match.groups()
    light, number = shot_number(light, LIGHT_ORDINALS), shot_number(ordinal, ORDINALS)
    percentage = int(percentage)
    if not 1 <= percentage <= 50 or not 1 <= light <= len(source_plan["lights"]):
        raise ValueError("Выберите существующий источник света и изменение мощности от 1 до 50%")
    shot, insert, hashes = checked_shot(base, source_plan, number, project_picture=project_picture)
    factor = 1 + (percentage / 100 if verb.casefold() == "усиль" else -percentage / 100)
    plan = dict(request=request, operation="light_energy", shot=number, camera=shot["name"],
                light=light, energy_factor=factor, frames=[frame - 1 for frame in insert["frames"]],
                fps=insert["fps"])
    return plan, insert, hashes


def retime_scene_plan(plan, seconds):
    old = plan["frames"]
    new = plan["fps"] * seconds
    if not 2 <= seconds <= 6 or old == new:
        raise ValueError("Выберите другую длительность сцены от 2 до 6 целых секунд")

    def frame_at(frame):
        return 1 + round(Fraction((frame - 1) * (new - 1), old - 1))

    for obj in plan["objects"]:
        for field in ("positions", "rotations"):
            for key in obj.get(field, ()):
                key[0] = frame_at(key[0])
            frames = [key[0] for key in obj.get(field, ())]
            if len(set(frames)) != len(frames):
                raise ValueError("После изменения длительности ключи попадают в один кадр")
    for shot in plan["shots"]:
        shot["frame"] = frame_at(shot["frame"])
        if "move" in shot:
            shot["move"][0] = frame_at(shot["move"][0])
    for check in plan.get("checks", ()):
        check["frames"] = [frame_at(frame) for frame in check["frames"]]
    for cue in plan.get("cues", ()):
        cue[0] = frame_at(cue[0])
        if (cue[0] - 1) / plan["fps"] + cue[1] > seconds:
            raise ValueError("Звуковой сигнал не помещается в новую длительность")
    plan["frames"] = new


def sequence_revision_plan(request, base):
    root = base.parent
    manifest = root / "project.json"
    receipt = root.parent / "local_job.json"
    history_path = root / "sequence-state.json"
    chained = base.name == "revision.mp4" and history_path.is_file()
    if chained:
        manifest = history_path
    else:
        if not manifest.is_file() or not receipt.is_file():
            return None
        local = json.loads(receipt.read_text(encoding="utf-8"))
        if not isinstance(local, dict) or local.get("profile") != "sequence":
            return None
        if base.name != "preview.mp4":
            raise ValueError("Укажите общий scene/preview.mp4 из текстовой сборки")
    text = normalize(request)
    format_edit = SEQUENCE_FORMAT.fullmatch(text)
    duration = SCENE_DURATION.fullmatch(text)
    mute = SCENE_MUTE.fullmatch(text)
    swap = SCENE_SWAP.fullmatch(text)
    match = SCENE_EDIT.fullmatch(text)
    if duration:
        number = shot_number(duration[1], ("первую", "вторую", "третью"))
    elif match:
        number = shot_number(match[2], ("первой", "второй", "третьей"))
    elif mute:
        number = shot_number(mute[1], ("первой", "второй", "третьей"))
    elif format_edit or swap:
        number = None
    else:
        raise ValueError("Укажите правку камеры, света, длительности, сигнала, формата или порядка сцен")
    project = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(project, dict) or project.get("schema_version") != 1 or project.get("out") != base.name:
        raise ValueError("Общее видео должно соответствовать проекту версии 1")
    shots = project["shots"]
    if (not isinstance(shots, list) or not 2 <= len(shots) <= 3
            or (number is not None and not 1 <= number <= len(shots))):
        raise ValueError("Выберите существующую сцену")
    if shots != [f"scene-{i:02d}/job.json" for i in range(1, len(shots) + 1)]:
        raise ValueError("Порядок заданий отличается от текстовой сборки")
    if swap:
        first, second = (shot_number(word, ("первую", "вторую", "третью")) for word in swap.groups())
        if first == second or max(first, second) > len(shots):
            raise ValueError("Для перестановки выберите две разные существующие сцены")
        order = list(range(1, len(shots) + 1))
        order[first - 1], order[second - 1] = order[second - 1], order[first - 1]
    if chained and (not isinstance(project.get("plan_sha256"), list) or len(project["plan_sha256"]) != len(shots)):
        raise ValueError("В ревизии не хватает контрольных сумм планов сцен")

    from blender.assemble_shots import picture_hashes, video_timing

    fingerprint = digest(base)
    if chained and project.get("movie_sha256") != fingerprint:
        raise ValueError("MP4 ревизии отличается от сохранённой версии")
    archive = None
    if not chained:
        archive = json.loads((root / "input_plan.json").read_text(encoding="utf-8"))
        if (not isinstance(archive, dict) or not isinstance(archive.get("scenes"), list)
                or len(archive["scenes"]) != len(shots)):
            raise ValueError("Архив плана не соответствует проекту")
    timing = video_timing(base)
    project_picture = project.get("audio") == "shots"
    picture_name = "preview-project-picture.mp4" if project_picture else "preview.mp4"
    expected = []
    history = []
    for index, reference in enumerate(shots, 1):
        config = root / reference
        job = json.loads(config.read_text(encoding="utf-8"))
        clip = config.parent / job["out"] / picture_name
        first, stop = job["frames"]
        clip_hash = digest(clip)
        frames = picture_hashes(clip)
        if len(frames) != stop - first or (tuple(job["size"]), job["fps"]) != (timing["size"], timing["fps"]):
            raise ValueError("Задания сцен отличаются от общего видео")
        if digest(clip) != clip_hash:
            raise ValueError("Клип сцены изменился во время проверки")
        source_plan = camera_plan(clip)
        if not isinstance(source_plan, dict) or len(source_plan["shots"]) != 1:
            raise ValueError("Текстовая правка сцены поддерживает один план")
        plan_path = config.parent / "plan.json"
        if chained:
            if digest(plan_path) != project["plan_sha256"][index - 1]:
                raise ValueError("План сцены отличается от ревизии")
        elif source_plan != archive["scenes"][index - 1]:
            raise ValueError("План сцены отличается от архивной версии")
        _, _, hashes = checked_shot(clip, source_plan, 1, project_picture=project_picture)
        history.append(dict(clip=clip, clip_sha256=clip_hash, scene_sha256=hashes["scene.blend"],
                            plan=source_plan, job=job, offset=len(expected)))
        expected.extend(frames)
    if picture_hashes(base) != expected or digest(base) != fingerprint:
        raise ValueError("Кадры общего видео отличаются от собранных сцен")
    if swap:
        history = [history[i - 1] for i in order]
        spans = [[entry["offset"], entry["offset"] + entry["plan"]["frames"]] for entry in history]
        plan = dict(request=request, operation="scene_swap", order=order, source_ranges=spans,
                    frames=[0, len(expected)], fps=history[0]["job"]["fps"])
        return plan, None, {PACKAGE[0]: fingerprint}, None, None, history
    if format_edit:
        aspect = re.sub(r"\s", "", format_edit[1])
        size = SEQUENCE_SIZES[aspect]
        width, height = timing["size"]
        if width * size[1] == height * size[0]:
            raise ValueError("Ролик уже в указанном формате")
        plan = dict(request=request, operation="sequence_format", format=aspect, size=size,
                    frames=[0, len(expected)], fps=history[0]["job"]["fps"])
        return plan, None, {PACKAGE[0]: fingerprint}, None, None, history
    from copy import deepcopy

    selected = history[number - 1]
    clip, offset = selected["clip"], selected["offset"]
    edited = deepcopy(selected["plan"])
    if mute:
        if not edited.get("cues"):
            raise ValueError("В этой сцене нет звукового сигнала")
        edited["cues"] = []
        plan = dict(request=request, operation="scene_mute", scene_index=number,
                    frames=[offset, offset + edited["frames"]], fps=edited["fps"])
        return plan, None, {PACKAGE[0]: fingerprint}, edited, None, history
    if duration:
        old_count = edited["frames"]
        retime_scene_plan(edited, int(duration[2]))
        _, insert, hashes = checked_shot(clip, selected["plan"], 1, project_picture=project_picture)
        insert["frames"] = [1, edited["frames"] + 1]
        plan = dict(operation="scene_duration", frames=[offset, offset + old_count],
                    new_frames=[offset, offset + edited["frames"]], fps=edited["fps"])
    else:
        text = f"{match[1]} в первом плане на {match[3]}%"
        result = light_plan(text, clip, edited, project_picture=project_picture)
        plan, insert, hashes = result or dolly_plan(text, clip, edited, project_picture=project_picture)
        plan["frames"] = [offset + frame for frame in plan["frames"]]
    plan.update(request=request, scene_index=number)
    hashes[PACKAGE[0]] = fingerprint
    insert.pop("camera")  # The scene has one camera and keeps its normal timeline.
    return plan, insert, hashes, edited, clip.parent.parent / "scene.blend", history


def finish_revision(out, base, plan, insert, hashes):
    write_json(out / "plan.json", plan)
    write_json(out / "insert.json", dict(insert, scene="scene.blend", out="insert"))
    # A snapshot keeps the edit usable on Windows even across drives.
    preview = out / "base.mp4"
    shutil.copyfile(base, preview)
    manifest = dict(schema_version=1, request=plan["request"], base=preview.name,
                    base_sha256=hashes[PACKAGE[0]], insert="insert.json",
                    replace_at=plan["frames"][0], out="revision.mp4")
    write_json(out / "revision.json", manifest)
    run(out / "revision.json", "--revision")
    return out / "revision.mp4"


def render_planned(out, base, plan, insert, hashes, edited_plan, source):
    path = out / "scene-plan.json"
    write_json(path, edited_plan)
    if plan["operation"] == "light_energy":
        edit = ["--edit-light", str(plan["light"]), "--light-shot", plan["camera"],
                "--energy-factor", str(plan["energy_factor"])]
    else:
        edit = ["--edit-camera", plan["camera"], "--distance-factor", str(plan["distance_factor"])]
    subprocess.run([BLENDER, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "2",
                    str(source), "-P", str(RUNNER.with_name("scene_plan.py")), "--",
                    "--plan", str(path), "--out", str(out), *edit],
                   cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"), check=True)
    if digest(source) != hashes["scene.blend"]:
        raise ValueError("Исходная сцена изменилась во время подготовки правки")
    return finish_revision(out, base, plan, insert, hashes)


def render_duration(out, base, plan, insert, hashes, edited_plan, history):
    from blender.assemble_shots import assemble, picture_hashes, replace_scene_audio

    plan_path = out / "scene-plan.json"
    write_json(plan_path, edited_plan)
    write_json(out / "plan.json", plan)
    write_json(out / "insert.json", insert)
    original = out / "base.mp4"
    shutil.copyfile(base, original)
    if digest(original) != hashes[PACKAGE[0]]:
        raise ValueError("Исходное видео изменилось перед правкой длительности")
    with TemporaryDirectory(prefix=".duration-", dir=out) as directory:
        built = Path(directory) / "scene"
        subprocess.run([BLENDER, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "2",
                        "-P", str(RUNNER.with_name("scene_plan.py")), "--",
                        "--plan", str(plan_path), "--out", str(built)],
                       cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"), check=True)
        (built / "scene.blend").replace(out / "scene.blend")
        sound = built / "mix.wav"
        first, stop = plan["frames"]
        mix = replace_scene_audio(original, sound if sound.is_file() else None, out / "mix.wav",
                                  first, stop, edited_plan["frames"])
    run(out / "insert.json")
    changed = out / "insert/preview.mp4"
    clips = [entry["clip"] for entry in history]
    clips[plan["scene_index"] - 1] = changed
    movie = assemble(clips, out / "revision.mp4", wav=mix)
    previous = picture_hashes(original)
    expected = previous[:first] + picture_hashes(changed) + previous[stop:]
    if picture_hashes(movie) != expected:
        raise ValueError("Монтаж изменил кадры соседних сцен")
    return movie


def render_scene_mute(out, base, plan, hashes):
    from blender.assemble_shots import picture_hashes, replace_scene_audio, video_timing
    from blender.export_render_job import AUDIO_RATE, mux_wav, read_wav

    write_json(out / "plan.json", plan)
    original = out / "base.mp4"
    shutil.copyfile(base, original)
    if digest(original) != hashes[PACKAGE[0]]:
        raise ValueError("Исходное видео изменилось перед правкой звука")
    first, stop = plan["frames"]
    mix = replace_scene_audio(original, None, out / "mix.wav", first, stop, stop - first)
    if mix is None:
        raise ValueError("В исходном MP4 нет звуковой дорожки")
    movie = out / "revision.mp4"
    duration, channels = read_wav(mix)
    mux_wav(original, mix, movie, round(duration * AUDIO_RATE), channels)
    if video_timing(movie) != video_timing(original) or picture_hashes(movie) != picture_hashes(original):
        raise ValueError("Правка звука изменила кадры или монтаж")
    return movie


def render_scene_swap(out, base, plan, hashes, history):
    from blender.assemble_shots import assemble, picture_hashes, reorder_scene_audio

    write_json(out / "plan.json", plan)
    original = out / "base.mp4"
    shutil.copyfile(base, original)
    if digest(original) != hashes[PACKAGE[0]]:
        raise ValueError("Исходное видео изменилось перед перестановкой сцен")
    spans = plan["source_ranges"]
    mix = reorder_scene_audio(original, out / "mix.wav", spans)
    movie = assemble([entry["clip"] for entry in history], out / "revision.mp4", wav=mix)
    before = picture_hashes(original)
    expected = [frame for first, stop in spans for frame in before[first:stop]]
    if picture_hashes(movie) != expected:
        raise ValueError("При перестановке изменились кадры сцен")
    return movie


def save_sequence_state(out, movie, plan, edited_plan, history, parent_hash):
    if plan["operation"] == "light_energy":
        edited_plan["lights"][plan["light"] - 1][2] *= plan["energy_factor"]
    for index, entry in enumerate(history, 1):
        folder = out / f"scene-{index:02d}"
        draft = folder / "draft"
        draft.mkdir(parents=True)
        selected = index == plan.get("scene_index")
        replaced = selected and plan["operation"] != "scene_mute"
        clip = out / "insert/preview.mp4" if replaced else entry["clip"]
        scene = out / "scene.blend" if replaced else clip.parent.parent / "scene.blend"
        blend_hash = digest(scene) if replaced else entry["scene_sha256"]
        clip_hash = digest(clip) if replaced else entry["clip_sha256"]
        render = json.loads((clip.parent / "render_job.json").read_text(encoding="utf-8"))
        if render["source"] != blend_hash or render["camera"] is not None:
            raise ValueError("Клип сцены не соответствует сохранённому заданию")
        for original, target, fingerprint in ((scene, folder / "scene.blend", blend_hash),
                                              (clip, draft / "preview.mp4", clip_hash)):
            shutil.copyfile(original, target)
            if digest(target) != fingerprint:
                raise ValueError("Сцена изменилась во время сохранения ревизии")
        write_json(draft / "render_job.json", render)
        write_json(folder / "plan.json", edited_plan if selected else entry["plan"])
        source_job = json.loads((out / "insert.json").read_text(encoding="utf-8")) if replaced else entry["job"]
        job = dict(source_job, out="draft")
        job.pop("wav", None)  # The version's master MP4 is the audio source.
        write_json(folder / "job.json", job)
    write_sequence_manifest(out, movie, len(history), parent_hash)


def write_sequence_manifest(out, movie, count, parent_hash):
    folders = [out / f"scene-{i:02d}" for i in range(1, count + 1)]
    shots = [f"{folder.name}/job.json" for folder in folders]
    plans = [digest(folder / "plan.json") for folder in folders]
    write_json(out / "sequence-state.json", dict(schema_version=1, out=movie.name, shots=shots,
                                               plan_sha256=plans, movie_sha256=digest(movie), parent_sha256=parent_hash))


def render_sequence_format(out, base, plan, hashes, history):
    from blender.assemble_shots import assemble, keep_project_audio

    write_json(out / "plan.json", plan)
    original = out / "base.mp4"
    shutil.copyfile(base, original)
    if digest(original) != hashes[PACKAGE[0]]:
        raise ValueError("Исходное видео изменилось перед сменой формата")
    jobs = []
    # Check each new camera frame before spending time rendering any scene.
    for index, entry in enumerate(history, 1):
        folder = out / f"scene-{index:02d}"
        folder.mkdir()
        input_plan = folder / "input-plan.json"
        write_json(input_plan, entry["plan"])
        source = entry["clip"].parent.parent / "scene.blend"
        if digest(source) != entry["scene_sha256"]:
            raise ValueError("Исходная сцена изменилась перед сменой формата")
        subprocess.run([BLENDER, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "2",
                        str(source), "-P", str(RUNNER.with_name("scene_plan.py")), "--", "--plan", str(input_plan),
                        "--out", str(folder), "--edit-size", *map(str, plan["size"])],
                       cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"), check=True)
        if digest(source) != entry["scene_sha256"]:
            raise ValueError("Исходная сцена изменилась во время подготовки формата")
        job = dict(entry["job"], size=plan["size"], out="draft")
        job.pop("wav", None)
        job_path = folder / "job.json"
        write_json(job_path, job)
        jobs.append(job_path)
    for job_path in jobs:
        run(job_path)
    picture = assemble([path.parent / "draft/preview.mp4" for path in jobs], out / "picture.mp4")
    movie = keep_project_audio(picture, original, out / "revision.mp4")
    write_sequence_manifest(out, movie, len(history), hashes[PACKAGE[0]])
    return movie


def revise_planned(out, base, plan, insert, hashes, edited_plan, *, source=None, history=None):
    source = source or base.parent.parent / "scene.blend"
    with file_lock(out.with_name(out.name + ".text-edit.lock")):
        if history is None:
            out.mkdir(parents=True)
            return render_planned(out, base, plan, insert, hashes, edited_plan, source)
        if out.exists():
            raise FileExistsError("Для новой ревизии выберите новую папку")
        with TemporaryDirectory(prefix=".sequence-edit-", dir=out.parent) as directory:
            staged = Path(directory) / "result"
            staged.mkdir()
            if plan["operation"] == "sequence_format":
                movie = render_sequence_format(staged, base, plan, hashes, history)
            elif plan["operation"] == "scene_duration":
                movie = render_duration(staged, base, plan, insert, hashes, edited_plan, history)
            elif plan["operation"] == "scene_mute":
                movie = render_scene_mute(staged, base, plan, hashes)
            elif plan["operation"] == "scene_swap":
                movie = render_scene_swap(staged, base, plan, hashes, history)
            else:
                movie = render_planned(staged, base, plan, insert, hashes, edited_plan, source)
            if plan["operation"] != "sequence_format":
                save_sequence_state(staged, movie, plan, edited_plan, history, hashes[PACKAGE[0]])
            staged.rename(out)
        return out / movie.name


def revise(out, base, plan, insert, hashes):
    with file_lock(out.with_name(out.name + ".text-edit.lock")):
        out.mkdir(parents=True)
        source = out / "scene.blend"
        shutil.copyfile(base.parent.parent / "scene.blend", source)
        if digest(source) != hashes["scene.blend"]:
            raise ValueError("Исходная сцена изменилась во время копирования")
        return finish_revision(out, base, plan, insert, hashes)
