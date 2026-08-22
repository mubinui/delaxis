"""The browser <-> server voice envelope.

Deliberately not a transparent relay of the provider's frames. The browser
learns only that it sends microphone PCM and receives speaker PCM; it never
sees the model id, the system prompt, or the provider's schema. That is what
lets the upstream protocol change, or the provider be swapped, without
reissuing every deployed page.

Audio travels as **binary** WebSocket frames (raw little-endian PCM16 mono),
which avoids ~33% base64 overhead and the encode/decode cost on both ends.
Everything else is a small JSON text frame keyed by ``t``.
"""

from __future__ import annotations

from typing import Final

# --- client -> server ------------------------------------------------------
# (binary frame) raw PCM16 mono at the negotiated input rate
CLIENT_STOP: Final = "stop"  # user released the mic; end of this turn's audio
CLIENT_BYE: Final = "bye"  # graceful teardown
# The outcome of a canvas operation the model asked for. The browser owns the
# canvas, so it — not the server — decides what actually happened.
CLIENT_TOOL_RESULT: Final = "tool_result"

CLIENT_FRAME_TYPES: Final = frozenset({CLIENT_STOP, CLIENT_BYE, CLIENT_TOOL_RESULT})

# --- server -> client ------------------------------------------------------
# (binary frame) raw PCM16 mono at the negotiated output rate
SERVER_READY: Final = "ready"  # upstream is live; carries the sample rates
SERVER_USER_TEXT: Final = "user_text"  # transcript of what the user said
SERVER_AGENT_TEXT: Final = "agent_text"  # transcript of what the model said
SERVER_INTERRUPTED: Final = "interrupted"  # barge-in: drop queued playback now
SERVER_TURN_END: Final = "turn_end"
SERVER_ERROR: Final = "error"
SERVER_ENDED: Final = "ended"
# The model wants to change the canvas. Carries the call id, the function name
# and its arguments; the browser applies it and answers with CLIENT_TOOL_RESULT.
SERVER_TOOL_CALL: Final = "tool_call"

SERVER_FRAME_TYPES: Final = frozenset(
    {
        SERVER_READY,
        SERVER_USER_TEXT,
        SERVER_AGENT_TEXT,
        SERVER_INTERRUPTED,
        SERVER_TURN_END,
        SERVER_ERROR,
        SERVER_ENDED,
        SERVER_TOOL_CALL,
    }
)

# --- close reasons carried on SERVER_ENDED ---------------------------------
REASON_CLIENT: Final = "client"
REASON_TIME_LIMIT: Final = "time_limit"
REASON_TURN_LIMIT: Final = "turn_limit"
REASON_BYTE_LIMIT: Final = "byte_limit"
REASON_UPSTREAM: Final = "upstream"
REASON_CAPACITY: Final = "capacity"

# --- WebSocket close codes -------------------------------------------------
# 1008 = policy violation, the standard code for a rejected credential.
CLOSE_UNAUTHORIZED: Final = 1008
# 4000-4999 is the application-private range.
CLOSE_REPLAY: Final = 4409
CLOSE_CAPACITY: Final = 4429
