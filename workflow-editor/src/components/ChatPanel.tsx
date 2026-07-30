import { useState, useRef, useEffect, useCallback } from 'react';
import { MessageSquare, Play, X, Send, Loader2, AlertCircle, RefreshCw, PlusCircle, Mic, MicOff } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { useWorkflowStore } from '../stores/workflowStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { API_BASE_URL } from '../api/client';
import { useVoiceSession, type VoiceLevels, type VoiceTranscript } from '../hooks/useVoiceSession';

interface Message {
    role: 'user' | 'assistant';
    content: string;
    voice?: boolean;
}

export const ChatPanel = () => {
    const [isOpen, setIsOpen] = useState(false);
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
            throw new Error(errorData.detail || `Failed to create session: ${response.status}`);
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

    if (!isOpen) {
        return (
            <button
                onClick={() => setIsOpen(true)}
                className="absolute bottom-6 right-6 z-50 w-12 h-12 flex items-center justify-center bg-[var(--color-primary)] text-white rounded-full shadow-lg hover:bg-[var(--color-primary-hover)] hover:scale-105 transition-all group"
                title="Test Workflow"
            >
                <Play size={20} fill="currentColor" />
                {/* Tooltip */}
                <span className="absolute right-full mr-2 px-2 py-1 bg-gray-800 dark:bg-slate-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
                    Test Workflow
                </span>
            </button>
        );
    }

    const handleSend = async () => {
        if (!input.trim()) {
            setError('Please enter a message');
            return;
        }

        if (!hasLoadedWorkflow) {
            setError('Please load a workflow from the sidebar first');
            return;
        }

        const userMessage = input;
        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setInput('');
        setIsLoading(true);
        setError(null);

        let activeSessionId = sessionId;

        try {
            // Ensure we have a session - Create one if missing!
            if (!activeSessionId) {
                activeSessionId = await createSession();
                setSessionId(activeSessionId);
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
                        message: userMessage,
                        max_turns: 10,
                        metadata: {},
                    }),
                }
            );

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
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

        } catch (err) {
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
                        content: `⚠️ **Session Expired**\nThe previous session was lost. Please send your message again to start a new conversation.`
                    },
                ]);
            } else {
                setError(errorMsg);
                setMessages(prev => [
                    ...prev,
                    {
                        role: 'assistant',
                        content: `❌ Error: ${errorMsg}`
                    },
                ]);
            }
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="absolute bottom-6 right-6 w-96 bg-white dark:bg-[#0b111b] rounded-xl shadow-2xl border border-gray-200 dark:border-slate-800 z-50 flex flex-col overflow-hidden animate-in slide-in-from-bottom-4 duration-200 h-[550px]">
            {/* Header - Shows current workflow name */}
            <div className={`p-4 ${hasLoadedWorkflow ? 'bg-[var(--color-primary)]' : 'bg-gray-700 dark:bg-slate-800'} text-white flex items-center justify-between shrink-0 transition-colors duration-300`}>
                <div className="flex items-center gap-2 overflow-hidden">
                    <MessageSquare size={18} className="shrink-0" />
                    <div className="min-w-0">
                        <span className="font-semibold block truncate">
                            {hasLoadedWorkflow ? workflowName : 'Test Workflow'}
                        </span>
                        {hasLoadedWorkflow && (
                            <span className="text-[10px] text-blue-100 block truncate">
                                ID: {currentWorkflowId}
                            </span>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                    <button
                        onClick={handleNewSession}
                        className="text-white/80 hover:text-white hover:bg-white/20 p-1.5 rounded-full transition-all"
                        title="Start New Session"
                    >
                        <PlusCircle size={18} />
                    </button>
                    <button
                        onClick={handleClearChat}
                        className="text-white/80 hover:text-white hover:bg-white/20 p-1.5 rounded-full transition-all"
                        title="Clear Chat History"
                    >
                        <RefreshCw size={16} />
                    </button>
                    <div className="w-px h-4 bg-white/20 mx-1"></div>
                    <button
                        onClick={() => setIsOpen(false)}
                        className="text-white/80 hover:text-white hover:bg-red-500/80 p-1.5 rounded-full transition-all"
                        title="Close Test Panel"
                    >
                        <X size={18} />
                    </button>
                </div>
            </div>

            {/* Workflow Status & JWT Config */}
            <div className="p-3 bg-gray-50 dark:bg-slate-900/60 border-b border-gray-200 dark:border-slate-800 space-y-2 shrink-0">
                {/* Workflow Status */}
                <div className="flex items-center justify-between text-xs">
                    <span className="text-gray-500 dark:text-slate-400">Canvas Status:</span>
                    {hasLoadedWorkflow ? (
                        <span className="text-green-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                            <span className="w-2 h-2 bg-green-500 dark:bg-emerald-400 rounded-full"></span>
                            {nodesLength} nodes, {edgesLength} edges
                        </span>
                    ) : hasWorkflow ? (
                        <span className="text-yellow-600 dark:text-amber-400 font-medium flex items-center gap-1">
                            <span className="w-2 h-2 bg-yellow-500 dark:bg-amber-400 rounded-full"></span>
                            Canvas has nodes (drop workflow to test)
                        </span>
                    ) : (
                        <span className="text-gray-400 dark:text-slate-500 font-medium flex items-center gap-1">
                            <span className="w-2 h-2 bg-gray-300 dark:bg-slate-600 rounded-full"></span>
                            Empty canvas
                        </span>
                    )}
                </div>

                {/* JWT Token Input */}
                <div className="space-y-1">
                    <div className="flex items-center justify-between">
                        <label className="text-xs font-semibold text-gray-500 dark:text-slate-400">Authentication</label>
                        <button
                            onClick={() => setShowJwtInput(!showJwtInput)}
                            className="text-xs text-[var(--color-primary)] hover:text-[var(--color-primary-hover)]"
                        >
                            {showJwtInput ? 'Hide' : 'Add JWT Token'}
                        </button>
                    </div>
                    {showJwtInput && (
                        <input
                            type="password"
                            value={jwtToken}
                            onChange={(e) => setJwtToken(e.target.value)}
                            placeholder="Bearer token (optional)"
                            className="w-full px-2 py-1.5 bg-white dark:bg-slate-950 border border-gray-300 dark:border-slate-700 text-gray-900 dark:text-slate-200 rounded text-xs font-mono"
                        />
                    )}
                </div>

                {/* Error Display */}
                {error && (
                    <div className="flex items-center gap-2 p-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded text-xs text-red-700 dark:text-red-400">
                        <AlertCircle size={14} className="shrink-0" />
                        <span>{error}</span>
                    </div>
                )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-gray-50 dark:bg-slate-950/40 min-h-0">
                {messages.length === 0 && (
                    <div className="text-center text-gray-400 dark:text-slate-500 text-sm mt-8">
                        <MessageSquare size={32} className="mx-auto mb-2 opacity-50" />
                        {hasLoadedWorkflow ? (
                            <p>Send a message to test your workflow!</p>
                        ) : (
                            <div>
                                <p className="font-medium">No workflow loaded</p>
                                <p className="text-xs mt-1">Drag a workflow from the sidebar to get started</p>
                            </div>
                        )}
                        {isLoading && <div className="mt-4"><Loader2 size={24} className="animate-spin text-[var(--color-primary)] mx-auto" /></div>}
                    </div>
                )}
                {messages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm ${msg.role === 'user'
                            ? 'bg-[var(--color-primary)] text-white rounded-br-none'
                            : 'bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 text-gray-700 dark:text-slate-300 rounded-bl-none shadow-sm'
                            }`}>
                            {msg.role === 'user' ? (
                                msg.content
                            ) : (
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={{
                                        // Code blocks
                                        code: ({ inline, className, children, ...props }: any) => {
                                            return inline ? (
                                                <code className="bg-gray-100 dark:bg-slate-800 text-gray-800 dark:text-slate-200 px-1 py-0.5 rounded text-xs font-mono" {...props}>
                                                    {children}
                                                </code>
                                            ) : (
                                                <pre className="bg-gray-900 dark:bg-slate-950 text-gray-100 dark:text-slate-200 p-3 rounded-lg overflow-x-auto my-2 text-xs">
                                                    <code className={className} {...props}>{children}</code>
                                                </pre>
                                            );
                                        },
                                        // Links
                                        a: ({ children, ...props }: any) => (
                                            <a className="text-[var(--color-primary)] hover:underline" target="_blank" rel="noopener noreferrer" {...props}>
                                                {children}
                                            </a>
                                        ),
                                        // Lists
                                        ul: ({ children }: any) => <ul className="list-disc list-inside my-1 space-y-0.5">{children}</ul>,
                                        ol: ({ children }: any) => <ol className="list-decimal list-inside my-1 space-y-0.5">{children}</ol>,
                                        // Paragraphs
                                        p: ({ children }: any) => <p className="my-1">{children}</p>,
                                        // Bold/Strong
                                        strong: ({ children }: any) => <strong className="font-semibold">{children}</strong>,
                                        // Headers
                                        h1: ({ children }: any) => <h1 className="text-lg font-bold mt-3 mb-1">{children}</h1>,
                                        h2: ({ children }: any) => <h2 className="text-base font-bold mt-2 mb-1">{children}</h2>,
                                        h3: ({ children }: any) => <h3 className="text-sm font-bold mt-2 mb-1">{children}</h3>,
                                        // Blockquote
                                        blockquote: ({ children }: any) => (
                                            <blockquote className="border-l-2 border-gray-300 dark:border-slate-700 pl-3 my-2 text-gray-600 dark:text-slate-400 italic">
                                                {children}
                                            </blockquote>
                                        ),
                                        // Table
                                        table: ({ children }: any) => (
                                            <div className="overflow-x-auto my-2">
                                                <table className="min-w-full text-xs border border-gray-200 dark:border-slate-800">{children}</table>
                                            </div>
                                        ),
                                        th: ({ children }: any) => <th className="bg-gray-100 dark:bg-slate-800 px-2 py-1 border-b border-gray-200 dark:border-slate-700 font-semibold text-left">{children}</th>,
                                        td: ({ children }: any) => <td className="px-2 py-1 border-b border-gray-200 dark:border-slate-800">{children}</td>,
                                    }}
                                >
                                    {msg.content}
                                </ReactMarkdown>
                            )}
                        </div>
                    </div>
                ))}
                {isLoading && messages.length > 0 && (
                    <div className="flex justify-start">
                        <div className="flex items-center gap-2 px-4 py-2.5 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl rounded-bl-none shadow-sm text-sm text-gray-500 dark:text-slate-400">
                            <Loader2 size={14} className="animate-spin" />
                            <span>Executing workflow...</span>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-gray-100 dark:border-slate-800 bg-white dark:bg-[#0b111b] shrink-0 space-y-2">
                <div className="flex items-center gap-2">
                    <div className="relative flex-1">
                        <input
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && !isLoading && handleSend()}
                            disabled={isLoading || !hasLoadedWorkflow || voice.isActive}
                            className="w-full pl-4 pr-10 py-2.5 bg-gray-100 dark:bg-slate-900 border-none rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 text-gray-800 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 disabled:opacity-50"
                            placeholder={
                                voice.isActive
                                    ? 'Voice mode — tap the mic to stop'
                                    : hasLoadedWorkflow
                                        ? 'Type a message...'
                                        : 'Load a workflow to start testing...'
                            }
                        />
                        <button
                            onClick={handleSend}
                            disabled={isLoading || !hasLoadedWorkflow || !input.trim() || voice.isActive}
                            className="absolute right-1.5 top-1.5 p-1.5 bg-[var(--color-primary)] text-white rounded-full hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <Send size={14} />
                        </button>
                    </div>
                    {/* Level meter, driven by the real signal so it stops moving
                        when the audio does. */}
                    <div
                        ref={vizRef}
                        aria-hidden="true"
                        className={`voice-viz ${voice.isActive ? 'is-on' : ''}`}
                    >
                        {[0, 1, 2, 3, 4].map((bar) => (
                            <i key={bar} />
                        ))}
                    </div>
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
                        className={`relative shrink-0 h-9 w-9 rounded-full flex items-center justify-center transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                            voice.isActive
                                ? 'bg-[var(--color-primary)] text-white'
                                : 'bg-gray-100 dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white'
                        }`}
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
                </div>
                {(voice.isActive || voice.error) && (
                    <p className={`text-[10px] leading-snug ${voice.error ? 'text-red-500 dark:text-rose-400' : 'text-gray-500 dark:text-slate-400'}`}>
                        {voice.error
                            ? voice.error
                            : voice.state === 'speaking'
                                ? 'Speaking… — voice replies come from the live model, so workflow tools do not run'
                                : 'Listening… — voice replies come from the live model, so workflow tools do not run'}
                    </p>
                )}
            </div>
        </div>
    );
};
