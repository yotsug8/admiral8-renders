"""Run one command in a fresh output directory; verify delivery, not visual quality.

The child keeps the caller's cwd. Pass its output path explicitly in command.
No shell, installation, cleanup, retries or background scheduling is performed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def stamp():
    return datetime.now(timezone.utc).isoformat()


def run(out, expected, command, reserve_mb=2048, timeout=None):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Output directory already exists; choose a new attempt')
    if not command or not expected:
        raise ValueError('Command and expected artifacts are required')
    if not math.isfinite(reserve_mb) or reserve_mb < 0:
        raise ValueError('Reserve must be finite and nonnegative')
    if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('Timeout must be finite and positive')
    artifacts = []
    for name in expected:
        p = (out / name).resolve()
        if p == out or not p.is_relative_to(out) or p.name in ('process.log', 'run.json', 'run.json.tmp'):
            raise ValueError('Expected artifacts must stay inside output directory and not be run logs')
        artifacts.append(p)
    ancestor = out.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    # Blender can write to TEMP even when the output goes to another volume.
    for location in {ancestor, Path(tempfile.gettempdir()).resolve()}:
        if shutil.disk_usage(location).free < reserve_mb * 1024**2:
            raise ValueError(f'Insufficient free space at {location}; reserve={reserve_mb:g} MiB')
    out.mkdir(parents=True, exist_ok=False)
    state = dict(status='starting', command=command, started_at=stamp(),
                 expected=[str(p.relative_to(out)) for p in artifacts],
                 reserve_mb=reserve_mb, quality_accepted=False)

    def save():
        temp = out / 'run.json.tmp'
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temp.replace(out / 'run.json')

    save()
    started = time.monotonic()
    process = None
    try:
        with (out / 'process.log').open('wb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, shell=False)
            state.update(status='running', pid=process.pid)
            save()
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError('Command timed out; direct child stopped')
        state['exit_code'] = code
        if code != 0:
            raise RuntimeError(f'Command failed with exit code {code}')
        evidence = []
        for p in artifacts:
            reserved = [out / name for name in ('process.log', 'run.json', 'run.json.tmp')]
            if (not p.resolve().is_relative_to(out) or not p.is_file() or p.stat().st_size == 0
                    or any(log.exists() and p.samefile(log) for log in reserved)):
                raise RuntimeError(f'Missing, empty or redirected artifact: {p.name}')
            h = hashlib.sha256()
            with p.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
            evidence.append(dict(path=str(p.relative_to(out)), bytes=p.stat().st_size, sha256=h.hexdigest()))
        state.update(status='artifacts_verified', artifacts=evidence)
        return state
    except (OSError, RuntimeError, KeyboardInterrupt) as exc:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        state.update(status='failed', error=str(exc), exit_code=process.returncode if process else None)
        raise
    finally:
        state.update(finished_at=stamp(), elapsed_seconds=round(time.monotonic()-started, 3))
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--expect', action='append', required=True)
    parser.add_argument('--reserve-mb', type=float, default=2048)
    parser.add_argument('--timeout', type=float)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    try:
        result = run(args.out, args.expect, command, args.reserve_mb, args.timeout)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'RUN_FAILED: {exc}', file=sys.stderr)
        return 1
    print(f"ARTIFACTS_VERIFIED: {len(result['artifacts'])}; visual/audio review still required")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
