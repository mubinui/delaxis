import { useState, useRef, useEffect, useCallback } from 'react';
import { X, ArrowUp, Loader2, AlertCircle, RotateCcw, SquarePen, Mic, MicOff, Paperclip, KeyRound } from 'lucide-react';
import { attachAndCompose } from '../utils/chatAttachments';
import { useShallow } from 'zustand/react/shallow';
import { useWorkflowStore } from '../stores/workflowStore';
import { useUiStore } from '../stores/uiStore';
import { StatusGlyph } from './shell/StatusGlyph';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { API_BASE_URL } from '../api/client';
import { useVoiceSession, type VoiceLevels, type VoiceTranscript } from '../hooks/useVoiceSession';
import { errorText } from '../utils/apiErrors';

interface Message {
    role: 'user' | 'assistant';
    content: string;
    voice?: boolean;
    /** Filenames sent with this message, so the transcript records them. */
    attachments?: string[];
}

export const ChatPanel = () => {
    // Opened from Test in the toolbar; the activity capsule reports while it waits.
    const isOpen = useUiStore((state) => state.testOpen);
    const setIsOpen = useUiStore((state) => state.setTestOpen);
    const setTestRunning = useUiStore((state) => state.setTestRunning);
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Get current workflow from canvas store (n8n-style). Select primitive counts
    // (not the arrays themselves) so this panel doesn't re-render on every node-drag
    // frame — only when the node/edge *count* actually changes.
    const nodesLength = useWorkflowStore((state) => state.nodes.length);
    const edgesLength = useWorkflowStore((state) => state.edges.length);
    const { currentWorkflowId, workflowName, applyNodeIo } = useWorkflowStore(
        useShallow((state) => ({
            currentWorkflowId: state.currentWorkflowId,
            workflowName: state.workflowName,
            applyNodeIo: state.applyNodeIo,
        })),
    );

    // Optional JWT for authenticated workflows
    // Picked but not yet sent. Uploaded on send, so changing your mind leaves
    // nothing on the server.
    const [staged, setStaged] = useState<File[]>([]);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [jwtToken, setJwtToken] = useState('');
    const [showJwtInput, setShowJwtInput] = useState(false);

    // Session state
    const [sessionId, setSessionId] = useState<string | null>(null);

    // Live voice. Transcript deltas arrive several times per turn, so they are
    // appended onto the trailing message of the same role instead of pushing a
    // new bubble per fragment.
    const handleTranscript = useCallback((entry: VoiceTranscript) => {
        if (!entry.text) return;
        setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === entry.role && last.voice) {
                return [...prev.slice(0, -1), { ...last, content: last.content + entry.text }];
            }
            return [...prev, { role: entry.role, content: entry.text, voice: true }];
        });
    }, []);

    // Levels arrive ~60x/second, so they are written straight to CSS custom
    // properties rather than through React state — re-rendering the panel every
    // frame would make the whole Studio stutter.
    const micRef = useRef<HTMLButtonElement>(null);
    const vizRef = useRef<HTMLDivElement>(null);

    const handleLevels = useCallback(({ level, bands, speaking }: VoiceLevels) => {
        micRef.current?.style.setProperty('--voice-level', level.toFixed(3));
        const viz = vizRef.current;
        if (!viz) return;
        viz.dataset.speaking = String(speaking);
        bands.forEach((value, index) => {
            (viz.children[index] as HTMLElement | undefined)?.style.setProperty('--b', value.toFixed(3));
        });
    }, []);

    const voice = useVoiceSession({
        sessionId,
        token: jwtToken,
        onTranscript: handleTranscript,
        onLevels: handleLevels,
    });

    useEffect(() => {
        setTestRunning(isLoading);
    }, [isLoading, setTestRunning]);

    // Auto-scroll to bottom when new messages arrive
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    // Reset session when workflow changes
    useEffect(() => {
        setSessionId(null);
        setMessages([]);
        setError(null);
    }, [currentWorkflowId]);

    // Check if canvas has a workflow
    const hasWorkflow = nodesLength > 0;
    const hasLoadedWorkflow = currentWorkflowId && hasWorkflow;

    const createSession = async () => {
        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
        };
        if (jwtToken.trim()) {
            headers['Authorization'] = `Bearer ${jwtToken.trim()}`;
        }

        const response = await fetch(`${API_BASE_URL}/api/v1/sessions`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                workflow_id: currentWorkflowId,
                user_id: 'test-user', // Default test user
                metadata: { source: 'editor_test_panel' }
            }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(errorText(errorData.detail, `Failed to create session: HTTP ${response.status}`));
        }

        const data = await response.json();
        return data.session_id;
    };

    // Auto-create session on panel open
    useEffect(() => {
        if (isOpen && !sessionId && hasLoadedWorkflow && !isLoading) {
            // We init session silently
            const initSession = async () => {
                try {
                    console.log('Auto-initializing session...');
                    const id = await createSession();
                    setSessionId(id);
                } catch (err) {
                    console.warn('Auto-init session failed:', err);
                    // Don't show error to user yet, wait for interaction
                }
            };
            initSession();
        }
    }, [isOpen]);

    const handleNewSession = () => {
        setSessionId(null);
        setMessages([]);
        setError(null);
        // Force immediate re-creation if open
        if (hasLoadedWorkflow) {
            createSession().then(id => setSessionId(id)).catch(e => console.error(e));
        }
    };

    const handleClearChat = async () => {
        // Just clear UI
        setMessages([]);
        setError(null);
        // We don't necessarily reset session ID on clear chat, 
        // but user might expect it. Let's keep ID but clear messages.
        // If they want a NEW session, they use the New Session button.
    };

    if (!isOpen) return null;

    const handleSend = async () => {
        // A file on its own is a legitimate message — "here, read this".
        if (!input.trim() && !staged.length) {
            setError('Please enter a message');
            return;
        }

        if (!hasLoadedWorkflow) {
            setError('Save or open a workflow first.');
            return;
        }

        const userMessage = input;
        const attachments = staged.map(file => file.name);
        setMessages(prev => [...prev, { role: 'user', content: userMessage, attachments }]);
        setInput('');
        setIsLoading(true);
        setError(null);
        // The canvas plays the run: wires leave the trigger now, and the path
        // turns green with the reply — or red if the workflow fails.
        useWorkflowStore.getState().resetExecution();
        useWorkflowStore.getState().beginFlow();

        let activeSessionId = sessionId;
        let outbound = userMessage;

        try {
            // Ensure we have a session - Create one if missing!
            if (!activeSessionId) {
                activeSessionId = await createSession();
                setSessionId(activeSessionId);
            }

            if (staged.length && activeSessionId) {
                // Index the files and bring their text back with the question:
                // a workflow without a retrieval tool would otherwise answer
                // from the filename alone and invent the contents.
                const result = await attachAndCompose(
                    API_BASE_URL, activeSessionId, userMessage, staged,
                );
                outbound = result.message;
                setStaged([]);
                const failed = result.uploaded.filter(item => !item.indexed);
                if (failed.length) {
                    setError(failed.map(item => `${item.file}: ${item.error}`).join('; '));
                }
            }

            // Prepare headers
            const headers: Record<string, string> = {
                'Content-Type': 'application/json',
            };
            if (jwtToken.trim()) {
                headers['Authorization'] = `Bearer ${jwtToken.trim()}`;
            }

            // Send message to session
            const response = await fetch(
                `${API_BASE_URL}/api/v1/sessions/${activeSessionId}/messages`,
                {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({
                        message: outbound,
                        max_turns: 10,
                        metadata: {},
                    }),
                }
            );

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(errorText(errorData.detail, `HTTP ${response.status}`));
            }

            const result = await response.json();

            // Extract response text
            const responseText = result.response || 'No response from agent';

            setMessages(prev => [
                ...prev,
                { role: 'assistant', content: responseText },
            ]);

            // Surface per-node/tool run data on the canvas (badges + Data tab).
            applyNodeIo(result.metadata?.node_io, result.metadata?.tool_io);
            useWorkflowStore.getState().finishFlow(true);

        } catch (err) {
            useWorkflowStore.getState().finishFlow(false);
            const errorMsg = err instanceof Error ? err.message : 'Unknown error occurred';

            // Auto-recovery: If session not found, expire it immediately and notify user
            if (errorMsg.includes('Session not found') || errorMsg.includes('404')) {
                console.warn(`Session ${activeSessionId} invalid, resetting.`);
                setSessionId(null);
                // We don't retry automatically to avoid infinite loops, but we reset so next try works

                setMessages(prev => [
                    ...prev,
                    {
                        role: 'assistant',
                        content: `**The session expired.** Send your message again to start a new one.`
                    },
                ]);
            } else {
                setError(errorMsg);
                setMessages(prev => [
                    ...prev,
                    {
                        role: 'assistant',
                        content: `Something went wrong: ${errorMsg}`
                    },
                ]);
            }
        } finally {
            setIsLoading(false);
        }
    };

    const status = hasLoadedWorkflow
        ? { shape: 'ok' as const, text: `${nodesLength} components · ${edgesLength} connections` }
        : hasWorkflow
            ? { shape: 'warn' as const, text: 'Save the workflow to test it' }
            : { shape: 'idle' as const, text: 'The canvas is empty' };

    return (
        <aside
            className="glass-pane from-right absolute right-2.5 z-30 w-[380px]"
            style={{ top: 'calc(var(--toolbar-h) + 10px)', bottom: 10 }}
            aria-label="Test chat"
        >
            <div className="flex shrink-0 items-center gap-2 pb-2 pl-[18px] pr-3 pt-3.5">
                <div className="min-w-0 flex-1">
                    <div className="title-2">Test</div>
                    <div className="hint flex items-center gap-1.5 truncate">
                        <StatusGlyph shape={status.shape} />
                        <span className="truncate">{hasLoadedWorkflow ? workflowName : status.text}</span>
                    </div>
                </div>
                <button onClick={() => setShowJwtInput(!showJwtInput)} className="btn btn-ghost btn-icon" aria-pressed={showJwtInput} title="Send a bearer token with each message" aria-label="Authentication">
                    <KeyRound size={14} />
                </button>
                <button onClick={handleClearChat} className="btn btn-ghost btn-icon" title="Clear the conversation" aria-label="Clear the conversation">
                    <RotateCcw size={14} />
                </button>
                <button onClick={handleNewSession} className="btn btn-ghost btn-icon" title="Start a new session" aria-label="Start a new session">
                    <SquarePen size={14} />
                </button>
                <button onClick={() => setIsOpen(false)} className="btn btn-ghost btn-icon" title="Close" aria-label="Close test chat">
                    <X size={15} />
                </button>
            </div>

            {(showJwtInput || error) && (
                <div className="shrink-0 space-y-2 px-[18px] pb-2">
                    {showJwtInput && (
                        <div>
                            <label className="field-label" htmlFor="test-jwt">Bearer token</label>
                            <input
                                id="test-jwt"
                                type="password"
                                value={jwtToken}
                                onChange={(e) => setJwtToken(e.target.value)}
                                placeholder="Optional — for workflows that require sign-in"
                                className="input mono"
                            />
                        </div>
                    )}
                    {error && (
                        <div className="flex items-start gap-2 rounded-xl p-2.5 text-[12px]" style={{ background: 'var(--clay-wash)', color: 'var(--clay)' }}>
                            <AlertCircle size={14} className="mt-px shrink-0" />
                            <span>{error}</span>
                        </div>
                    )}
                </div>
            )}

            {/* Messages */}
            <div className="scroll-soft flex min-h-0 flex-1 flex-col gap-3.5 px-[18px] py-2">
                {messages.length === 0 && (
                    <div className="empty-state my-auto">
                        <div className="headline">{hasLoadedWorkflow ? 'Say something to the workflow' : 'Nothing to test yet'}</div>
                        <p className="hint max-w-[260px]">
                            {hasLoadedWorkflow
                                ? 'Each message runs the workflow end to end. Handoffs and tool calls show up in the timeline.'
                                : 'Build a workflow on the canvas and save it, or open a saved one from the name at the top.'}
                        </p>
                        {isLoading && <Loader2 size={18} className="mt-2 animate-spin" />}
                    </div>
                )}
                {messages.map((msg, i) => (
                    msg.role === 'user' ? (
                        <div key={i} className="msg-user">
                            {msg.content}
                            {msg.attachments && msg.attachments.length > 0 && (
                                <div className="mt-1.5 flex flex-wrap gap-1.5">
                                    {msg.attachments.map((name) => (
                                        <span key={name} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]" style={{ background: 'rgba(127,127,127,.25)' }}>
                                            <Paperclip size={10} />
                                            {name}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div key={i} className="msg-bot reading !text-[13.5px] !leading-[1.55]">
                            <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={{
                                    a: ({ children, ...props }: any) => (
                                        <a target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
                                    ),
                                    table: ({ children }: any) => (
                                        <div className="my-2 overflow-x-auto"><table className="min-w-full text-xs">{children}</table></div>
                                    ),
                                    th: ({ children }: any) => <th className="px-2 py-1 text-left font-semibold" style={{ borderBottom: '1px solid var(--line)' }}>{children}</th>,
                                    td: ({ children }: any) => <td className="px-2 py-1" style={{ borderBottom: '1px solid var(--line)' }}>{children}</td>,
                                }}
                            >
                                {msg.content}
                            </ReactMarkdown>
                        </div>
                    )
                ))}
                {isLoading && messages.length > 0 && (
                    <div className="trace">
                        <div><StatusGlyph shape="busy" /><span>Running the workflow…</span></div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Composer */}
            <div className="shrink-0 px-3 pb-3 pt-1.5">
                {staged.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                        {staged.map((file, index) => (
                            <span key={`${file.name}-${index}`} className="chip max-w-full !pr-1">
                                <span className="truncate">{file.name}</span>
                                <button
                                    type="button"
                                    onClick={() => setStaged(prev => prev.filter((_, i) => i !== index))}
                                    aria-label={`Remove ${file.name}`}
                                    className="btn btn-ghost btn-sm btn-icon !h-4 !w-4"
                                >
                                    <X size={10} />
                                </button>
                            </span>
                        ))}
                    </div>
                )}
                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    hidden
                    accept=".txt,.md,.markdown,.rst,.log,.csv,.tsv,.json,.jsonl,.yaml,.yml,.xml,.html,.pdf,.docx,.doc,.xlsx,.xls,.pptx,.png,.jpg,.jpeg,.gif,.webp,.bmp,.svg,.tiff"
                    onChange={(e) => {
                        // Read the files out before anything else: the state
                        // updater below runs during the next render, and by
                        // then clearing value has already emptied the list.
                        const picked = Array.from(e.target.files ?? []);
                        // Cleared, so re-picking a removed file still fires.
                        e.target.value = '';
                        setStaged(prev => [...prev, ...picked]);
                    }}
                />
                <div className="composer">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && !isLoading && handleSend()}
                        disabled={isLoading || !hasLoadedWorkflow || voice.isActive}
                        aria-label="Message"
                        placeholder={
                            voice.isActive
                                ? 'Voice mode — tap the mic to stop'
                                : hasLoadedWorkflow
                                    ? `Message ${workflowName}`
                                    : 'Save or open a workflow to start'
                        }
                    />
                    <div className="flex items-center gap-1">
                        <button
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={isLoading || !hasLoadedWorkflow || voice.isActive}
                            title="Attach a file"
                            aria-label="Attach a file"
                            className="btn btn-ghost btn-icon"
                        >
                            <Paperclip size={15} />
                        </button>
                        {/* Voice needs a live session to attach to, which only exists
                            after the first message. */}
                        <button
                            ref={micRef}
                            onClick={voice.toggle}
                            disabled={!hasLoadedWorkflow || !sessionId}
                            title={
                                !sessionId
                                    ? 'Send a message first to start a session'
                                    : voice.isActive
                                        ? 'Stop voice'
                                        : 'Talk to this workflow'
                            }
                            aria-label="Voice"
                            aria-pressed={voice.isActive}
                            className={`btn btn-icon relative ${voice.isActive ? 'btn-primary' : 'btn-ghost'}`}
                        >
                            {voice.state === 'starting' ? (
                                <Loader2 size={15} className="animate-spin" />
                            ) : voice.isActive ? (
                                <Mic size={15} />
                            ) : (
                                <MicOff size={15} />
                            )}
                            {voice.isActive && (
                                <>
                                    {/* Ambient ring keeps the control alive between
                                        utterances; the reactive one tracks the level. */}
                                    <span className="voice-ring-ambient" />
                                    <span className="voice-ring-live" />
                                </>
                            )}
                        </button>
                        {/* Level meter, driven by the real signal so it stops moving
                            when the audio does. */}
                        <div ref={vizRef} aria-hidden="true" className={`voice-viz ${voice.isActive ? 'is-on' : ''}`}>
                            {[0, 1, 2, 3, 4].map((bar) => (
                                <i key={bar} />
                            ))}
                        </div>
                        <span className="flex-1" />
                        {isLoading && <span className="hint mr-1">Running…</span>}
                        <button
                            onClick={handleSend}
                            disabled={isLoading || !hasLoadedWorkflow || (!input.trim() && !staged.length) || voice.isActive}
                            className="send-btn"
                            aria-label="Send"
                            title="Send"
                        >
                            <ArrowUp size={15} strokeWidth={2.2} />
                        </button>
                    </div>
                </div>
                {(voice.isActive || voice.error) && (
                    <p className="hint mt-1.5 px-1" style={voice.error ? { color: 'var(--clay)' } : undefined}>
                        {voice.error
                            ? voice.error
                            : voice.state === 'speaking'
                                ? 'Speaking… Voice replies come from the live model, so workflow tools do not run.'
                                : 'Listening… Voice replies come from the live model, so workflow tools do not run.'}
                    </p>
                )}
            </div>
        </aside>
    );
};
