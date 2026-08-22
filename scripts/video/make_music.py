#!/usr/bin/env python
"""Synthesise the background bed for the tour.

Generated rather than licensed: a stock track means a licence to track and a
file to ship, and this only has to sit under narration without asking for
attention. Everything here is pure synthesis, so it is royalty-free by
construction and can be rendered to whatever length the cut happens to be.

The bed is a slow eight-chord phrase in A minor. Eight rather than four because
the tour runs three and a half minutes: a four-chord loop comes round seven
times and starts to nag, where this comes round twice and reads as one long
idea.

Every note is a waveform, not a tone. An earlier version stacked bare sines and
put a pure sine an octave below the root, and the result buzzed: a sine at 73 Hz
is a hum rather than a note, and three sines with nothing between them read as a
test signal. Each voice is now a harmonic series with a steep roll-off — the
shape of a filtered sawtooth, which is what a pad actually is — and the bass
carries its own second and third harmonics so it lands as a bass note.

Over the pads sit two things with an attack, because pads alone read as a held
drone: a sparse pluck every couple of seconds through the body, and an opening
motif — four rising notes timed to the logo assembling itself, resolving into
the tonic as the wordmark lands.

Level follows the film rather than sitting flat — it opens, steps back under the
dense middle where the narration is working hardest, and swells again for the
closing card. The opening motif sits outside that envelope, since fading it up
over five seconds would swallow the very notes it exists to play.

    python scripts/video/make_music.py --seconds 150

Needs numpy (per-sample Python at 48 kHz for three minutes is minutes of work)
and ffmpeg for the final shaping.
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
# Written as frequencies rather than note names so the voicing is explicit.
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

#: Harmonics above this are not generated. The bed is meant to sit under a
#: voice, and anything up here only competes with consonants.
CUTOFF = 1800.0
#: How far apart the two copies of each voice sit. A fixed offset in hertz, not
#: a ratio: detuning by a ratio makes every harmonic beat at its own rate, so
#: the top of the spectrum shimmers several times a second. That was the buzz.
CHORUS_HZ = 0.18
#: The octave-down root, quiet enough to be felt rather than heard.
BASS_LEVEL = 0.34

# Working headroom for the synthesis; the real level is set by the
# normalisation below, not here.
PEAK = 0.16
#: What the finished bed is normalised to — average level, not peak. The
#: assembler sets the balance against this, so changing the synthesis cannot
#: quietly change the mix. Peak is the wrong anchor: a richer waveform has a
#: higher crest factor, so normalising by peak made the bed audibly quieter the
#: moment the sines became harmonic voices, without a single gain being touched.
TARGET_RMS_DBFS = -18.0
#: Never let the correction push a transient into the ceiling.
CEILING_DBFS = -1.5

#: Rendered in blocks so a three-minute bed does not need a dozen
#: multi-hundred-megabyte arrays alive at once. Phase comes off global time, so
#: the blocks join seamlessly.
BLOCK_SECONDS = 15.0


# --------------------------------------------------------------------------- #
# Voices
# --------------------------------------------------------------------------- #


def _voice(t: np.ndarray, frequency: float) -> np.ndarray:
    """One sustained pad note: a harmonic series with a steep roll-off.

    This is the shape of a filtered sawtooth rather than a sine, which is the
    difference between a chord that sounds like an instrument and one that
    sounds like a signal generator.
    """
    count = max(1, min(10, int(CUTOFF // frequency)))
    tone = np.zeros_like(t)
    total = 0.0
    for harmonic in range(1, count + 1):
        amplitude = 1.0 / (harmonic ** 1.6)
        total += amplitude
        f = frequency * harmonic
        tone += amplitude * (
            np.sin(2 * np.pi * f * t)
            + np.sin(2 * np.pi * (f + CHORUS_HZ) * t + 1.1)
        )
    return tone / (2 * total)


def _bass(t: np.ndarray, frequency: float) -> np.ndarray:
    """The root an octave down, with enough harmonic to read as a note.

    A bare sine here sits between 73 and 130 Hz, which a listener hears as the
    room vibrating rather than as music.
    """
    return (
        np.sin(2 * np.pi * frequency * t)
        + 0.30 * np.sin(2 * np.pi * frequency * 2 * t + 0.7)
        + 0.12 * np.sin(2 * np.pi * frequency * 3 * t + 1.4)
    ) / 1.42


def _struck(local: np.ndarray, frequency: float) -> np.ndarray:
    """A plucked note — the same harmonics, weighted for something with an edge."""
    return (
        np.sin(2 * np.pi * frequency * local)
        + 0.40 * np.sin(2 * np.pi * frequency * 2 * local)
        + 0.16 * np.sin(2 * np.pi * frequency * 3 * local)
        + 0.07 * np.sin(2 * np.pi * frequency * 4 * local)
    ) / 1.63


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


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


def _arc(t: np.ndarray | float, seconds: float) -> np.ndarray | float:
    """Level across the whole piece: in, back for the middle, up for the close.

    The narration is densest through the body, so the bed gives way there and
    only comes forward again once the closing card is on screen.
    """
    opening = np.clip(t / 5.0, 0, 1)                       # fade up under the title
    holding = np.clip((6.0 - t) / 6.0, 0, 1)               # full while the title holds
    closing = np.clip((t - (seconds - 16.0)) / 9.0, 0, 1)  # swell for the outro
    forward = np.maximum(holding, closing)                 # full at both ends, back between
    return opening * (0.70 + 0.30 * forward)


# --------------------------------------------------------------------------- #
# Layers
# --------------------------------------------------------------------------- #


def _pads(t: np.ndarray) -> np.ndarray:
    """The sustained chords for one block of time.

    Envelopes are accumulated per *pitch* before any oscillator runs. Two
    overlapping chords often share a note — Am and F both hold middle C — and
    generating it twice with different phases makes the two copies fight each
    other through the whole crossfade. Summed first, the common tone simply
    sustains through the change, which is what it is supposed to do.
    """
    length = CHORD_SECONDS
    first = max(0, int(t[0] / length) - 1)
    last = int(t[-1] / length) + 1

    pad_envelope: dict[float, np.ndarray] = {}
    bass_envelope: dict[float, np.ndarray] = {}

    for slot in range(first, last + 1):
        chord = PROGRESSION[slot % len(PROGRESSION)]
        envelope = _chord_envelope(t - slot * length, length)
        if not envelope.any():
            continue

        for partial, frequency in enumerate(chord):
            # Upper voices quieter, as they are in anything acoustic.
            weight = 0.62 ** partial
            if frequency in pad_envelope:
                pad_envelope[frequency] += envelope * weight
            else:
                pad_envelope[frequency] = envelope * weight

        root = chord[0] / 2
        if root in bass_envelope:
            bass_envelope[root] += envelope
        else:
            bass_envelope[root] = envelope

    out = np.zeros_like(t)
    for frequency, envelope in pad_envelope.items():
        out += _voice(t, frequency) * envelope
    for frequency, envelope in bass_envelope.items():
        out += _bass(t, frequency) * envelope * BASS_LEVEL
    return out


def _add_note(
    out: np.ndarray, at: float, frequency: float,
    seconds: float, amplitude: float, decay: float,
) -> None:
    """Strike one note into the mix, decaying from its own start.

    Phase runs from the note's own beginning rather than global time, which is
    what gives it an attack — the pads do the opposite, and that is the whole
    difference between something struck and something held.
    """
    start = int(at * RATE)
    if start >= len(out) or start < 0:
        return
    count = min(int(seconds * RATE), len(out) - start)
    if count <= 0:
        return

    local = np.arange(count) / RATE
    envelope = np.exp(-local * decay) * np.clip(local / 0.012, 0, 1)  # soft edge, no click
    out[start:start + count] += (_struck(local, frequency) * envelope * amplitude).astype(out.dtype)


#: Rising A minor, landing on the octave. Timed against the title card: the
#: notes fall where the axis draws, the nodes pop, and the wordmark arrives.
MOTIF: tuple[tuple[float, float], ...] = (
    (0.45, 220.00),   # A3, as the axis draws
    (0.95, 261.63),   # C4
    (1.45, 329.63),   # E4
    (1.95, 440.00),   # A4, as the wordmark lands
)


def _intro_motif(out: np.ndarray) -> None:
    for index, (at, frequency) in enumerate(MOTIF):
        _add_note(out, at, frequency, 3.4, 0.62 - index * 0.04, 0.95)
    # The tonic underneath, so the four notes resolve into something rather than
    # simply stopping.
    for partial, frequency in enumerate(PROGRESSION[0]):
        _add_note(out, 2.1, frequency, 7.0, 0.24 * (0.55 ** partial), 0.40)


def _plucks(out: np.ndarray, seconds: float) -> None:
    """A note every couple of seconds, drawn from whichever chord is sounding.

    Deliberately not a melody: a figure that rocks between two notes of the
    chord gives the bed forward motion without ever becoming something the
    viewer follows instead of the narration.
    """
    step = 0
    at = CHORD_SECONDS + 1.5  # let the opening motif finish first
    while at < seconds - 6.0:
        chord = PROGRESSION[int(at / CHORD_SECONDS) % len(PROGRESSION)]
        pick = (chord[2], chord[1], chord[2] * 2, chord[1])[step % 4]
        # Alternating weight, so the figure breathes instead of ticking, and
        # following the arc so it ducks under the busy middle with everything else.
        weight = 0.075 if step % 2 == 0 else 0.046
        _add_note(out, at, pick, 2.4, weight * float(_arc(at, seconds)), 1.5)
        at += CHORD_SECONDS / 4
        step += 1


def render(seconds: float) -> np.ndarray:
    total = int(seconds * RATE)
    out = np.zeros(total, dtype=np.float32)

    block = int(BLOCK_SECONDS * RATE)
    for begin in range(0, total, block):
        end = min(begin + block, total)
        t = np.arange(begin, end, dtype=np.float64) / RATE
        chunk = _pads(t)
        chunk *= 0.85 + 0.15 * np.sin(2 * np.pi * t / 19.0)  # a very slow breath
        chunk *= _arc(t, seconds)
        out[begin:end] += chunk.astype(np.float32)

    _plucks(out, seconds)
    # After the arc: the opening motif plays over the title card, where the arc
    # is still ramping up from silence and would fade it out from underneath.
    _intro_motif(out)

    out *= PEAK
    return np.clip(out, -1.0, 1.0)


# --------------------------------------------------------------------------- #


def _ffmpeg(command: list[str], what: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-1500:])
        raise SystemExit(f"ffmpeg failed while {what}")
    return result.stderr


def _levels(path: Path) -> tuple[float, float]:
    """Return (mean, peak) in dBFS."""
    report = _ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        "measuring the bed",
    )
    found: dict[str, float] = {}
    for line in report.splitlines():
        for key in ("mean_volume", "max_volume"):
            if key in line:
                found[key] = float(line.split(key + ":")[1].split("dB")[0])
    if "mean_volume" not in found or "max_volume" not in found:
        raise SystemExit("could not read the bed's level")
    return found["mean_volume"], found["max_volume"]


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

    _ffmpeg(
        ["ffmpeg", "-y", "-i", str(raw),
         "-af", ",".join([
             # Gentle: the harmonics were rolled off during synthesis, so this
             # only takes the last of the edge off rather than doing the work.
             "lowpass=f=2600",
             "highpass=f=58",
             # Short, dense taps read as a small room. The earlier 180 and
             # 340 ms pair was long enough to hear as separate repeats, and it
             # comb-filtered the pad into something metallic.
             "aecho=0.9:0.75:29|41|67|113:0.16|0.12|0.09|0.06",
             "aformat=channel_layouts=stereo",
             "afade=t=in:st=0:d=0.8",  # short: the motif shapes its own entrance
             f"afade=t=out:st={max(args.seconds - 3.0, 0):.2f}:d=3.0",
         ]),
         "-ar", "48000", str(shaped)],
        "shaping the bed",
    )

    # The filter chain above loses several dB in places that are awkward to
    # predict. Rather than hand-tuning PEAK against it, measure what came out
    # and correct to a fixed level, so the assembler can set the balance
    # against a number that does not move.
    mean, peak = _levels(shaped)
    correction = TARGET_RMS_DBFS - mean
    if peak + correction > CEILING_DBFS:
        correction = CEILING_DBFS - peak
    _ffmpeg(
        ["ffmpeg", "-y", "-i", str(shaped), "-af", f"volume={correction:.2f}dB",
         "-ar", "48000", str(args.out)],
        "levelling the bed",
    )

    raw.unlink(missing_ok=True)
    shaped.unlink(missing_ok=True)
    print(f"  {args.out}  ({args.seconds:.1f}s, {mean + correction:.1f} dBFS mean, "
          f"{peak + correction:.1f} dBFS peak)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
