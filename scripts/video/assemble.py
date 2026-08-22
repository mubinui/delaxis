#!/usr/bin/env python
"""Mux the narration onto the screen recording.

Builds one continuous audio track by laying each scene's speech at the start of
its shot and padding the remainder with silence — the same per-scene budget the
recorder held to — then muxes it onto the capture.

    python scripts/video/assemble.py

Requires ffmpeg. Reads docs/video/build/{timeline.json,screen.webm,*.wav} and
writes docs/video/delaxis-2.0-tour.mp4.
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
OUTPUT = PROJECT_ROOT / "docs" / "video" / "delaxis-2.0-tour.mp4"
SAMPLE_RATE = 24_000


def ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise SystemExit("ffmpeg is not on PATH")
    return binary


def build_audio(timeline: dict) -> Path:
    """Concatenate speech and silence into one track matching the shot timings."""
    track = BUILD / "narration.wav"
    frames = bytearray()

    for scene in timeline["scenes"]:
        speech_path = BUILD / scene["audio"]
        with wave.open(str(speech_path), "rb") as handle:
            if handle.getframerate() != SAMPLE_RATE:
                raise SystemExit(f"{speech_path.name} is not {SAMPLE_RATE} Hz")
            frames += handle.readframes(handle.getnframes())

        # Pad to the shot's full length so the next line starts exactly when the
        # next shot does. Without this the audio would drift ahead of the video
        # by the accumulated tail of every scene.
        pad_seconds = scene["hold_seconds"] - scene["speech_seconds"]
        if pad_seconds > 0:
            frames += b"\x00" * (int(pad_seconds * SAMPLE_RATE) * 2)

    with wave.open(str(track), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))

    return track


def duration(path: Path) -> float:
    probe = shutil.which("ffprobe")
    if not probe:
        return 0.0
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def main() -> int:
    timeline_path = BUILD / "timeline.json"
    screen = BUILD / "screen.webm"
    for required in (timeline_path, screen):
        if not required.exists():
            raise SystemExit(f"missing {required} — run make_narration.py and record.mjs first")

    timeline = json.loads(timeline_path.read_text())
    track = build_audio(timeline)

    video_seconds = duration(screen)
    audio_seconds = duration(track)
    print(f"  video {video_seconds:6.1f}s   audio {audio_seconds:6.1f}s   drift {video_seconds - audio_seconds:+.1f}s")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg(), "-y",
        "-i", str(screen),
        "-i", str(track),
        # H.264 + AAC so it plays everywhere, including in a GitHub release page
        # and an embedded README player.
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=1920:1080:flags=lanczos,fps=30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        # The capture runs a beat past the last line; end with the audio so it
        # does not close on silence.
        "-shortest",
        "-movflags", "+faststart",
        str(OUTPUT),
    ]
    print("  encoding…")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-2000:])
        raise SystemExit("ffmpeg failed")

    size_mb = OUTPUT.stat().st_size / 1_048_576
    print(f"\n  {OUTPUT}")
    print(f"  {duration(OUTPUT):.1f}s · {size_mb:.1f} MB · 1920x1080")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
