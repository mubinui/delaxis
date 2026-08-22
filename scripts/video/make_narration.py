#!/usr/bin/env python
"""Render the narration with Gemini's speech model and time each scene.

Writes one WAV per scene plus ``timeline.json``, which ``record.mjs`` reads to
hold each shot for exactly as long as its narration runs. Audio is generated
first and the recording follows it, rather than the other way round: speech has
a natural pace that cannot be trimmed to fit a shot without sounding rushed,
whereas a shot can be held for any length.

    python scripts/video/make_narration.py            # render anything missing
    python scripts/video/make_narration.py --force    # re-render everything

Also renders ``voice-input.wav``: the sentence Chromium is handed as a fake
microphone during the voice chapter. The session recorded there is a real one,
so the words it hears have to come from somewhere.

Needs GEMINI_API_KEY. Each scene is cached by a hash of its text, so editing one
line re-renders that line alone.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.video.scenes import SCENES, VOICE_INSTRUCTION  # noqa: E402

OUT_DIR = PROJECT_ROOT / "docs" / "video" / "build"
MODEL = os.environ.get("DELAXIS_TTS_MODEL", "gemini-3.1-flash-tts-preview")
# Sulafat is documented as warm; Achernar (soft), Vindemiatrix (gentle) and
# Leda (youthful) are the other female voices worth trying. Override with
# DELAXIS_TTS_VOICE to swap without touching the script.
VOICE = os.environ.get("DELAXIS_TTS_VOICE", "Sulafat")
SAMPLE_RATE = 24_000

# The first cut was measured to the point of dragging. This asks for the same
# warmth at a brisker clip — the pace of someone genuinely pleased to show you
# something, not of a training module.
STYLE = (
    "Read this warmly and brightly, with a friendly, natural, human delivery. "
    "Keep a lively pace — engaged and upbeat, never rushed and never robotic. "
    "Sound like someone happily showing a friend something they built: "
)


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                for name in ("GEMINI_API_KEY=", "GOOGLE_API_KEY="):
                    if line.startswith(name):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set (env or .env)")
    return key


def synthesise(text: str, key: str, attempts: int = 4, styled: bool = True) -> bytes:
    """Return raw PCM for one line, retrying the transient failures.

    ``styled`` prepends the delivery direction. It is dropped automatically when
    a generation comes back blocked: the safety filter occasionally objects to
    the *combination* of the direction and a short line, while the line on its
    own is fine. Losing the styling on one line is a far better outcome than
    failing the whole render.
    """
    prompt = (STYLE + text) if styled else text
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
        },
    }).encode()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}"
    last: Exception | None = None

    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.load(response)
            try:
                inline = body["candidates"][0]["content"]["parts"][0]["inlineData"]
            except (KeyError, IndexError):
                # A blocked or empty generation returns 200 with no audio. Report
                # what actually came back instead of a bare KeyError.
                reason = (
                    body.get("promptFeedback", {}).get("blockReason")
                    or (body.get("candidates") or [{}])[0].get("finishReason")
                    or json.dumps(body)[:220]
                )
                if styled and "PROHIBITED" in str(reason).upper():
                    print(f"       (styling dropped for this line: {reason})")
                    return synthesise(text, key, attempts=attempts, styled=False)
                last = RuntimeError(f"no audio returned ({reason})")
                time.sleep(2 ** attempt)
                continue
            return base64.b64decode(inline["data"])
        except urllib.error.HTTPError as exc:
            last = exc
            # 429 and 5xx are worth waiting out; a 400 will never succeed.
            if exc.code not in (429, 500, 502, 503, 504):
                raise SystemExit(f"TTS rejected the request ({exc.code}): {exc.read()[:300]!r}")
            time.sleep(2 ** attempt * 2)
        except Exception as exc:
            last = exc
            time.sleep(2 ** attempt)

    raise SystemExit(f"TTS failed after {attempts} attempts: {last}")


def write_wav(path: Path, pcm: bytes) -> float:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return round(len(pcm) / 2 / SAMPLE_RATE, 3)


def write_voice_input(key: str) -> Path:
    """Render what the browser will 'hear' during the voice chapter.

    Chromium takes a WAV as a fake capture device and loops it, so the file is
    padded with a long silence: without it the model hears the same instruction
    over and over and starts adding the agent twice. The lead-in gives the
    session a moment to connect before anyone speaks.
    """
    path = OUT_DIR / "voice-input.wav"
    digest = hashlib.sha256(VOICE_INSTRUCTION.encode()).hexdigest()[:12]
    stamp = OUT_DIR / "voice-input.sha"

    if path.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        print(f"  [--] {'voice input':18} cached")
        return path

    # Unstyled: this is someone talking to their computer, not a voice-over.
    pcm = synthesise(VOICE_INSTRUCTION, key, styled=False)
    raw = OUT_DIR / "voice-input-raw.wav"
    with wave.open(str(raw), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"\x00" * SAMPLE_RATE * 2)  # a second before speaking
        handle.writeframes(pcm)
        handle.writeframes(b"\x00" * SAMPLE_RATE * 2 * 50)  # loop never comes round

    # Chromium wants a rate it can open as a capture device.
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw),
         "-ar", "48000", "-ac", "1", "-sample_fmt", "s16", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-800:])
        raise SystemExit("ffmpeg failed while preparing the microphone input")

    raw.unlink(missing_ok=True)
    stamp.write_text(digest + "\n")
    print(f"  [--] {'voice input':18} render  {len(pcm) / 2 / SAMPLE_RATE:6.2f}s")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-render every scene")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = api_key()

    manifest_path = OUT_DIR / "timeline.json"
    cached = {}
    if manifest_path.exists() and not args.force:
        try:
            cached = {s["id"]: s for s in json.loads(manifest_path.read_text())["scenes"]}
        except (json.JSONDecodeError, KeyError):
            cached = {}

    timeline = []
    total = 0.0

    for index, scene in enumerate(SCENES, start=1):
        digest = hashlib.sha256(scene.say.encode()).hexdigest()[:12]
        wav = OUT_DIR / f"{index:02d}-{scene.id}.wav"

        previous = cached.get(scene.id)
        if previous and previous.get("digest") == digest and wav.exists():
            seconds = previous["speech_seconds"]
            print(f"  [{index:02d}] {scene.id:18} cached  {seconds:6.2f}s")
        else:
            pcm = synthesise(scene.say, key)
            seconds = write_wav(wav, pcm)
            print(f"  [{index:02d}] {scene.id:18} render  {seconds:6.2f}s")

        hold = round(seconds + scene.tail_seconds, 3)
        total += hold
        timeline.append({
            "id": scene.id,
            "action": scene.action,
            # Scenes sharing a chapter are recorded as one continuous take.
            "chapter": scene.chapter,
            # Title-card scenes render from titles/<card>.html instead of the app.
            "card": scene.card,
            "digest": digest,
            "audio": wav.name,
            "speech_seconds": seconds,
            "hold_seconds": hold,
        })

    manifest_path.write_text(json.dumps(
        {"voice": VOICE, "model": MODEL, "sample_rate": SAMPLE_RATE,
         "total_seconds": round(total, 2), "scenes": timeline},
        indent=2,
    ) + "\n")

    write_voice_input(key)

    minutes, seconds = divmod(total, 60)
    print(f"\n  {len(timeline)} scenes · {int(minutes)}m {seconds:04.1f}s")
    print(f"  timeline -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
