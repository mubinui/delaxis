"""Shared chatbot page generation: theme presets, markdown support, config injection.

Single source of truth used by both the flash-deployment pipeline
(``src.api.routers.deployments``) and the AI frontend builder
(``src.api.routers.builder``). All colors are expressed as CSS variables so a
deployment's ``theme`` selects a preset instead of being silently ignored.
"""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any
from urllib.parse import urlparse

#: Bumped whenever the generated page changes in a way existing deployments
#: should receive. Pages are written to disk at deploy time, so without this a
#: fix to the page — an error message that read "[object Object]", say — would
#: only ever reach deployments created afterwards.
PAGE_VERSION = 3
GENERATOR = "delaxis-chatbot-page"

DEFAULT_THEME = "midnight"

# Each theme is a map of CSS variable name -> value, emitted as a :root block.
# Variable vocabulary mirrors workflow-editor/demo-assets/deployed-chat.html.
THEMES: dict[str, dict[str, str]] = {
    "midnight": {
        "bg": "#101820",
        "surface": "#121d29",
        "panel": "#0f1720",
        "border": "#263241",
        "text": "#e6edf3",
        "muted": "#9fb0c2",
        "accent": "#2f6fed",
        "accent-text": "#ffffff",
        "assistant-bubble": "#1b2a3a",
        "assistant-border": "#314257",
        "input-bg": "#111c28",
        "input-border": "#34465c",
        "code-bg": "#0b1220",
        "code-text": "#f8fafc",
        "link": "#93c5fd",
        "ok": "#74d99f",
        "shadow": "rgba(0,0,0,.28)",
    },
    "daylight": {
        "bg": "#f6f7fb",
        "surface": "#ffffff",
        "panel": "#eef1f7",
        "border": "#d8deea",
        "text": "#172033",
        "muted": "#5b6b83",
        "accent": "#2563eb",
        "accent-text": "#ffffff",
        "assistant-bubble": "#eef3ff",
        "assistant-border": "#dbe4f8",
        "input-bg": "#ffffff",
        "input-border": "#cbd5e1",
        "code-bg": "#111827",
        "code-text": "#f8fafc",
        "link": "#2563eb",
        "ok": "#16a34a",
        "shadow": "rgba(15,23,42,.12)",
    },
    "ocean": {
        "bg": "#04121b",
        "surface": "#072433",
        "panel": "#051a26",
        "border": "#12405a",
        "text": "#d8f0fa",
        "muted": "#86b3c7",
        "accent": "#06b6d4",
        "accent-text": "#04222d",
        "assistant-bubble": "#0a3346",
        "assistant-border": "#155a77",
        "input-bg": "#06202e",
        "input-border": "#17506c",
        "code-bg": "#021018",
        "code-text": "#e0f2fe",
        "link": "#67e8f9",
        "ok": "#5eead4",
        "shadow": "rgba(0,0,0,.35)",
    },
    "forest": {
        "bg": "#0c130d",
        "surface": "#131f15",
        "panel": "#0f1810",
        "border": "#28402b",
        "text": "#e7f0e7",
        "muted": "#9bb59d",
        "accent": "#22c55e",
        "accent-text": "#052e13",
        "assistant-bubble": "#1a2b1c",
        "assistant-border": "#2f4a33",
        "input-bg": "#122014",
        "input-border": "#33523a",
        "code-bg": "#081109",
        "code-text": "#ecfdf5",
        "link": "#86efac",
        "ok": "#4ade80",
        "shadow": "rgba(0,0,0,.32)",
    },
    "sunset": {
        "bg": "#1a1023",
        "surface": "#241531",
        "panel": "#1e1229",
        "border": "#3f2a52",
        "text": "#f4e8f7",
        "muted": "#bda3c9",
        "accent": "#f97316",
        "accent-text": "#331303",
        "assistant-bubble": "#2e1c3d",
        "assistant-border": "#4c3361",
        "input-bg": "#251733",
        "input-border": "#503a66",
        "code-bg": "#140b1c",
        "code-text": "#fdf4ff",
        "link": "#fdba74",
        "ok": "#86efac",
        "shadow": "rgba(0,0,0,.35)",
    },
    "mono": {
        "bg": "#ffffff",
        "surface": "#ffffff",
        "panel": "#f4f4f5",
        "border": "#d4d4d8",
        "text": "#111111",
        "muted": "#52525b",
        "accent": "#111111",
        "accent-text": "#ffffff",
        "assistant-bubble": "#f4f4f5",
        "assistant-border": "#d4d4d8",
        "input-bg": "#ffffff",
        "input-border": "#a1a1aa",
        "code-bg": "#18181b",
        "code-text": "#fafafa",
        "link": "#111111",
        "ok": "#16a34a",
        "shadow": "rgba(0,0,0,.10)",
    },
}

THEME_LABELS: dict[str, str] = {
    "midnight": "Midnight",
    "daylight": "Daylight",
    "ocean": "Ocean",
    "forest": "Forest",
    "sunset": "Sunset",
    "mono": "Mono",
}

# var() fallbacks keep this usable when injected into pages without a theme block.
MARKDOWN_STYLE = """
        .md-content p { margin: 0 0 8px; }
        .md-content p:last-child { margin-bottom: 0; }
        .md-content ul, .md-content ol { margin: 8px 0; padding-left: 20px; }
        .md-content li { margin: 3px 0; }
        .md-content code { background: rgba(148,163,184,.18); border-radius: 4px; padding: 2px 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: .92em; }
        .md-content pre { background: var(--code-bg, #0b1220); color: var(--code-text, #f8fafc); border-radius: 8px; padding: 12px; overflow: auto; white-space: pre; }
        .md-content pre code { background: transparent; padding: 0; color: inherit; }
        .md-content blockquote { margin: 8px 0; border-left: 3px solid var(--muted, #64748b); padding-left: 10px; color: var(--muted, #64748b); }
        .md-content a { color: var(--link, #2563eb); text-decoration: underline; }
        .md-content table { border-collapse: collapse; width: 100%; margin: 8px 0; }
        .md-content th, .md-content td { border: 1px solid rgba(148,163,184,.45); padding: 6px 8px; text-align: left; }
"""

VOICE_STYLE = """
        .mic {
          position: relative;
          border: 1px solid var(--input-border); background: var(--input-bg); color: var(--text);
          border-radius: var(--brand-radius, 10px); width: 44px; height: 44px; flex: 0 0 auto;
          display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
          transition: background .15s, border-color .15s, color .15s;
        }
        .mic:hover:not(:disabled) { border-color: var(--accent); }
        .mic:disabled { opacity: .5; cursor: not-allowed; }
        .mic svg { width: 18px; height: 18px; display: block; }
        .mic[hidden] { display: none; }
        .mic.busy { opacity: .7; cursor: progress; }
        .mic.live { background: var(--accent); border-color: var(--accent); color: var(--accent-text); }

        /* Two rings. The ambient one keeps the control feeling alive between
           utterances; the reactive one is scaled from the measured audio level
           (--voice-level, 0..1) so what you see is the actual signal. */
        .mic.live::after,
        .mic.live::before {
          content: ''; position: absolute; inset: -1px; border-radius: inherit;
          border: 2px solid var(--accent); pointer-events: none;
        }
        .mic.live::after { animation: micAmbient 2.2s ease-out infinite; }
        .mic.live::before {
          transform: scale(calc(1 + var(--voice-level, 0) * 0.55));
          opacity: calc(0.15 + var(--voice-level, 0) * 0.6);
          transition: transform .06s linear, opacity .06s linear;
        }
        @keyframes micAmbient {
          0%   { transform: scale(1);   opacity: .40; }
          100% { transform: scale(1.5); opacity: 0; }
        }

        /* Level meter. Each bar is driven by its own frequency band, so the
           strip reads as speech rather than a decorative loop. */
        .voice-viz {
          display: none; align-items: center; justify-content: center; gap: 3px;
          height: 20px; margin-left: 2px;
        }
        .voice-viz.on { display: flex; }
        .voice-viz i {
          width: 3px; border-radius: 2px; background: var(--accent); opacity: .75;
          height: calc(3px + var(--b, 0) * 17px);
          transition: height .07s linear, opacity .18s linear;
        }
        /* The agent's own voice is shown in a calmer tone, so it is obvious at a
           glance who is talking. */
        .voice-viz.speaking i { background: var(--muted); opacity: .95; }

        @media (prefers-reduced-motion: reduce) {
          .mic.live::after { animation: none; opacity: 0; }
          .mic.live::before { transition: none; transform: none; opacity: .35; }
          .voice-viz i { transition: none; height: 9px; }
        }
"""

# The whole realtime audio client, inlined. Deployed pages are validated against
# any external asset reference, and the worklet is loaded from a blob: URL for
# the same reason — there is no separate file to fetch.
VOICE_SCRIPT = r"""
        // --- Live voice -------------------------------------------------------
        // Microphone PCM goes up to this application over a WebSocket, which
        // relays it to the realtime model and streams speech back. The browser
        // never talks to the model provider and never sees an API key.
        //
        // Voice replies come straight from the realtime model using the
        // deployment's persona: the workflow's tools and routing do not run.
        const VOICE = (function () {
          var IDLE = 'idle', STARTING = 'starting', LISTENING = 'listening', SPEAKING = 'speaking';
          var state = IDLE;
          var ws = null, inCtx = null, outCtx = null, micStream = null;
          var node = null, source = null, micGain = null, outGain = null;
          var playHead = 0, queued = [], onState = null, onText = null;
          var inRate = 16000, outRate = 24000;
          var inAnalyser = null, outAnalyser = null, frameHandle = null, onLevel = null;

          // The visualiser reads real audio, so it stops when the audio stops —
          // a decorative loop would keep dancing through silence and dropouts.
          var BANDS = 5;

          function makeAnalyser(ctx, from) {
            var analyser = ctx.createAnalyser();
            analyser.fftSize = 256;
            analyser.smoothingTimeConstant = 0.7;
            from.connect(analyser);
            return analyser;
          }

          function startLevels() {
            if (frameHandle !== null) return;
            var bins = new Uint8Array(128);
            var tick = function () {
              frameHandle = requestAnimationFrame(tick);
              // Whoever is currently making sound is what we show.
              var speaking = queued.length > 0;
              var analyser = speaking ? outAnalyser : inAnalyser;
              if (!analyser || !onLevel) return;
              analyser.getByteFrequencyData(bins);
              // Speech energy sits low in the spectrum; sampling the whole range
              // would leave the upper bars permanently flat.
              var usable = Math.floor(bins.length * 0.55);
              var per = Math.max(1, Math.floor(usable / BANDS));
              var bands = [];
              var total = 0;
              for (var b = 0; b < BANDS; b++) {
                var sum = 0;
                for (var i = 0; i < per; i++) sum += bins[b * per + i] || 0;
                var value = (sum / per) / 255;
                bands.push(value);
                total += value;
              }
              onLevel(Math.min(1, (total / BANDS) * 1.6), bands, speaking);
            };
            frameHandle = requestAnimationFrame(tick);
          }

          function stopLevels() {
            if (frameHandle !== null) cancelAnimationFrame(frameHandle);
            frameHandle = null;
            inAnalyser = null;
            outAnalyser = null;
            if (onLevel) onLevel(0, [0, 0, 0, 0, 0], false);
          }

          // 128-frame quanta are far too small to send individually; batch to
          // ~40ms so the socket sees ~25 modest frames a second.
          var WORKLET_SRC = [
            'class MicCapture extends AudioWorkletProcessor {',
            '  constructor(options) {',
            '    super();',
            '    var o = (options && options.processorOptions) || {};',
            '    this.target = o.targetRate || 16000;',
            '    this.ratio = sampleRate / this.target;',
            '    this.chunk = Math.round(this.target * 0.04);',
            '    this.buf = []; this.pos = 0;',
            '  }',
            '  process(inputs) {',
            '    var input = inputs[0] && inputs[0][0];',
            '    if (!input) return true;',
            // Resample only when the requested rate was not honoured. The
            // AudioContext sampleRate hint is advisory, not a guarantee.
            '    if (this.ratio === 1) {',
            '      for (var i = 0; i < input.length; i++) this.buf.push(input[i]);',
            '    } else {',
            '      while (this.pos < input.length) {',
            '        this.buf.push(input[Math.floor(this.pos)]);',
            '        this.pos += this.ratio;',
            '      }',
            '      this.pos -= input.length;',
            '    }',
            '    while (this.buf.length >= this.chunk) {',
            '      var slice = this.buf.splice(0, this.chunk);',
            '      var pcm = new Int16Array(slice.length);',
            '      for (var j = 0; j < slice.length; j++) {',
            '        var s = Math.max(-1, Math.min(1, slice[j]));',
            '        pcm[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;',
            '      }',
            '      this.port.postMessage(pcm.buffer, [pcm.buffer]);',
            '    }',
            '    return true;',
            '  }',
            '}',
            'registerProcessor("mic-capture", MicCapture);'
          ].join('\n');

          function setState(next) {
            state = next;
            if (onState) onState(next);
          }

          function send(obj) {
            if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
          }

          // Playback is scheduled on a moving head rather than played on
          // arrival, so consecutive chunks are gapless.
          function enqueue(int16) {
            if (!outCtx) return;
            var buf = outCtx.createBuffer(1, int16.length, outRate);
            var ch = buf.getChannelData(0);
            for (var i = 0; i < int16.length; i++) ch[i] = int16[i] / 0x8000;
            var src = outCtx.createBufferSource();
            src.buffer = buf;
            src.connect(outGain);
            var now = outCtx.currentTime;
            if (playHead < now + 0.05) playHead = now + 0.05; // jitter cushion
            src.start(playHead);
            playHead += buf.duration;
            queued.push(src);
            src.onended = function () {
              var at = queued.indexOf(src);
              if (at !== -1) queued.splice(at, 1);
              if (!queued.length && state === SPEAKING) setState(LISTENING);
              duck();
            };
            // Duck the microphone while the agent speaks. Without this, laptop
            // speakers feed straight back in and the model interrupts itself.
            duck();
            if (state === LISTENING) setState(SPEAKING);
          }

          function duck() {
            if (micGain && inCtx) {
              micGain.gain.setTargetAtTime(queued.length ? 0 : 1, inCtx.currentTime, 0.02);
            }
          }

          function flushPlayback() {
            for (var i = 0; i < queued.length; i++) {
              try { queued[i].stop(); } catch (_) { /* already ended */ }
            }
            queued = [];
            playHead = 0;
            duck();
          }

          // Split out from attachCapture so the permission dialog happens before
          // a ticket is minted: tickets live ~30s, and a user can easily sit on
          // that dialog for longer, which expired the ticket before the socket
          // opened.
          async function requestMic() {
            if (micStream) return micStream;
            micStream = await navigator.mediaDevices.getUserMedia({
              audio: {
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
              },
            });
            return micStream;
          }

          async function attachCapture() {
            await requestMic();
            inCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: inRate });
            await inCtx.resume();
            source = inCtx.createMediaStreamSource(micStream);
            micGain = inCtx.createGain();
            source.connect(micGain);
            // Tapped before the ducking gain, so the meter still shows the user
            // talking over the agent — which is exactly when barge-in matters.
            inAnalyser = makeAnalyser(inCtx, source);

            var onPcm = function (buffer) {
              if (ws && ws.readyState === 1) ws.send(buffer);
            };

            var usedWorklet = false;
            if (inCtx.audioWorklet) {
              try {
                // blob: is same-origin and needs no network fetch. A strict CSP
                // without blob: in script-src rejects it, hence the fallback.
                var url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: 'application/javascript' }));
                await inCtx.audioWorklet.addModule(url);
                URL.revokeObjectURL(url);
                node = new AudioWorkletNode(inCtx, 'mic-capture', {
                  processorOptions: { targetRate: inRate },
                });
                node.port.onmessage = function (event) { onPcm(event.data); };
                micGain.connect(node);
                usedWorklet = true;
              } catch (_) {
                usedWorklet = false;
              }
            }

            if (!usedWorklet) {
              // Deprecated but universally available and CSP-free.
              var ratio = inCtx.sampleRate / inRate;
              node = inCtx.createScriptProcessor(4096, 1, 1);
              node.onaudioprocess = function (event) {
                var input = event.inputBuffer.getChannelData(0);
                var count = Math.floor(input.length / ratio);
                var pcm = new Int16Array(count);
                for (var i = 0; i < count; i++) {
                  var s = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)]));
                  pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                onPcm(pcm.buffer);
              };
              micGain.connect(node);
              // ScriptProcessor only runs while connected to a destination;
              // a zero gain keeps it silent.
              var mute = inCtx.createGain();
              mute.gain.value = 0;
              node.connect(mute);
              mute.connect(inCtx.destination);
            }
          }

          async function start(opts) {
            if (state !== IDLE) return;
            onState = (opts && opts.onState) || null;
            onText = (opts && opts.onText) || null;
            onLevel = (opts && opts.onLevel) || null;
            setState(STARTING);
            try {
              // Microphone first, ticket second — see requestMic.
              await requestMic();
              var ticket = await opts.mintTicket();
              inRate = ticket.input_sample_rate || inRate;
              outRate = ticket.output_sample_rate || outRate;

              // Created inside the click handler's task so Safari/iOS allow it.
              outCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: outRate });
              outGain = outCtx.createGain();
              outGain.connect(outCtx.destination);
              outAnalyser = makeAnalyser(outCtx, outGain);
              await outCtx.resume();

              await attachCapture();
              startLevels();

              var scheme = location.protocol === 'https:' ? 'wss://' : 'ws://';
              var base = (opts.apiBase || '').replace(/^http/, 'ws');
              var origin = base || (scheme + location.host);
              ws = new WebSocket(origin + ticket.ws_path + '?ticket=' + encodeURIComponent(ticket.ticket));
              ws.binaryType = 'arraybuffer';

              ws.onmessage = function (event) {
                if (typeof event.data !== 'string') {
                  enqueue(new Int16Array(event.data));
                  return;
                }
                var frame;
                try { frame = JSON.parse(event.data); } catch (_) { return; }
                if (frame.t === 'ready') { setState(LISTENING); return; }
                if (frame.t === 'interrupted') { flushPlayback(); setState(LISTENING); return; }
                if (frame.t === 'user_text' && onText) { onText('user', frame.d); return; }
                if (frame.t === 'agent_text' && onText) { onText('assistant', frame.d); return; }
                if (frame.t === 'error') { if (onText) onText('error', frame.message || 'Voice error'); stop(); return; }
                if (frame.t === 'ended') { stop(frame.reason); return; }
              };
              ws.onerror = function () { stop('error'); };
              ws.onclose = function () { if (state !== IDLE) stop('closed'); };
            } catch (err) {
              if (onText) onText('error', (err && err.message) || 'Microphone unavailable');
              stop('error');
            }
          }

          function stop(reason) {
            if (ws && ws.readyState === 1) send({ t: 'bye' });
            stopLevels();
            flushPlayback();
            try { if (node) node.disconnect(); } catch (_) { /* ignore */ }
            try { if (micGain) micGain.disconnect(); } catch (_) { /* ignore */ }
            try { if (source) source.disconnect(); } catch (_) { /* ignore */ }
            if (micStream) {
              micStream.getTracks().forEach(function (track) { track.stop(); });
            }
            if (inCtx) { try { inCtx.close(); } catch (_) { /* ignore */ } }
            if (outCtx) { try { outCtx.close(); } catch (_) { /* ignore */ } }
            if (ws) { try { ws.close(); } catch (_) { /* ignore */ } }
            ws = null; node = null; source = null; micGain = null;
            inCtx = null; outCtx = null; outGain = null; micStream = null;
            setState(IDLE);
            return reason;
          }

          return {
            start: start,
            stop: stop,
            endTurn: function () { send({ t: 'stop' }); },
            isActive: function () { return state !== IDLE; },
            state: function () { return state; },
          };
        })();

        // Learning the session id without the page's cooperation. Every
        // deployable page has to create a conversation via POST /api/v1/sessions
        // (the page validator refuses to publish one that does not), so watching
        // responses go by is more reliable than requiring a generated page to
        // expose an internal variable. A page may still override this by
        // defining window.DELAXIS_VOICE_HOOKS.sessionId.
        var VOICE_SESSION = (function () {
          var lastId = null;
          var original = window.fetch;
          if (typeof original === 'function') {
            window.fetch = function () {
              var promise = original.apply(this, arguments);
              try {
                var first = arguments[0];
                var url = String((first && first.url) || first || '');
                if (url.indexOf('/api/v1/sessions') !== -1) {
                  promise.then(function (response) {
                    if (response && response.ok) {
                      response.clone().json().then(function (body) {
                        var id = body && (body.session_id || body.id);
                        if (id) lastId = String(id);
                      }).catch(function () { /* not JSON */ });
                    }
                    return response;
                  }).catch(function () { /* request failed */ });
                }
              } catch (_) { /* never break the page's own fetch */ }
              return promise;
            };
          }
          return {
            current: function () {
              var hooks = window.DELAXIS_VOICE_HOOKS;
              if (hooks && typeof hooks.sessionId === 'function') {
                var fromHook = hooks.sessionId();
                if (fromHook) return String(fromHook);
              }
              return lastId;
            },
          };
        })();

        async function mintVoiceTicket(apiBase, deployment) {
          var sessionId = VOICE_SESSION.current();
          if (!sessionId) throw new Error('Send a message first to start a conversation');
          var response = await fetch((apiBase || '') + '/api/v1/voice/ticket', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, deployment: deployment || null }),
          });
          if (!response.ok) {
            var detail = '';
            try { detail = (await response.json()).detail || ''; } catch (_) { /* no body */ }
            throw new Error(detail || ('Voice unavailable (' + response.status + ')'));
          }
          return response.json();
        }

        // Self-mounting UI. A generated page has no known markup, so the button
        // is placed relative to whatever submit control exists, and falls back
        // to a floating button.
        (function () {
          var cfg = window.CHATBOT_CONFIG || {};
          if (!cfg.voice || !cfg.voice.enabled) return;

          function mount() {
            var button = document.getElementById('mic');
            if (!button) {
              button = document.createElement('button');
              button.id = 'mic';
              button.type = 'button';
              var anchor = document.querySelector('#send, button[type=submit], form button');
              if (anchor && anchor.parentNode) {
                anchor.parentNode.insertBefore(button, anchor);
              } else {
                button.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:60';
                document.body.appendChild(button);
              }
            }
            button.className = 'mic';
            button.hidden = false;
            button.setAttribute('aria-label', 'Talk to the assistant');
            button.setAttribute('aria-pressed', 'false');
            button.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">'
              + '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"/>'
              + '<path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>';

            // Level meter, mounted next to the button wherever that ended up.
            var viz = document.getElementById('voice-viz');
            if (!viz) {
              viz = document.createElement('div');
              viz.id = 'voice-viz';
              viz.className = 'voice-viz';
              viz.setAttribute('aria-hidden', 'true');
              for (var i = 0; i < 5; i++) viz.appendChild(document.createElement('i'));
              if (button.parentNode) button.parentNode.insertBefore(viz, button);
            }
            var bars = viz.getElementsByTagName('i');

            var hooks = window.DELAXIS_VOICE_HOOKS || {};
            var status = hooks.status || function () {};
            var LABELS = {
              starting: 'Connecting voice…',
              listening: 'Listening…',
              speaking: 'Speaking…',
              idle: 'Ready',
            };

            function applyState(next) {
              button.classList.toggle('live', next === 'listening' || next === 'speaking');
              button.classList.toggle('speaking', next === 'speaking');
              button.classList.toggle('busy', next === 'starting');
              button.setAttribute('aria-pressed', next === 'idle' ? 'false' : 'true');
              viz.classList.toggle('on', next === 'listening' || next === 'speaking');
              status(LABELS[next] || 'Ready', false);
              // One input mode at a time: a typed turn during a voice session
              // would go to the workflow while the realtime model knew nothing
              // about it, and the two histories would diverge.
              var input = document.getElementById('input');
              var send = document.getElementById('send');
              var hint = document.getElementById('hint');
              var active = next !== 'idle';
              if (input) input.disabled = active;
              if (send) send.disabled = active;
              if (hint && active) hint.textContent = 'Voice mode — tap the mic again to stop';
              else if (hint && hooks.resetHint) hooks.resetHint();
            }

            button.addEventListener('click', function () {
              if (VOICE.isActive()) { VOICE.stop('client'); return; }
              VOICE.start({
                apiBase: cfg.api_url || '',
                mintTicket: function () { return mintVoiceTicket(cfg.api_url || '', cfg.name || ''); },
                onState: applyState,
                onText: function (role, text) {
                  if (role === 'error') { status(text, true); return; }
                  if (hooks.transcript) hooks.transcript(role, text);
                },
                onLevel: function (level, bands, speaking) {
                  // Custom properties rather than inline geometry, so the CSS
                  // owns the look and honours prefers-reduced-motion.
                  button.style.setProperty('--voice-level', level.toFixed(3));
                  viz.classList.toggle('speaking', speaking);
                  for (var i = 0; i < bars.length; i++) {
                    bars[i].style.setProperty('--b', (bands[i] || 0).toFixed(3));
                  }
                },
              });
            });
          }

          if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', mount);
          } else {
            mount();
          }
        })();
"""

MARKDOWN_SCRIPT = r"""
        function escapeHtml(value) {
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function inlineMarkdown(value) {
            let html = escapeHtml(value);
            html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
            return html;
        }
        function renderMarkdown(markdown) {
            const lines = String(markdown || '').split(/\r?\n/);
            const blocks = [];
            let list = null;
            let code = [];
            let inCode = false;
            function closeList() {
                if (!list) return;
                blocks.push('<' + list.type + '>' + list.items.map(item => '<li>' + inlineMarkdown(item) + '</li>').join('') + '</' + list.type + '>');
                list = null;
            }
            function closeCode() {
                if (!inCode) return;
                blocks.push('<pre><code>' + escapeHtml(code.join('\n')) + '</code></pre>');
                code = [];
                inCode = false;
            }
            for (const line of lines) {
                if (line.trim().startsWith('```')) {
                    if (inCode) closeCode(); else { closeList(); inCode = true; code = []; }
                    continue;
                }
                if (inCode) { code.push(line); continue; }
                if (!line.trim()) { closeList(); continue; }
                const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
                const unordered = line.match(/^\s*[-*]\s+(.+)$/);
                if (ordered || unordered) {
                    const type = ordered ? 'ol' : 'ul';
                    if (!list || list.type !== type) { closeList(); list = { type, items: [] }; }
                    list.items.push((ordered || unordered)[1]);
                    continue;
                }
                closeList();
                if (line.startsWith('### ')) blocks.push('<h3>' + inlineMarkdown(line.slice(4)) + '</h3>');
                else if (line.startsWith('## ')) blocks.push('<h2>' + inlineMarkdown(line.slice(3)) + '</h2>');
                else if (line.startsWith('# ')) blocks.push('<h1>' + inlineMarkdown(line.slice(2)) + '</h1>');
                else if (line.startsWith('> ')) blocks.push('<blockquote>' + inlineMarkdown(line.slice(2)) + '</blockquote>');
                else blocks.push('<p>' + inlineMarkdown(line) + '</p>');
            }
            closeCode();
            closeList();
            return blocks.join('');
        }
"""

CONFIG_SNIPPET = "<script>window.CHATBOT_CONFIG = __CHATBOT_CONFIG__;</script>"

_HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)
_SCRIPT_OPEN_RE = re.compile(r"<script\b", re.IGNORECASE)
# Absolute ws:// or wss:// URLs in a string literal. Relative sockets built from
# location.host (which is what the injected voice client does) do not match.
_WS_URL_RE = re.compile(r"""['"](wss?://[^'"\s]+)['"]""", re.IGNORECASE)


def normalize_theme(theme: str | None) -> str:
    """Map any theme value onto a known preset id."""
    if theme and theme.strip().lower() in THEMES:
        return theme.strip().lower()
    return DEFAULT_THEME


def theme_css(theme: str) -> str:
    """Emit the ``:root { --bg: ...; }`` block for a theme preset."""
    variables = THEMES[normalize_theme(theme)]
    lines = "\n".join(f"      --{name}: {value};" for name, value in variables.items())
    return f":root {{\n{lines}\n    }}"


def all_theme_css(theme: str) -> str:
    """The deployment's theme as ``:root``, plus every preset as an override block.

    Emitting all of them is what lets a visitor switch theme from the page's
    settings without a round trip — the picker only has to set
    ``data-delaxis-theme`` on <html>.
    """
    blocks = [theme_css(theme)]
    for theme_id, variables in THEMES.items():
        lines = "\n".join(f"      --{name}: {value};" for name, value in variables.items())
        blocks.append(f'[data-delaxis-theme="{theme_id}"] {{\n{lines}\n    }}')
    return "\n    ".join(blocks)


# Everything a generated design is allowed to change. Anything outside this set
# is ignored, so a design spec can restyle the page but never break its wiring.
BRAND_COLOR_KEYS = frozenset(THEMES[DEFAULT_THEME])
_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%/]+\)|hsla?\([\d\s.,%/]+\)|[a-z]+)$")
_FONT_RE = re.compile(r"^[\w\s,\"'\-]{1,180}$")


def sanitize_brand(brand: dict[str, Any] | None) -> dict[str, str]:
    """Keep only the presentation values that are safe to inline as CSS.

    A generated design arrives as model output, so every value is treated as
    untrusted: anything that is not a plain colour, a font stack, or a small
    length is dropped rather than written into a stylesheet.
    """
    if not brand:
        return {}
    clean: dict[str, str] = {}
    for key, value in brand.items():
        text = str(value).strip()
        if not text or ";" in text or "}" in text or "<" in text:
            continue
        if key in BRAND_COLOR_KEYS and _COLOR_RE.match(text):
            clean[key] = text
        elif key == "font" and _FONT_RE.match(text):
            clean[key] = text
        elif key == "radius" and re.match(r"^\d{1,2}(px|rem)$", text):
            clean[key] = text
    return clean


def _parse_color(value: str) -> tuple[float, float, float] | None:
    """(r, g, b) in 0-255 for a hex or rgb() colour, or None if not parseable."""
    text = value.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits[:3])
        if len(digits) in (6, 8):
            try:
                return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                return None
        return None
    match = re.match(r"rgba?\(([^)]+)\)", text)
    if match:
        parts = [p.strip() for p in re.split(r"[,\s/]+", match.group(1)) if p.strip()]
        if len(parts) >= 3:
            try:
                return tuple(float(p.rstrip("%")) * (2.55 if p.endswith("%") else 1) for p in parts[:3])  # type: ignore[return-value]
            except ValueError:
                return None
    return None


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        srgb = value / 255
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast between two colours; 0.0 when either cannot be parsed."""
    fg, bg = _parse_color(foreground), _parse_color(background)
    if fg is None or bg is None:
        return 0.0
    light, dark = sorted((_relative_luminance(fg), _relative_luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# (foreground var, background var, minimum ratio). Body copy needs 4.5:1;
# secondary text and large UI elements are held to 3:1, per WCAG AA.
CONTRAST_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("text", "bg", 4.5),
    ("text", "surface", 4.5),
    ("text", "panel", 4.5),
    ("text", "assistant-bubble", 4.5),
    ("muted", "bg", 3.0),
    ("muted", "panel", 3.0),
    ("muted", "surface", 3.0),
    ("accent-text", "accent", 4.5),
    ("link", "assistant-bubble", 3.0),
)


def _shift(color: str, amount: float) -> str:
    """Nudge a colour toward white (positive) or black (negative)."""
    rgb = _parse_color(color)
    if rgb is None:
        return color
    target = 255.0 if amount > 0 else 0.0
    weight = abs(amount)
    return "#" + "".join(f"{int(round(c + (target - c) * weight)):02x}" for c in rgb)


# Surfaces that sit on the page background. When a design restyles `bg` without
# naming these, they are derived from it — leaving them at the theme's value is
# what produces a cream page with dark panels bolted onto it.
_BACKGROUND_FAMILY: tuple[tuple[str, float], ...] = (
    ("surface", 0.04),
    ("panel", 0.07),
    ("assistant-bubble", 0.05),
    ("input-bg", 0.02),
)


def _readable_on(background: str, minimum: float, preferred: str) -> str:
    """A foreground colour that clears ``minimum`` against ``background``.

    The preferred value wins when it already passes; otherwise this falls back
    to near-black or near-white, whichever has more contrast. Something legible
    is always returned, so a palette is never left unreadable.
    """
    if contrast_ratio(preferred, background) >= minimum:
        return preferred
    dark, light = "#111111", "#ffffff"
    return dark if contrast_ratio(dark, background) >= contrast_ratio(light, background) else light


def harmonize_brand(theme: str, brand: dict[str, Any] | None) -> tuple[dict[str, str], list[str]]:
    """Make a generated palette readable, keeping as much of it as possible.

    A generated palette regularly looks right in the abstract and fails in
    practice — pale grey on cream, or button text that vanishes on its own
    accent. Rather than trusting the model to check, each pair is measured here.

    Backgrounds are always kept, because they carry the design's intent; only
    the text colour on top is corrected, first to the theme's own value and then
    to black or white if that is still not enough. Returns the adjusted brand
    plus a note for every colour that had to change.
    """
    clean = sanitize_brand(brand)
    if not clean:
        return {}, []

    base = THEMES[normalize_theme(theme)]
    notes: list[str] = []

    def effective(name: str) -> str:
        return clean.get(name, base.get(name, "#000000"))

    # A design that changes the page background but not the panels on it would
    # otherwise inherit the theme's — a cream page with midnight panels. Derive
    # the unstated ones so the palette stays coherent.
    page_background = clean.get("bg")
    if page_background:
        going_lighter = _relative_luminance(_parse_color(page_background) or (0, 0, 0)) > 0.5
        for name, amount in _BACKGROUND_FAMILY:
            if name not in clean:
                clean[name] = _shift(page_background, -amount if going_lighter else amount)

    for foreground, background, minimum in CONTRAST_PAIRS:
        background_value = effective(background)
        if contrast_ratio(effective(foreground), background_value) >= minimum:
            continue
        replacement = _readable_on(background_value, minimum, base.get(foreground, "#111111"))
        if replacement == effective(foreground):
            continue
        clean[foreground] = replacement
        notes.append(f"{foreground} was unreadable on {background}, corrected to {replacement}")

    return clean, notes


def brand_css(brand: dict[str, Any] | None) -> str:
    """A ``:root`` override block for a generated design, or nothing."""
    clean = sanitize_brand(brand)
    if not clean:
        return ""
    lines = []
    for key, value in clean.items():
        name = "brand-font" if key == "font" else "brand-radius" if key == "radius" else key
        lines.append(f"      --{name}: {value};")
    # Placed after the theme blocks so it wins, but still under the visitor's
    # own theme choice if they pick one from the settings drawer.
    return ":root {\n" + "\n".join(lines) + "\n    }"


def theme_presets() -> list[dict[str, Any]]:
    """Theme list for the studio's deploy UI."""
    return [
        {"id": theme_id, "label": THEME_LABELS.get(theme_id, theme_id.title()), "vars": variables}
        for theme_id, variables in THEMES.items()
    ]


def safe_json(obj: Any) -> str:
    """JSON that is safe to embed inside a <script> block ('</' cannot close the tag)."""
    return json.dumps(obj).replace("</", "<\\/")


def ensure_config_contract(html: str) -> str:
    """Guarantee the page carries the __CHATBOT_CONFIG__ placeholder before any app script.

    The assignment must execute before the code that reads ``window.CHATBOT_CONFIG``,
    so it is inserted at the top of <head> (never appended at the end of <body>).
    """
    if "__CHATBOT_CONFIG__" in html:
        return html
    match = _HEAD_OPEN_RE.search(html)
    if match:
        return f"{html[:match.end()]}\n  {CONFIG_SNIPPET}{html[match.end():]}"
    match = _SCRIPT_OPEN_RE.search(html)
    if match:
        return f"{html[:match.start()]}{CONFIG_SNIPPET}\n{html[match.start():]}"
    return f"{CONFIG_SNIPPET}\n{html}"


def inject_runtime_config(html: str, config: dict[str, Any]) -> str:
    """Substitute the runtime config into the page, adding the contract if missing."""
    html = ensure_config_contract(html)
    return html.replace("__CHATBOT_CONFIG__", safe_json(config))


def ensure_markdown_support(html: str) -> str:
    """Add the markdown renderer (style + script) to pages that lack one.

    The script lands in <head> so ``renderMarkdown`` is defined before any body
    script runs. Every replacement is count=1 and has a fallback anchor, so the
    helpers never silently no-op on pages missing </style> or </body>.
    """
    if "function renderMarkdown" in html:
        return html
    if "</style>" in html:
        html = html.replace("</style>", f"{MARKDOWN_STYLE}\n  </style>", 1)
    elif "</head>" in html:
        html = html.replace("</head>", f"<style>{MARKDOWN_STYLE}</style>\n</head>", 1)
    else:
        html = f"<style>{MARKDOWN_STYLE}</style>\n{html}"

    script = f"<script>\n{MARKDOWN_SCRIPT}\n</script>"
    if "</head>" in html:
        html = html.replace("</head>", f"{script}\n</head>", 1)
    else:
        match = _SCRIPT_OPEN_RE.search(html)
        if match:
            html = f"{html[:match.start()]}{script}\n{html[match.start():]}"
        else:
            html = f"{html}\n{script}"
    return html


def ensure_voice_support(html: str) -> str:
    """Add the live-voice client (style + script) to a page that lacks one.

    Same shape as ``ensure_markdown_support``: idempotent, every replacement is
    count=1, and each has a fallback anchor so it never silently no-ops on a page
    missing ``</style>`` or ``</head>``. The script self-mounts its own button, so
    this works on an AI-generated page whose markup is unknown.
    """
    if "const VOICE = (function" in html:
        return html
    if "</style>" in html:
        html = html.replace("</style>", f"{VOICE_STYLE}\n  </style>", 1)
    elif "</head>" in html:
        html = html.replace("</head>", f"<style>{VOICE_STYLE}</style>\n</head>", 1)
    else:
        html = f"<style>{VOICE_STYLE}</style>\n{html}"

    # Must run after the page's own script has had a chance to define its hooks
    # and create a session, so this goes at the end of <body> rather than <head>.
    script = f"<script>\n{VOICE_SCRIPT}\n</script>"
    if "</body>" in html:
        html = html.replace("</body>", f"{script}\n</body>", 1)
    else:
        html = f"{html}\n{script}"
    return html


def page_defects(html: str) -> list[str]:
    """Structural problems that make a page not work as a chatbot.

    Checked separately from the cosmetic warnings because a generated page that
    hits any of these is not deployable — its buttons do nothing, or its chat
    never reaches the API. Catching them here is what stops a broken page from
    being published.
    """
    defects: list[str] = []
    lowered = html.lower()

    if "window.chatbot_config" not in lowered:
        defects.append("Never reads window.CHATBOT_CONFIG, so it does not know which workflow to talk to.")
    if "/api/v1/sessions" not in html:
        defects.append("Never calls /api/v1/sessions, so no conversation is ever created.")
    elif "/messages" not in html:
        defects.append("Creates a session but never posts to /messages, so nothing is ever sent.")

    # Something has to turn a user action into a request. Without any of these
    # the page renders and the buttons are inert.
    if not any(token in html for token in ("addEventListener", "onsubmit", "onclick", "onSubmit", "onClick")):
        defects.append("No event handlers, so nothing happens when the user presses send.")
    if "fetch(" not in html and "XMLHttpRequest" not in html:
        defects.append("Never makes an HTTP request.")

    # Somewhere to type and something to submit.
    if "<textarea" not in lowered and "<input" not in lowered:
        defects.append("No text input, so there is no way to send a message.")

    # Deployed pages are served from this app with no network egress guarantees;
    # a CDN reference is a blank screen for anyone behind a firewall.
    for pattern in ("src=\"http", "src='http", "href=\"http"):
        index = lowered.find(pattern.lower())
        while index != -1:
            snippet = html[index : index + 160]
            if any(host in snippet for host in ("cdn.", "unpkg.com", "jsdelivr", "googleapis.com", "cdnjs")):
                defects.append("Loads an external CDN asset, which will not resolve in an offline deployment.")
                break
            index = lowered.find(pattern.lower(), index + 1)

    # A page must never open a socket to a third party. This matters much more
    # now that live voice exists: the whole point of relaying audio through this
    # application is that the provider key stays server-side, and a generated
    # page that dialled the provider directly would defeat that while sailing
    # straight past the CDN scan above (which only looks at src=/href=).
    for match in _WS_URL_RE.finditer(html):
        host = (urlparse(match.group(1)).hostname or "").lower()
        if host and host not in ("localhost", "127.0.0.1", "[::1]"):
            defects.append(
                "Opens a WebSocket to an external host; a deployed page must only "
                "talk to its own origin."
            )
            break

    if html.lstrip().startswith("```") or html.rstrip().endswith("```"):
        defects.append("Still wrapped in markdown code fences.")

    # De-duplicate while keeping order, so the CDN scan cannot report twice.
    seen: set[str] = set()
    return [d for d in defects if not (d in seen or seen.add(d))]


def validate_page(html: str, *, voice_enabled: bool = False) -> list[str]:
    """Warnings for a page about to be deployed (powers the deploy preview)."""
    warnings: list[str] = []
    lowered = html.lower()
    if "<!doctype" not in lowered:
        warnings.append("Missing <!doctype html> declaration.")
    if "<head" not in lowered:
        warnings.append("Missing <head> section.")
    if "<body" not in lowered:
        warnings.append("Missing <body> section.")
    if "function rendermarkdown" not in lowered:
        warnings.append("Markdown renderer missing — assistant replies will render as plain text.")
    if voice_enabled and "/api/v1/voice/ticket" not in html:
        warnings.append("Voice is enabled but the page has no voice client — the mic will not appear.")
    warnings.extend(page_defects(html))
    return warnings


EMBED_TEMPLATE = r"""/* Delaxis embed widget for the "__DEPLOYMENT_ID__" deployment.
 *
 * Usage on any page:
 *   <script src="https://your-delaxis-host/d/__DEPLOYMENT_ID__/embed.js" defer></script>
 *
 * Options are read from the script tag's data- attributes:
 *   data-position="right|left"   which corner the launcher sits in
 *   data-label="Chat with us"    launcher tooltip and aria-label
 *   data-open="true"             open the panel on load
 *   data-width / data-height     panel size in px
 */
(function () {
  var script = document.currentScript
    || document.querySelector('script[src*="/d/__DEPLOYMENT_ID__/embed.js"]');
  var data = (script && script.dataset) || {};
  var origin = '__ORIGIN__';
  if (!origin && script) {
    try { origin = new URL(script.src).origin; } catch (e) { origin = ''; }
  }
  var src = origin + '/d/__DEPLOYMENT_ID__/';
  var side = data.position === 'left' ? 'left' : 'right';
  var label = data.label || '__TITLE__';
  var width = parseInt(data.width, 10) || 400;
  var height = parseInt(data.height, 10) || 620;
  var accent = data.accent || '__ACCENT__';

  // A single id keeps a double-included script from stacking two launchers.
  if (document.getElementById('delaxis-embed-__DEPLOYMENT_ID__')) return;

  var root = document.createElement('div');
  root.id = 'delaxis-embed-__DEPLOYMENT_ID__';

  var style = document.createElement('style');
  style.textContent = [
    '#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-launcher{position:fixed;bottom:20px;' + side + ':20px;z-index:2147483000;',
    'width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;color:#fff;background:' + accent + ';',
    'box-shadow:0 10px 30px rgba(0,0,0,.28);display:grid;place-items:center;transition:transform .15s}',
    '#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-launcher:hover{transform:scale(1.06)}',
    '#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-panel{position:fixed;bottom:88px;' + side + ':20px;z-index:2147483000;',
    'width:' + width + 'px;height:' + height + 'px;max-width:calc(100vw - 32px);max-height:calc(100vh - 120px);',
    'border:0;border-radius:14px;overflow:hidden;background:#fff;box-shadow:0 24px 70px rgba(0,0,0,.35);display:none}',
    '#delaxis-embed-__DEPLOYMENT_ID__.delaxis-open .delaxis-panel{display:block}',
    '@media (max-width:520px){#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-panel{',
    'inset:0;width:100%;height:100%;max-width:none;max-height:none;border-radius:0}}',
  ].join('');

  var frame = document.createElement('iframe');
  frame.className = 'delaxis-panel';
  frame.title = label;
  frame.setAttribute('loading', 'lazy');
  // The page needs storage for its conversation list, and forms for the composer.
  frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin allow-popups');

  var button = document.createElement('button');
  button.className = 'delaxis-launcher';
  button.type = 'button';
  button.setAttribute('aria-label', label);
  button.title = label;
  button.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.5 8.5 0 0 1-3.8-.9L3 21l2-4.9A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z"/></svg>';

  function toggle(open) {
    var isOpen = open === undefined ? !root.classList.contains('delaxis-open') : open;
    root.classList.toggle('delaxis-open', isOpen);
    button.setAttribute('aria-expanded', String(isOpen));
    // Loading on first open keeps the host page's initial render untouched.
    if (isOpen && !frame.src) frame.src = src;
  }

  button.addEventListener('click', function () { toggle(); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') toggle(false);
  });

  root.appendChild(style);
  root.appendChild(frame);
  root.appendChild(button);
  document.body.appendChild(root);

  if (data.open === 'true') toggle(true);

  // Minimal programmatic control for host pages that want their own button.
  window.DelaxisChat = window.DelaxisChat || {};
  window.DelaxisChat['__DEPLOYMENT_ID__'] = {
    open: function () { toggle(true); },
    close: function () { toggle(false); },
    toggle: function () { toggle(); },
  };
  // Pre-rename alias: host pages already shipping window.OakChat keep working.
  window.OakChat = window.DelaxisChat;
})();
"""


def embed_script(*, deployment_id: str, title: str, theme: str, origin: str = "") -> str:
    """The one-line embed widget: a floating launcher that opens the chat in an iframe."""
    accent = THEMES[normalize_theme(theme)]["accent"]
    return (
        EMBED_TEMPLATE
        .replace("__DEPLOYMENT_ID__", deployment_id)
        .replace("__TITLE__", title.replace("\\", "\\\\").replace("'", "\\'"))
        .replace("__ACCENT__", accent)
        .replace("__ORIGIN__", origin.rstrip("/"))
    )


PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <!-- Identifies this page as one this server generated, and which revision of
       it, so a deployment written before a fix can be refreshed in place. -->
  <meta name="generator" content="__GENERATOR__" />
  <title>__TITLE__</title>
  <script>window.CHATBOT_CONFIG = __CHATBOT_CONFIG__;</script>
  <style>
    __THEME_CSS__
    __BRAND_CSS__
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0; background: var(--bg); color: var(--text);
      font-family: var(--brand-font, Inter), ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    button { font: inherit; cursor: pointer; }
    .app { display: grid; grid-template-columns: 264px 1fr; height: 100dvh; }

    /* ---- Sidebar: the visitor's own conversations ---- */
    .side {
      display: flex; flex-direction: column; min-height: 0;
      background: var(--panel); border-right: 1px solid var(--border);
    }
    .side-head { padding: 16px 14px 12px; border-bottom: 1px solid var(--border); }
    .brand { font-size: 15px; font-weight: 700; line-height: 1.3; margin: 0 0 10px; }
    .new-chat {
      width: 100%; display: flex; align-items: center; justify-content: center; gap: 7px;
      padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--brand-radius, 8px);
      background: var(--surface); color: var(--text); font-size: 13px; font-weight: 600;
      transition: border-color .15s, background .15s;
    }
    .new-chat:hover { border-color: var(--accent); }
    .chats { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
    .chats-empty { padding: 12px 8px; font-size: 12px; color: var(--muted); line-height: 1.5; }
    .chat-item {
      display: flex; align-items: center; gap: 8px; width: 100%;
      padding: 8px 10px; border: 0; border-radius: 8px; background: transparent;
      color: var(--muted); font-size: 13px; text-align: left;
    }
    .chat-item:hover { background: var(--surface); color: var(--text); }
    .chat-item[aria-current="true"] { background: var(--surface); color: var(--text); font-weight: 600; }
    .chat-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .chat-del {
      border: 0; background: transparent; color: var(--muted); padding: 2px 4px;
      border-radius: 4px; opacity: 0; font-size: 15px; line-height: 1;
    }
    .chat-item:hover .chat-del, .chat-del:focus { opacity: 1; }
    .chat-del:hover { color: #ef4444; }
    .side-foot { padding: 10px 12px; border-top: 1px solid var(--border); }
    .side-foot button {
      width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 10px;
      border: 0; border-radius: 8px; background: transparent; color: var(--muted); font-size: 13px;
    }
    .side-foot button:hover { background: var(--surface); color: var(--text); }

    /* ---- Main chat column ---- */
    .main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
    .top {
      display: flex; align-items: center; gap: 12px; padding: 12px 20px;
      border-bottom: 1px solid var(--border); background: var(--surface);
    }
    .burger { display: none; border: 0; background: transparent; color: var(--text); font-size: 18px; padding: 4px 6px; }
    .top h1 { font-size: 15px; font-weight: 700; margin: 0; }
    .status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
    .dot.err { background: #ef4444; }
    .spacer { flex: 1; }
    .icon-btn {
      border: 1px solid var(--border); background: transparent; color: var(--muted);
      border-radius: 8px; padding: 6px 10px; font-size: 12px; font-weight: 600;
    }
    .icon-btn:hover { color: var(--text); border-color: var(--accent); }

    .messages { flex: 1; overflow-y: auto; padding: 24px 20px; }
    .thread { max-width: 780px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; }
    .row { display: flex; gap: 12px; align-items: flex-start; }
    .row.user { flex-direction: row-reverse; }
    .avatar {
      flex: 0 0 28px; width: 28px; height: 28px; border-radius: 8px;
      display: grid; place-items: center; font-size: 11px; font-weight: 700;
      background: var(--assistant-bubble); border: 1px solid var(--assistant-border); color: var(--text);
    }
    .row.user .avatar { background: var(--accent); border-color: var(--accent); color: var(--accent-text); }
    .bubble-wrap { min-width: 0; max-width: 88%; }
    .bubble {
      padding: 11px 14px; border-radius: var(--brand-radius, 12px); font-size: 14px; line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .row.assistant .bubble { background: var(--assistant-bubble); border: 1px solid var(--assistant-border); }
    .row.user .bubble { background: var(--accent); color: var(--accent-text); white-space: pre-wrap; }
    .row.error .bubble { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.45); }
    .meta {
      display: flex; gap: 10px; align-items: center; margin-top: 5px;
      font-size: 11px; color: var(--muted); opacity: 0; transition: opacity .15s;
    }
    .row:hover .meta, .meta:focus-within { opacity: 1; }
    .row.user .meta { justify-content: flex-end; }
    .meta button { border: 0; background: transparent; color: inherit; padding: 0; font-size: 11px; text-decoration: underline; }
    .typing { display: inline-flex; gap: 4px; padding: 4px 0; }
    .typing i {
      width: 6px; height: 6px; border-radius: 50%; background: var(--muted);
      animation: blink 1.2s infinite ease-in-out;
    }
    .typing i:nth-child(2) { animation-delay: .18s; }
    .typing i:nth-child(3) { animation-delay: .36s; }
    @keyframes blink { 0%, 60%, 100% { opacity: .25 } 30% { opacity: 1 } }

    .suggestions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
    .suggestions button {
      border: 1px solid var(--border); background: var(--surface); color: var(--muted);
      border-radius: 999px; padding: 7px 13px; font-size: 12.5px;
    }
    .suggestions button:hover { color: var(--text); border-color: var(--accent); }

    .composer { border-top: 1px solid var(--border); background: var(--surface); padding: 14px 20px 18px; }
    .composer form { max-width: 780px; margin: 0 auto; display: flex; gap: 10px; align-items: flex-end; }
    .composer textarea {
      flex: 1; resize: none; min-height: 44px; max-height: 180px; padding: 12px 14px;
      background: var(--input-bg); border: 1px solid var(--input-border); color: var(--text);
      border-radius: 10px; font: inherit; font-size: 14px; line-height: 1.45;
    }
    .composer textarea:focus { outline: none; border-color: var(--accent); }

    /* Attachments. The button matches the mic so the two controls flanking the
       box read as a pair rather than as two unrelated widgets. */
    .attach {
      flex: 0 0 auto; width: 40px; height: 40px; border-radius: 10px; cursor: pointer;
      border: 1px solid var(--border); background: var(--surface);
      color: var(--muted); display: grid; place-items: center;
    }
    .attach:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
    .attach:disabled { opacity: .5; cursor: not-allowed; }
    .attach svg { width: 18px; height: 18px; display: block; }

    .chips { max-width: 780px; margin: 0 auto 10px; display: flex; flex-wrap: wrap; gap: 8px; }
    .chips[hidden] { display: none; }
    .chip {
      display: inline-flex; align-items: center; gap: 8px; max-width: 100%;
      padding: 5px 8px 5px 11px; border-radius: 999px; font-size: 12.5px;
      border: 1px solid var(--border); background: var(--surface); color: var(--text);
    }
    .chip.pending { opacity: .6; }
    .chip.failed { border-color: #d9534f; color: #d9534f; }
    .chip span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .chip button {
      border: 0; background: none; cursor: pointer; color: var(--muted);
      font-size: 15px; line-height: 1; padding: 0 2px;
    }
    .chip button:hover { color: var(--text); }

    /* Attachments shown inside a sent message, so the transcript records what
       was actually sent rather than only the words. */
    .bubble .files { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
    .bubble .files em {
      font-style: normal; font-size: 12px; padding: 3px 9px; border-radius: 999px;
      background: rgba(127, 127, 127, .18);
    }
    .send {
      border: 0; background: var(--accent); color: var(--accent-text);
      border-radius: var(--brand-radius, 10px); padding: 0 18px; height: 44px; font-weight: 700;
    }
    .send:disabled { opacity: .5; cursor: not-allowed; }
    .hint { max-width: 780px; margin: 8px auto 0; font-size: 11px; color: var(--muted); }

    /* ---- Settings drawer ---- */
    .scrim { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 40; }
    .drawer {
      position: fixed; top: 0; right: 0; bottom: 0; width: min(360px, 100%); z-index: 50;
      background: var(--panel); border-left: 1px solid var(--border);
      display: flex; flex-direction: column; box-shadow: -18px 0 50px var(--shadow);
    }
    /* A class selector beats the user-agent [hidden] rule, so display:none has
       to be restated or the drawer would render open on load. */
    .drawer[hidden], .scrim[hidden] { display: none; }
    .drawer header {
      display: flex; align-items: center; padding: 16px 18px; border-bottom: 1px solid var(--border);
    }
    .drawer header h2 { margin: 0; font-size: 14px; font-weight: 700; }
    .drawer .body { padding: 18px; overflow-y: auto; display: flex; flex-direction: column; gap: 20px; }
    .field { display: flex; flex-direction: column; gap: 6px; }
    .field label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
    .field select {
      background: var(--input-bg); border: 1px solid var(--input-border); color: var(--text);
      border-radius: 8px; padding: 9px 10px; font: inherit; font-size: 13px;
    }
    .check { display: flex; align-items: center; gap: 9px; font-size: 13px; }
    .facts { font-size: 12px; color: var(--muted); line-height: 1.9; }
    .facts code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--text); }
    .danger {
      border: 1px solid rgba(239,68,68,.5); background: transparent; color: #ef4444;
      border-radius: 8px; padding: 9px 12px; font-size: 13px; font-weight: 600;
    }
    .danger:hover { background: rgba(239,68,68,.1); }

    __MARKDOWN_STYLE__

    __VOICE_STYLE__

    @media (max-width: 860px) {
      .app { grid-template-columns: 1fr; }
      .side {
        position: fixed; inset: 0 auto 0 0; width: 264px; z-index: 45;
        transform: translateX(-100%); transition: transform .2s ease;
      }
      body.nav-open .side { transform: none; }
      .burger { display: block; }
      .messages { padding: 18px 14px; }
      .composer { padding: 12px 14px 16px; }
    }
    @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
  </style>
</head>
<body>
  <div class="app">
    <aside class="side" id="side">
      <div class="side-head">
        <p class="brand">__TITLE__</p>
        <button class="new-chat" id="new-chat" type="button"><span aria-hidden="true">+</span> New chat</button>
      </div>
      <nav class="chats" id="chats" aria-label="Your conversations"></nav>
      <div class="side-foot">
        <button id="open-settings" type="button"><span aria-hidden="true">⚙</span> Settings</button>
      </div>
    </aside>

    <main class="main">
      <div class="top">
        <button class="burger" id="burger" type="button" aria-label="Show conversations">☰</button>
        <h1>__TITLE__</h1>
        <span class="status"><span class="dot" id="status-dot"></span><span id="status-text">Ready</span></span>
        <span class="spacer"></span>
        <button class="icon-btn" id="top-new" type="button">New chat</button>
      </div>

      <div class="messages" id="messages"><div class="thread" id="thread"></div></div>

      <div class="composer">
        <div class="chips" id="chips" hidden></div>
        <form id="form">
          <input type="file" id="files" multiple hidden
                 accept=".txt,.md,.markdown,.rst,.log,.csv,.tsv,.json,.jsonl,.yaml,.yml,.xml,.html,.pdf,.docx,.doc,.xlsx,.xls,.pptx,.png,.jpg,.jpeg,.gif,.webp,.bmp,.svg,.tiff">
          <button class="attach" id="attach" type="button" aria-label="Attach a file" title="Attach a file">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
          <textarea id="input" rows="1" placeholder="Ask anything…" autocomplete="off"></textarea>
          <!-- Unhidden by the voice client only when the deployment enables it,
               so a text-only deployment shows no dead control. -->
          <button class="mic" id="mic" type="button" hidden aria-label="Talk to the assistant"></button>
          <button class="send" id="send" type="submit">Send</button>
        </form>
        <p class="hint" id="hint">Enter to send · Shift + Enter for a new line</p>
      </div>
    </main>
  </div>

  <div class="scrim" id="scrim" hidden></div>
  <aside class="drawer" id="drawer" hidden aria-label="Settings">
    <header>
      <h2>Settings</h2>
      <span class="spacer"></span>
      <button class="icon-btn" id="close-settings" type="button">Close</button>
    </header>
    <div class="body">
      <div class="field">
        <label for="theme-select">Appearance</label>
        <select id="theme-select">__THEME_OPTIONS__</select>
      </div>
      <label class="check"><input type="checkbox" id="enter-sends" checked /> Enter sends the message</label>
      <label class="check"><input type="checkbox" id="keep-history" checked /> Remember my conversations on this device</label>
      <div class="field">
        <label>Connected to</label>
        <p class="facts">
          Workflow <code>__WORKFLOW_ID__</code><br />
          Provider <code>__PROVIDER_ID__</code><br />
          Model <code>__MODEL_ID__</code>
        </p>
      </div>
      <button class="danger" id="clear-all" type="button">Delete all conversations</button>
    </div>
  </aside>

  <script>
    __MARKDOWN_SCRIPT__

    const cfg = window.CHATBOT_CONFIG || {};
    // Empty api_url = same origin: the app serving this page also serves the API.
    const apiBase = cfg.api_url || '';
    const deployment = cfg.name || cfg.workflow_id || 'chatbot';
    const greeting = cfg.greeting || 'Hi, how can I help?';
    const suggestions = Array.isArray(cfg.suggestions) ? cfg.suggestions.slice(0, 4) : [];

    // --- Local persistence -------------------------------------------------
    // Only ids and titles live here; the messages themselves come from the API,
    // which stays the single source of truth across devices and reloads.
    const KEY = (name) => 'delaxis:' + deployment + ':' + name;
    const store = {
      read(name, fallback) {
        try { const raw = localStorage.getItem(KEY(name)); return raw ? JSON.parse(raw) : fallback; }
        catch (_) { return fallback; }
      },
      write(name, value) {
        try { localStorage.setItem(KEY(name), JSON.stringify(value)); } catch (_) { /* private mode */ }
      },
      drop(name) { try { localStorage.removeItem(KEY(name)); } catch (_) { /* ignore */ } },
    };

    const settings = Object.assign(
      { theme: cfg.theme || '', enterSends: true, keepHistory: true },
      store.read('settings', {}),
    );

    function visitorId() {
      let id = store.read('visitor', null);
      if (!id) {
        id = 'visitor-' + (crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(16).slice(2));
        store.write('visitor', id);
      }
      return id;
    }

    let chats = settings.keepHistory ? store.read('chats', []) : [];
    let activeId = settings.keepHistory ? store.read('active', null) : null;
    let messages = [];
    let busy = false;

    const el = {
      thread: document.getElementById('thread'),
      messages: document.getElementById('messages'),
      chats: document.getElementById('chats'),
      input: document.getElementById('input'),
      send: document.getElementById('send'),
      form: document.getElementById('form'),
      hint: document.getElementById('hint'),
      statusDot: document.getElementById('status-dot'),
      statusText: document.getElementById('status-text'),
      drawer: document.getElementById('drawer'),
      scrim: document.getElementById('scrim'),
      attach: document.getElementById('attach'),
      filePicker: document.getElementById('files'),
      chips: document.getElementById('chips'),
    };

    // Files chosen but not yet sent. They are uploaded when the message is
    // sent, not when they are picked: a visitor who changes their mind should
    // not have left a file on the server.
    let staged = [];

    function renderChips() {
      el.chips.replaceChildren();
      el.chips.hidden = staged.length === 0;
      staged.forEach((item, index) => {
        const chip = document.createElement('div');
        chip.className = 'chip' + (item.state ? ' ' + item.state : '');

        const label = document.createElement('span');
        label.textContent = item.error ? item.file.name + ' — ' + item.error : item.file.name;
        label.title = label.textContent;
        chip.appendChild(label);

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.textContent = '\u00d7';
        remove.setAttribute('aria-label', 'Remove ' + item.file.name);
        remove.addEventListener('click', () => {
          staged.splice(index, 1);
          renderChips();
        });
        chip.appendChild(remove);
        el.chips.appendChild(chip);
      });
    }

    /**
     * Send the staged files up and index them.
     *
     * Multipart, so Content-Type is left alone deliberately — setting it by
     * hand omits the boundary the browser generates and the server rejects the
     * body as malformed.
     */
    async function uploadStaged(collection) {
      if (!staged.length) return [];
      const body = new FormData();
      staged.forEach((item) => body.append('files', item.file, item.file.name));

      const response = await fetch(
        apiBase + '/api/v1/rag/collections/' + encodeURIComponent(collection) + '/files',
        { method: 'POST', body },
      );
      if (!response.ok) throw new Error(errorText(await response.text(), response.status));

      const result = await response.json();
      const failed = (result.files || []).filter((file) => !file.indexed);
      if (failed.length) {
        // Keep the ones that failed on screen with their reason; drop the rest.
        staged = staged.filter((item) =>
          failed.some((file) => file.file === item.file.name));
        staged.forEach((item) => {
          const match = failed.find((file) => file.file === item.file.name);
          item.state = 'failed';
          item.error = (match && match.error) || 'could not be read';
        });
        renderChips();
        throw new Error(failed.map((file) => file.file + ': ' + file.error).join('; '));
      }
      return (result.files || []).map((file) => file.file);
    }

    function persist() {
      if (!settings.keepHistory) return;
      store.write('chats', chats);
      store.write('active', activeId);
    }

    function setStatus(text, isError) {
      el.statusText.textContent = text;
      el.statusDot.classList.toggle('err', Boolean(isError));
    }

    // --- Rendering ---------------------------------------------------------
    function messageRow(message) {
      const row = document.createElement('div');
      row.className = 'row ' + (message.error ? 'error' : message.role);

      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.setAttribute('aria-hidden', 'true');
      avatar.textContent = message.role === 'user' ? 'You' : 'AI';

      const wrap = document.createElement('div');
      wrap.className = 'bubble-wrap';

      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      if (message.role === 'user') {
        bubble.textContent = message.content;
        if (message.attachments && message.attachments.length) {
          const files = document.createElement('div');
          files.className = 'files';
          message.attachments.forEach((name) => {
            const tag = document.createElement('em');
            tag.textContent = name;
            files.appendChild(tag);
          });
          bubble.appendChild(files);
        }
      } else {
        bubble.classList.add('md-content');
        bubble.innerHTML = renderMarkdown(message.content);
      }
      wrap.appendChild(bubble);

      const meta = document.createElement('div');
      meta.className = 'meta';
      if (message.timestamp) {
        const time = document.createElement('span');
        time.textContent = new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        meta.appendChild(time);
      }
      if (message.role !== 'user') {
        const copy = document.createElement('button');
        copy.type = 'button';
        copy.textContent = 'Copy';
        copy.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(message.content);
            copy.textContent = 'Copied';
            setTimeout(() => { copy.textContent = 'Copy'; }, 1400);
          } catch (_) { copy.textContent = 'Press ⌘C'; }
        });
        meta.appendChild(copy);
      }
      if (message.retry) {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = 'Retry';
        retry.addEventListener('click', () => send(message.retry));
        meta.appendChild(retry);
      }
      wrap.appendChild(meta);

      row.appendChild(avatar);
      row.appendChild(wrap);
      return row;
    }

    function render() {
      el.thread.replaceChildren();
      const shown = messages.length ? messages : [{ role: 'assistant', content: greeting }];
      shown.forEach((message) => el.thread.appendChild(messageRow(message)));

      if (!messages.length && suggestions.length) {
        const row = document.createElement('div');
        row.className = 'suggestions';
        suggestions.forEach((text) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = text;
          button.addEventListener('click', () => send(text));
          row.appendChild(button);
        });
        el.thread.appendChild(row);
      }

      if (busy) {
        const row = document.createElement('div');
        row.className = 'row assistant';
        row.innerHTML = '<div class="avatar" aria-hidden="true">AI</div>'
          + '<div class="bubble-wrap"><div class="bubble"><span class="typing" role="status" aria-label="Thinking">'
          + '<i></i><i></i><i></i></span></div></div>';
        el.thread.appendChild(row);
      }

      el.messages.scrollTop = el.messages.scrollHeight;
    }

    function renderChats() {
      el.chats.replaceChildren();
      if (!chats.length) {
        const empty = document.createElement('p');
        empty.className = 'chats-empty';
        empty.textContent = settings.keepHistory
          ? 'No conversations yet. Send a message to start one.'
          : 'History is off, so conversations are not kept on this device.';
        el.chats.appendChild(empty);
        return;
      }
      chats.forEach((chat) => {
        const item = document.createElement('button');
        item.className = 'chat-item';
        item.type = 'button';
        item.setAttribute('aria-current', String(chat.id === activeId));

        const title = document.createElement('span');
        title.className = 'chat-title';
        title.textContent = chat.title || 'New conversation';
        item.appendChild(title);

        const del = document.createElement('span');
        del.className = 'chat-del';
        del.setAttribute('role', 'button');
        del.setAttribute('aria-label', 'Delete conversation');
        del.textContent = '×';
        del.addEventListener('click', (event) => { event.stopPropagation(); removeChat(chat.id); });
        item.appendChild(del);

        item.addEventListener('click', () => openChat(chat.id));
        el.chats.appendChild(item);
      });
    }

    // --- API ---------------------------------------------------------------
    // The API reports failures as a structured object, not a string. Handing
    // that object to Error() renders "[object Object]" to the visitor, which
    // tells them nothing and hides the one line that would — so pull the
    // readable field out of whichever shape came back.
    function errorText(raw, status) {
      const fallback = 'Request failed with ' + status;
      let body;
      try { body = JSON.parse(raw); } catch (_) { return raw || fallback; }

      const detail = body && body.detail !== undefined ? body.detail : body;
      if (typeof detail === 'string' && detail) return detail;
      // Validation failures arrive as a list of {loc, msg}.
      if (Array.isArray(detail)) {
        const parts = detail.map((item) => item && item.msg).filter(Boolean);
        if (parts.length) return parts.join('; ');
      } else if (detail && typeof detail === 'object') {
        if (detail.error_message) return detail.error_message;
        if (detail.message) return detail.message;
      }
      return raw || fallback;
    }

    async function api(path, options) {
      const response = await fetch(apiBase + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, options));
      if (!response.ok) {
        const error = new Error(errorText(await response.text(), response.status));
        error.status = response.status;
        throw error;
      }
      return response.json();
    }

    async function ensureSession() {
      if (activeId) return activeId;
      const data = await api('/api/v1/sessions', {
        method: 'POST',
        body: JSON.stringify({
          workflow_id: cfg.workflow_id,
          user_id: visitorId(),
          metadata: { deployment: cfg.name },
        }),
      });
      activeId = data.session_id;
      chats = [{ id: activeId, title: 'New conversation', updatedAt: Date.now() }].concat(chats);
      persist();
      renderChats();
      return activeId;
    }

    async function loadHistory(sessionId) {
      // The server owns the transcript; a session it no longer knows about is
      // dropped from the local list rather than left as a dead entry.
      try {
        const data = await api('/api/v1/sessions/' + sessionId + '/history');
        messages = (data.messages || [])
          .filter((message) => message.role === 'user' || message.role === 'assistant')
          .map((message) => ({ role: message.role, content: message.content, timestamp: message.timestamp }));
        return true;
      } catch (error) {
        if (error.status === 404) {
          chats = chats.filter((chat) => chat.id !== sessionId);
          if (activeId === sessionId) activeId = null;
          persist();
          renderChats();
        }
        messages = [];
        return false;
      }
    }

    async function openChat(sessionId) {
      activeId = sessionId;
      persist();
      renderChats();
      setStatus('Loading…');
      await loadHistory(sessionId);
      setStatus('Ready');
      render();
      document.body.classList.remove('nav-open');
    }

    function newChat() {
      activeId = null;
      messages = [];
      persist();
      renderChats();
      render();
      setStatus('Ready');
      el.input.focus();
      document.body.classList.remove('nav-open');
    }

    function removeChat(sessionId) {
      chats = chats.filter((chat) => chat.id !== sessionId);
      // Best effort: the local list is authoritative for this visitor either way.
      fetch(apiBase + '/api/v1/sessions/' + sessionId, { method: 'DELETE' }).catch(() => {});
      if (activeId === sessionId) { activeId = null; messages = []; render(); }
      persist();
      renderChats();
    }

    /**
     * Put what the files actually say into the message.
     *
     * Naming the file and telling the agent to go and retrieve it only works if
     * that particular workflow happens to have a retrieval tool attached. Asked
     * about a file it could not read, a model does not say so — it answers from
     * the filename and invents the contents, which is worse than refusing. So
     * the passages are fetched here and travel with the question, and every
     * workflow can answer from an attachment whether or not it has any tools.
     */
    async function withAttachmentContext(content, collection, names) {
      const listed = names.join(', ');
      let passages = [];
      try {
        const response = await fetch(
          apiBase + '/api/v1/rag/collections/' + encodeURIComponent(collection) + '/query',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // A message with no words is still a request to look at the file.
            body: JSON.stringify({ query: content || 'summarise this document', top_k: 6 }),
          },
        );
        if (response.ok) passages = (await response.json()).results || [];
      } catch (_) { /* fall through to the filenames alone */ }

      if (!passages.length) {
        return (content || 'I have attached a file.')
          + '\n\n[Attached: ' + listed + '. The text could not be read, so answer only '
          + 'from what is already known and say the attachment could not be read.]';
      }

      // Budgeted: a long document would otherwise crowd out the conversation.
      let budget = 6000;
      const quoted = [];
      for (const passage of passages) {
        const text = String(passage.text || '');
        if (text.length > budget) break;
        budget -= text.length;
        quoted.push('--- ' + (passage.source || 'attachment') + ' ---\n' + text);
      }

      return (content || 'Please read the attached file and summarise it.')
        + '\n\n[Attached: ' + listed + '. The relevant extracts follow. Answer from these, '
        + 'and say so if they do not contain the answer.]\n\n'
        + quoted.join('\n\n');
    }

    async function send(text) {
      const content = String(text || '').trim();
      // A file on its own is a legitimate message — "here, read this".
      if ((!content && !staged.length) || busy) return;

      const attachments = staged.map((item) => item.file.name);
      busy = true;
      el.send.disabled = true;
      el.attach.disabled = true;
      messages.push({ role: 'user', content, attachments, timestamp: Date.now() });
      render();
      setStatus(staged.length ? 'Uploading…' : 'Thinking…');

      try {
        const sessionId = await ensureSession();

        // Indexed per conversation, so one visitor's uploads cannot be
        // retrieved from another's chat.
        let outbound = content;
        if (staged.length) {
          const collection = 'chat-' + sessionId;
          const stored = await uploadStaged(collection);
          staged = [];
          renderChips();
          setStatus('Reading…');
          outbound = await withAttachmentContext(content, collection, stored);
          setStatus('Thinking…');
        }

        const data = await api('/api/v1/sessions/' + sessionId + '/messages', {
          method: 'POST',
          body: JSON.stringify({
            message: outbound,
            max_turns: cfg.max_turns || 10,
            metadata: { provider_id: cfg.provider_id, model_id: cfg.model_id },
          }),
        });
        messages.push({
          role: 'assistant',
          content: data.response || 'No response was produced.',
          timestamp: Date.now(),
        });
        const chat = chats.find((item) => item.id === sessionId);
        if (chat) {
          if (chat.title === 'New conversation') chat.title = content.slice(0, 48);
          chat.updatedAt = Date.now();
          persist();
          renderChats();
        }
        setStatus('Ready');
      } catch (error) {
        messages.push({
          role: 'assistant',
          error: true,
          content: 'Could not get a reply: ' + error.message,
          retry: content,
          timestamp: Date.now(),
        });
        setStatus('Connection problem', true);
      } finally {
        busy = false;
        el.send.disabled = false;
        el.attach.disabled = false;
        render();
        el.input.focus();
      }
    }

    // --- Settings ----------------------------------------------------------
    function syncHint() {
      el.hint.textContent = settings.enterSends
        ? 'Enter to send · Shift + Enter for a new line'
        : 'Shift + Enter to send';
    }

    function applySettings() {
      if (settings.theme) document.documentElement.setAttribute('data-delaxis-theme', settings.theme);
      syncHint();
      store.write('settings', settings);
    }

    // --- Live voice hooks --------------------------------------------------
    // The voice client is injected separately (it also has to work on custom
    // generated pages), so this page just tells it which session is active and
    // how to render into the existing thread and status dot.
    window.DELAXIS_VOICE_HOOKS = {
      sessionId: function () { return activeId; },
      status: setStatus,
      resetHint: syncHint,
      transcript: function (role, text) {
        if (!text) return;
        // Transcript deltas arrive several times per turn; append to the trailing
        // message of the same role rather than adding a bubble per fragment.
        const last = messages[messages.length - 1];
        if (last && last.role === role && last.voice) {
          last.content += text;
        } else {
          messages.push({ role: role, content: text, voice: true });
        }
        render();
      },
    };

    function openSettings(open) {
      el.drawer.hidden = !open;
      el.scrim.hidden = !open;
    }

    const themeSelect = document.getElementById('theme-select');
    themeSelect.value = settings.theme || (cfg.theme || 'midnight');
    themeSelect.addEventListener('change', () => {
      settings.theme = themeSelect.value;
      applySettings();
    });

    const enterSends = document.getElementById('enter-sends');
    enterSends.checked = settings.enterSends;
    enterSends.addEventListener('change', () => {
      settings.enterSends = enterSends.checked;
      applySettings();
    });

    const keepHistory = document.getElementById('keep-history');
    keepHistory.checked = settings.keepHistory;
    keepHistory.addEventListener('change', () => {
      settings.keepHistory = keepHistory.checked;
      if (!settings.keepHistory) { store.drop('chats'); store.drop('active'); }
      applySettings();
      persist();
      renderChats();
    });

    document.getElementById('clear-all').addEventListener('click', () => {
      chats.slice().forEach((chat) => removeChat(chat.id));
      newChat();
    });

    document.getElementById('open-settings').addEventListener('click', () => openSettings(true));
    document.getElementById('close-settings').addEventListener('click', () => openSettings(false));
    el.scrim.addEventListener('click', () => { openSettings(false); document.body.classList.remove('nav-open'); });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') openSettings(false); });

    document.getElementById('new-chat').addEventListener('click', newChat);
    document.getElementById('top-new').addEventListener('click', newChat);
    document.getElementById('burger').addEventListener('click', () => {
      document.body.classList.toggle('nav-open');
      el.scrim.hidden = !document.body.classList.contains('nav-open');
    });

    // --- Composer ----------------------------------------------------------
    function autoGrow() {
      el.input.style.height = 'auto';
      el.input.style.height = Math.min(el.input.scrollHeight, 180) + 'px';
    }
    el.input.addEventListener('input', autoGrow);
    el.input.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      const shouldSend = settings.enterSends ? !event.shiftKey : event.shiftKey;
      if (!shouldSend) return;
      event.preventDefault();
      el.form.requestSubmit();
    });
    el.form.addEventListener('submit', (event) => {
      event.preventDefault();
      const text = el.input.value;
      el.input.value = '';
      autoGrow();
      send(text);
    });

    el.attach.addEventListener('click', () => el.filePicker.click());
    el.filePicker.addEventListener('change', () => {
      for (const file of el.filePicker.files) {
        staged.push({ file: file, state: 'pending', error: '' });
      }
      // Cleared, so picking the same file again after removing it still fires.
      el.filePicker.value = '';
      renderChips();
      el.input.focus();
    });

    // Dropping a file on the page is what people try first.
    ['dragover', 'drop'].forEach((name) => {
      document.addEventListener(name, (event) => {
        if (!event.dataTransfer || !Array.from(event.dataTransfer.types || []).includes('Files')) return;
        event.preventDefault();
        if (name !== 'drop') return;
        for (const file of event.dataTransfer.files) {
          staged.push({ file: file, state: 'pending', error: '' });
        }
        renderChips();
      });
    });

    // --- Boot --------------------------------------------------------------
    applySettings();
    renderChats();
    render();
    if (activeId) { openChat(activeId); } else { el.input.focus(); }
  </script>
</body>
</html>
"""


def page_generation(html: str) -> int | None:
    """Which revision of the built-in template produced ``html``, if it did.

    ``None`` means the page did not come from here — a custom generated
    frontend — and must be left alone. Pages written before the stamp existed
    are recognised by markup only the built-in template has ever contained, so
    they can be refreshed too rather than being stranded on the version they
    happened to be deployed with.
    """
    match = re.search(
        rf'<meta name="generator" content="{re.escape(GENERATOR)}/(\d+)"', html
    )
    if match:
        return int(match.group(1))
    if 'id="chats"' in html and 'class="composer"' in html and "__CHATBOT_CONFIG__" not in html:
        return 1
    return None


def default_chatbot_html(
    *,
    title: str,
    greeting: str,
    workflow_id: str,
    provider_id: str,
    model_id: str,
    theme: str,
    config: dict[str, Any],
    brand: dict[str, Any] | None = None,
    voice_enabled: bool = False,
) -> str:
    """The default deployable chat page.

    Substitution is done with ``str.replace`` rather than an f-string so the CSS
    and JS below can be written normally instead of with every brace doubled.

    ``brand`` restyles the page (colours, font, corner radius) without touching
    its wiring — that is what a generated design gets to change.

    ``voice_enabled`` only inlines the mic styling; the voice client itself is
    added by ``ensure_voice_support`` so the default page and a custom generated
    one get exactly the same implementation.
    """
    return (
        PAGE_TEMPLATE
        .replace("__GENERATOR__", f"{GENERATOR}/{PAGE_VERSION}")
        .replace("__VOICE_STYLE__", VOICE_STYLE if voice_enabled else "")
        .replace("__BRAND_CSS__", brand_css(brand))
        .replace("__TITLE__", escape(title))
        .replace("__GREETING__", escape(greeting))
        .replace("__WORKFLOW_ID__", escape(workflow_id))
        .replace("__PROVIDER_ID__", escape(provider_id))
        .replace("__MODEL_ID__", escape(model_id))
        .replace("__THEME_CSS__", all_theme_css(theme))
        .replace("__MARKDOWN_STYLE__", MARKDOWN_STYLE)
        .replace("__MARKDOWN_SCRIPT__", MARKDOWN_SCRIPT)
        .replace("__THEME_OPTIONS__", "".join(
            f'<option value="{theme_id}">{escape(THEME_LABELS.get(theme_id, theme_id.title()))}</option>'
            for theme_id in THEMES
        ))
        # Last: the config JSON must not be scanned for other placeholders.
        .replace("__CHATBOT_CONFIG__", safe_json(config))
    )
