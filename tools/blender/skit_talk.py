# Анимации разговора для любой сценки (tools/skit/skit.py) — исполняется внутри render_scene.py и anim_to_dmx.py
# (там есть arm, sc, ACTS, FPS). Что делать — из A8_TALK (JSON, список на одного актёра):
#   {name, base, line, off, dur, jaw, head, mood}
#   base — стойка, line — реплика (громкость из A8_VOICES), off — когда в анимации начинается голос, dur — длина;
#   jaw — кость челюсти (есть у Пуджа, Акса, Тайда; нет — говорит головой), head — кость головы;
#   mood — «down»: опускает голову (сник), «up»: задирает подбородок (хвастается), иначе ровно.
# Кивки, сглаживание и приглушённое качание стойки — из hook_talk.py (подключается как библиотека).
import json, math, os

A8_LIB = True
_lib = os.path.join(os.path.dirname(os.path.abspath(globals().get("__file__", "skit_talk.py"))), "hook_talk.py")
exec(compile(open(_lib, encoding="utf-8").read(), _lib, "exec"))

TALK = json.loads(os.environ.get("A8_TALK", "[]"))
MOOD = {"down": (14, 22), "up": (-5, -9)}              # (шея, голова) в градусах: наклон вперёд +


def speaker(s):
    pose = talker(s["base"], s["line"], s["off"], s["dur"], head=s["head"], jaw=s.get("jaw"),
                  jaw_max=s.get("jaw_max", 22), nod=s.get("nod", 5 if s.get("jaw") else 7), grin=s.get("grin", 0.0))
    neck = next((b.name for b in arm.pose.bones if "neck" in b.name.lower()), None)
    mood = MOOD.get(s.get("mood"))
    loud = smooth_series(voice(s["line"], s["off"]), int(s["dur"] * FPS))
    # без челюсти голова ещё и покачивается в такт речи — слабо и плавно, как Снайпер в «Крюке»
    sway = soft([(0 if s.get("jaw") else 1.6) * loud[k] * math.sin(k / FPS * 4) for k in range(len(loud))])

    def full(t, k):
        pose(t, k)
        if mood:
            d = sm(0.1, 1.1, t)                         # входит в настроение за секунду
            if neck:
                turn(neck, X, R(mood[0] * d))
            turn(s["head"], X, R(mood[1] * d))
        if sway[k]:
            turn(s["head"], X, R(sway[k])); turn(s["head"], Z, R(sway[k] * 0.8))
    return full


CUSTOM = {s["name"]: bake(s["name"], s["dur"], speaker(s)) for s in TALK}
LOOPING = {k: False for k in CUSTOM}
