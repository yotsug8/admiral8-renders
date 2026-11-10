"""Plan supported local edits against a verified 2D preview."""

import hashlib
import json
import math
import os
import re


DRAFT_FPS = 15
PULSE_SECONDS = .28  # scene.js: two 0.14-second legs
EFFECT_SECONDS = {"move": .6, "dim": .3, "show": .3, "hide": .25,
                  "pulse": PULSE_SECONDS, "gray": .3, "color": .3,
                  "shake": .3, "out": .3, "pop": .4, "slam": .28, "stamp": .24}
SECONDS = r'\d{1,5}(?:[,.]\d{1,6})?'
ACCENT = re.compile(
    r'(?:добавь акцент на|подчеркни) +(?:«([\w-]+)»|([\w-]+)) '
    rf'+на +({SECONDS}) *(?:с|секунде)\.?', re.IGNORECASE
)
PAUSE = re.compile(
    rf'(?:продли|увеличь) паузу на ({SECONDS}) *с после ({SECONDS}) *с\.?', re.IGNORECASE
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_preview(scene, base):
    receipt = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    if (receipt["schema_version"] != 1 or receipt["fps"] != DRAFT_FPS
            or type(receipt["frames"]) is not int or receipt["frames"] < 1
            or receipt["scene_sha256"] != digest(scene) or receipt["video_sha256"] != digest(base)):
        raise ValueError("Сценарий или MP4 отличается от сохранённой версии предпросмотра")
    return receipt


def write_preview(scene, base, frames, *, wav=None):
    receipt = dict(schema_version=1, fps=DRAFT_FPS, frames=frames,
                   scene_sha256=digest(scene), video_sha256=digest(base))
    if wav is not None:
        receipt["wav_sha256"] = digest(wav)
    write_json(base.with_suffix(".json"), receipt)


def plan_revision(scene, base, out, request):
    accent = ACCENT.fullmatch(request.strip())
    pause = PAUSE.fullmatch(request.strip())
    if not accent and not pause:
        raise ValueError("Укажите «Подчеркни marker на 1,25 с» или «Продли паузу на 1 с после 3,2 с»")
    receipt = read_preview(scene, base)
    if receipt.get("wav_sha256"):
        raise ValueError("Голосовой план можно использовать в монтаже. Его текстовая правка пока недоступна")
    episode = json.loads(scene.read_text(encoding="utf-8-sig"))
    parts = episode.get("parts", [])
    if len(parts) != 1 or episode.get("hook") or episode.get("outro"):
        raise ValueError("Пока запрос поддерживается в сценарии с одной сценой")
    part = parts[0]
    plan = dict(request=request, fps=DRAFT_FPS, source_frames=receipt["frames"], base=os.path.relpath(base, out),
                base_sha256=receipt["video_sha256"])
    if pause:
        extra, at = (float(value.replace(",", ".")) for value in pause.groups())
        changes = extend_pause(part, at, extra, receipt["frames"])
        plan.update(operation="extend_pause", at=at, extra_seconds=extra, shifted_effects=changes)
        return episode, plan, None

    quoted, plain, seconds = accent.groups()
    target = quoted or plain
    at = float(seconds.replace(",", "."))
    effect, frames = add_accent(part.get("scene", {}), target, at, receipt["frames"])
    plan.update(operation="accent", effect=effect, frames=frames)
    manifest = dict(schema_version=1, request=request, base=plan["base"],
                    base_sha256=plan["base_sha256"], insert="edit/insert.mp4",
                    replace_at=frames[0], out="revision.mp4")
    return episode, plan, manifest


def effect_seconds(effect):
    preset = effect.get("fx")
    return PULSE_SECONDS if preset == "pulse" else effect.get("dur") or EFFECT_SECONDS[preset]


def add_accent(picture, target, at, total_frames):
    items = [item for item in picture.get("items", []) if item.get("id") == target]
    if len(items) != 1:
        raise ValueError(f"В сцене нужен ровно один элемент верхнего уровня с ID {target}")
    entrance = items[0].get("in")
    if isinstance(entrance, dict):
        entrance = entrance.get("fx")
    if entrance in ("pop", "slam", "stamp"):
        raise ValueError("Для этого элемента уже задано появление с изменением масштаба")
    for existing in picture.get("fx", []):
        preset = existing.get("fx")
        if existing.get("target") != target or preset not in ("move", "pulse", "pop", "slam", "stamp"):
            continue
        start = existing.get("at") or 0
        length = effect_seconds(existing)
        if (type(start) not in (int, float) or type(length) not in (int, float)
                or start < at + PULSE_SECONDS and start + length > at):
            raise ValueError("Акцент может пересечься с существующим изменением масштаба")

    # Include a boundary frame on each side of the tween where possible.
    first = max(0, math.ceil(at * DRAFT_FPS) - 1)
    stop = math.ceil((at + PULSE_SECONDS) * DRAFT_FPS) + 1
    if stop > total_frames:
        raise ValueError("Акцент с возвратом в исходную позу должен помещаться в предпросмотр")
    effect = dict(target=target, fx="pulse", at=at, to=1.16)
    picture.setdefault("fx", []).append(effect)
    return effect, (first, stop)


def static_items(items, inherited=None):
    for item in items:
        node = dict(inherited or {}, **item)
        if (node.get("type", "text") not in ("text", "panel", "row", "col", "shape", "number", "chip", "stamp")
                or node.get("in") or node.get("start") is not None):
            return False
        if not static_items(node.get("items") or (), node.get("child")):
            return False
    return True


def extend_pause(part, at, extra, total_frames):
    if not 0 < extra <= 10 or at >= total_frames / DRAFT_FPS:
        raise ValueError("Пауза должна начинаться внутри ролика и прибавлять не более 10 секунд")
    picture = part.get("scene", {})
    if (picture.get("camera") is not False or part.get("voice") or part.get("voice_file")
            or part.get("sfx") or picture.get("sounds") or picture.get("cues")
            or not static_items(picture.get("items") or ())):
        raise ValueError("Для продления паузы нужна сцена без речи, звуков, движения камеры и таймеров элементов")
    changed = []
    for index, effect in enumerate(picture.get("fx", [])):
        start = effect.get("at", 0)
        if start is None:
            start = 0
        if (effect.get("fx") not in EFFECT_SECONDS or effect.get("stagger")
                or type(start) not in (int, float) or not math.isfinite(start) or start < 0):
            raise ValueError("Для продления паузы нужны поддерживаемые эффекты с числовым временем")
        duration = effect_seconds(effect)
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Для продления паузы нужна положительная длительность эффектов")
        if start < at < start + duration:
            raise ValueError(f"На {at:g} с ещё идёт эффект {effect['fx']}. Укажите время между эффектами")
        if start >= at:
            effect["at"] = round(start + extra, 9)
            changed.append(dict(index=index, before=start, after=effect["at"]))
    part["hold"] = round(float(part.get("hold", 0)) + extra, 9)
    return changed
