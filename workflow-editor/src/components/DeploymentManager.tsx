import React, { useEffect, useMemo, useState } from 'react';
import { Rocket, Code, Copy, Check, Terminal, Layers, X, ExternalLink, Trash2, RefreshCw } from 'lucide-react';
import { useWorkflowStore } from '../stores/workflowStore';
import { useLibraryStore } from '../stores/libraryStore';
import { api } from '../api/client';
import type { DeploymentConfig } from '../api/backendTypes';

/** Snippets the backend renders for a deployment (GET /deployments/{id}/integration). */
interface IntegrationSnippets {
    url: string;
    embed_script_url: string;
    auth_mode: string;
    snippets: {
        widget: string;
        widget_options: string;
        iframe: string;
        link: string;
        curl: string;
    };
}

interface DeploymentManagerProps {
    onClose: () => void;
}

const CopyButton: React.FC<{ text: string; label?: string }> = ({ text, label = 'Copy' }) => {
    const [copied, setCopied] = useState(false);
    return (
        <button
            onClick={() => {
                navigator.clipboard.writeText(text);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            }}
            className="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-800 transition-colors flex items-center gap-1.5"
        >
            {copied ? <Check className="w-3.5 h-3.5 text-green-600" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied' : label}
        </button>
    );
};

const SnippetBlock: React.FC<{ title: string; hint: string; code: string }> = ({ title, hint, code }) => (
    <div className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
                <div className="text-xs font-bold text-gray-800 dark:text-gray-200">{title}</div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-relaxed">{hint}</p>
            </div>
            {code && <CopyButton text={code} />}
        </div>
        <pre className="p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs font-mono text-gray-800 dark:text-gray-200 overflow-x-auto leading-relaxed">
            {code || 'Loading…'}
        </pre>
    </div>
);

export const DeploymentManager: React.FC<DeploymentManagerProps> = ({ onClose }) => {
    const { workflowName, currentWorkflowId } = useWorkflowStore();
    const { deployments, fetchOperationsData, deleteDeployment } = useLibraryStore();
    const [activeTab, setActiveTab] = useState<'deployments' | 'embed' | 'api'>('deployments');
    const [refreshing, setRefreshing] = useState(false);
    const [selectedId, setSelectedId] = useState<string>('');
    const [integration, setIntegration] = useState<IntegrationSnippets | null>(null);
    const [integrationError, setIntegrationError] = useState<string | null>(null);

    useEffect(() => {
        void fetchOperationsData().catch(() => undefined);
    }, [fetchOperationsData]);

    const selected = useMemo(
        () => deployments.find((d) => d.id === selectedId) ?? deployments[0],
        [deployments, selectedId],
    );

    // Snippets come from the backend so the origin is right behind a proxy or a
    // custom domain, rather than being guessed from window.location.
    useEffect(() => {
        if (!selected) {
            setIntegration(null);
            return;
        }
        let cancelled = false;
        setIntegrationError(null);
        api<IntegrationSnippets>(`/api/v1/deployments/${selected.id}/integration`)
            .then((data) => { if (!cancelled) setIntegration(data); })
            .catch((error: unknown) => {
                if (cancelled) return;
                setIntegration(null);
                setIntegrationError(error instanceof Error ? error.message : 'Could not load the snippets.');
            });
        return () => { cancelled = true; };
    }, [selected?.id]);

    const origin = window.location.origin;
    const workflowId = currentWorkflowId || 'support_triage';

    const refresh = async () => {
        setRefreshing(true);
        try {
            await fetchOperationsData();
        } finally {
            setRefreshing(false);
        }
    };

    // Attribute values are user-controlled (deployment titles), so quote-escape them
    const attr = (value: string) => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

    const embedFor = (deployment: DeploymentConfig) =>
        `<iframe\n  src="${origin}${deployment.url}"\n  style="width: 100%; height: 640px; border: 0; border-radius: 12px;"\n  title="${attr(deployment.title || 'AI Chatbot')}"\n></iframe>`;

    const apiSnippet = `# 1. Create a session for the workflow
curl -X POST ${origin}/api/v1/sessions \\
  -H 'Content-Type: application/json' \\
  -d '{"workflow_id": "${workflowId}", "user_id": "demo"}'

# 2. Send a message (use session_id from step 1)
curl -X POST ${origin}/api/v1/sessions/<session_id>/messages \\
  -H 'Content-Type: application/json' \\
  -d '{"message": "Hello!"}'`;

    const tabClass = (tab: typeof activeTab) =>
        `px-4 py-2 text-xs font-bold border-b-2 transition-all flex items-center gap-2 ${activeTab === tab
            ? 'border-blue-600 text-blue-600 dark:text-blue-400'
            : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
        }`;

    return (
        <div className="absolute inset-0 bg-[var(--color-canvas-bg)] flex flex-col z-30 overflow-hidden">
            {/* Top Toolbar Strip */}
            <div className="h-14 bg-white dark:bg-[#0b111b] border-b border-gray-200 dark:border-slate-800 flex items-center justify-between px-6 shrink-0 shadow-sm">
                <div className="flex items-center gap-2">
                    <Rocket className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                    <span className="font-bold text-xs text-gray-900 dark:text-white uppercase tracking-wider">
                        Deployments
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 font-bold">
                        {workflowName || 'Workflow'}
                    </span>
                </div>
                <button
                    onClick={onClose}
                    className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800"
                >
                    <X className="w-5 h-5" />
                </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full flex flex-col gap-6">
                <div className="p-4 rounded-2xl glass-panel-subtle flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                    <div>
                        <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                            Ship your workflow as a live chatbot
                        </h3>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xl leading-relaxed">
                            Flash-deploy from the Launchpad to publish a chat page served by this app at
                            <span className="font-mono"> /d/&lt;name&gt;/</span>. Drop it into another site with
                            one script tag, embed it as an iframe, or call the REST API directly.
                        </p>
                    </div>
                    <button
                        onClick={refresh}
                        className="px-4 py-2 text-xs font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-xl shadow-md shadow-blue-600/10 transition-all flex items-center gap-2 shrink-0"
                    >
                        <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                        Refresh
                    </button>
                </div>

                <div className="flex border-b border-gray-200 dark:border-slate-800 gap-2">
                    <button onClick={() => setActiveTab('deployments')} className={tabClass('deployments')}>
                        <Rocket className="w-4 h-4" /> Live Deployments
                    </button>
                    <button onClick={() => setActiveTab('embed')} className={tabClass('embed')}>
                        <Code className="w-4 h-4" /> Integrate
                    </button>
                    <button onClick={() => setActiveTab('api')} className={tabClass('api')}>
                        <Layers className="w-4 h-4" /> REST API
                    </button>
                </div>

                {activeTab === 'deployments' && (
                    <div className="flex flex-col gap-3">
                        {deployments.length === 0 && (
                            <div className="p-8 rounded-xl border border-dashed border-gray-300 dark:border-slate-700 text-center">
                                <Terminal className="w-8 h-8 mx-auto text-gray-400 mb-3" />
                                <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">No deployments yet</p>
                                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                    Open the Launchpad panel and use Flash Deploy to publish this workflow as a chat page.
                                </p>
                            </div>
                        )}
                        {deployments.map((deployment) => (
                            <div
                                key={deployment.id}
                                className="p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex items-start justify-between gap-4"
                            >
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm font-bold text-gray-900 dark:text-white truncate">{deployment.title}</span>
                                        <span
                                            className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${deployment.status === 'active'
                                                ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300'
                                                : 'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300'
                                                }`}
                                        >
                                            {deployment.status}
                                        </span>
                                    </div>
                                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                        workflow <span className="font-mono">{deployment.workflow_id}</span> · created{' '}
                                        {new Date(deployment.created_at).toLocaleString()}
                                    </div>
                                    <a
                                        href={deployment.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="text-xs text-blue-600 dark:text-blue-400 inline-flex items-center gap-1 mt-2 font-medium"
                                    >
                                        {origin}
                                        {deployment.url} <ExternalLink size={11} />
                                    </a>
                                </div>
                                <div className="flex items-center gap-1 shrink-0">
                                    <CopyButton text={embedFor(deployment)} label="Copy embed" />
                                    <button
                                        onClick={() => void deleteDeployment(deployment.id)}
                                        className="p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 rounded-lg transition-colors"
                                        title="Delete deployment"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {activeTab === 'embed' && (
                    <div className="flex flex-col gap-4">
                        {deployments.length === 0 ? (
                            <div className="p-8 rounded-xl border border-dashed border-gray-300 dark:border-slate-700 text-center">
                                <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">No deployments yet</p>
                                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                    Flash Deploy a workflow first — the integration snippets appear here once a chatbot is live.
                                </p>
                            </div>
                        ) : (
                            <>
                                <div className="flex items-center gap-3">
                                    <label className="text-xs font-semibold text-gray-700 dark:text-gray-300 shrink-0">
                                        Deployment
                                    </label>
                                    <select
                                        value={selected?.id ?? ''}
                                        onChange={(event) => setSelectedId(event.target.value)}
                                        className="flex-1 px-3 py-2 rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs font-medium text-gray-800 dark:text-gray-200"
                                    >
                                        {deployments.map((deployment) => (
                                            <option key={deployment.id} value={deployment.id}>
                                                {deployment.title} — {deployment.url}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                {integrationError && (
                                    <p className="text-xs text-red-600 dark:text-red-400">{integrationError}</p>
                                )}

                                <SnippetBlock
                                    title="Floating widget"
                                    hint="One script tag. Adds a launcher in the corner that opens the chat in an iframe — the recommended way to add it to an existing site."
                                    code={integration?.snippets.widget ?? ''}
                                />
                                <SnippetBlock
                                    title="Widget with options"
                                    hint="Position, label and size are set with data- attributes on the same tag."
                                    code={integration?.snippets.widget_options ?? ''}
                                />
                                <SnippetBlock
                                    title="Inline iframe"
                                    hint="Put the chat inside your own layout. Give it at least 520px of height."
                                    code={integration?.snippets.iframe ?? embedFor(selected!)}
                                />

                                <div className="p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
                                    <p>
                                        Direct link:{' '}
                                        <a
                                            href={integration?.snippets.link ?? `${origin}${selected?.url ?? ''}`}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="text-blue-600 dark:text-blue-400 underline font-mono"
                                        >
                                            {integration?.snippets.link ?? `${origin}${selected?.url ?? ''}`}
                                        </a>
                                    </p>
                                    {integration?.auth_mode === 'public' && (
                                        <p className="mt-2">
                                            This deployment is <strong>public</strong> — anyone with the link can chat, and
                                            every message costs model tokens. Tighten <span className="font-mono">REQUESTS_PER_MINUTE</span>{' '}
                                            and pin a cheap model before sharing it.
                                        </p>
                                    )}
                                    <p className="mt-2">
                                        Sessions, theming, custom pages and cross-domain setup are covered in{' '}
                                        <span className="font-mono">docs/integration.md</span>.
                                    </p>
                                </div>
                            </>
                        )}
                    </div>
                )}

                {activeTab === 'api' && (
                    <div className="flex flex-col gap-4">
                        <span className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
                            Talk to your workflow programmatically. Create a session, then post messages to it.
                            Full API reference is at{' '}
                            <a href="/docs" target="_blank" rel="noreferrer" className="text-blue-600 dark:text-blue-400 underline">
                                {origin}/docs
                            </a>
                            .
                        </span>
                        <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">cURL example</span>
                            <CopyButton text={apiSnippet} label="Copy cURL" />
                        </div>
                        <pre className="p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs font-mono text-gray-800 dark:text-gray-200 overflow-x-auto leading-relaxed">
                            {apiSnippet}
                        </pre>
                    </div>
                )}
            </div>
        </div>
    );
};
