import React, { useState } from 'react';
import { Play, Sparkles, Cpu, DollarSign, Clock, RefreshCw, X } from 'lucide-react';
import { useLibraryStore } from '../stores/libraryStore';

interface LiveLlmTesterProps {
    onClose: () => void;
}

export const LiveLlmTester: React.FC<LiveLlmTesterProps> = ({ onClose }) => {
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

    return (
        <div className="absolute inset-0 bg-[var(--color-canvas-bg)] flex flex-col z-30 animate-fade-in overflow-hidden">
            {/* Top Toolbar Strip */}
            <div className="h-14 bg-white dark:bg-[#0b111b] border-b border-gray-200 dark:border-slate-800 flex items-center justify-between px-6 shrink-0 shadow-sm">
                <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-purple-600 dark:text-purple-400 animate-pulse" />
                    <span className="font-bold text-xs text-gray-900 dark:text-white uppercase tracking-wider">
                        Live LLM Validation Playground
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 font-bold">
                        LiteLLM Core Engine
                    </span>
                </div>
                <button
                    onClick={onClose}
                    className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800"
                    title="Close Live Tester and return to Canvas"
                >
                    <X className="w-5 h-5" />
                </button>
            </div>

            {/* Split Screen Workspace */}
            <div className="flex flex-1 overflow-hidden">
                {/* Left Controls Column */}
                <div className="w-1/2 border-r border-gray-200 dark:border-slate-800 bg-white/60 dark:bg-[#070b12]/60 overflow-y-auto p-6 flex flex-col gap-5">
                    {/* Provider & Model Selectors */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="text-[11px] font-bold text-gray-500 dark:text-gray-400 block mb-1">
                                API Provider Gateway
                            </label>
                            <select
                                value={provider}
                                onChange={(e) => setProvider(e.target.value)}
                                className="w-full p-2 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white"
                            >
                                {llmProviders.map((p) => (
                                    <option key={p.id} value={p.id}>{p.name}</option>
                                ))}
                                {llmProviders.length === 0 && <option value="openrouter">OpenRouter API</option>}
                            </select>
                        </div>
                        <div>
                            <label className="text-[11px] font-bold text-gray-500 dark:text-gray-400 block mb-1">
                                Target LLM Model
                            </label>
                            <input
                                type="text"
                                value={model}
                                onChange={(e) => setModel(e.target.value)}
                                className="w-full p-2 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white font-mono"
                                placeholder="e.g. google/gemma-3-27b-it"
                            />
                        </div>
                    </div>

                    {/* Override Secret Key */}
                    <div>
                        <label className="text-[11px] font-bold text-gray-500 dark:text-gray-400 block mb-1">
                            Override Secret API Key (Optional)
                        </label>
                        <input
                            type="password"
                            value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                            className="w-full p-2 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white font-mono"
                            placeholder="Leave empty to utilize server-configured default tokens"
                        />
                    </div>

                    {/* Sliders Strip */}
                    <div className="grid grid-cols-2 gap-4 bg-gray-50/50 dark:bg-slate-900/30 p-3 rounded-xl border border-gray-100 dark:border-slate-800">
                        <div>
                            <div className="flex justify-between text-[11px] mb-1">
                                <span className="font-bold text-gray-600 dark:text-gray-400">Temperature</span>
                                <span className="font-mono text-blue-600 dark:text-sky-400">{temperature}</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="1.5"
                                step="0.05"
                                value={temperature}
                                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                                className="w-full accent-blue-600 cursor-pointer"
                            />
                        </div>
                        <div>
                            <div className="flex justify-between text-[11px] mb-1">
                                <span className="font-bold text-gray-600 dark:text-gray-400">Max Output Tokens</span>
                                <span className="font-mono text-purple-600 dark:text-purple-400">{maxTokens}</span>
                            </div>
                            <input
                                type="range"
                                min="256"
                                max="8192"
                                step="256"
                                value={maxTokens}
                                onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                                className="w-full accent-purple-600 cursor-pointer"
                            />
                        </div>
                    </div>

                    {/* System Instructions */}
                    <div>
                        <label className="text-[11px] font-bold text-gray-500 dark:text-gray-400 block mb-1">
                            System Role Definitions & Guardrails
                        </label>
                        <textarea
                            rows={3}
                            value={systemPrompt}
                            onChange={(e) => setSystemPrompt(e.target.value)}
                            className="w-full p-2.5 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white font-mono resize-none leading-relaxed"
                        />
                    </div>

                    {/* User Prompt Query */}
                    <div className="flex-1 flex flex-col">
                        <label className="text-[11px] font-bold text-gray-500 dark:text-gray-400 block mb-1">
                            Incoming User Prompt / Message
                        </label>
                        <textarea
                            rows={5}
                            value={userPrompt}
                            onChange={(e) => setUserPrompt(e.target.value)}
                            className="w-full flex-1 p-2.5 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white font-mono resize-none leading-relaxed"
                        />
                    </div>

                    {/* Action Trigger */}
                    <button
                        onClick={handleRunTest}
                        disabled={loading}
                        className="w-full py-3 text-xs font-bold text-white bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 rounded-xl shadow-md shadow-purple-600/10 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                        {loading ? (
                            <>
                                <RefreshCw className="w-4 h-4 animate-spin" />
                                Evaluating Inference Engine...
                            </>
                        ) : (
                            <>
                                <Play className="w-4 h-4 fill-current" />
                                Execute Live Stream Testing
                            </>
                        )}
                    </button>
                </div>

                {/* Right Results Column */}
                <div className="w-1/2 bg-gray-50/30 dark:bg-[#05080d] overflow-y-auto p-6 flex flex-col">
                    <span className="text-[11px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider block mb-3">
                        Inference Output & Telemetry Cost Attribution
                    </span>

                    {/* Metric Stats Banner */}
                    {result ? (
                        <div className="grid grid-cols-3 gap-3 mb-4 shrink-0 animate-fade-in">
                            <div className="p-3 rounded-xl bg-white dark:bg-[#0f1723] border border-gray-200 dark:border-slate-800/80 flex flex-col gap-1">
                                <div className="flex items-center gap-1.5 text-gray-400">
                                    <Clock className="w-3.5 h-3.5" />
                                    <span className="text-[10px] font-bold">Latency</span>
                                </div>
                                <span className="text-sm font-mono font-bold text-blue-600 dark:text-sky-400">
                                    {result.latency_ms} ms
                                </span>
                            </div>

                            <div className="p-3 rounded-xl bg-white dark:bg-[#0f1723] border border-gray-200 dark:border-slate-800/80 flex flex-col gap-1">
                                <div className="flex items-center gap-1.5 text-gray-400">
                                    <Cpu className="w-3.5 h-3.5" />
                                    <span className="text-[10px] font-bold">Total Tokens</span>
                                </div>
                                <span className="text-sm font-mono font-bold text-purple-600 dark:text-purple-400">
                                    {result.token_usage?.total_tokens || 0}
                                </span>
                            </div>

                            <div className="p-3 rounded-xl bg-white dark:bg-[#0f1723] border border-gray-200 dark:border-slate-800/80 flex flex-col gap-1">
                                <div className="flex items-center gap-1.5 text-gray-400">
                                    <DollarSign className="w-3.5 h-3.5" />
                                    <span className="text-[10px] font-bold">Est. Run Cost</span>
                                </div>
                                <span className="text-sm font-mono font-bold text-emerald-600 dark:text-emerald-400">
                                    ${result.estimated_cost_usd?.toFixed(6) || '0.000000'}
                                </span>
                            </div>
                        </div>
                    ) : (
                        <div className="p-4 rounded-xl bg-blue-50/50 dark:bg-blue-950/20 border border-blue-100 dark:border-slate-800/60 text-xs text-blue-800 dark:text-sky-300 mb-4 flex items-center gap-2">
                            <Sparkles className="w-4 h-4 shrink-0" />
                            <span>Configure target inputs and launch inference test to monitor runtime trace allocations real-time.</span>
                        </div>
                    )}

                    {/* Output Text Window */}
                    <div className="flex-1 rounded-xl border border-gray-200 dark:border-slate-800/80 bg-white dark:bg-[#0b111b] overflow-y-auto p-4 flex flex-col">
                        <span className="text-[10px] font-bold text-gray-400 dark:text-slate-600 uppercase block mb-2 pb-2 border-b border-gray-100 dark:border-slate-900/60">
                            Payload Streaming Context
                        </span>

                        {loading ? (
                            <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-2">
                                <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
                                <span className="text-xs">Waiting for the model response...</span>
                            </div>
                        ) : error ? (
                            <div className="flex-1 flex flex-col gap-2">
                                <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50">
                                    <span className="text-xs font-bold text-red-700 dark:text-red-300 block mb-1">
                                        LLM call failed
                                    </span>
                                    <pre className="text-xs text-red-600 dark:text-red-400 font-mono whitespace-pre-wrap bg-transparent border-none p-0">
                                        {error}
                                    </pre>
                                </div>
                                <span className="text-[11px] text-gray-500 dark:text-gray-400">
                                    Check the API key, provider, and model id, then try again.
                                </span>
                            </div>
                        ) : result ? (
                            <pre className="text-xs text-gray-800 dark:text-gray-200 font-mono whitespace-pre-wrap word-break bg-transparent border-none p-0">
                                {result.response}
                            </pre>
                        ) : (
                            <div className="flex-1 flex items-center justify-center text-gray-300 dark:text-slate-700 text-xs italic">
                                Model output will appear here
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
