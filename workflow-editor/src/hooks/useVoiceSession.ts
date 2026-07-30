/**
 * Live voice for the Studio's test chat.
 *
 * Mirrors the client injected into deployed pages (see VOICE_SCRIPT in
 * src/api/chatbot_page.py). The two are separate implementations on purpose:
 * a deployed page is a single self-contained HTML file with no build step, so it
 * cannot import this. The shared contract is the frame protocol in
 * src/api/voice/protocol.py — change one side and the drift test will complain.
 *
 * Audio: microphone PCM16 mono goes up as binary frames at the rate the server
 * asks for; speech comes back as binary PCM16 at the output rate and is
 * scheduled on a moving playhead so consecutive chunks are gapless.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../api/client';

export type VoiceState = 'idle' | 'starting' | 'listening' | 'speaking' | 'error';

export interface VoiceTranscript {
    role: 'user' | 'assistant';
    text: string;
}

/** Live audio levels for the visualiser: overall 0..1 plus per-band values. */
export interface VoiceLevels {
    level: number;
    bands: number[];
    /** True while the agent is the one making sound. */
    speaking: boolean;
}

const BANDS = 5;
const SILENT: VoiceLevels = { level: 0, bands: [0, 0, 0, 0, 0], speaking: false };

interface TicketResponse {
    ticket: string;
    ws_path: string;
    input_sample_rate: number;
    output_sample_rate: number;
    max_session_seconds: number;
}

interface UseVoiceSessionOptions {
    /**
     * Session to speak into; voice inherits the session's auth. Not needed for
     * `purpose: 'builder'`, which is a design conversation with no workflow.
     */
    sessionId: string | null;
    /** 'session' speaks to a workflow; 'builder' talks through what to build. */
    purpose?: 'session' | 'builder';
    /** For the builder: whatever is already written, so it continues from that. */
    draft?: string;
    /** Optional JWT, same one the panel uses for its REST calls. */
    token?: string;
    onTranscript?: (entry: VoiceTranscript) => void;
    /**
     * Called on every animation frame with the measured audio level. Kept out of
     * React state deliberately — 60 setState calls a second would re-render the
     * whole panel; the consumer writes CSS custom properties instead.
     */
    onLevels?: (levels: VoiceLevels) => void;
}

// ~40ms of audio per frame: small enough to feel live, large enough that the
// socket is not handling hundreds of tiny frames a second.
const CHUNK_SECONDS = 0.04;

export const useVoiceSession = ({
    sessionId,
    purpose = 'session',
    draft = '',
    token,
    onTranscript,
    onLevels,
}: UseVoiceSessionOptions) => {
    const [state, setState] = useState<VoiceState>('idle');
    const [error, setError] = useState<string | null>(null);

    const ws = useRef<WebSocket | null>(null);
    const inCtx = useRef<AudioContext | null>(null);
    const outCtx = useRef<AudioContext | null>(null);
    const stream = useRef<MediaStream | null>(null);
    const processor = useRef<ScriptProcessorNode | AudioWorkletNode | null>(null);
    const micGain = useRef<GainNode | null>(null);
    const outGain = useRef<GainNode | null>(null);
    const playHead = useRef(0);
    const queued = useRef<AudioBufferSourceNode[]>([]);
    const outRate = useRef(24000);
    const transcriptRef = useRef(onTranscript);
    const levelsRef = useRef(onLevels);
    const inAnalyser = useRef<AnalyserNode | null>(null);
    const outAnalyser = useRef<AnalyserNode | null>(null);
    const frame = useRef<number | null>(null);

    transcriptRef.current = onTranscript;
    levelsRef.current = onLevels;

    const makeAnalyser = useCallback((ctx: AudioContext, from: AudioNode) => {
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.7;
        from.connect(analyser);
        return analyser;
    }, []);

    const stopLevels = useCallback(() => {
        if (frame.current !== null) cancelAnimationFrame(frame.current);
        frame.current = null;
        inAnalyser.current = null;
        outAnalyser.current = null;
        levelsRef.current?.(SILENT);
    }, []);

    const startLevels = useCallback(() => {
        if (frame.current !== null) return;
        const bins = new Uint8Array(128);
        const tick = () => {
            frame.current = requestAnimationFrame(tick);
            // Whoever is currently making sound is what gets shown.
            const speaking = queued.current.length > 0;
            const analyser = speaking ? outAnalyser.current : inAnalyser.current;
            if (!analyser || !levelsRef.current) return;
            analyser.getByteFrequencyData(bins);
            // Speech energy sits low in the spectrum; sampling the full range
            // would leave the upper bars permanently flat.
            const usable = Math.floor(bins.length * 0.55);
            const per = Math.max(1, Math.floor(usable / BANDS));
            const bands: number[] = [];
            let total = 0;
            for (let b = 0; b < BANDS; b += 1) {
                let sum = 0;
                for (let i = 0; i < per; i += 1) sum += bins[b * per + i] ?? 0;
                const value = sum / per / 255;
                bands.push(value);
                total += value;
            }
            levelsRef.current({ level: Math.min(1, (total / BANDS) * 1.6), bands, speaking });
        };
        frame.current = requestAnimationFrame(tick);
    }, []);

    /** Duck the mic while the agent is speaking, or laptop speakers feed back in. */
    const duck = useCallback(() => {
        const ctx = inCtx.current;
        if (micGain.current && ctx) {
            micGain.current.gain.setTargetAtTime(queued.current.length ? 0 : 1, ctx.currentTime, 0.02);
        }
    }, []);

    const flushPlayback = useCallback(() => {
        queued.current.forEach((node) => {
            try {
                node.stop();
            } catch {
                /* already finished */
            }
        });
        queued.current = [];
        playHead.current = 0;
        duck();
    }, [duck]);

    const teardown = useCallback(() => {
        stopLevels();
        flushPlayback();
        try {
            processor.current?.disconnect();
            micGain.current?.disconnect();
        } catch {
            /* ignore */
        }
        stream.current?.getTracks().forEach((track) => track.stop());
        try {
            inCtx.current?.close();
            outCtx.current?.close();
            ws.current?.close();
        } catch {
            /* ignore */
        }
        ws.current = null;
        processor.current = null;
        micGain.current = null;
        outGain.current = null;
        inCtx.current = null;
        outCtx.current = null;
        stream.current = null;
    }, [flushPlayback, stopLevels]);

    const stop = useCallback(() => {
        if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify({ t: 'bye' }));
        }
        teardown();
        setState('idle');
    }, [teardown]);

    const enqueue = useCallback(
        (pcm: Int16Array) => {
            const ctx = outCtx.current;
            if (!ctx || !outGain.current) return;
            const buffer = ctx.createBuffer(1, pcm.length, outRate.current);
            const channel = buffer.getChannelData(0);
            for (let i = 0; i < pcm.length; i += 1) channel[i] = pcm[i] / 0x8000;
            const source = ctx.createBufferSource();
            source.buffer = buffer;
            source.connect(outGain.current);
            const now = ctx.currentTime;
            if (playHead.current < now + 0.05) playHead.current = now + 0.05;
            source.start(playHead.current);
            playHead.current += buffer.duration;
            queued.current.push(source);
            source.onended = () => {
                queued.current = queued.current.filter((node) => node !== source);
                duck();
                if (!queued.current.length) setState((prev) => (prev === 'speaking' ? 'listening' : prev));
            };
            duck();
            setState((prev) => (prev === 'listening' ? 'speaking' : prev));
        },
        [duck],
    );

    const start = useCallback(async () => {
        // Only a session-scoped conversation needs a session; the builder is
        // free-standing.
        if (purpose === 'session' && !sessionId) {
            setError('Send a message first to start a conversation.');
            setState('error');
            return;
        }
        setError(null);
        setState('starting');

        try {
            const headers: Record<string, string> = { 'Content-Type': 'application/json' };
            if (token?.trim()) headers.Authorization = `Bearer ${token.trim()}`;

            const response = await fetch(`${API_BASE_URL}/api/v1/voice/ticket`, {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    session_id: sessionId ?? '',
                    purpose,
                    // Sent once when the ticket is minted; the server holds it
                    // against that ticket rather than trusting the socket.
                    draft: purpose === 'builder' ? draft : '',
                }),
            });
            if (!response.ok) {
                const detail = await response.json().catch(() => null);
                throw new Error(detail?.detail || `Voice unavailable (${response.status})`);
            }
            const ticket: TicketResponse = await response.json();
            outRate.current = ticket.output_sample_rate;
            const inRate = ticket.input_sample_rate;

            // Both contexts are created inside the click handler's task so
            // Safari/iOS do not leave them suspended.
            const output = new AudioContext({ sampleRate: ticket.output_sample_rate });
            outCtx.current = output;
            outGain.current = output.createGain();
            outGain.current.connect(output.destination);
            outAnalyser.current = makeAnalyser(output, outGain.current);
            await output.resume();

            stream.current = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });

            const input = new AudioContext({ sampleRate: inRate });
            inCtx.current = input;
            await input.resume();
            const source = input.createMediaStreamSource(stream.current);
            micGain.current = input.createGain();
            source.connect(micGain.current);
            // Tapped before the ducking gain, so the meter still shows the user
            // talking over the agent — which is when barge-in matters.
            inAnalyser.current = makeAnalyser(input, source);
            startLevels();

            // The sampleRate constructor hint is advisory — read back what we
            // actually got and resample if it was not honoured.
            const ratio = input.sampleRate / inRate;
            const frames = Math.max(256, 2 ** Math.round(Math.log2(inRate * CHUNK_SECONDS * ratio)));
            const node = input.createScriptProcessor(frames, 1, 1);
            node.onaudioprocess = (event) => {
                if (ws.current?.readyState !== WebSocket.OPEN) return;
                const samples = event.inputBuffer.getChannelData(0);
                const count = Math.floor(samples.length / ratio);
                const pcm = new Int16Array(count);
                for (let i = 0; i < count; i += 1) {
                    const clamped = Math.max(-1, Math.min(1, samples[Math.floor(i * ratio)]));
                    pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
                }
                ws.current.send(pcm.buffer);
            };
            micGain.current.connect(node);
            // A ScriptProcessorNode only runs while connected to a destination;
            // a zero-gain sink keeps it silent.
            const sink = input.createGain();
            sink.gain.value = 0;
            node.connect(sink);
            sink.connect(input.destination);
            processor.current = node;

            const base = API_BASE_URL
                ? API_BASE_URL.replace(/^http/, 'ws')
                : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
            const socket = new WebSocket(
                `${base}${ticket.ws_path}?ticket=${encodeURIComponent(ticket.ticket)}`,
            );
            socket.binaryType = 'arraybuffer';
            ws.current = socket;

            socket.onmessage = (event) => {
                if (typeof event.data !== 'string') {
                    enqueue(new Int16Array(event.data as ArrayBuffer));
                    return;
                }
                let frame: Record<string, unknown>;
                try {
                    frame = JSON.parse(event.data);
                } catch {
                    return;
                }
                switch (frame.t) {
                    case 'ready':
                        setState('listening');
                        break;
                    case 'interrupted':
                        flushPlayback();
                        setState('listening');
                        break;
                    case 'user_text':
                        transcriptRef.current?.({ role: 'user', text: String(frame.d ?? '') });
                        break;
                    case 'agent_text':
                        transcriptRef.current?.({ role: 'assistant', text: String(frame.d ?? '') });
                        break;
                    case 'error':
                        setError(String(frame.message ?? 'Voice error'));
                        setState('error');
                        teardown();
                        break;
                    case 'ended':
                        if (frame.reason === 'time_limit') setError('Voice session reached its time limit.');
                        teardown();
                        setState('idle');
                        break;
                    default:
                        break;
                }
            };
            socket.onerror = () => {
                setError('Voice connection failed.');
                setState('error');
                teardown();
            };
            socket.onclose = () => {
                setState((prev) => (prev === 'error' ? prev : 'idle'));
            };
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Microphone unavailable');
            setState('error');
            teardown();
        }
    }, [sessionId, purpose, draft, token, enqueue, flushPlayback, teardown, makeAnalyser, startLevels]);

    const toggle = useCallback(() => {
        if (state === 'idle' || state === 'error') void start();
        else stop();
    }, [state, start, stop]);

    // Never leave a billed session or a live microphone open on unmount.
    useEffect(() => teardown, [teardown]);

    return {
        state,
        error,
        isActive: state !== 'idle' && state !== 'error',
        start,
        stop,
        toggle,
    };
};
