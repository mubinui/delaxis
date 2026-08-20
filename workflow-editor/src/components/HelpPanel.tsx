import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BookOpen, CheckCircle2, Lightbulb, MessageCircleQuestion, Send, Stethoscope, X, XCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useShallow } from 'zustand/react/shallow';
import { API_BASE_URL } from '../api/client';
import { useLibraryStore } from '../stores/libraryStore';
import { useWorkflowStore } from '../stores/workflowStore';
import { ALL_COMPONENT_HELP, helpForDiagnostic } from '../utils/componentHelp';
import { diagnoseWorkflow, summarizeDiagnostics } from '../utils/graphDiagnostics';
import { StatusBadge } from './studio/StatusBadge';

type Tab = 'issues' | 'components' | 'ask';

const severityIcon = { error: XCircle, warning: AlertTriangle, info: CheckCircle2 };

/**
 * Reads the graph digest the explain endpoint accepts.
 *
 * Built from an explicit allowlist, never a config spread: node config carries a
 * raw api_key, and this payload is sent to a third-party model.
 */
const buildDigest = (nodes: any[], edges: any[]) => ({
    pattern: nodes.some((n) => n.data?.config?.is_selector) ? 'selector' : 'sequential',
    nodes: nodes.map((node) => {
        const model = node.data?.config?.model_config ?? node.data?.config?.llm_config ?? {};
        return {
            id: String(node.id),
            type: String(node.type ?? 'agent'),
            label: String(node.data?.label ?? node.id),
            provider_id: String(model.provider_id ?? ''),
            model: String(model.model ?? ''),
            tools: Array.isArray(node.data?.config?.tools) ? node.data.config.tools.map(String) : [],
        };
    }),
    edges: edges.map((edge) => ({ source: String(edge.source), target: String(edge.target) })),
});

export const HelpPanel = ({ onClose }: { onClose: () => void }) => {
    const [tab, setTab] = useState<Tab>('issues');
    const [expanded, setExpanded] = useState<string | null>(null);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [busy, setBusy] = useState<string | null>(null);
    const [question, setQuestion] = useState('');
    const [askAnswer, setAskAnswer] = useState('');

    const { nodes, edges, onNodesChange } = useWorkflowStore(
        useShallow((state) => ({
            nodes: state.nodes,
            edges: state.edges,
            onNodesChange: state.onNodesChange,
        })),
    );

    // Selection lives on the node itself (React Flow), so select by dispatching
    // a change rather than through a store action.
    const selectNode = (nodeId: string) =>
        onNodesChange(nodes.map((node) => ({ id: node.id, type: 'select' as const, selected: node.id === nodeId })));
    const { savedAgents, savedTools, providers, fetchLibraryItems } = useLibraryStore();

    useEffect(() => {
        void fetchLibraryItems().catch(() => undefined);
    }, [fetchLibraryItems]);

    const diagnostics = useMemo(
        () => diagnoseWorkflow({ nodes, edges, agents: savedAgents, tools: savedTools, providers }),
        [nodes, edges, savedAgents, savedTools, providers],
    );
    const summary = useMemo(() => summarizeDiagnostics(diagnostics), [diagnostics]);

    const streamExplain = async (key: string, payload: Record<string, unknown>) => {
        setBusy(key);
        setAnswers((prev) => ({ ...prev, [key]: '' }));
        try {
            const response = await fetch(`${API_BASE_URL}/api/v1/builder/explain-diagnostic`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...payload, graph: buildDigest(nodes, edges) }),
            });
            if (!response.ok || !response.body) {
                const detail = await response.text();
                setAnswers((prev) => ({ ...prev, [key]: `Could not reach the model: ${detail.slice(0, 200)}` }));
                return;
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let text = '';
            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() ?? '';
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const data = line.slice(6).trim();
                    if (data === '[DONE]') continue;
                    try {
                        const token = JSON.parse(data).token;
                        if (token) {
                            text += token;
                            setAnswers((prev) => ({ ...prev, [key]: text }));
                        }
                    } catch {
                        // partial frame; the next chunk completes it
                    }
                }
            }
        } catch (error) {
            setAnswers((prev) => ({ ...prev, [key]: (error as Error).message }));
        } finally {
            setBusy(null);
        }
    };

    const tabClass = (value: Tab) =>
        `flex-1 px-2 py-1.5 text-[11px] font-bold rounded-md transition-colors ${
            tab === value
                ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-sm'
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
        }`;

    return (
        <aside className="absolute top-4 right-4 bottom-24 z-40 w-[380px] rounded-2xl border border-[var(--color-ui-border)] bg-white dark:bg-[#0b111b] shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right-4 fade-in duration-200">
            <div className="flex items-center justify-between border-b border-[var(--color-ui-border)] px-4 py-3">
                <div className="flex items-center gap-2">
                    <Stethoscope size={15} className="text-blue-600 dark:text-blue-400" />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-slate-100">Help</span>
                    <StatusBadge
                        tone={summary.tone}
                        label={
                            summary.errors + summary.warnings === 0
                                ? 'All clear'
                                : `${summary.errors} error${summary.errors === 1 ? '' : 's'} · ${summary.warnings} warning${summary.warnings === 1 ? '' : 's'}`
                        }
                        compact
                    />
                </div>
                <button onClick={onClose} className="text-slate-400 hover:text-slate-700 dark:hover:text-white" title="Close help">
                    <X size={16} />
                </button>
            </div>

            <div className="flex gap-1 border-b border-[var(--color-ui-border)] bg-slate-50 dark:bg-slate-900/40 p-1.5">
                <button onClick={() => setTab('issues')} className={tabClass('issues')}>Issues</button>
                <button onClick={() => setTab('components')} className={tabClass('components')}>Components</button>
                <button onClick={() => setTab('ask')} className={tabClass('ask')}>Ask</button>
            </div>

            <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
                {tab === 'issues' && diagnostics.length === 0 && (
                    <div className="rounded-xl border border-dashed border-emerald-300 dark:border-emerald-900/60 p-6 text-center">
                        <CheckCircle2 size={22} className="mx-auto mb-2 text-emerald-500" />
                        <p className="text-xs font-bold text-slate-700 dark:text-slate-200">Nothing to fix</p>
                        <p className="mt-1 text-[11px] text-slate-500">Every component on the canvas looks configured.</p>
                    </div>
                )}

                {tab === 'issues' && diagnostics.map((finding) => {
                    const Icon = severityIcon[finding.severity];
                    const isOpen = expanded === finding.id;
                    return (
                        <div key={finding.id} className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 overflow-hidden">
                            <button
                                onClick={() => setExpanded(isOpen ? null : finding.id)}
                                className="w-full flex items-start gap-2 p-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                            >
                                <Icon
                                    size={14}
                                    className={`mt-0.5 shrink-0 ${
                                        finding.severity === 'error'
                                            ? 'text-red-500'
                                            : finding.severity === 'warning'
                                              ? 'text-amber-500'
                                              : 'text-slate-400'
                                    }`}
                                />
                                <span className="min-w-0 flex-1">
                                    <span className="block text-[11px] font-bold text-slate-800 dark:text-slate-100">{finding.title}</span>
                                    <span className="mt-0.5 block text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">{finding.detail}</span>
                                </span>
                            </button>

                            {isOpen && (
                                <div className="space-y-2 border-t border-slate-100 dark:border-slate-800 px-3 pb-3 pt-2">
                                    {finding.fixHint && (
                                        <p className="text-[10px] font-medium text-slate-600 dark:text-slate-300">→ {finding.fixHint}</p>
                                    )}
                                    {finding.suggestions && finding.suggestions.length > 0 && (
                                        <p className="text-[10px] text-slate-500">Did you mean: <span className="font-mono">{finding.suggestions.join(', ')}</span></p>
                                    )}
                                    <div className="flex flex-wrap gap-1.5">
                                        {finding.nodeId && (
                                            <button
                                                onClick={() => selectNode(finding.nodeId!)}
                                                className="rounded-md border border-slate-200 dark:border-slate-700 px-2 py-1 text-[10px] font-semibold text-slate-600 dark:text-slate-300 hover:border-blue-500"
                                            >
                                                Show node
                                            </button>
                                        )}
                                        <button
                                            disabled={busy === finding.id}
                                            onClick={() => streamExplain(finding.id, { mode: 'explain', diagnostic: finding })}
                                            className="inline-flex items-center gap-1 rounded-md border border-blue-200 dark:border-blue-900/60 px-2 py-1 text-[10px] font-semibold text-blue-600 dark:text-blue-400 disabled:opacity-50 hover:bg-blue-50 dark:hover:bg-blue-950/40"
                                        >
                                            <MessageCircleQuestion size={10} /> {busy === finding.id ? 'Working…' : 'Explain'}
                                        </button>
                                        <button
                                            disabled={busy === `${finding.id}-fix`}
                                            onClick={() => streamExplain(`${finding.id}-fix`, { mode: 'fix', diagnostic: finding })}
                                            className="inline-flex items-center gap-1 rounded-md border border-blue-200 dark:border-blue-900/60 px-2 py-1 text-[10px] font-semibold text-blue-600 dark:text-blue-400 disabled:opacity-50 hover:bg-blue-50 dark:hover:bg-blue-950/40"
                                        >
                                            <Lightbulb size={10} /> {busy === `${finding.id}-fix` ? 'Working…' : 'Suggest a fix'}
                                        </button>
                                    </div>
                                    {[finding.id, `${finding.id}-fix`].map((key) =>
                                        answers[key] ? (
                                            <div key={key} className="markdown-help rounded-lg bg-slate-50 dark:bg-slate-950/60 p-2 text-[10px] leading-relaxed text-slate-700 dark:text-slate-300">
                                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{answers[key]}</ReactMarkdown>
                                            </div>
                                        ) : null,
                                    )}
                                    {helpForDiagnostic(finding) && (
                                        <button
                                            onClick={() => { setTab('components'); setExpanded(helpForDiagnostic(finding)!.id); }}
                                            className="inline-flex items-center gap-1 text-[10px] font-semibold text-slate-500 hover:text-blue-600"
                                        >
                                            <BookOpen size={10} /> About {helpForDiagnostic(finding)!.label}
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}

                {tab === 'components' && ALL_COMPONENT_HELP.map((entry) => {
                    const isOpen = expanded === entry.id;
                    return (
                        <div key={entry.id} className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 overflow-hidden">
                            <button
                                onClick={() => setExpanded(isOpen ? null : entry.id)}
                                className="w-full p-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                            >
                                <span className="block text-[11px] font-bold text-slate-800 dark:text-slate-100">{entry.label}</span>
                                <span className="mt-0.5 block text-[10px] text-slate-500 dark:text-slate-400">{entry.summary}</span>
                            </button>
                            {isOpen && (
                                <div className="markdown-help space-y-2 border-t border-slate-100 dark:border-slate-800 px-3 pb-3 pt-2 text-[10px] leading-relaxed text-slate-600 dark:text-slate-300">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.body}</ReactMarkdown>
                                    <p><span className="font-bold text-slate-700 dark:text-slate-200">Input:</span> {entry.inputs}</p>
                                    <p><span className="font-bold text-slate-700 dark:text-slate-200">Output:</span> {entry.outputs}</p>
                                </div>
                            )}
                        </div>
                    );
                })}

                {tab === 'ask' && (
                    <div className="space-y-2">
                        <p className="text-[10px] text-slate-500 dark:text-slate-400">
                            Ask about this workflow. The model sees your node labels, providers and connections — never your API keys.
                        </p>
                        <div className="flex gap-1.5">
                            <input
                                value={question}
                                onChange={(event) => setQuestion(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' && question.trim()) {
                                        void streamExplain('ask', { mode: 'ask', question }).then(() => setAskAnswer(''));
                                    }
                                }}
                                placeholder="Why is my selector not routing?"
                                className="flex-1 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-[11px] text-slate-800 dark:text-slate-200"
                            />
                            <button
                                disabled={busy === 'ask' || !question.trim()}
                                onClick={() => void streamExplain('ask', { mode: 'ask', question })}
                                className="rounded-lg bg-blue-600 px-2.5 text-white disabled:opacity-40"
                                title="Ask"
                            >
                                <Send size={13} />
                            </button>
                        </div>
                        {(answers.ask || askAnswer) && (
                            <div className="markdown-help rounded-lg bg-slate-50 dark:bg-slate-950/60 p-2.5 text-[10px] leading-relaxed text-slate-700 dark:text-slate-300">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{answers.ask || askAnswer}</ReactMarkdown>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </aside>
    );
};
