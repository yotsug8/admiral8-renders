"""Make a local footfall cue from the evaluated sole of the Rain lightcase study."""

import argparse
import json
from pathlib import Path
import wave

import numpy as np


FPS = 30
RATE = 48_000
FRAMES = 180
GROUND_M = .00115
SUPPORT_TOLERANCE_M = .002


def landing_frame(report):
    """Locate the first sustained return to support after the recovery step."""
    if report.get("passed") is not True:
        raise ValueError("Use a passing preflight report")
    rows = report["frames"][:FRAMES]
    if [row["frame"] for row in rows] != list(range(FRAMES)):
        raise ValueError("Preflight must cover every frame of the clip")
    heights = np.array([row["sole_z_m"]["R"] for row in rows], dtype=float)
    if not np.isfinite(heights).all():
        raise ValueError("Sole heights must be finite")
    apex = int(np.argmax(heights))
    if heights[apex] - GROUND_M < .02:
        raise ValueError("No airborne recovery step")
    for frame in range(apex + 1, FRAMES - 2):
        if np.all(np.abs(heights[frame:frame + 3] - GROUND_M) <= SUPPORT_TOLERANCE_M):
            return frame
    raise ValueError("Recovery step does not return to support")


def write_footfall(path, frame):
    time = np.arange(RATE * 14 // 100) / RATE
    noise = np.random.default_rng(92).uniform(-1, 1, len(time))
    tread = np.convolve(noise, np.ones(9) / 9, mode="same")
    sole = .24 * np.sin(2 * np.pi * 94 * time) * np.exp(-42 * time)
    floor = .09 * np.sin(2 * np.pi * 168 * time) * np.exp(-66 * time)
    texture = .22 * tread * np.exp(-92 * time)
    attack = np.minimum(time / .002, 1)
    tail = np.clip((.14 - time) / .02, 0, 1)
    impact = (sole + floor + texture) * attack * tail

    start = frame * (RATE // FPS)
    samples = np.zeros(FRAMES * (RATE // FPS), dtype="<i2")
    samples[start:start + len(impact)] = np.round(32767 * impact).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        output.writeframes(samples.tobytes())
    return start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preflight", type=Path)
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()
    report = json.loads(args.preflight.read_text(encoding="utf-8"))
    frame = landing_frame(report)
    if frame * (RATE // FPS) + RATE * 14 // 100 > FRAMES * (RATE // FPS):
        parser.error("Footfall tail exceeds the exported clip")
    sample = write_footfall(args.wav, frame)
    print(f"Landing frame {frame}, sample {sample}, {sample / RATE:.6f} s")


if __name__ == "__main__":
    main()
