# Реплики героев из русской озвучки доты: выгрузка из пакета игры и каталог с текстом (распознавание faster-whisper).
# Файлы игры — только локально, в _game/vo/ (в репозиторий не коммитить). В сценарии: «| реплика pud_kill_05» —
# вместо синтеза звучит настоящая реплика героя (tools/skit/voices.py), субтитры — текст из сценария.
#   py -3.11 tools/skit/game_vo.py pudge sniper           выгрузить и распознать → _game/vo/<герой>.json {файл: текст}
#   py -3.11 tools/skit/game_vo.py find pudge мясо        поиск по тексту каталога
import glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
from paths import DOTA_ROOT, S2V
VO = os.path.join(REPO, "_game", "vo")
PAK = os.path.join(DOTA_ROOT, "game", "dota_russian", "pak01_dir.vpk")
PREFIX = {"pudge": "pud_", "sniper": "snip_"}


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
    for hero in a:
        print(hero, "реплик:", len(catalog(hero)))


if __name__ == "__main__":
    main()
