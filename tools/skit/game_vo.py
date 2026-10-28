# Реплики героев из русской озвучки доты: выгрузка из пакета игры и каталог с текстом (распознавание faster-whisper).
# Файлы игры — только локально, в _game/vo/ (в репозиторий не коммитить). В сценарии: «| реплика pud_kill_05» —
# вместо синтеза звучит настоящая реплика героя (tools/skit/voices.py), субтитры — текст из сценария.
#   py -3.11 tools/skit/game_vo.py pudge sniper           выгрузить и распознать → _game/vo/<герой>.json {файл: текст}
#   py -3.11 tools/skit/game_vo.py find pudge мясо        поиск по тексту каталога
#   голос героя на любой текст — мгновенное клонирование Fish по образцу из его реплик (reference, бесплатная модель):
#   в сценарии «голос sniper ref=sniper» (tools/skit/voices.py)
#   py -3.11 tools/skit/game_vo.py clone sniper           свой закрытый голос на Fish из ~минуты спокойной речи героя (нужен баланс API)
#                                                         (id → _game/vo/fish_voices.json; в сценарии: голос sniper fish=<id>)
import glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
from paths import DOTA_ROOT, S2V
VO = os.path.join(REPO, "_game", "vo")
PAK = os.path.join(DOTA_ROOT, "game", "dota_russian", "pak01_dir.vpk")
PREFIX = {"pudge": "pud_", "sniper": "snip_", "tidehunter": "tide_"}


def path(name):
    """Файл реплики по имени (pud_kill_05) — mp3 из выгрузки."""
    hero = next((h for h, p in PREFIX.items() if name.startswith(p)), name.split("_")[0])
    return os.path.join(VO, "sounds", "vo", hero, name + ".mp3")


def extract(hero):
    d = os.path.join(VO, "sounds", "vo", hero)
    if not glob.glob(os.path.join(d, "*.mp3")):
        subprocess.run([S2V, "-i", PAK, "--vpk_filepath", f"sounds/vo/{hero}/", "-o", VO, "-d"], check=True, capture_output=True)
    return sorted(glob.glob(os.path.join(d, "*.mp3")))


def catalog(hero):
    out = os.path.join(VO, hero + ".json")
    db = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    files = [f for f in extract(hero) if os.path.splitext(os.path.basename(f))[0] not in db]
    if files:
        from faster_whisper import WhisperModel
        m = WhisperModel("small", device="cpu", compute_type="int8")
        for i, f in enumerate(files):
            segs, _ = m.transcribe(f, language="ru", beam_size=3, vad_filter=False)
            db[os.path.splitext(os.path.basename(f))[0]] = " ".join(s.text.strip() for s in segs).strip()
            if i % 25 == 0:
                json.dump(db, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print(f"  {hero}: {len(db)}", flush=True)
        json.dump(db, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return db


# образец для клона — реплики с верным текстом (распознавание каталога ошибается: «крайне амеро», «Яуна» — с неверным
# текстом образца клон звучит плохо, участник: «у Снайпера голос плохой»); отсылки к другим играм (tf2) — не брать
REF_LINES = {
    "sniper": {
        "snip_spawn_07": "Привет, я Снайпер! Добро пожаловать на стрельбище!",
        "snip_rare_01": "Твоя смерть многим пойдёт на пользу. Почти всем.",
        "snip_rare_04": "Почему я улыбаюсь? Потому что люблю свою работу!",
        "snip_respawn_10": "Не могу удержаться от выстрела на удачу.",
        "snip_rare_03": "Умирать легко. Сейчас продемонстрирую.",
        "snip_kill_14": "Тяжко в перестрелке без огнестрела, а?",
        "snip_kill_blade_03": "Кто-то пришёл на перестрелку с ножом!",
        "snip_kill_07": "Твоя жизнь — всего лишь вспышка боли!",
        "snip_death_09": "Уйду из жизни под звуки выстрелов!",
        "snip_kill_arrow_07": "За огнестрелом будущее, мой друг.",
        "snip_spawn_06": "Вокруг меня всегда свистят пули.",
    },
}


def reference(hero, seconds=22):
    """Образец голоса героя для мгновенного клонирования Fish: ~22 с спокойной речи из его русской озвучки
    → (_game/vo/ref_<герой>.wav, текст образца). Строится один раз."""
    import re
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    wav, txt_path = os.path.join(VO, f"ref_{hero}.wav"), os.path.join(VO, f"ref_{hero}.json")
    if os.path.exists(wav) and os.path.exists(txt_path):
        return wav, json.load(open(txt_path, encoding="utf-8"))["text"]
    db = catalog(hero)
    laugh = re.compile(r"(х[еа]-?){2,}|([аоуыэ])\2{2,}|[аоуэ]-[аоуэ]-")
    good = list(REF_LINES[hero].items()) if hero in REF_LINES else \
        sorted(((k, v) for k, v in db.items() if len(re.findall(r"[а-яё]+", v.lower())) >= 4 and not laugh.search(v.lower())
                and not any(x in k for x in ("pain", "death", "laugh", "attack", "fail", "shrapnel", "devour"))), key=lambda x: -len(x[1]))
    files, texts, total = [], [], 0.0
    for k, v in good:
        p = path(k)
        m = os.path.exists(p) and re.search(r"Duration: (\d+):(\d+):([\d.]+)", subprocess.run([FF, "-i", p], capture_output=True, text=True, errors="replace").stderr)
        if not m:
            continue
        files.append(p); texts.append(v); total += float(m[3])
        if total >= seconds:
            break
    lst = os.path.join(VO, f"ref_{hero}.lst")
    open(lst, "w", encoding="utf-8").write("".join(f"file '{os.path.abspath(f)}'\n" for f in files))
    subprocess.run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-ac", "1", "-ar", "44100", wav], check=True)
    json.dump({"text": " ".join(texts), "files": [os.path.basename(f) for f in files], "seconds": round(total, 1)},
              open(txt_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return wav, " ".join(texts)


def clone(hero, seconds=70):
    """Голос героя на Fish Audio по образцам его русской озвучки: спокойные реплики (без смеха и криков), ~70 с."""
    import re, uuid, urllib.request, urllib.error, winreg
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    db = catalog(hero)
    laugh = re.compile(r"(х[еа]-?){2,}|([аоуыэ])\2{2,}|[аоуэ]-[аоуэ]-|!.*!")
    good = sorted(((k, v) for k, v in db.items() if len(re.findall(r"[а-яё]+", v.lower())) >= 4 and not laugh.search(v.lower())
                   and not any(x in k for x in ("pain", "death", "laugh", "attack", "fail", "shrapnel"))), key=lambda x: -len(x[1]))
    take, total = [], 0.0
    for k, v in good:
        info = subprocess.run([FF, "-i", path(k)], capture_output=True, text=True, errors="replace").stderr
        dm = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
        if not os.path.exists(path(k)) or not dm:
            continue
        hh, mm, ss = dm.groups()
        take.append((k, v)); total += int(hh) * 3600 + int(mm) * 60 + float(ss)
        if total >= seconds or len(take) >= 20:               # у Fish не больше 20 образцов
            break
    files, texts = [path(k) for k, _ in take], [v for _, v in take]
    print(f"  {hero}: образцов {len(files)}, {total:.0f} с")
    key = os.environ.get("FISH_API_KEY") or winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment"), "FISH_API_KEY")[0]
    b = uuid.uuid4().hex; body = b""; NL = "\r\n"

    def field(n, v):
        return f"--{b}{NL}Content-Disposition: form-data; name=\"{n}\"{NL}{NL}{v}{NL}".encode()
    for n, v in (("visibility", "private"), ("type", "tts"), ("title", f"a8 {hero} (dota ru)"), ("train_mode", "fast"), ("enhance_audio_quality", "true")):
        body += field(n, v)
    for f, t in zip(files, texts):
        body += f"--{b}{NL}Content-Disposition: form-data; name=\"voices\"; filename=\"{os.path.basename(f)}\"{NL}Content-Type: audio/mpeg{NL}{NL}".encode()
        body += open(f, "rb").read() + NL.encode() + field("texts", t)
    body += f"--{b}--{NL}".encode()
    req = urllib.request.Request("https://api.fish.audio/model", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + key.strip(), "Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        m = json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Fish отказал ({e.code}): {e.read().decode(errors='replace')[:1500]}")
    out = os.path.join(VO, "fish_voices.json")
    ids = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    ids[hero] = m["_id"]; json.dump(ids, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  {hero}: голос Fish {m['_id']} ({m.get('state')})")
    return m["_id"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if a[:1] == ["find"]:
        db = json.load(open(os.path.join(VO, a[1] + ".json"), encoding="utf-8"))
        q = " ".join(a[2:]).lower()
        for k, v in db.items():
            if q in v.lower() or q in k:
                print(k.ljust(28), v)
        return
    if a[:1] == ["clone"]:
        for hero in a[1:]:
            clone(hero)
        return
    for hero in a:
        print(hero, "реплик:", len(catalog(hero)))


if __name__ == "__main__":
    main()
