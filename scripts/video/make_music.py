#!/usr/bin/env python
"""Synthesise the background bed for the tour.

Generated rather than licensed: a stock track means a licence to track and a
file to ship, and this only has to sit under narration without asking for
attention. Everything here is pure synthesis, so it is royalty-free by
construction and can be rendered to whatever length the cut happens to be.

The bed is a slow eight-chord phrase in A minor. Eight rather than four because
the tour runs about two and a half minutes: a four-chord loop comes round five
times and starts to nag, where this comes round twice and reads as one long
idea. Each chord is three sine partials with a little detune plus a root an
octave down, and a soft bell marks the change.

Level follows the film rather than sitting flat — it opens, steps back under the
dense middle where the narration is working hardest, and swells again for the
closing card.

    python scripts/video/make_music.py --seconds 150

Needs numpy (per-sample Python at 48 kHz for two minutes is minutes of work) and
ffmpeg for the final shaping.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD = PROJECT_ROOT / "docs" / "video" / "build"
RATE = 48_000

# Am - F - C - G, then Am - Dm - F - G. The second phrase leaves the tonic
# sooner, which is what stops the repeat sounding like the same bar again.
# Written as frequencies rather than note names so the detune below is obvious.
PROGRESSION: list[tuple[float, ...]] = [
    (220.00, 261.63, 329.63),   # Am
    (174.61, 261.63, 349.23),   # F
    (261.63, 329.63, 392.00),   # C
    (196.00, 246.94, 392.00),   # G
    (220.00, 261.63, 329.63),   # Am
    (146.83, 174.61, 220.00),   # Dm
    (174.61, 261.63, 349.23),   # F
    (196.00, 246.94, 392.00),   # G
]

CHORD_SECONDS = 7.5
#: Crossfade between chords. A chord therefore sounds for CHORD_SECONDS plus
#: this, overlapping its successor for the whole of it — the overlap is what
#: makes the change read as a swell rather than a switch.
CROSSFADE = 2.8
# Working headroom for the synthesis; the real level is set by the normalisation
# below, not here.
PEAK = 0.16
#: What the finished bed is normalised to. The assembler sets the balance
#: against this, so changing the synthesis cannot quietly change the mix.
TARGET_PEAK_DBFS = -3.0


def _chord_envelope(local: np.ndarray, length: float) -> np.ndarray:
    """Equal-power fade in and out, overlapping the neighbouring chords.

    The chord occupies ``length + CROSSFADE``: it rises over the first
    CROSSFADE, holds, then falls over the last CROSSFADE — which is exactly the
    window in which the next chord is rising. Sine against cosine keeps the two
    summing to constant power through the change.

    Fading a chord in and out inside its own slot instead, however gently, puts
    a hole in the bed at every boundary, because both neighbours reach zero at
    the same instant.
    """
    rising = np.sin(np.pi / 2 * np.clip(local / CROSSFADE, 0, 1))
    falling = np.cos(np.pi / 2 * np.clip((local - length) / CROSSFADE, 0, 1))
    inside = (local >= 0) & (local <= length + CROSSFADE)
    return rising * falling * inside


def _arc(t: np.ndarray, seconds: float) -> np.ndarray:
    """Level across the whole piece: in, back for the middle, up for the close.

    The narration is densest through the body, so the bed gives way there and
    only comes forward again once the closing card is on screen.
    """
    opening = np.clip(t / 5.0, 0, 1)                       # fade up under the title
    holding = np.clip((6.0 - t) / 6.0, 0, 1)               # full while the title holds
    closing = np.clip((t - (seconds - 16.0)) / 9.0, 0, 1)  # swell for the outro
    forward = np.maximum(holding, closing)                 # full at both ends, back between
    return opening * (0.70 + 0.30 * forward)


def render(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE), dtype=np.float64) / RATE
    out = np.zeros_like(t)

    length = CHORD_SECONDS
    # One extra slot so the last chord is still fading in at the final sample
    # rather than cutting off mid-swell.
    slots = int(seconds / length) + 2

    for slot in range(slots):
        chord = PROGRESSION[slot % len(PROGRESSION)]
        local = t - slot * length
        envelope = _chord_envelope(local, length)
        if not envelope.any():
            continue

        for partial, frequency in enumerate(chord):
            # A few cents of detune per partial: exact intervals read as
            # synthetic, slightly imperfect ones read as an instrument.
            detune = 1.0 + (partial - 1) * 0.0006
            phase = partial * 1.7 + slot * 0.31
            # Phase runs off global time, so nothing clicks at a chord boundary.
            # Upper partials quieter, as they are in anything acoustic.
            out += np.sin(2 * np.pi * frequency * detune * t + phase) * envelope * (0.5 ** partial)

        # Root an octave down for weight. Without it the bed sits entirely in
        # the same range as the voice.
        out += np.sin(2 * np.pi * (chord[0] / 2) * t) * envelope * 0.45

        # A bell on the change — the only thing in the bed with an attack, and
        # the reason the loop reads as moving rather than holding.
        strike = np.exp(-np.clip(local, 0, None) * 1.3) * ((local >= 0) & (local < length))
        out += np.sin(2 * np.pi * chord[2] * 2 * t) * strike * 0.055

    # A very slow breath across the whole bed, then the arc.
    out *= 0.85 + 0.15 * np.sin(2 * np.pi * t / 19.0)
    out *= _arc(t, seconds)
    out *= PEAK

    return np.clip(out, -1.0, 1.0)


def _ffmpeg(command: list[str], what: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-1500:])
        raise SystemExit(f"ffmpeg failed while {what}")
    return result.stderr


def _peak_dbfs(path: Path) -> float:
    report = _ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        "measuring the bed",
    )
    for line in report.splitlines():
        if "max_volume" in line:
            return float(line.split("max_volume:")[1].split("dB")[0])
    raise SystemExit("could not read the bed's peak level")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--out", default=str(BUILD / "music.wav"))
    args = parser.parse_args()

    BUILD.mkdir(parents=True, exist_ok=True)
    raw = BUILD / "music-raw.wav"
    shaped = BUILD / "music-shaped.wav"
    with wave.open(str(raw), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes((render(args.seconds) * 32767).astype("<i2").tobytes())

    # Soften and widen it. A raw sine stack is harsh in the upper mids and dead
    # centre; the low-pass takes the edge off and the echo gives it some space.
    _ffmpeg(
        ["ffmpeg", "-y", "-i", str(raw),
         "-af", ",".join([
             "lowpass=f=1800",
             # Low enough to let the octave-down roots through: Dm's sits at
             # 73 Hz, and cutting it made that chord noticeably quieter than
             # the rest of the phrase.
             "highpass=f=55",
             "aecho=0.6:0.55:180|340:0.28|0.18",
             "aformat=channel_layouts=stereo",
             "afade=t=in:st=0:d=2.5",
             f"afade=t=out:st={max(args.seconds - 3.0, 0):.2f}:d=3.0",
         ]),
         "-ar", "48000", str(shaped)],
        "shaping the bed",
    )

    # The filter chain above loses several dB in places that are awkward to
    # predict — the echo's input gain most of all. Rather than hand-tuning PEAK
    # against it, measure what came out and correct to a fixed level, so the
    # assembler can set the balance against a number that does not move.
    correction = TARGET_PEAK_DBFS - _peak_dbfs(shaped)
    _ffmpeg(
        ["ffmpeg", "-y", "-i", str(shaped), "-af", f"volume={correction:.2f}dB",
         "-ar", "48000", str(args.out)],
        "levelling the bed",
    )

    raw.unlink(missing_ok=True)
    shaped.unlink(missing_ok=True)
    print(f"  {args.out}  ({args.seconds:.1f}s, peak {TARGET_PEAK_DBFS:g} dBFS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
