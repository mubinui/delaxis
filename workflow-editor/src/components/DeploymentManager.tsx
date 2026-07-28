import React, { useEffect, useState } from 'react';
import { Rocket, Code, Copy, Check, Terminal, Layers, X, ExternalLink, Trash2, RefreshCw } from 'lucide-react';
import { useWorkflowStore } from '../stores/workflowStore';
import { useLibraryStore } from '../stores/libraryStore';
import type { DeploymentConfig } from '../api/backendTypes';

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

export const DeploymentManager: React.FC<DeploymentManagerProps> = ({ onClose }) => {
    const { workflowName, currentWorkflowId } = useWorkflowStore();
    const { deployments, fetchOperationsData, deleteDeployment } = useLibraryStore();
    const [activeTab, setActiveTab] = useState<'deployments' | 'embed' | 'api'>('deployments');
    const [refreshing, setRefreshing] = useState(false);

    useEffect(() => {
        void fetchOperationsData().catch(() => undefined);
    }, [fetchOperationsData]);

    const origin = window.location.origin;
    const workflowId = currentWorkflowId || 'demo_multi_agent';

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
                            <span className="font-mono"> /d/&lt;name&gt;/</span>. Embed it anywhere with an
                            iframe, or call the REST API directly.
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
                        <Code className="w-4 h-4" /> Embed Widget
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
                    <div className="flex flex-col gap-3">
                        {deployments.length === 0 ? (
                            <div className="p-8 rounded-xl border border-dashed border-gray-300 dark:border-slate-700 text-center">
                                <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">No deployments yet</p>
                                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                    Flash Deploy a workflow first — the embed snippet appears here once a chatbot is live.
                                </p>
                            </div>
                        ) : (
                            <>
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                                        Paste this iframe into any page to embed a deployed chatbot.
                                    </span>
                                    <CopyButton text={embedFor(deployments[0])} label="Copy snippet" />
                                </div>
                                <pre className="p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs font-mono text-gray-800 dark:text-gray-200 overflow-x-auto leading-relaxed">
                                    {embedFor(deployments[0])}
                                </pre>
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                    The page is served by this Open Agent Kit instance — make it reachable from wherever you embed it.
                                </p>
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
