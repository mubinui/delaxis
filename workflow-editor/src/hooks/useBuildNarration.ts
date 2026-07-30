/**
 * Spoken progress while the builder works.
 *
 * A build is a 10-60 second wait behind a spinner, and the interesting part —
 * which model was chosen, how many agents came back, whether the generated page
 * passed validation — is exactly what you cannot see while looking away. So the
 * builder says it.
 *
 * Uses the browser's SpeechSynthesis rather than a cloud voice on purpose:
 * narration has to start the instant a phase begins, must not add a per-build
 * cost, must not need an API key, and must not be able to fail a build. A
 * server-side voice would lose on all four. The speak() surface here is
 * deliberately narrow, so a Gemini TTS backend could be added behind it later
 * without touching any caller.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'delaxis-build-narration';

/** Slightly quicker than default — progress lines are short and functional. */
const RATE = 1.05;

const supported = () => typeof window !== 'undefined' && 'speechSynthesis' in window;

function readPreference(): boolean {
    if (!supported()) return false;
    try {
        // Off unless asked for: a machine that starts talking unprompted is worse
        // than one that stays quiet.
        return window.localStorage.getItem(STORAGE_KEY) === 'on';
    } catch {
        return false;
    }
}

export const useBuildNarration = () => {
    const [enabled, setEnabled] = useState(readPreference);
    // Mirrored into a ref so speak() can stay a stable callback — it is passed
    // into a dozen build flows and should not change identity on every toggle.
    const enabledRef = useRef(enabled);
    const voice = useRef<SpeechSynthesisVoice | null>(null);

    useEffect(() => {
        enabledRef.current = enabled;
    }, [enabled]);

    // Voices load asynchronously in most browsers, so this resolves once and is
    // simply skipped if the list is never populated.
    useEffect(() => {
        if (!supported()) return undefined;
        const pick = () => {
            const voices = window.speechSynthesis.getVoices();
            if (!voices.length) return;
            voice.current =
                voices.find((v) => /^en-(GB|US)$/.test(v.lang) && /natural|premium|enhanced/i.test(v.name)) ??
                voices.find((v) => v.lang.startsWith('en') && v.localService) ??
                voices.find((v) => v.lang.startsWith('en')) ??
                voices[0];
        };
        pick();
        window.speechSynthesis.addEventListener('voiceschanged', pick);
        return () => window.speechSynthesis.removeEventListener('voiceschanged', pick);
    }, []);

    const cancel = useCallback(() => {
        if (supported()) window.speechSynthesis.cancel();
    }, []);

    /**
     * Queue one line. Browsers queue utterances themselves, so phases spoken in
     * order stay in order without any bookkeeping here.
     */
    const speak = useCallback((text: string) => {
        if (!enabledRef.current || !supported() || !text.trim()) return;
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = RATE;
        if (voice.current) utterance.voice = voice.current;
        window.speechSynthesis.speak(utterance);
    }, []);

    /** Interrupt whatever is queued and say this instead — used for errors. */
    const say = useCallback(
        (text: string) => {
            cancel();
            speak(text);
        },
        [cancel, speak],
    );

    const toggle = useCallback(() => {
        setEnabled((previous) => {
            const next = !previous;
            try {
                window.localStorage.setItem(STORAGE_KEY, next ? 'on' : 'off');
            } catch {
                /* private mode */
            }
            if (!next && supported()) window.speechSynthesis.cancel();
            return next;
        });
    }, []);

    // Never leave a queue talking after the panel closes.
    useEffect(() => cancel, [cancel]);

    return { enabled, supported: supported(), speak, say, cancel, toggle };
};

/**
 * Phrases for each build phase. Kept together so the narration reads as one
 * voice rather than strings scattered through the panel, and so they stay short
 * — a long sentence is still being spoken when the next phase starts.
 */
export const narration = {
    modelChosen: (model: string) => (model ? `Using ${prettyModel(model)}.` : ''),
    planning: 'Planning your chatbot.',
    planned: (agents: number, tools: number) => {
        const parts: string[] = [];
        if (agents) parts.push(`${agents} agent${agents === 1 ? '' : 's'}`);
        if (tools) parts.push(`${tools} tool${tools === 1 ? '' : 's'}`);
        return parts.length ? `Plan ready: ${parts.join(' and ')}.` : 'Plan ready.';
    },
    applying: 'Adding it to the canvas.',
    applied: 'Done. The workflow is on the canvas.',
    designing: 'Designing the interface.',
    designed: (fallback: boolean) =>
        fallback
            ? 'The model was unavailable, so I used the built-in page.'
            : 'Interface ready. Check the preview.',
    repairingApi: 'Reading the API and building a tool.',
    repairedApi: (name: string) => (name ? `Tool ready: ${name}.` : 'Tool ready.'),
    generatingConfig: 'Writing the configuration.',
    deploying: 'Deploying.',
    deployed: 'Deployed. The link is in the panel.',
    failed: (what: string) => `${what} failed. Check the message in the panel.`,
};

/** "anthropic/claude-opus-5" -> "Claude Opus 5" — model ids do not read aloud well. */
function prettyModel(modelId: string): string {
    const bare = modelId.includes('/') ? modelId.slice(modelId.lastIndexOf('/') + 1) : modelId;
    return bare
        .replace(/[-_.]/g, ' ')
        .replace(/\bgpt\b/gi, 'GPT')
        .replace(/\b(\w)/g, (m) => m.toUpperCase())
        .trim();
}
