# Голоса сценки: каждая реплика — wav + огибающая громкости 30 раз в секунду (по ней рот, мимика и субтитры).
# Пишет <папка>/<реплика>.wav и <папка>/voices.json: {реплика: {text — для субтитров, say — как произносится, env, dur, who, voice}}.
# Чем озвучивать (по очереди, что доступно):
#   Fish Audio — если задан FISH_API_KEY (голос героя — id модели fish.audio из сценария);
#   робот Windows (System.Speech, русский голос — Павел/Ирина) — если это Windows;
#   edge-tts (ru-RU-DmitryNeural / SvetlanaNeural) — иначе.
# Готовые реплики не переозвучиваются, пока не изменились текст и голос (ключ — в voices.json).
#   py -3.11 tools/skit/voices.py <папка> <реплики.json>   — [{name, who, text, voice}]
import hashlib, json, os, subprocess, sys, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
SR = 48000
SIL = 0.02                         # тише этого (доля пика) — тишина по краям, обрезается


def _ff():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _pcm(path):
    raw = subprocess.run([_ff(), "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def _fish(text, voice, out):
    import video
    video.tts_fish(text, out, voice=voice, align=False)


def _sapi(text, voice, out):
    """Робот Windows: голос по имени (часть имени, например «Pavel») или первый русский."""
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v = $s.GetInstalledVoices() | % { $_.VoiceInfo } | ? { $_.Culture.Name -eq 'ru-RU' }; "
          f"$p = $v | ? {{ $_.Name -like '*{voice or ''}*' }} | select -First 1; if (-not $p) {{ $p = $v | select -First 1 }}; "
          "if ($p) { $s.SelectVoice($p.Name) }; $s.Rate = 1; "
          f"$s.SetOutputToWaveFile('{out}'); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], input=text.encode("utf-8"), check=True)


def _edge(text, voice, out):
    import video
    video.tts(text, out, voice=voice if voice and "Neural" in voice else None)


def _fake(text, voice, out):
    """Проверка без голоса (SKIT_FAKE=1): гул с громкостью по слогам, 0,075 с на букву."""
    t = np.arange(int(0.075 * len(text) * SR)) / SR
    a = 0.3 * np.sin(2 * np.pi * 140 * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 4 * t)) ** 2
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((a * 32767).astype(np.int16).tobytes())


def engine():
    if os.environ.get("SKIT_FAKE"):
        return "fake"
    if os.environ.get("FISH_API_KEY"):
        return "fish"
    return "sapi" if os.name == "nt" else "edge"


def make(folder, lines):
    """lines — [{name, who, text, voice}]; voice — словарь {fish|sapi|edge: имя} или строка. Возвращает voices.json."""
    os.makedirs(folder, exist_ok=True)
    db_path = os.path.join(folder, "voices.json")
    db = json.load(open(db_path, encoding="utf-8")) if os.path.exists(db_path) else {}
    eng = engine()
    for ln in lines:
        v = ln.get("voice") or {}
        v = v.get(eng, "") if isinstance(v, dict) else v
        import video
        say = video.say_text(ln["text"])                       # {7.33|семь тридцать три} → как произносить
        key = hashlib.md5(f"{eng}|{v}|{say}".encode()).hexdigest()[:12]
        wav = os.path.join(folder, ln["name"] + ".wav")
        if db.get(ln["name"], {}).get("key") == key and os.path.exists(wav):
            continue
        raw = os.path.join(folder, ln["name"] + (".raw.wav" if eng in ("sapi", "fake") else ".raw.mp3"))
        print(f"  голос {ln['name']} ({ln['who']}, {eng}{' ' + v if v else ''}): {say}")
        {"fish": _fish, "sapi": _sapi, "edge": _edge, "fake": _fake}[eng](say, v, raw)
        a = _pcm(raw); os.remove(raw)
        # тишина по краям — прочь: время реплики в сценке = время звука
        on = np.where(np.abs(a) > SIL * max(1e-6, np.abs(a).max()))[0]
        if len(on):
            a = a[max(0, on[0] - int(0.03 * SR)): on[-1] + int(0.08 * SR)]
        with wave.open(wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
        # огибающая: громкость кадра (30 в секунду) к 95-му перцентилю, 0…1
        hop = SR // 30; n = len(a) // hop + 1
        rms = np.array([np.sqrt(np.mean(a[i * hop:(i + 1) * hop] ** 2)) if len(a[i * hop:(i + 1) * hop]) else 0 for i in range(n)])
        env = np.clip(rms / max(1e-6, np.percentile(rms, 95)), 0, 1)
        db[ln["name"]] = {"text": video.show_text(ln["text"]), "say": say, "env": [round(float(x), 3) for x in env],
                          "dur": round(len(a) / SR, 3), "who": ln["who"], "voice": f"{eng}:{v}", "key": key}
    json.dump(db, open(db_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return db


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    make(sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")))
