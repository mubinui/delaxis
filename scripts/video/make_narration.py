#!/usr/bin/env python
"""Render the narration with Gemini's speech model and time each scene.

Writes one WAV per scene plus ``timeline.json``, which ``record.mjs`` reads to
hold each shot for exactly as long as its narration runs. Audio is generated
first and the recording follows it, rather than the other way round: speech has
a natural pace that cannot be trimmed to fit a shot without sounding rushed,
whereas a shot can be held for any length.

    python scripts/video/make_narration.py            # render anything missing
    python scripts/video/make_narration.py --force    # re-render everything

Needs GEMINI_API_KEY. Each scene is cached by a hash of its text, so editing one
line re-renders that line alone.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.video.scenes import SCENES  # noqa: E402

OUT_DIR = PROJECT_ROOT / "docs" / "video" / "build"
MODEL = os.environ.get("DELAXIS_TTS_MODEL", "gemini-3.1-flash-tts-preview")
# Charon reads as measured and low, which suits explanation. The alternative
# voices lean bright and start to sound like an advert over four minutes.
VOICE = os.environ.get("DELAXIS_TTS_VOICE", "Charon")
SAMPLE_RATE = 24_000

# Read as narration for a product walkthrough, not as an announcement.
STYLE = (
    "Read this calmly and clearly, like a knowledgeable colleague explaining "
    "software to someone over their shoulder. Unhurried, warm, never salesy: "
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


def synthesise(text: str, key: str, attempts: int = 4) -> bytes:
    """Return raw PCM for one line, retrying the transient failures."""
    payload = json.dumps({
        "contents": [{"parts": [{"text": STYLE + text}]}],
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
            inline = body["candidates"][0]["content"]["parts"][0]["inlineData"]
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

    minutes, seconds = divmod(total, 60)
    print(f"\n  {len(timeline)} scenes · {int(minutes)}m {seconds:04.1f}s")
    print(f"  timeline -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
