# Голоса сценки: каждая реплика — wav + огибающая громкости 30 раз в секунду (по ней рот, мимика и субтитры).
# Пишет <папка>/<реплика>.wav и <папка>/voices.json: {реплика: {text — для субтитров, say — как произносится, env, dur, who, voice}}.
# Чем озвучивать (по очереди, что доступно):
#   Fish Audio — если задан FISH_API_KEY (голос героя — id модели fish.audio из сценария);
#   робот Windows (System.Speech, русский голос — Павел/Ирина) — если это Windows;
#   edge-tts (ru-RU-DmitryNeural / SvetlanaNeural) — иначе.
# SKIT_LOCAL_TTS=1 — только локальный SAPI на Windows и явные игровые реплики.
# Готовые реплики не переозвучиваются, пока не изменились текст и голос (ключ — в voices.json).
#   py -3.11 tools/skit/voices.py <папка> <реплики.json>   — [{name, who, text, voice}]
import hashlib, json, os, subprocess, sys, wave
from tempfile import NamedTemporaryFile
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
    key = fish_key()
    if not key:
        raise RuntimeError('Fish API key is unavailable')
    # video caches its environment at import time; registry-only keys must reach
    # the actual backend, including recursive synthesis of split phrases.
    previous = video.FISH_KEY
    try:
        video.FISH_KEY = key
        video.tts_fish(text, out, voice=voice, align=False)
    finally:
        video.FISH_KEY = previous


def _sapi(text, voice, out, *, visemes=None):
    """Записать WAV и при необходимости метки формы рта из того же синтеза."""
    ps = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = $speaker.GetInstalledVoices() |
        Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'ru-RU' }
    $selected = $voices | Where-Object {
        !$env:A8_SAPI_VOICE -or
        $_.VoiceInfo.Name.IndexOf($env:A8_SAPI_VOICE, [StringComparison]::OrdinalIgnoreCase) -ge 0
    } | Select-Object -First 1
    if (!$selected) { $selected = $voices | Select-Object -First 1 }
    if (!$selected) { throw 'No enabled ru-RU SAPI voice is installed.' }
    $speaker.SelectVoice($selected.VoiceInfo.Name)
    $speaker.Rate = 1
    $line = [IO.File]::ReadAllText($env:A8_SAPI_TEXT, [Text.Encoding]::UTF8)
    $speaker.SetOutputToWaveFile($env:A8_SAPI_WAV)
    if ($env:A8_SAPI_VISEMES) {
        $assembly = [System.Speech.Synthesis.SpeechSynthesizer].Assembly.Location
        Add-Type -ReferencedAssemblies $assembly -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Speech.Synthesis;
public static class A8VisemeCapture {
    public static string[] Speak(SpeechSynthesizer speaker, string text) {
        var rows = new List<string>();
        speaker.VisemeReached += (sender, e) => rows.Add(String.Format(
            CultureInfo.InvariantCulture, "{0},{1}", e.AudioPosition.Ticks, e.Viseme));
        speaker.Speak(text);
        return rows.ToArray();
    }
}
"@
        $events = [A8VisemeCapture]::Speak($speaker, $line)
        if (!$events) { throw 'The selected voice returned no viseme events.' }
        [IO.File]::WriteAllLines($env:A8_SAPI_VISEMES, $events)
    } else {
        $speaker.Speak($line)
    }
} finally {
    $speaker.Dispose()
}
"""
    with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False) as source:
        try:
            source.write(text)
            source.close()
            env = dict(os.environ, A8_SAPI_TEXT=source.name, A8_SAPI_WAV=os.path.abspath(out),
                       A8_SAPI_VOICE=voice or "",
                       A8_SAPI_VISEMES=os.path.abspath(visemes) if visemes else "")
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           env=env, check=True)
        finally:
            source.close()
            os.remove(source.name)


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
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
                k = winreg.QueryValueEx(handle, "FISH_API_KEY")[0]
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
    if os.environ.get("SKIT_LOCAL_TTS"):
        if os.name != "nt":
            raise RuntimeError("SKIT_LOCAL_TTS требует Windows и русский голос SAPI")
        return "sapi"
    if fish_key():
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
    db = {}
    if os.path.exists(db_path):
        with open(db_path, encoding='utf-8') as source:
            db = json.load(source)
    eng0 = engine()
    local_tts = bool(os.environ.get("SKIT_LOCAL_TTS"))
    for ln in lines:
        v = ln.get("voice") or {}
        pitch = float(v.get("pitch", 0)) if isinstance(v, dict) else 0.0   # сдвиг тона, полутоны (один голос Windows — разные герои;
                                                                            # голос героя по образцу — без сдвига: Снайпер звучал выше себя)
        eng = eng0
        if not local_tts and isinstance(v, dict) and eng0 not in v and "edge" in v and eng0 != "fake":
            eng = "edge"
        if not local_tts and isinstance(v, dict) and "ref" in v and eng0 != "fake" and fish_key():
            eng = "fishref"
        if ln.get("game") and eng0 != "fake":                  # настоящая реплика нужна только вне проверки плана
            eng = "game"
        v = v.get("ref" if eng == "fishref" else eng, "") if isinstance(v, dict) else v
        if eng in ("fishref", "fish"):
            pitch = 0.0
        if eng == "game":
            v = ln["game"]
        import video
        say = video.say_text(ln["text"])                       # {7.33|семь тридцать три} → как произносить
        refv = ""
        if eng == "fishref":
            # Validate the reference language even when synthesized speech is
            # cached; a cache hit must not bypass the Russian-voice contract.
            reference_wav, _ = __import__("game_vo").reference(v)
            if v in __import__("game_vo").REF_LINES:
                refv = open(os.path.join(REPO, "_game", "vo", f"ref_{v}.json"), encoding="utf-8").read()
            else:
                # A newly verified Russian reference must not inherit speech
                # synthesized from an older English reference for this hero.
                # Legacy entries without provenance are deliberately invalidated.
                with open(reference_wav, "rb") as source:
                    refv = "audio-sha256:" + hashlib.sha256(source.read()).hexdigest()
        key = hashlib.md5(f"{eng}|{v}|{say}|{pitch if eng != 'game' else 0}{'|' + refv if refv else ''}".encode()).hexdigest()[:12]
        wav = os.path.join(folder, ln["name"] + ".wav")
        if db.get(ln["name"], {}).get("key") == key and os.path.exists(wav):
            db[ln["name"]].update(text=video.show_text(ln["text"]), say=say,
                                  who=ln["who"], voice=f"{eng}:{v}")
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
        h = heard(wav, say) if eng != "fake" and not local_tts else None
        if h:
            print(f"    распознано: «{h[0]}» — совпадение {h[1]:.0%}" + ("  ⚠ ГОЛОС НЕ СОВПАЛ С ТЕКСТОМ" if h[1] < 0.6 else ""))
        db[ln["name"]] = {"text": video.show_text(ln["text"]), "say": say, "env": [round(float(x), 3) for x in env],
                          "dur": round(len(a) / SR, 3), "who": ln["who"], "voice": f"{eng}:{v}", "key": key}
    with open(db_path, "w", encoding="utf-8") as output:
        json.dump(db, output, ensure_ascii=False, indent=1)
    return db


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    make(sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")))
