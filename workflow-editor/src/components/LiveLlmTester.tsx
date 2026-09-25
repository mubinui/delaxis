import { useState } from 'react';
import { ArrowUp, Copy } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useLibraryStore } from '../stores/libraryStore';
import { Toolbar, MoreMenu } from './shell/Toolbar';
import { ActivityCapsule } from './shell/ActivityCapsule';
import { StatusGlyph } from './shell/StatusGlyph';
import { useUiStore } from '../stores/uiStore';

/** A slider drawn the way macOS 27 draws one: a thin track, an ink fill, a capsule knob. */
const Slider = ({ label, value, display, min, max, step, onChange }: {
    label: string; value: number; display: string; min: number; max: number; step: number; onChange: (value: number) => void;
}) => (
    <label className="block">
        <span className="field-row"><span className="field-label">{label}</span><span className="mono text-dim">{display}</span></span>
        <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(event) => onChange(Number(event.target.value))}
            className="w-full"
        />
    </label>
);

/** Send one prompt to any LiteLLM model and see the reply, latency, tokens and cost. */
export const LiveLlmTester = () => {
    const go = useUiStore((state) => state.go);
    const providers = useLibraryStore((s) => s.providers);
    const llmProviders = providers.filter((p) => p.type === 'llm' && p.enabled !== false);
    const [provider, setProvider] = useState('openrouter');
    const [model, setModel] = useState('google/gemma-3-27b-it');
    const [apiKey, setApiKey] = useState('');
    const [systemPrompt, setSystemPrompt] = useState('You are a helpful and precise enterprise AI expert.');
    const [userPrompt, setUserPrompt] = useState('Compare CrewAI hierarchical and sequential processes concisely.');
    const [temperature, setTemperature] = useState(0.7);
    const [maxTokens, setMaxTokens] = useState(2048);

    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [result, setResult] = useState<{
        response: string;
        latency_ms: number;
        token_usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
        estimated_cost_usd: number;
        status: string;
    } | null>(null);

    const handleRunTest = async () => {
        setLoading(true);
        setResult(null);
        setError(null);

        try {
            const res = await fetch('/api/v1/studio/test-llm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider,
                    model,
                    api_key: apiKey.trim() || undefined,
                    system_prompt: systemPrompt,
                    user_prompt: userPrompt,
                    temperature,
                    max_tokens: maxTokens,
                }),
            });

            if (!res.ok) {
                // The backend returns an honest error payload on LLM failure
                let detailMessage = `Server returned HTTP ${res.status}`;
                try {
                    const body = await res.json();
                    const detail = body?.detail;
                    if (detail?.message) {
                        detailMessage = `${detail.message}${detail.error ? `\n\n${detail.error}` : ''}`;
                    } else if (typeof detail === 'string') {
                        detailMessage = detail;
                    }
                } catch {
                    // keep the generic message
                }
                throw new Error(detailMessage);
            }

            const data = await res.json();
            setResult(data);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setLoading(false);
        }
    };

    const canSend = !loading && model.trim() && userPrompt.trim();

    return (
        <>
            <div className="page">
                <div className="page-inner">
                    <div className="page-head">
                        <div>
                            <h1 className="display">Model tester</h1>
                            <p className="lead mt-1 max-w-[640px]">
                                Send one prompt to any LiteLLM model. Check the key, the latency and the cost before you wire it into an agent.
                            </p>
                        </div>
                    </div>

                    <div className="mt-5 grid gap-5 lg:grid-cols-[440px_minmax(0,1fr)]">
                        <form
                            className="panel flex flex-col gap-4 p-5"
                            onSubmit={(event) => { event.preventDefault(); if (canSend) void handleRunTest(); }}
                        >
                            <div className="grid grid-cols-2 gap-3">
                                <label className="block">
                                    <span className="field-label">Provider</span>
                                    <select value={provider} onChange={(e) => setProvider(e.target.value)} className="select">
                                        {llmProviders.map((p) => (
                                            <option key={p.id} value={p.id}>{p.name}</option>
                                        ))}
                                        {llmProviders.length === 0 && <option value="openrouter">OpenRouter</option>}
                                    </select>
                                </label>
                                <label className="block">
                                    <span className="field-label">Model</span>
                                    <input type="text" value={model} onChange={(e) => setModel(e.target.value)} className="input mono !text-[12px]" placeholder="google/gemma-3-27b-it" spellCheck={false} />
                                </label>
                            </div>
                            <label className="block">
                                <span className="field-label">API key</span>
                                <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} className="input mono" placeholder="Use the key set on the server" autoComplete="off" />
                                <span className="hint mt-1 block">Optional. Sent with this request only.</span>
                            </label>
                            <div className="grid grid-cols-2 gap-5">
                                <Slider label="Temperature" value={temperature} display={temperature.toFixed(2)} min={0} max={1.5} step={0.05} onChange={setTemperature} />
                                <Slider label="Max output tokens" value={maxTokens} display={maxTokens.toLocaleString()} min={256} max={8192} step={256} onChange={setMaxTokens} />
                            </div>
                            <label className="block">
                                <span className="field-label">System prompt</span>
                                <textarea rows={3} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} className="textarea" />
                            </label>
                            <label className="block">
                                <span className="field-label">Prompt</span>
                                <textarea
                                    rows={6}
                                    value={userPrompt}
                                    onChange={(e) => setUserPrompt(e.target.value)}
                                    onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canSend) void handleRunTest(); }}
                                    className="textarea"
                                />
                            </label>
                            <div className="flex items-center justify-end gap-2.5">
                                <span className="hint">⌘↩</span>
                                <button type="submit" disabled={!canSend} className="btn btn-primary">
                                    <ArrowUp size={14} strokeWidth={2.2} />
                                    {loading ? 'Sending…' : 'Send'}
                                </button>
                            </div>
                        </form>

                        <div className="flex min-w-0 flex-col gap-4">
                            <div className="panel figures px-5 py-3.5" aria-live="polite">
                                <div className={`figure ${result ? '' : 'is-zero'}`}><b>{result ? result.latency_ms.toLocaleString() : '—'}{result && <small>ms</small>}</b><span>Latency</span></div>
                                <div className={`figure ${result ? '' : 'is-zero'}`}><b>{result ? (result.token_usage?.total_tokens ?? 0).toLocaleString() : '—'}</b><span>Tokens</span></div>
                                <div className={`figure ${result ? '' : 'is-zero'}`}><b>{result ? `$${result.estimated_cost_usd?.toFixed(6) ?? '0.000000'}` : '—'}</b><span>Estimated cost</span></div>
                                <div className="figure">
                                    <b className="flex h-[25px] items-center gap-2 !text-[15px]">
                                        <StatusGlyph shape={loading ? 'busy' : error ? 'bad' : result ? 'ok' : 'idle'} />
                                        {loading ? 'Waiting' : error ? 'Failed' : result ? 'Answered' : 'Not sent'}
                                    </b>
                                    <span>Status</span>
                                </div>
                            </div>

                            <section className="panel flex min-h-[420px] flex-1 flex-col gap-3 px-6 py-5">
                                <div className="flex items-center gap-2">
                                    <span className="h-section flex-1">Response</span>
                                    {result && <span className="chip mono">{model}</span>}
                                    {result && (
                                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void navigator.clipboard?.writeText(result.response)}>
                                            <Copy size={12} /> Copy
                                        </button>
                                    )}
                                </div>
                                {loading ? (
                                    <div className="empty-state flex-1">
                                        <StatusGlyph shape="busy" />
                                        <span>Waiting for the model…</span>
                                    </div>
                                ) : error ? (
                                    <div className="flex flex-col gap-2">
                                        <div className="rounded-xl p-3" style={{ background: 'var(--clay-wash)' }}>
                                            <div className="headline" style={{ color: 'var(--clay)' }}>The call failed</div>
                                            <pre className="mono mt-1 whitespace-pre-wrap" style={{ color: 'var(--clay)' }}>{error}</pre>
                                        </div>
                                        <p className="hint">Check the API key, the provider and the model id, then send again.</p>
                                    </div>
                                ) : result ? (
                                    <div className="reading">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.response}</ReactMarkdown>
                                    </div>
                                ) : (
                                    <div className="empty-state flex-1">
                                        <div className="headline">No reply yet</div>
                                        <p className="hint max-w-[340px]">Pick a provider and a model, write a prompt, and send it. The reply, latency, tokens and cost appear here.</p>
                                    </div>
                                )}
                            </section>
                        </div>
                    </div>
                </div>
            </div>
            <Toolbar center={<ActivityCapsule onStatusClick={() => go('studio')} />} actions={<MoreMenu />} />
        </>
    );
};
