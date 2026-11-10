"""Turn a dialogue brief into a Blender job with Russian audio and facial animation."""

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import wave

import numpy as np

from local_scene_planner import choices, infer, record
from paths import BLENDER, S2V, VPK
from render_storage import file_lock
from scene_revision import write_json


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "out/studio/resources"
TAVERN = RESOURCES / "sets/tavern-crownfall.glb"
CROWNFALL_STAGE = "models/events/crownfall/tussle_stage/minifight_tavern.vmdl_c"
CAST = {
    "pudge": r"пудж(?:а|у|ом|е)?|pudge",
    "invoker": r"инвокер(?:а|у|ом|е)?|invoker",
    "axe": r"акс(?:а|у|ом|е)?|axe",
    "rubick": r"рубик(?:а|у|ом|е)?|rubick",
    "lina": r"лин(?:а|у|ы|е|ой)|lina",
    "kunkka": r"кунк(?:ка|ку|ки|ке|кой)|kunkka",
    "sniper": r"снайпер(?:а|у|ом|е)?|sniper",
    "tidehunter": r"тайдхантер(?:а|у|ом|е)?|tidehunter",
}
DIALOGUE = re.compile(
    r"\b(?:диалог\w*|разговор\w*|спор\w*|реплик\w*|разговарива\w*|говор\w*"
    r"|спрашива\w*|отвеча\w*|обсужда\w*|dialogue|speak\w*|ask\w*|talk\w*)\b", re.I)
DURATION = re.compile(r"\b(\d{1,3})(?:\s*[-–]\s*|\s+)(?:секунд\w*|сек\.?|seconds?)\b", re.I)
PORTRAIT = re.compile(r"\bвертикальн\w*\b|\b9\s*:\s*16\b", re.I)
LANDSCAPE = re.compile(r"\bгоризонтальн\w*\b|\b16\s*:\s*9\b", re.I)
FINALE = re.compile(r"(?:\bв конце|\bв финале)\s+([^.!?\n]+)", re.I)
EMOTIONS = {"neutral": None, "amused": "улыбка", "annoyed": "хмурый",
            "surprised": "удивлён", "doubtful": "скепсис"}
LINE = re.compile(r"^\s*(?P<who>[\w ]{1,28})\s*[:：]\s*(?P<line>.+)$")
FPS = 30
SR = 48000


def cast_for(text):
    positions = [(m.start(), hero) for hero, pattern in CAST.items()
                 if (m := re.search(rf"\b(?:{pattern})\b", text, re.I))]
    return [hero for _, hero in sorted(positions)]


def wants_dialogue(request):
    return len(cast_for(request)) >= 2 or bool(DIALOGUE.search(request))


def plan_request(request, runtime, model, reference=None):
    actors = cast_for(request)
    if len(actors) != 2:
        raise ValueError("Для этой постановки укажите двух героев Dota. Например, Пуджа и Инвокера.")
    if PORTRAIT.search(request) and LANDSCAPE.search(request):
        raise ValueError("Укажите один формат кадра для ролика.")
    seconds = {int(value) for value in DURATION.findall(request)}
    if len(seconds) > 1 or any(not 5 <= value <= 60 for value in seconds):
        raise ValueError("Задайте одну длительность диалога от 5 до 60 секунд.")
    duration = next(iter(seconds), None)
    portrait = bool(PORTRAIT.search(request)) or bool(not LANDSCAPE.search(request) and reference
                                                     and reference.get("aspect") == "portrait")
    set_name = "tavern" if re.search(r"\b(?:таверн\w*|tavern)\b", request, re.I) else "studio"
    explicit = []
    for row in request.splitlines():
        match = LINE.fullmatch(row)
        if match and len(who := cast_for(match["who"])) == 1:
            explicit.append(dict(who=who[0], text=match["line"].strip(" «»"), emotion="neutral"))
    if explicit:
        lines = explicit
    else:
        if not DIALOGUE.search(request):
            raise ValueError("Этот маршрут ставит разговор двух героев. Опишите диалог или приложите реплики.")
        finale = FINALE.search(request)
        final_cast = cast_for(finale[1]) if finale else []
        max_lines = min(12, max(2, round(duration / 4))) if duration else 3
        if len(final_cast) == 1 and not duration:
            max_lines = 2
        schema = record({"lines": {"type": "array", "minItems": 2, "maxItems": max_lines,
                                  "items": record({"who": choices(actors), "text": {"type": "string", "maxLength": 250},
                                                   "emotion": choices(EMOTIONS)})}})
        words = max(7, round((duration - 1.7) * 2.25)) if duration else 19
        instructions = (
            "Ты сценарист коротких сцен. Напиши связный русский диалог по замыслу пользователя. "
            "Порядок: в первой реплике возникает вопрос или конфликт, следующая меняет ситуацию, "
            "последняя даёт развязку. Если пользователь назвал финал, раскрой его только в конце. "
            "Каждая реплика добавляет новую информацию. Не противоречь тому, что герой уже сказал. "
            f"Используй обоих героев: {' и '.join(actors)}. Первым говорит тот, кому есть что выяснить. "
            f"Около {words} русских слов суммарно. Всего до {max_lines} реплик. "
            "Не вставляй ремарки, имена говорящих, закадровый текст или описание кадра в поле text."
        )
        if len(final_cast) == 1:
            instructions += f" Обязательный говорящий в последней реплике: {final_cast[0]}. После него никто не говорит."
        result = infer(request, runtime, model, contract=(instructions, schema), max_tokens=720)
        lines = result.get("lines") if isinstance(result, dict) else None
    if (not isinstance(lines, list) or not 2 <= len(lines) <= 12
            or any(not isinstance(line, dict) or line.keys() != {"who", "text", "emotion"}
                   or line["who"] not in actors or line["emotion"] not in EMOTIONS
                   or not isinstance(line["text"], str) or not 2 <= len(line["text"]) <= 250
                   or not re.search("[а-яё]", line["text"], re.I)
                   or re.search(r"[<>\[\]{}|\r\n]", line["text"]) for line in lines)
            or (not explicit and len({line["text"].strip().casefold() for line in lines}) != len(lines))
            or {line["who"] for line in lines} != set(actors)):
        raise ValueError("Не получился русский диалог для обоих героев. Уточните тему или добавьте их реплики.")
    if not explicit and len(final_cast) == 1 and lines[-1]["who"] != final_cast[0]:
        raise ValueError("Планировщик не сохранил указанного героя в финале. Уточните порядок реплик.")
    return dict(request=request, actors=actors, lines=lines, duration=duration, set=set_name,
                size=[540, 960] if portrait else [960, 540])


def synthesize(out, lines, duration):
    from skit.character_voice import align, generate, voice_reference
    from skit.voices import _ff, _pcm

    references = {hero: voice_reference(hero) for hero in dict.fromkeys(line["who"] for line in lines)}
    paths = {line["name"]: out / (line["name"] + ".wav") for line in lines}
    for line in lines:
        generate(line["text"], references[line["who"]], paths[line["name"]])
    clips = {name: _pcm(path) for name, path in paths.items()}
    pauses = len(lines) - 1
    if duration:
        current = sum(map(len, clips.values())) / SR
        speed = (duration - 1.5 - .34 * pauses) / current
        if not .72 <= speed <= 1.4:
            raise ValueError("Длина текста не подходит для заданного времени. Уточните длительность или реплики.")
        if abs(speed - 1) > .08:
            for name, path in paths.items():
                stretched = path.with_suffix(".tempo.wav")
                subprocess.run([_ff(), "-v", "error", "-i", str(path), "-af", f"atempo={1/speed:.5f}",
                                str(stretched)], check=True)
                stretched.replace(path)
                clips[name] = _pcm(path)
    data = {}
    for line in lines:
        name = line["name"]
        audio = clips[name]
        hop = SR // FPS
        rms = np.array([np.sqrt(np.mean(chunk ** 2)) for chunk in np.array_split(audio, range(hop, len(audio), hop))])
        norm = np.percentile(rms, 95)
        if norm < 1e-4:
            raise ValueError("Локальный голос вернул тишину.")
        data[name] = dict(text=line["text"], say=line["text"], who=line["who"], dur=len(audio)/SR,
                          env=np.minimum(1, rms/norm).tolist(), words=align(line["text"], paths[name]),
                          reference=references[line["who"]].name)
    write_json(out / "voices.json", data)
    return data, clips


def prepare_tavern():
    if TAVERN.is_file():
        return
    print("Подготовка игровой таверны", flush=True)
    TAVERN.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".crownfall-", dir=TAVERN.parent) as directory:
        source, staged = (Path(directory) / name for name in ("source.glb", "packed.glb"))
        subprocess.run([S2V, "-i", VPK, "--vpk_filepath", CROWNFALL_STAGE, "-o", str(source), "-d",
                        "--gltf_export_format", "glb", "--gltf_export_materials", "--gltf_textures_adapt"], check=True)
        subprocess.run([BLENDER, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "2",
                        "-P", str(ROOT / "tools/blender/prepare_tavern.py"), "--",
                        "--shell", str(source), "--out", str(staged)], check=True)
        staged.replace(TAVERN)


def build_dialogue(out, plan, reference, *, prepare_only=False):
    sys.path.insert(0, str(ROOT / "tools/blender"))
    from run_render_job import FF, run_job
    from skit import skit
    from skit.hero_render import export
    from hero_parts import hero_model

    sys.path.insert(0, str(ROOT))
    from video import loudnorm

    if not Path(VPK).is_file() or not shutil.which(S2V):
        raise ValueError("Для героев нужны установленная Dota 2 и Source2Viewer по инструкции проекта.")
    if plan["set"] == "tavern":
        prepare_tavern()
    for hero in plan["actors"]:
        skit.troupe(hero)
        body, parts = hero_model(hero)
        for asset in [body, *parts]:
            path, detail = export(asset)
            if not Path(path).is_file() or Path(path).stat().st_size <= 228:
                raise ValueError(f"Не выгружен ресурс {asset}. {detail}")

    cast = plan["actors"]
    if plan["set"] == "tavern" and set(cast) == {"pudge", "invoker"}:
        cast = ("pudge", "invoker")
    actors = {hero: dict(hero=hero, at=(0, (index-.5)*190), stance=None, look=None, voice={})
              for index, hero in enumerate(cast)}
    lines = [dict(line, name=f"line{index:02d}")
             for index, line in enumerate(plan["lines"], 1)]
    print("Синтез голосов героев", flush=True)
    metadata, clips = synthesize(out, lines, plan["duration"])
    pause = .34
    if plan["duration"]:
        remaining = plan["duration"] - 1.5 - sum(line["dur"] for line in metadata.values())
        pause = remaining / (len(lines)-1)
        if not .15 <= pause <= .78:
            raise ValueError("Длительность не укладывается в естественные паузы. Уточните реплики или время.")
    events = [dict(kind="line", who=line["who"], name=line["name"], text=line["text"],
                   emo=EMOTIONS[line["emotion"]], emo2=None, mood=None, shot=None, gesture=None,
                   pause_before=pause if index else 0)
              for index, line in enumerate(lines)]
    scene_path = out / "scene.json"
    skit.build(dict(name="dialogue", map=None, cast=actors, events=events, flat_ground=True), metadata, str(out))
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    scene.update(dialogue_set=plan["set"], render_size=plan["size"])
    first = lines[0]["who"]
    other = next(hero for hero in actors if hero != first)
    fov = 68 if plan["set"] == "tavern" and plan["size"][0] < plan["size"][1] else 37
    wide = {"fov": fov, "fstop": 4.5}
    if plan["set"] == "tavern":
        wide["height"] = 2.92
    establishing = [0, "dialogue_wide", first, other, wide]
    close = [.65, "close", first, None, dict(skit.P_CLOSE, ang=48, fstop=3.8, face_center=True)]
    remaining = scene["shots"][1:]
    for shot in remaining:
        shot[4].update(ang=48, fstop=3.8, face_center=True)
    scene["shots"] = [establishing, close, *remaining]
    if reference and reference.get("palette"):
        scene["reference_palette"] = reference["palette"]
    write_json(scene_path, scene)
    audio = np.zeros(scene["frames"] * SR // FPS, np.float32)
    for name, (_, offset) in scene["voices"].items():
        clip = clips[name]
        start = round(offset * SR)
        if start + len(clip) > len(audio):
            raise ValueError("Реплика выходит за границу видео.")
        audio[start:start+len(clip)] += clip
    raw = out / "mix-raw.wav"
    with wave.open(str(raw), "wb") as wav:
        wav.setparams((1, 2, SR, 0, "NONE", "not compressed"))
        wav.writeframes((audio.clip(-1, 1)*32767).astype("<i2").tobytes())
    mixed = out / "mix.wav"
    subprocess.run([FF, "-v", "error", "-i", str(raw), "-af", loudnorm(str(raw)),
                    "-ar", str(SR), "-ac", "2", str(mixed)], check=True)
    blend = out / "scene.blend"
    env = dict(os.environ, A8_BLEND=str(blend), A8_SAMPLES="96", A8_DOTA="on=0")
    print("Подготовка сцены, мимики и камер", flush=True)
    subprocess.run([BLENDER, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "2",
                    "-P", str(ROOT / "tools/blender/render_scene.py"), "--", str(scene_path),
                    str(out / "draft"), "all"], check=True, env=env)
    config = out / "job.json"
    write_json(config, dict(schema_version=1, scene=blend.name, out="draft", frames=[0, scene["frames"]],
                            size=plan["size"], fps=FPS, wav=mixed.name))
    if not prepare_only:
        print(f"Проверенный ролик: {run_job(config)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference-look", type=Path)
    parser.add_argument("--prepare-only", action="store_true", help="Подготовить сцену и звук для пробных кадров")
    args = parser.parse_args()
    try:
        os.environ.setdefault("A8_DIALOGUE_CONTENT", str(RESOURCES / "dota-content"))
        reference = json.loads(args.reference_look.read_text(encoding="utf-8")) if args.reference_look else None
        out = args.out.resolve()
        with file_lock(out.parent / "dialogue-assets.lock"):
            plan = plan_request(args.request, args.runtime, args.model, reference)
            out.mkdir(parents=True)
            write_json(out / "plan.json", plan)
            build_dialogue(out, plan, reference, prepare_only=args.prepare_only)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Локальная сборка не завершена. {error}") from None


if __name__ == "__main__":
    crt = os.environ.get("A8_CRT") if os.name == "nt" else None
    with os.add_dll_directory(crt) if crt else nullcontext():
        main()
