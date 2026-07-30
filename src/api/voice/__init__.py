"""Live voice: a server-side bridge between a browser and a realtime audio model.

The browser never talks to the model provider directly — it speaks a small,
versioned envelope to this application, which relays audio to and from the
upstream realtime socket. That keeps the provider API key on the server, keeps
the deployed chatbot pages free of third-party origins (they are validated
against exactly that), and leaves room to swap providers without touching a
single line of page JavaScript.
"""

from src.api.voice.config import LiveVoiceConfig, load_live_config
from src.api.voice.persona import build_system_instruction

__all__ = ["LiveVoiceConfig", "load_live_config", "build_system_instruction"]
