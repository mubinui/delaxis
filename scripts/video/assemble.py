#!/usr/bin/env python
"""Cut the tour together: crossfades, narration, and a music bed under it.

Reads what ``make_narration.py`` and ``record.mjs`` produced and outputs the
finished file.

    python scripts/video/assemble.py

Three things have to line up, and the order matters:

1. Segments are dissolved into each other with ``xfade``. Each transition eats
   its overlap out of the running time, so the finished video is shorter than
   the sum of its parts.
2. The narration is therefore laid out against the *post-transition* timeline,
   not the recording order. Getting this wrong drifts the voice a full second
   off the picture by the end.
3. The music is ducked under the narration by a sidechain compressor rather than
   set to a fixed low level, so it can breathe in the gaps and still stay out of
   the way when someone is speaking.

Requires ffmpeg.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD = PROJECT_ROOT / "docs" / "video" / "build"
OUTPUT = PROJECT_ROOT / "docs" / "video" / "delaxis-2.1-tour.mp4"

SPEECH_RATE = 24_000
#: Dissolve length between segments. Long enough to read as deliberate, short
#: enough that a title card does not linger as a ghost over the app.
TRANSITION = 0.9

# The balance, in one place. ``make_music.py`` normalises the bed to a fixed
# peak, so these are the only numbers that decide how the mix sounds — the two
# gains are relative to each other and moving one without the other is what
# makes a bed either inaudible or distracting.
VOICE_GAIN_DB = 5.0   # after compression, to land the film near broadcast level
BED_GAIN_DB = -9.0    # roughly 12 dB under the voice when nothing is being said
DUCK_THRESHOLD = 0.1  # the bed starts giving way once the voice passes -20 dBFS
DUCK_RATIO = 3.0      # about 10 dB of duck at speaking level


def tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"{name} is not on PATH")
    return path


def duration(path: Path) -> float:
    result = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def run(command: list[str], what: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-2500:])
        raise SystemExit(f"ffmpeg failed: {what}")


# --------------------------------------------------------------------------- #
# Video
# --------------------------------------------------------------------------- #


def stitch_video(segments: list[Path]) -> tuple[Path, list[float]]:
    """Dissolve the segments together; return the file and each one's start time."""
    lengths = [duration(path) for path in segments]
    output = BUILD / "stitched.mp4"

    if len(segments) == 1:
        shutil.copy(segments[0], output)
        return output, [0.0]

    # Where each segment begins once the overlaps are removed.
    starts = [0.0]
    for index in range(1, len(segments)):
        starts.append(starts[-1] + lengths[index - 1] - TRANSITION)

    inputs: list[str] = []
    for path in segments:
        inputs += ["-i", str(path)]

    # xfade takes two streams at a time, so they are folded left to right. The
    # offset is measured against the accumulated result, not the original clip.
    steps: list[str] = []
    label = "0:v"
    accumulated = lengths[0]
    for index in range(1, len(segments)):
        offset = accumulated - TRANSITION
        nxt = f"v{index}"
        steps.append(
            f"[{label}][{index}:v]xfade=transition=fade:duration={TRANSITION}:offset={offset:.3f}[{nxt}]"
        )
        label = nxt
        accumulated = offset + lengths[index]

    steps.append(f"[{label}]fps=30,format=yuv420p[vout]")

    run(
        [tool("ffmpeg"), "-y", *inputs,
         "-filter_complex", ";".join(steps),
         "-map", "[vout]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-an", str(output)],
        "stitching segments",
    )
    return output, starts


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #


def build_narration(timeline: dict, segments: list[dict], starts: list[float], total: float) -> Path:
    """One track with each line placed where its shot actually lands."""
    track = BUILD / "narration.wav"
    frames = bytearray(int(total * SPEECH_RATE) * 2)

    # Scene id -> which segment it was recorded in.
    owner = {
        scene_id: index
        for index, segment in enumerate(segments)
        for scene_id in segment["scenes"]
    }

    cursor: dict[int, float] = {}
    for scene in timeline["scenes"]:
        segment_index = owner.get(scene["id"])
        if segment_index is None:
            continue

        # Offset within the segment, then the segment's own start in the cut.
        within = cursor.get(segment_index, 0.0)
        cursor[segment_index] = within + scene["hold_seconds"]
        at = starts[segment_index] + within

        with wave.open(str(BUILD / scene["audio"]), "rb") as handle:
            speech = handle.readframes(handle.getnframes())

        start_byte = int(at * SPEECH_RATE) * 2
        end_byte = min(start_byte + len(speech), len(frames))
        if start_byte < len(frames):
            frames[start_byte:end_byte] = speech[: end_byte - start_byte]

    with wave.open(str(track), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SPEECH_RATE)
        handle.writeframes(bytes(frames))
    return track


def build_music(total: float) -> Path:
    music = BUILD / "music.wav"
    run(
        [sys.executable, str(Path(__file__).with_name("make_music.py")),
         "--seconds", f"{total:.2f}", "--out", str(music)],
        "rendering the music bed",
    )
    return music


# --------------------------------------------------------------------------- #


def main() -> int:
    manifest = BUILD / "segments.json"
    timeline_path = BUILD / "timeline.json"
    for required in (manifest, timeline_path):
        if not required.exists():
            raise SystemExit(f"missing {required} — run make_narration.py and record.mjs first")

    segments = json.loads(manifest.read_text())["segments"]
    timeline = json.loads(timeline_path.read_text())
    paths = [BUILD / segment["file"] for segment in segments]

    print(f"  {len(paths)} segment(s), {TRANSITION}s dissolves")
    video, starts = stitch_video(paths)
    total = duration(video)
    print(f"  video      {total:6.1f}s")

    narration = build_narration(timeline, segments, starts, total)
    music = build_music(total)
    print(f"  narration  {duration(narration):6.1f}s")
    print(f"  music      {duration(music):6.1f}s")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    run(
        [tool("ffmpeg"), "-y",
         "-i", str(video), "-i", str(narration), "-i", str(music),
         "-filter_complex", ";".join([
             # Narration carries the piece: high-passed for rumble, compressed
             # so the quiet ends of lines stay present, then brought up.
             "[1:a]aresample=48000,aformat=channel_layouts=stereo,"
             "highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=8:release=180,"
             f"volume={VOICE_GAIN_DB}dB[voice]",
             # A copy of the voice drives the ducking, so the bed steps back the
             # moment anyone speaks and comes up again in the gaps — which is
             # what a fixed low level cannot do.
             "[voice]asplit=2[voice_out][key]",
             f"[2:a]aresample=48000,aformat=channel_layouts=stereo,volume={BED_GAIN_DB}dB[bed]",
             f"[bed][key]sidechaincompress=threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}"
             ":attack=15:release=350:detection=rms[ducked]",
             "[voice_out][ducked]amix=inputs=2:duration=first:normalize=0,"
             "alimiter=limit=0.95[aout]",
         ]),
         "-map", "0:v", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", "-shortest",
         str(OUTPUT)],
        "mixing the final cut",
    )

    size_mb = OUTPUT.stat().st_size / 1_048_576
    print(f"\n  {OUTPUT}")
    print(f"  {duration(OUTPUT):.1f}s · {size_mb:.1f} MB · 1920x1080 · narration + ducked bed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
