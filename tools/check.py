# Проверка всего репозитория одной командой — после любой правки, до коммита:
#   python tools/check.py            все выпуски (быстрая проверка без голоса: ключевые кадры, раскладка, метки) + логика сценок
#   python tools/check.py demo_layouts        только выбранные выпуски
# Выпуски без нужных ресурсов пропускаются. Код 1 — ошибки, 2 — неполная проверка/блокировка.
import argparse
import glob, json, os, re, subprocess, sys
from contextlib import contextmanager

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BAD = re.compile(r"⚠|НЕ НАЙДЕНО|Traceback|Error|ПРОВЕРКА|ВНИМАНИЕ|JS-ошибка")


@contextmanager
def exclusive_check(path=None):
    """Protect shared QA/cache outputs; OS releases the lock on process exit."""
    path = path or os.path.join(REPO, 'qa', 'check.lock')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            acquire = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as exc:
            raise RuntimeError('Check lock unavailable: another check may be running; do not delete its lock file') from exc
        try:
            yield
        finally:
            lock.seek(0)
            release()


def run(cmd, env):
    r = subprocess.run(cmd, cwd=REPO, env=dict(os.environ, PYTHONUTF8="1", **env), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    lines, after = [], False
    for l in out.splitlines():
        if BAD.search(l) or (after and l.startswith("   ")):          # после «ПРОВЕРКА РАСКЛАДКИ» — список нарушений
            lines.append(l.strip())
        after = after or "ПРОВЕРКА РАСКЛАДКИ" in l
    if r.returncode and not lines:
        lines.append(next((line.strip() for line in reversed(out.splitlines()) if line.strip()),
                          f"Процесс завершился с кодом {r.returncode}"))
    return r.returncode, lines


def needs_game(path):
    with open(path, encoding="utf-8") as source:
        data = json.load(source)
    def visit(value):
        if isinstance(value, dict):
            return value.get('type') in ('model', 'stage') or any(visit(v) for v in value.values())
        if isinstance(value, list):
            return any(visit(v) for v in value)
        return isinstance(value, str) and value.replace('\\', '/').startswith(('game:', 'file:_game/'))
    return visit(data)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Проверка выпусков и сценариев")
    parser.add_argument("prefix", nargs="*", help="Проверить только выпуски с указанными префиксами")
    parser.add_argument("--troupe", type=os.path.abspath,
                        help="Справочник героев для тестовой сборки сценок")
    parser.add_argument("--frames-dir", type=os.path.abspath,
                        help="Дополнительно сохранить отдельные контрольные кадры в указанную папку")
    args = parser.parse_args()
    pick = args.prefix
    if args.troupe and (pick or not os.path.isfile(args.troupe)):
        parser.error("--troupe требует существующий файл и запуск без выбора выпусков")
    troupe = args.troupe or os.path.join(REPO, "_game", "data", "troupe.json")
    eps = sorted(glob.glob(os.path.join(REPO, "episodes", "*.json")))
    if pick:
        eps = [e for e in eps if any(os.path.basename(e).startswith(p) for p in pick)]
        missing = [p for p in pick if not any(os.path.basename(e).startswith(p) for e in eps)]
        if missing:
            print("итог: не найдены выпуски:", ', '.join(missing))
            sys.exit(2)
    os.makedirs(os.path.join(REPO, "qa"), exist_ok=True)
    fails = tested = skipped = 0
    for e in eps:
        name = os.path.splitext(os.path.basename(e))[0]
        if needs_game(e) and not os.path.isdir(os.path.join(REPO, "_game")):
            skipped += 1
            print(f"{name}: пропуск — нужны файлы игры (_game/)"); continue
        code, lines = run([sys.executable, "video.py", e, f"qa/check_{name}.mp4"],
                          {"FV_SILENT": "1", "FV_QA_ONLY": "1", "FV_QA_DIR": args.frames_dir or "", "FV_WORKERS": "2"})
        ok = code == 0 and not lines
        tested += 1
        fails += not ok
        print(f"{name}: {'ок' if ok else 'ПРОБЛЕМЫ'}")
        for l in lines:
            print("   ", l)
    for sk in [] if pick else sorted(glob.glob(os.path.join(REPO, "skits", "*.txt"))):
        name = os.path.basename(sk)
        if not os.path.isfile(troupe):
            skipped += 1
            print(f"сценка {name}: пропуск — нет _game/data/troupe.json (tools/dota_engine/troupe.py)"); continue
        code, lines = run([sys.executable, "tools/skit/skit.py", sk, "--plan"],
                          {"SKIT_FAKE": "1", "SKIT_CHECK_TROUPE": args.troupe or ""})
        lines = [l for l in lines if "ground.npz" not in l]          # без карты земли — плоско, это не ошибка
        ok = code == 0 and not lines
        tested += 1
        fails += not ok
        print(f"сценка {name}: {'ок' if ok else 'ПРОБЛЕМЫ'}")
        for l in lines:
            print("   ", l)
    print(f"покрытие: выполнено {tested}, пропущено {skipped}")
    if fails:
        print(f"итог: проблем: {fails}")
        sys.exit(1)
    if not tested or skipped:
        print("итог: неполная проверка")
        sys.exit(2)
    print("итог: всё в порядке")
    sys.exit(0)


if __name__ == "__main__":
    try:
        with exclusive_check():
            main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
