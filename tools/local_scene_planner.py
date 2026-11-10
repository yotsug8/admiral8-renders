"""Turn a bounded free-text brief into an editable Blender shot plan on CPU."""

import argparse
import json
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryFile
import time
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


MAX_REQUEST_LENGTH = 600
COLORS = {
    "red": [.57, .045, .036], "green": [.065, .49, .20], "blue": [.048, .25, .69],
    "orange": [.76, .26, .044], "purple": [.38, .10, .58], "white": [.78, .79, .74],
    "yellow": [.69, .56, .045], "black": [.026, .031, .043],
}
SHAPES = {"ball": "sphere", "cube": "box", "cylinder": "cylinder", "crystal": "ico"}
MOTIONS = ("up", "down", "left", "right", "hold")
SHAPE_WORDS = {"ball": r"шар\w*|balls?", "cube": r"куб\w*|cubes?",
               "cylinder": r"цилиндр\w*|cylinders?", "crystal": r"кристалл\w*|crystals?"}
COLOR_WORDS = {
    "red": r"красн\w*|red", "green": r"зел[её]н\w*|green", "blue": r"син\w*|blue",
    "orange": r"оранжев\w*|orange", "purple": r"фиолетов\w*|purple", "white": r"бел\w*|white",
    "yellow": r"ж[её]лт\w*|yellow", "black": r"ч[её]рн\w*|black",
}


def choices(values):
    return {"type": "string", "enum": list(values)}


def record(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


SCHEMA = record({
    "status": choices(("plan", "reject")),
    "reason": {"type": "string", "maxLength": 160},
    "aspect": choices(("portrait", "landscape")),
    "seconds": {"type": "integer", "minimum": 2, "maximum": 6},
    "order": choices(("sequential", "simultaneous")),
    "sound": {"type": "boolean"},
    "close_up": {"type": "integer", "minimum": 0, "maximum": 3},
    "objects": {"type": "array", "maxItems": 3,
                "items": record({"shape": choices(SHAPES), "color": choices(COLORS),
                                 "motion": choices(MOTIONS)})},
})
INSTRUCTIONS = """Translate the Russian or English user brief into the given JSON schema.
The only supported scene is a fixed studio setup showing one to three colored
geometric objects on simple pedestals. Each can rise, descend, move a short distance
left or right, or stay still. Motion can happen one after another or together.
Support portrait or landscape, 2 to 6 whole seconds, silence or a simple signal tone.
Use close_up=0 for one wide shot. Only when requested, support two shots:
a wide shot followed by a close-up of one named object. Set close_up to that
object's one-based index in objects. Reject other shot structures or ambiguous
close-up subjects.
Reject any requested people, animals, dialogue, music, captions, imported assets,
other shapes/colors, physics, repeated motion or extra shots. Do not approximate
unsupported requirements. For rejection use status=reject, objects=[], a short
reason in Russian, and defaults landscape, 3, sequential, false, 0 for other fields.
For a valid request use status=plan and reason="". Use landscape, 3 seconds and no
sound if unspecified. List objects in requested order. Translate "шар" as ball,
"куб" as cube, "кристалл" as crystal, "цилиндр" as cylinder.
Translate adjectives literally and keep each motion paired with its subject.
Before choosing close_up, identify the named subject after "крупный план".
Example input: "Белый куб поднимается. Общий план, потом крупный план куба".
Example output: {"status":"plan","reason":"","aspect":"landscape","seconds":3,
"order":"sequential","sound":false,"close_up":1,"objects":[{"shape":"cube","color":"white",
"motion":"up"}]}."""

ACTION_SCHEMA = record({
    "status": choices(("plan", "reject")),
    "reason": {"type": "string", "maxLength": 160},
    "aspect": choices(("portrait", "landscape")),
    "seconds": {"type": "integer", "minimum": 3, "maximum": 5},
    "gesture": choices(("nod", "shake")),
    "side": choices(("left", "right")),
    "color": choices(("blue", "green", "yellow", "red")),
})
ACTION_INSTRUCTIONS = """Plan a silent studio shot of Rain noticing a signal lamp
and then either nodding once or shaking her head. The brief must name Rain
(Рейн), a lamp and the gesture. Fill the color and screen side literally.
Support one fixed shot, no other characters, speech, music, props in the hand,
or extra actions. Reject these unsupported requests without approximating.
Defaults: 3 seconds, horizontal. Use reason="" for a valid plan.
Кивает means nod; качает головой means shake; справа means right.
Example: "Рейн замечает зелёный индикатор слева и качает головой. Без звука."
Output: {"status":"plan","reason":"","aspect":"landscape","seconds":3,
"gesture":"shake","side":"left","color":"green"}."""

CONTACT_SCHEMA = record({
    "status": choices(("plan", "reject")),
    "reason": {"type": "string", "maxLength": 160},
    "aspect": choices(("portrait", "landscape")),
    "hold": choices(("half_second", "one_second")),
    "sound": {"type": "boolean"},
})
CONTACT_INSTRUCTIONS = """Составь JSON-план сценки о роботе и кнопке сброса.
Поддерживаются два формата: portrait (вертикальный) и landscape (горизонтальный).
Робот может заметить красный сигнал, подойти, нажать и удерживать кнопку,
а при зелёном сигнале отпустить её. Эти детали разрешены, но необязательны в запросе.
Допустимы полсекунды (half_second) и одна секунда (one_second) удержания.
По умолчанию landscape, half_second, sound=true. Фраза «без звука» даёт sound=false.
Отклоняй посторонние действия, других персонажей, речь, музыку, титры и другие сроки.
У подходящего запроса status="plan" и reason="".
Пример: «Вертикальный ролик. Робот нажимает кнопку сброса и держит одну секунду».
Ответ: {"status":"plan","reason":"","aspect":"portrait","hold":"one_second","sound":true}.
Пример: «Робот полсекунды удерживает кнопку. Без звука».
Ответ: {"status":"plan","reason":"","aspect":"landscape","hold":"half_second","sound":false}."""

PUSH_SCHEMA = record({
    "status": choices(("plan", "reject")),
    "distance_cm": {"type": "integer", "enum": [10, 20]},
})
PUSH_INSTRUCTIONS = """Составь JSON-план немой горизонтальной сценки. Один робот
подходит к ящику, толкает его ладонью на 10 или 20 см и убирает руку.
Ящик остаётся на полу. Разрешены описания этих фаз. Отклоняй подъём,
других персонажей, прочие действия, дистанции, форматы и звук.
Пример: «Робот подходит и ладонью сдвигает ящик на 20 см. Без звука».
Ответ: {"status":"plan","distance_cm":20}.
Пример: «Робот толкает ящик на десять сантиметров».
Ответ: {"status":"plan","distance_cm":10}."""

LIFT_SCHEMA = record({"status": choices(("plan", "reject")),
                      "pause_frames": {"type": "integer", "enum": [9, 18]}})
LIFT_INSTRUCTIONS = """План немой горизонтальной сценки с Рейн. Она берётся за
ручку чемодана, ждёт 0,3 или 0,6 секунды, затем поднимает чемодан и ловит равновесие.
Длительность паузы до подъёма: 0,3 секунды = 9 кадров, 0,6 = 18 кадров.
Отклоняй речь, звук, другие действия, персонажей, ракурсы и сроки.
Пример: «Рейн берётся за ручку чемодана, ждёт 0,3 секунды и поднимает его. Без звука».
Ответ: {"status":"plan","pause_frames":9}."""

SEQUENCE_ITEM = record({"shape": choices(SHAPES), "color": choices(COLORS),
                        "motion": choices(MOTIONS), "seconds": {"type": "integer", "minimum": 2, "maximum": 6},
                        "sound": {"type": "boolean"}})
SEQUENCE_SCHEMA = record({"status": choices(("plan", "reject")),
                          "aspect": choices(("portrait", "landscape")),
                          "scenes": {"type": "array", "maxItems": 3, "items": SEQUENCE_ITEM}})
SEQUENCE_INSTRUCTIONS = """Составь JSON для ролика из 2 или 3 пронумерованных сцен.
Каждая «Сцена 1:», «Сцена 2:» и «Сцена 3:» задаёт отдельный план с одним цветным
геометрическим предметом. Сохрани порядок. Общий формат landscape или portrait.
Длительность каждой сцены 2–6 целых секунд, по умолчанию 2. Звук по умолчанию false.
«Со звуковым сигналом» означает sound=true только для этой сцены.
Формы: шар ball, куб cube, цилиндр cylinder, кристалл crystal.
Движения: поднимается up, опускается down, влево left, вправо right, стоит hold.
Отклоняй людей, диалоги, текст, музыку, другие действия или несколько предметов в сцене.
Пример: «Горизонтально. Сцена 1: красный шар поднимается, 2 секунды, без звука.
Сцена 2: синий куб опускается, 3 секунды, со звуковым сигналом».
Ответ: {"status":"plan","aspect":"landscape","scenes":[
{"shape":"ball","color":"red","motion":"up","seconds":2,"sound":false},
{"shape":"cube","color":"blue","motion":"down","seconds":3,"sound":true}]}."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def infer(request, runtime, model, *, character=False, contact=False, push=False, lift=False,
          sequence=False, contract=None, max_tokens=320):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    token = secrets.token_hex(16)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    instructions, schema = INSTRUCTIONS, SCHEMA
    if character:
        instructions, schema = ACTION_INSTRUCTIONS, ACTION_SCHEMA
    if contact:
        instructions, schema = CONTACT_INSTRUCTIONS, CONTACT_SCHEMA
    if push:
        instructions, schema = PUSH_INSTRUCTIONS, PUSH_SCHEMA
    if lift:
        instructions, schema = LIFT_INSTRUCTIONS, LIFT_SCHEMA
    if sequence:
        instructions, schema = SEQUENCE_INSTRUCTIONS, SEQUENCE_SCHEMA
    if contract:
        instructions, schema = contract
    payload = {
        "messages": [{"role": "system", "content": instructions},
                     {"role": "user", "content": request}],
        "temperature": 0, "seed": 19, "max_tokens": max_tokens, "stream": False,
        "response_format": {"type": "json_object", "schema": schema},
    }
    command = [str(runtime), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
               "--api-key", token, "-ngl", "0", "-c", "2048", "-t", "4", "-np", "1"]
    with TemporaryFile() as log, subprocess.Popen(
        command, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as server:
        try:
            ready_until = time.monotonic() + 45
            while time.monotonic() < ready_until and server.poll() is None:
                try:
                    with opener.open(url + "/health", timeout=1):
                        break
                except (URLError, TimeoutError):
                    time.sleep(.15)
            else:
                raise RuntimeError("Локальная модель не загрузилась. Проверьте GGUF и память.")
            query = Request(url + "/v1/chat/completions", data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
            with opener.open(query, timeout=120) as response:
                choice = json.loads(response.read(65536))["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("Модель не завершила план")
            return json.loads(choice["message"]["content"])
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def validate_intent(result):
    required = SCHEMA["properties"].keys() - {"close_up"}
    if not isinstance(result, dict) or not required <= result.keys() <= SCHEMA["properties"].keys():
        raise ValueError("Модель вернула неполный план")
    if result["status"] == "reject":
        reason = result["reason"]
        raise ValueError("Запрос вне возможностей планировщика. " + (reason if isinstance(reason, str) else ""))
    objects = result["objects"]
    focus = result.get("close_up", 0)
    if (result["status"] != "plan" or result["reason"] != "" or not isinstance(objects, list)
            or not 1 <= len(objects) <= 3 or type(result["seconds"]) is not int or not 2 <= result["seconds"] <= 6
            or result["aspect"] not in ("portrait", "landscape") or type(result["sound"]) is not bool
            or type(focus) is not int or not 0 <= focus <= len(objects)
            or result["order"] not in ("sequential", "simultaneous")):
        raise ValueError("Модель вернула неподдерживаемый план")
    for item in objects:
        if (not isinstance(item, dict) or item.keys() != {"shape", "color", "motion"}
                or item["shape"] not in SHAPES or item["color"] not in COLORS or item["motion"] not in MOTIONS):
            raise ValueError("Форма, цвет или движение выходят за поддерживаемый набор")


def named_values(words, request):
    return {name for name, pattern in words.items()
            if re.search(rf"\b(?:{pattern})\b", request, re.IGNORECASE)}


def compile_action(request, result):
    if (not isinstance(result, dict) or result.keys() != ACTION_SCHEMA["properties"].keys()
            or result["status"] != "plan" or not isinstance(result["reason"], str)):
        raise ValueError("Нужен запрос на реакцию Rain на световой сигнал")
    request_words = {
        "gesture": {"nod": r"кив\w*|nod\w*", "shake": r"кач\w* головой|shake\w* (?:her |the )?head"},
        "side": {"left": r"слева|лев\w*|left", "right": r"справа|прав\w*|right"},
        "color": COLOR_WORDS,
    }
    if (not re.search(r"\b(?:Rain|Рейн)\b", request, re.IGNORECASE)
            or not re.search(r"\b(?:ламп\w*|lamp|индикатор\w*)\b", request, re.IGNORECASE)):
        raise ValueError("Назовите Rain и сигнальную лампу")
    if re.search(r"\b(?:говорит|произносит|держит|бер[её]т|по[её]т|speaks|says|holds|takes|sings)\b",
                 request, re.IGNORECASE):
        raise ValueError("Поддерживается немая реакция без предмета в руках")
    for field, vocabulary in request_words.items():
        explicit = named_values(vocabulary, request)
        if result[field] not in ACTION_SCHEMA["properties"][field]["enum"] or explicit != {result[field]}:
            raise ValueError(f"Модель не подтвердила параметр действия: {field}")
    orientations = named_values({
        "portrait": r"вертикальн\w*|portrait|9\s*:\s*16",
        "landscape": r"горизонтальн\w*|landscape|16\s*:\s*9",
    }, request)
    if len(orientations) > 1 or result["aspect"] not in ("portrait", "landscape"):
        raise ValueError("Нужна одна ориентация кадра")
    aspect = next(iter(orientations), result["aspect"])
    seconds = result["seconds"]
    durations = {float(value.replace(",", ".")) for value in re.findall(
        r"(?<![\d.,-])(\d+(?:[,.]\d+)?)\s*(?:секунд\w*|seconds?)\b", request, re.IGNORECASE)}
    if (type(seconds) is not int or not 3 <= seconds <= 5 or len(durations) > 1
            or any(value not in (3, 4, 5) for value in durations)):
        raise ValueError("Длительность действия должна быть от 3 до 5 целых секунд")
    seconds = int(next(iter(durations), seconds))
    return dict(schema_version=1, request=request, actor="rain", gesture=result["gesture"],
                signal=dict(side=result["side"], color=result["color"], frame=14),
                size=[432, 768] if aspect == "portrait" else [640, 360],
                fps=30, frames=seconds * 30)


def compile_contact(request, result):
    if (not isinstance(result, dict) or result.keys() != CONTACT_SCHEMA["properties"].keys()
            or result["status"] != "plan" or result["reason"] != ""
            or result["aspect"] not in ("portrait", "landscape")
            or result["hold"] not in ("half_second", "one_second") or type(result["sound"]) is not bool):
        raise ValueError("Поддерживается сцена, где робот нажимает и удерживает кнопку сброса")
    if not all(re.search(pattern, request, re.IGNORECASE) for pattern in
               (r"\bробот\w*", r"\bкнопк\w*", r"\b(?:нажим|нажм|нажа|удерж)\w*")):
        raise ValueError("Назовите робота и действие с кнопкой")
    content = re.sub(r"\bбез (?:речи|реплик|музыки|титров|субтитров)\b", "", request, flags=re.IGNORECASE)
    if re.search(r"\b(?:говор\w*|произнос\w*|речь|реплик\w*|музык\w*|титр\w*|субтитр\w*)\b",
                 content, re.IGNORECASE):
        raise ValueError("Для этой сцены доступны звуки действий, речь и титры не поддерживаются")
    holds = named_values({"half_second": r"полсекунды|0[.,]5\s+секунд\w*",
                          "one_second": r"(?:одну\s+)?секунду|1\s+секунд\w*"}, request)
    numbers = {float(value.replace(",", ".")) for value in re.findall(
        r"(?<![\d.,-])(\d+(?:[,.]\d+)?)\s*секунд\w*\b", request, re.IGNORECASE)}
    has_duration = re.search(r"\bсекунд\w*\b", request, re.IGNORECASE)
    if (len(holds) > 1 or numbers - {0.5, 1.0} or (has_duration and not holds)
            or (holds and holds != {result["hold"]})):
        raise ValueError("Подтвердите удержание кнопки на полсекунды или секунду")
    orientations = named_values({"portrait": r"вертикальн\w*|9\s*:\s*16",
                                 "landscape": r"горизонтальн\w*|16\s*:\s*9"}, request)
    if len(orientations) > 1:
        raise ValueError("Нужна одна ориентация кадра")
    return dict(schema_version=1, request=request, actor="robot", action="reset_button",
                aspect=next(iter(orientations), result["aspect"]),
                hold_frames=15 if result["hold"] == "half_second" else 30,
                sound=result["sound"] and not re.search(r"\bбез (?:звука|аудио)\b", request, re.IGNORECASE))


def compile_push(request, result):
    if (not isinstance(result, dict) or result.keys() != PUSH_SCHEMA["properties"].keys()
            or result["status"] != "plan" or type(result["distance_cm"]) is not int
            or result["distance_cm"] not in (10, 20)):
        raise ValueError("Поддерживается немая сцена, где робот толкает ящик по полу на 10 или 20 см")
    if not all(re.search(pattern, request, re.IGNORECASE) for pattern in
               (r"\bробот\w*", r"\bящик\w*", r"\b(?:толк\w*|сдвиг\w*|сдвин\w*)")):
        raise ValueError("Назовите робота, ящик и толчок")
    content = re.sub(r"\bбез (?:звука|аудио|музыки|речи)\b", "", request, flags=re.IGNORECASE)
    if re.search(r"\b(?:подним\w*|поднят\w*|перенос\w*|нес[её]т|говор\w*|произнос\w*|"
                 r"вертикальн\w*|звук\w*|аудио|музык\w*|титр\w*)\b|\b9\s*:\s*16", content, re.IGNORECASE):
        raise ValueError("Для толчка поддерживается горизонтальная немая сцена с ящиком на полу")
    values = {word.casefold() for word in re.findall(
        r"(?<![\w.,-])(\d+(?:[.,]\d+)?|десять|двадцать)\s*(?:см|сантиметр\w*)\b", request, re.IGNORECASE)}
    words = {10: {"10", "десять"}, 20: {"20", "двадцать"}}
    if not values or values - words[result["distance_cm"]]:
        raise ValueError("Подтвердите расстояние толчка: 10 или 20 см")
    return dict(schema_version=1, request=request, actor="robot", action="push_crate",
                distance_cm=result["distance_cm"])


def compile_lift(request, result):
    if (not isinstance(result, dict) or result.keys() != LIFT_SCHEMA["properties"].keys()
            or result["status"] != "plan" or type(result["pause_frames"]) is not int
            or result["pause_frames"] not in (9, 18)):
        raise ValueError("Поддерживается немая сценка, где Рейн поднимает чемодан после паузы")
    if not all(re.search(pattern, request, re.IGNORECASE) for pattern in
               (r"\b(?:Рейн|Rain)\b", r"\bчемодан\w*", r"\bподн(?:им|ят)\w*", r"\b(?:жд[её]т|пауз\w*)\b")):
        raise ValueError("Назовите Рейн, чемодан, паузу и подъём")
    content = re.sub(r"\bбез (?:звука|аудио|музыки|речи)\b", "", request, flags=re.IGNORECASE)
    if re.search(r"\b(?:брос\w*|ставит|опуска\w*|переда\w*|говор\w*|произнос\w*|"
                 r"вертикальн\w*|звук\w*|аудио|музык\w*|титр\w*)\b|\b9\s*:\s*16", content, re.IGNORECASE):
        raise ValueError("Для подъёма поддерживается немая горизонтальная сцена с одним чемоданом")
    values = {value.replace(',', '.') for value in re.findall(
        r"(?<![\w.,-])(\d+(?:[.,]\d+)?)\s*секунд\w*\b", request, re.IGNORECASE)}
    expected = {9: '0.3', 18: '0.6'}[result['pause_frames']]
    if values != {expected}:
        raise ValueError("Подтвердите паузу перед подъёмом: 0,3 или 0,6 секунды")
    return dict(schema_version=1, request=request, actor="rain", action="lift_case",
                pause_frames=result['pause_frames'])


def verify_objects(request, items):
    shapes = named_values(SHAPE_WORDS, request)
    colors = named_values(COLOR_WORDS, request)
    if ((shapes and shapes != {item["shape"] for item in items})
            or (colors and colors != {item["color"] for item in items})):
        raise ValueError("Модель изменила названные формы или цвета")


def verify_close_up(subject_text, items, focus):
    subject = re.split(r"[.!?;,:]", subject_text, maxsplit=1)[0]
    shapes = named_values(SHAPE_WORDS, subject)
    colors = named_values(COLOR_WORDS, subject)
    candidates = [i for i, item in enumerate(items, 1)
                  if item["shape"] in shapes and (not colors or item["color"] in colors)]
    if candidates != [focus]:
        raise ValueError("Модель не подтвердила названный предмет крупного плана")


def compile_plan(request, result):
    validate_intent(result)
    orientations = {
        name for name, pattern in (
            ("portrait", r"\b(?:вертикальн\w*|portrait)\b|\b9\s*:\s*16\b"),
            ("landscape", r"\b(?:горизонтальн\w*|landscape)\b|\b16\s*:\s*9\b"),
        ) if re.search(pattern, request, re.IGNORECASE)
    }
    seconds = {float(value.replace(",", ".")) for value in re.findall(
        r"(?<![\d.,-])(\d+(?:[,.]\d+)?)\s*(?:секунд\w*|seconds?)\b", request, re.IGNORECASE
    )}
    if len(orientations) > 1 or len(seconds) > 1 or any(not 2 <= value <= 6 or not value.is_integer()
                                                       for value in seconds):
        raise ValueError("Нужны одна ориентация и целая длительность от 2 до 6 секунд")
    count = 24 * int(next(iter(seconds), result["seconds"]))
    portrait = next(iter(orientations), result["aspect"]) == "portrait"
    sound = result["sound"] and not re.search(r"\b(?:без звука|без аудио|silent|no sound)\b", request, re.IGNORECASE)
    wants_close = re.search(r"\b(?:крупн\w*\s+план\w*|close[- ]up)\b", request, re.IGNORECASE)
    wants_wide = re.search(r"\b(?:общ\w*\s+план\w*|wide shot)\b", request, re.IGNORECASE)
    wants_two = re.search(r"\b(?:два|двух|2|two)\s+(?:план\w*|shots?)\b", request, re.IGNORECASE)
    wants_one = re.search(r"\b(?:один|1|one)\s+(?:план\w*|shot)\b", request, re.IGNORECASE)
    focus = result.get("close_up", 0) if wants_close else 0
    if ((wants_close or wants_two) and not focus
            or (focus and (wants_one or not wants_wide or wants_wide.start() > wants_close.start()))):
        raise ValueError("Для двух планов укажите общий план и назовите предмет для крупного")
    together = re.search(r"\b(?:одновременно|вместе|simultaneously|together)\b", request, re.IGNORECASE)
    sequence = r"по очереди|поочер[её]дно|one after another"
    if not focus:
        sequence += r"|затем|потом|then"
    one_by_one = re.search(rf"\b(?:{sequence})\b", request, re.IGNORECASE)
    if together and one_by_one:
        raise ValueError("Уточните, двигать предметы одновременно или по очереди")
    order = "simultaneous" if together else "sequential" if one_by_one else result["order"]
    items = result["objects"]
    verify_objects(request, items)
    if wants_close:
        verify_close_up(request[wants_close.end():], items, focus)
    coats = {"Floor": {"rgb": [.061, .084, .13], "roughness": .75},
             "Pedestal": {"rgb": [.17, .22, .30], "metal": .4, "roughness": .44}}
    objects = [dict(name="Studio floor", kind="box", position=[0, 0, -.08],
                    size=[400, 400, .16], material="Floor")]
    checks, cues = [], []
    moves = sum(item["motion"] != "hold" for item in items)
    available = count - (20 if focus else 14)
    length = available // moves if order == "sequential" and moves else available
    move_index = 0
    subject = None
    other_end = 1
    for i, item in enumerate(items):
        x = (i - (len(items) - 1) / 2) * (1.90 if focus else 1.20)
        objects.append(dict(name=f"Pedestal {i + 1}", kind="cylinder", position=[x, 0, .15],
                            size=[1.0, .84, .30], material="Pedestal"))
        name, color, motion = f"Object {i + 1}", item["color"], item["motion"]
        coats[color] = {"rgb": COLORS[color], "metal": .22, "roughness": .32}
        start = [x, 0, .58]
        end = start.copy()
        if motion == "up":
            end[2] += .59
        elif motion == "down":
            start[2] += .59
        elif motion in ("left", "right"):
            end[0] += -.20 if motion == "left" else .20
        obj = dict(name=name, kind=SHAPES[item["shape"]], position=start, size=[.56, .56, .56], material=color)
        if motion != "hold":
            first = 7 + (move_index * length if order == "sequential" else 0)
            last = first + length
            obj["positions"] = [[1, start], [first, start], [last, end]]
            if sound and last not in {cue[0] for cue in cues}:
                cues.append([last, .16, 420 + 70 * move_index, .14])
            if i + 1 != focus:
                other_end = max(other_end, last + 1)
            move_index += 1
        if i + 1 == focus:
            subject = obj
        objects.append(obj)
        checks.append(dict(kind="in_frame", object=name, frames=[1, count], minimum=.045))
    wide_lens = (44 if len(items) <= 2 else 34) if portrait else 49
    if focus:
        wide_lens = (37 if len(items) <= 2 else 25) if portrait else (45 if len(items) <= 2 else 39)
    shots = [dict(name="Studio view", frame=1,
                  position=[1.35, -5.95, 3.75] if portrait else [1.7, -6.8, 2.9],
                  target=[0, 0, .63], lens=wide_lens)]
    if subject is not None:
        positions = subject.get("positions")
        cut = max(count // 4, positions[1][0]) if positions else count // 2
        if order == "sequential":
            cut = max(cut, other_end)
        start = subject["position"]
        end = positions[-1][1] if positions else start
        x = (start[0] + end[0]) / 2
        z = (start[2] + end[2]) / 2
        shots.append(dict(name="Object close-up", frame=cut,
                          position=[x, -2.60, 1.72] if portrait else [x, -3.75, 1.78],
                          target=[x, 0, z], lens=48 if portrait else 53))
        for check in checks:
            if check["object"] != subject["name"]:
                check["frames"][1] = cut - 1
    return dict(schema_version=1, request=request, size=[432, 768] if portrait else [640, 360],
                fps=24, frames=count, materials=coats, objects=objects, checks=checks, cues=cues,
                shots=shots,
                lights=[[[-3, -4, 5], [0, 0, .4], 1050, 4, [1, .86, .72]],
                        [[2, -2, 4], [0, 0, .5], 760, 3, [.64, .84, 1]],
                        [[0, 3, 4], [0, 0, .7], 940, 3, [.54, .82, 1]]])


SCENE_LABEL = re.compile(r"\bсцена\s+(\d+)\s*[:.]\s*", re.IGNORECASE)
SEQUENCE_MOTIONS = {"up": r"поднима\w*|вверх", "down": r"опуска\w*|вниз",
                    "left": r"влево|налево", "right": r"вправо|направо",
                    "hold": r"стоит|оста[её]тся на месте|не движется|неподвиж\w*"}


def compile_sequence(request, result):
    labels = list(SCENE_LABEL.finditer(request))
    if len(labels) not in (2, 3) or [match[1] for match in labels] != [str(i) for i in range(1, len(labels)+1)]:
        raise ValueError("Укажите две или три сцены подряд в формате «Сцена 1: … Сцена 2: …»")
    if (not isinstance(result, dict) or result.keys() != SEQUENCE_SCHEMA["properties"].keys()
            or result["status"] != "plan" or result["aspect"] not in ("landscape", "portrait")
            or not isinstance(result["scenes"], list) or len(result["scenes"]) != len(labels)):
        raise ValueError("Модель не подтвердила список сцен")
    prefix = request[:labels[0].start()]
    if re.search(r"\b\d+(?:[.,]\d+)?\s*секунд\w*\b", prefix, re.IGNORECASE):
        raise ValueError("Укажите длительность внутри каждой сцены")
    scenes = []
    for i, (label, item) in enumerate(zip(labels, result["scenes"], strict=True)):
        end = labels[i+1].start() if i+1 < len(labels) else len(request)
        text = request[label.end():end].strip()
        if (not isinstance(item, dict) or item.keys() != SEQUENCE_ITEM["properties"].keys()
                or type(item["seconds"]) is not int or not 2 <= item["seconds"] <= 6
                or type(item["sound"]) is not bool):
            raise ValueError(f"Неполный план сцены {i+1}")
        for field, words in (("shape", SHAPE_WORDS), ("color", COLOR_WORDS), ("motion", SEQUENCE_MOTIONS)):
            if item[field] not in words or named_values(words, text) != {item[field]}:
                raise ValueError(f"Не подтверждён предмет или движение в сцене {i+1}")
        if re.search(r"\b(?:крупн\w*\s+план\w*|два\s+план\w*|музык\w*|реплик\w*|субтитр\w*)\b", text, re.IGNORECASE):
            raise ValueError(f"Сцена {i+1} поддерживает один план и простой звуковой сигнал")
        intent = dict(status="plan", reason="", aspect=result["aspect"], seconds=item["seconds"],
                      order="sequential", sound=item["sound"],
                      objects=[{field: item[field] for field in ("shape", "color", "motion")}])
        scene = compile_plan(f"{prefix} {text}".strip(), intent)
        if re.search(r"\b(?:со звуком|со звуковым сигналом)\b", text, re.IGNORECASE) and not scene["cues"]:
            raise ValueError(f"Модель пропустила звуковой сигнал в сцене {i+1}")
        scenes.append(scene)
    if len({tuple(scene["size"]) for scene in scenes}) != 1:
        raise ValueError("Для монтажа нужен общий формат всех сцен")
    return dict(schema_version=1, request=request, scenes=scenes)


def plan_request(request, runtime, model, profile):
    request = request.strip()
    if not 1 <= len(request) <= MAX_REQUEST_LENGTH:
        raise ValueError(f"Нужен запрос до {MAX_REQUEST_LENGTH} символов")
    if profile in ("objects", "sequence") and (
        not named_values(SHAPE_WORDS, request)
        or re.search(r"\b(?:интервью|диалог\w*|озвуч\w*|субтитр\w*|реплик\w*|музык\w*"
                     r"|interview|dialogue|voiceover|subtitles?|music)\b", request, re.IGNORECASE)
    ):
        raise ValueError("Опишите сцену с шаром, кубом, цилиндром или кристаллом. "
                         "Диалоги, музыка и субтитры пока недоступны в этом режиме.")
    compilers = {"objects": compile_plan, "rain": compile_action, "contact": compile_contact,
                 "push": compile_push, "lift": compile_lift, "sequence": compile_sequence}
    result = infer(request, runtime.resolve(strict=True), model.resolve(strict=True),
                   character=profile == "rain", contact=profile == "contact",
                   push=profile == "push", lift=profile == "lift", sequence=profile == "sequence")
    return compilers[profile](request, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True, help="Local llama-server executable")
    parser.add_argument("--model", type=Path, required=True, help="Local instruction model in GGUF")
    parser.add_argument("--request", required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--character", action="store_true", help="Plan Rain's response to a signal lamp")
    modes.add_argument("--contact", action="store_true", help="Plan a robot pressing and holding a reset button")
    modes.add_argument("--push", action="store_true", help="Plan a robot pushing a crate along the floor")
    modes.add_argument("--lift", action="store_true", help="Plan Rain lifting a case after a pause")
    modes.add_argument("--sequence", action="store_true", help="Plan two or three geometric scenes in order")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.out.suffix.lower() != ".json" or args.out.exists():
            raise ValueError("Нужен новый выходной файл JSON")
        profiles = ((args.character, "rain"), (args.contact, "contact"),
                    (args.push, "push"), (args.lift, "lift"), (args.sequence, "sequence"))
        profile = next((name for enabled, name in profiles if enabled), "objects")
        plan = plan_request(args.request, args.runtime, args.model, profile)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(plan, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(args.out.resolve())
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        sys.exit(f"План не создан. {exc}")


if __name__ == "__main__":
    main()
