#!/usr/bin/env python
"""Synthesise the music for the tour: plucked strings in a hall.

Generated rather than licensed — a stock track means a licence to track and a
file to ship, and this has to render to whatever length the cut happens to be.

Two earlier attempts stacked sine harmonics into sustained pads and both sounded
like a signal generator, because that is what they were. Additive synthesis of a
held chord has no attack, no decay and no room, and no amount of choosing
harmonics fixes that: the ear identifies an instrument by how a note *starts and
stops*, not by its spectrum.

So this plays notes instead. Each one is a plucked string, modelled rather than
drawn — Karplus-Strong: excite a delay line the length of one period with a
short burst of noise, then feed it back through itself with a gentle averaging
filter. The noise decorrelates into a pitch, the high harmonics die away first,
and what comes out has the attack and the decay of something struck. It is four
lines of arithmetic and it sounds like an instrument, which twenty sine
oscillators did not.

The other half is the room. Notes are convolved with a real impulse response —
exponentially decaying noise, darkened, decorrelated between the two channels —
so they ring and overlap into each other. Reverb is most of what makes music
sound soothing rather than dry, and an echo with a few taps is not reverb.

The arrangement is a slow rolling arpeggio through eight chords in A minor: up
through the chord and back down, one note every one and a quarter seconds, each
ringing for three or four. They overlap into a wash. Underneath sits a very
quiet pad, only for warmth.

    python scripts/video/make_music.py --seconds 150

Needs numpy and ffmpeg.
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
PROGRESSION: list[tuple[float, float, float]] = [
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
#: Six notes per chord, so one lands every one and a quarter seconds. Slower
#: than feels right on paper and exactly right in the room, because each note is
#: still ringing when the next three arrive.
ARPEGGIO = 6

PEAK = 0.68
#: What the finished piece is normalised to — average level, not peak. Peak is
#: the wrong anchor for a mix whose crest factor changes with the arrangement.
TARGET_RMS_DBFS = -18.0
CEILING_DBFS = -1.5


# --------------------------------------------------------------------------- #
# A plucked string
# --------------------------------------------------------------------------- #


def synth_note(frequency: float, seconds: float, half_life: float = 1.8,
               softness: float = 0.5) -> np.ndarray:
    """A smooth, professional FM electric piano / bell note.
    
    Provides a cleaner, more modern corporate tech sound compared to the
    experimental Karplus-Strong plucked strings.
    """
    count = int(seconds * RATE)
    t = np.arange(count) / RATE
    
    # Envelope: quick attack, exponential decay
    attack_time = 0.05 * softness
    decay = np.exp(-t * (0.693 / half_life))
    attack = np.clip(t / attack_time, 0, 1)
    env = attack * decay
    
    # FM Synthesis
    # Modulator creates the bright attack that fades into a pure sine wave
    mod_index = 2.5 * env  # modulation index decreases as note decays
    mod_ratio = 2.01       # slightly inharmonic for a warm electric piano/bell tone
    modulator = np.sin(2 * np.pi * (frequency * mod_ratio) * t)
    
    carrier = np.sin(2 * np.pi * frequency * t + mod_index * modulator)
    
    note = carrier * env
    
    # Ease the tail
    tail = int(0.25 * RATE)
    if count > tail:
        note[-tail:] *= np.linspace(1.0, 0.0, tail) ** 2
        
    loudest = np.abs(note).max()
    return note / loudest if loudest > 0 else note


def _place(out: np.ndarray, at: float, note: np.ndarray, gain: float) -> None:
    start = int(at * RATE)
    if start < 0 or start >= len(out):
        return
    count = min(len(note), len(out) - start)
    if count > 0:
        out[start:start + count] += (note[:count] * gain).astype(out.dtype)


# --------------------------------------------------------------------------- #
# Arrangement
# --------------------------------------------------------------------------- #


def _arc(t: float, seconds: float) -> float:
    """Level across the piece: in, back under the busy middle, up for the close."""
    opening = min(max(t / 4.0, 0.0), 1.0)
    holding = min(max((7.0 - t) / 7.0, 0.0), 1.0)
    closing = min(max((t - (seconds - 15.0)) / 8.0, 0.0), 1.0)
    return opening * (0.70 + 0.30 * max(holding, closing))


#: The reveal: four notes rising to the octave, landing as the wordmark does.
OPENING: tuple[tuple[float, float], ...] = (
    (0.55, 220.00),   # A3, as the axis draws
    (1.15, 261.63),   # C4
    (1.75, 329.63),   # E4
    (2.35, 440.00),   # A4, as the wordmark lands
)


def _opening(out: np.ndarray) -> None:
    for index, (at, frequency) in enumerate(OPENING):
        _place(out, at, synth_note(frequency, 6.0, half_life=2.4, softness=0.45),
               0.62 - index * 0.03)
    # The chord underneath, so the four notes arrive somewhere rather than
    # simply stopping. Rolled very slightly, the way a hand would play it.
    for index, frequency in enumerate((110.00, 220.00, 261.63, 329.63, 440.00)):
        _place(out, 3.05 + index * 0.055, synth_note(frequency, 8.0, half_life=3.0, softness=0.6),
               0.30 - index * 0.02)


def _arpeggio(out: np.ndarray, seconds: float) -> None:
    """Up through each chord and back down, one note at a time."""
    step = CHORD_SECONDS / ARPEGGIO
    at = CHORD_SECONDS + 0.6   # let the opening ring out first
    index = 0

    while at < seconds - 2.0:
        low, middle, high = PROGRESSION[int(at / CHORD_SECONDS) % len(PROGRESSION)]
        # Up and back: root, middle, top, octave, top, middle.
        note = (low, middle, high, low * 2, high, middle)[index % ARPEGGIO]

        level = _arc(at, seconds)
        # The first note of each chord is the one that says the harmony changed,
        # so it is a little stronger than the ones filling in behind it.
        weight = 0.34 if index % ARPEGGIO == 0 else 0.21
        _place(out, at, synth_note(note, 5.0, half_life=1.9, softness=0.5), weight * level)

        # The root an octave down on the chord change, quiet, for the floor.
        if index % ARPEGGIO == 0:
            _place(out, at, synth_note(low / 2, 7.0, half_life=2.8, softness=0.75), 0.24 * level)

        at += step
        index += 1


def _pad(seconds: float) -> np.ndarray:
    """A very quiet sustained bed under the strings, for warmth only.

    Deliberately dull and deliberately faint: the plucks and the room carry the
    piece, and anything assertive here is what made the earlier versions drone.
    """
    total = int(seconds * RATE)
    out = np.zeros(total, dtype=np.float32)
    block = int(15 * RATE)

    for begin in range(0, total, block):
        end = min(begin + block, total)
        t = np.arange(begin, end, dtype=np.float64) / RATE
        chunk = np.zeros_like(t)

        first = max(0, int(t[0] / CHORD_SECONDS) - 1)
        last = int(t[-1] / CHORD_SECONDS) + 1
        for slot in range(first, last + 1):
            chord = PROGRESSION[slot % len(PROGRESSION)]
            local = t - slot * CHORD_SECONDS
            # Equal power in and out, overlapping the neighbouring chord for the
            # whole crossfade — fading inside its own slot would leave a hole at
            # every boundary, because both neighbours reach zero together.
            rising = np.sin(np.pi / 2 * np.clip(local / 3.0, 0, 1))
            falling = np.cos(np.pi / 2 * np.clip((local - CHORD_SECONDS) / 3.0, 0, 1))
            envelope = rising * falling * ((local >= 0) & (local <= CHORD_SECONDS + 3.0))
            if not envelope.any():
                continue
            for partial, frequency in enumerate(chord):
                chunk += np.sin(2 * np.pi * frequency * t + partial * 1.7) * envelope * (0.5 ** partial)

        arc = np.array([_arc(x, seconds) for x in t[::2048]])
        chunk *= np.interp(t, t[::2048], arc)
        out[begin:end] += chunk.astype(np.float32)

    return out * 0.055


def render(seconds: float) -> np.ndarray:
    out = np.zeros(int(seconds * RATE), dtype=np.float32)
    _opening(out)
    _arpeggio(out, seconds)
    out += _pad(seconds)
    out *= PEAK
    return np.clip(out, -1.0, 1.0)


# --------------------------------------------------------------------------- #
# The room
# --------------------------------------------------------------------------- #


def impulse_response(seconds: float = 2.6) -> np.ndarray:
    """A hall, as decaying noise.

    Reverb is the difference between notes and music, and a handful of echo taps
    is not reverb — it is a few distinct repeats that comb-filter whatever goes
    through them. Thousands of dense random reflections decaying exponentially
    is what a room actually does.

    The two channels are generated independently, so they are decorrelated and
    the result has width without anything being panned.
    """
    count = int(seconds * RATE)
    rng = np.random.default_rng(20260822)
    response = rng.normal(0.0, 1.0, (count, 2))

    t = np.arange(count) / RATE
    decay = np.exp(-t * (6.5 / seconds))
    decay *= np.clip(t / 0.018, 0, 1)          # a build-up, not a click
    response *= decay[:, None]

    # A real room absorbs the top end as the tail dies. Smoothing does this
    # crudely and cheaply, and the result is a darker, softer tail.
    window = np.hanning(21)
    window /= window.sum()
    for channel in range(2):
        response[:, channel] = np.convolve(response[:, channel], window, mode="same")

    return response / np.abs(response).max()


# --------------------------------------------------------------------------- #


def _ffmpeg(command: list[str], what: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-1800:])
        raise SystemExit(f"ffmpeg failed while {what}")
    return result.stderr


def _write(path: Path, samples: np.ndarray, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def _levels(path: Path) -> tuple[float, float]:
    report = _ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        "measuring the music",
    )
    found: dict[str, float] = {}
    for line in report.splitlines():
        for key in ("mean_volume", "max_volume"):
            if key in line:
                found[key] = float(line.split(key + ":")[1].split("dB")[0])
    if len(found) < 2:
        raise SystemExit("could not read the level")
    return found["mean_volume"], found["max_volume"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--out", default=str(BUILD / "music.wav"))
    args = parser.parse_args()

    BUILD.mkdir(parents=True, exist_ok=True)
    dry = BUILD / "music-dry.wav"
    room = BUILD / "music-ir.wav"
    wet = BUILD / "music-wet.wav"

    _write(dry, render(args.seconds))
    _write(room, impulse_response().reshape(-1), channels=2)

    _ffmpeg(
        ["ffmpeg", "-y", "-i", str(dry), "-i", str(room),
         "-filter_complex",
         # irlink=false keeps the two sides of the room independent, which is
         # where the width comes from.
         "[0:a]aformat=channel_layouts=stereo[d];"
         "[d][1:a]afir=dry=0.72:wet=0.85:irlink=false:maxir=4[r];"
         "[r]highpass=f=48,lowpass=f=7000,"
         "afade=t=in:st=0:d=0.5,"
         f"afade=t=out:st={max(args.seconds - 3.5, 0):.2f}:d=3.5[out]",
         "-map", "[out]", "-ar", "48000", str(wet)],
        "putting the strings in a room",
    )

    mean, peak = _levels(wet)
    correction = TARGET_RMS_DBFS - mean
    if peak + correction > CEILING_DBFS:
        correction = CEILING_DBFS - peak

    _ffmpeg(
        ["ffmpeg", "-y", "-i", str(wet), "-af", f"volume={correction:.2f}dB",
         "-ar", "48000", str(args.out)],
        "levelling the music",
    )

    for scratch in (dry, room, wet):
        scratch.unlink(missing_ok=True)
    print(f"  {args.out}  ({args.seconds:.1f}s, {mean + correction:.1f} dBFS mean, "
          f"{peak + correction:.1f} dBFS peak)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
