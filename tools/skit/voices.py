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
    """Робот Windows: голос по имени (часть имени, например «Pavel») или первый русский. Текст — через файл в UTF-8:
    через stdin PowerShell читал его в кодировке консоли, и робот проговаривал по буквам кракозябры."""
    txt = out + ".txt"
    open(txt, "w", encoding="utf-8").write(text)
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v = $s.GetInstalledVoices() | % { $_.VoiceInfo } | ? { $_.Culture.Name -eq 'ru-RU' }; "
          f"$p = $v | ? {{ $_.Name -like '*{voice or ''}*' }} | select -First 1; if (-not $p) {{ $p = $v | select -First 1 }}; "
          "if ($p) { $s.SelectVoice($p.Name) }; $s.Rate = 1; "
          f"$t = [IO.File]::ReadAllText('{txt}', [Text.Encoding]::UTF8); "
          f"$s.SetOutputToWaveFile('{out}'); $s.Speak($t); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    finally:
        os.remove(txt)


def _edge(text, voice, out):
    import video
    video.tts(text, out, voice=voice if voice and "Neural" in voice else None)


def _game(text, name, out):
    """Реплика героя из игры (выгружена в _game/vo/, tools/skit/game_vo.py) — копия файла."""
    import shutil
    sys.path.insert(0, HERE); import game_vo
    src = game_vo.path(name)
    if not os.path.exists(src):
        raise SystemExit(f"нет реплики {name}: py -3.11 tools/skit/game_vo.py <герой> (выгрузка из русской озвучки)")
    shutil.copy(src, out)


def fish_key():
    """Ключ Fish: из окружения или из настроек Windows (setx пишет туда — приложение видит его только после перезапуска)."""
    k = os.environ.get("FISH_API_KEY")
    if not k and os.name == "nt":
        import winreg
        try:
            k = winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment"), "FISH_API_KEY")[0]
        except OSError:
            k = None
    return (k or "").strip() or None


def _fishref(text, hero, out):
    """Голос героя на любой текст: мгновенное клонирование Fish по образцу из его русской озвучки (game_vo.reference),
    бесплатная модель s2.1-pro-free — без своей модели и без баланса API."""
    import urllib.request, ormsgpack
    sys.path.insert(0, HERE); import game_vo
    wav, txt = game_vo.reference(hero)
    payload = {"text": text, "format": "mp3", "references": [{"audio": open(wav, "rb").read(), "text": txt}]}
    req = urllib.request.Request("https://api.fish.audio/v1/tts", data=ormsgpack.packb(payload), method="POST",
                                 headers={"Authorization": "Bearer " + fish_key(), "Content-Type": "application/msgpack", "model": "s2.1-pro-free"})
    open(out, "wb").write(urllib.request.urlopen(req, timeout=180).read())


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


_ASR = []


def heard(wav, say):
    """Распознать реплику (faster-whisper, если есть) и сравнить с текстом: (распознано, совпадение 0…1) или None.
    Звук на слух не проверить — так ловится озвучка не того текста (кракозябры, обрыв)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    import difflib, re
    if not _ASR:
        _ASR.append(WhisperModel("small", device="cpu", compute_type="int8"))
    segs, _ = _ASR[0].transcribe(wav, language="ru")
    txt = " ".join(s.text.strip() for s in segs)
    norm = lambda x: re.sub(r"[^а-яё]", "", x.lower().replace("ё", "е"))
    return txt, difflib.SequenceMatcher(None, norm(txt), norm(say)).ratio()


def make(folder, lines):
    """lines — [{name, who, text, voice}]; voice — словарь {fish|sapi|edge: имя} или строка. Возвращает voices.json."""
    os.makedirs(folder, exist_ok=True)
    db_path = os.path.join(folder, "voices.json")
    db = json.load(open(db_path, encoding="utf-8")) if os.path.exists(db_path) else {}
    eng0 = engine()
    for ln in lines:
        v = ln.get("voice") or {}
        pitch = float(v.get("pitch", 0)) if isinstance(v, dict) else 0.0   # сдвиг тона, полутоны (один голос Windows — разные герои)
        eng = eng0
        if isinstance(v, dict) and eng0 not in v and "edge" in v and eng0 != "fake":   # у героя свой голос (Edge) — им, а не общим
            eng = "edge"
        if isinstance(v, dict) and "ref" in v and eng0 != "fake" and fish_key():   # голос героя по образцу его озвучки (Fish)
            eng = "fishref"
        if ln.get("game"):                                     # настоящая реплика героя из русской озвучки (tools/skit/game_vo.py)
            eng = "game"
        v = v.get("ref" if eng == "fishref" else eng, "") if isinstance(v, dict) else v
        if eng == "game":
            v = ln["game"]
        import video
        say = video.say_text(ln["text"])                       # {7.33|семь тридцать три} → как произносить
        key = hashlib.md5(f"{eng}|{v}|{say}|{pitch if eng != 'game' else 0}".encode()).hexdigest()[:12]
        wav = os.path.join(folder, ln["name"] + ".wav")
        if db.get(ln["name"], {}).get("key") == key and os.path.exists(wav):
            continue
        raw = os.path.join(folder, ln["name"] + (".raw.wav" if eng in ("sapi", "fake") else ".raw.mp3"))
        print(f"  голос {ln['name']} ({ln['who']}, {eng}{' ' + v if v else ''}): {say}")
        {"fish": _fish, "sapi": _sapi, "edge": _edge, "fake": _fake, "game": _game, "fishref": _fishref}[eng](say, v, raw)
        if pitch and eng != "game":
            r = 2 ** (pitch / 12); shifted = raw + ".p.wav"
            subprocess.run([_ff(), "-y", "-v", "error", "-i", raw, "-af", f"aresample={SR},asetrate={SR}*{r:.4f},aresample={SR},atempo={1 / r:.4f}", shifted], check=True)
            os.replace(shifted, raw) if raw.endswith(".wav") else (os.remove(raw), os.rename(shifted, raw + ".wav")); raw = raw if raw.endswith(".wav") else raw + ".wav"
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
        h = heard(wav, say) if eng != "fake" else None         # гул проверки (SKIT_FAKE) — не речь
        if h:
            print(f"    распознано: «{h[0]}» — совпадение {h[1]:.0%}" + ("  ⚠ ГОЛОС НЕ СОВПАЛ С ТЕКСТОМ" if h[1] < 0.6 else ""))
        db[ln["name"]] = {"text": video.show_text(ln["text"]), "say": say, "env": [round(float(x), 3) for x in env],
                          "dur": round(len(a) / SR, 3), "who": ln["who"], "voice": f"{eng}:{v}", "key": key}
    json.dump(db, open(db_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return db


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    make(sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")))
