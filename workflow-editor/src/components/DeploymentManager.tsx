import React, { useEffect, useMemo, useState } from 'react';
import { Copy, Check, ExternalLink, RefreshCw } from 'lucide-react';
import { Toolbar, MoreMenu } from './shell/Toolbar';
import { ActivityCapsule } from './shell/ActivityCapsule';
import { StatusGlyph } from './shell/StatusGlyph';
import { useUiStore } from '../stores/uiStore';
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

const CopyButton: React.FC<{ text: string; label?: string }> = ({ text, label = 'Copy' }) => {
    const [copied, setCopied] = useState(false);
    return (
        <button
            onClick={() => {
                navigator.clipboard.writeText(text);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            }}
            className="btn btn-sm"
        >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? 'Copied' : label}
        </button>
    );
};

const SnippetBlock: React.FC<{ title: string; hint: string; code: string }> = ({ title, hint, code }) => (
    <div className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
                <div className="headline">{title}</div>
                <p className="hint mt-0.5">{hint}</p>
            </div>
            {code && <CopyButton text={code} />}
        </div>
        <pre className="well mono overflow-x-auto p-4 leading-relaxed" style={{ color: 'var(--text)' }}>
            {code || 'Loading…'}
        </pre>
    </div>
);

export const DeploymentManager: React.FC = () => {
    const go = useUiStore((state) => state.go);
    const { currentWorkflowId } = useWorkflowStore();
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

    const TABS: Array<{ id: typeof activeTab; label: string }> = [
        { id: 'deployments', label: 'Live pages' },
        { id: 'embed', label: 'Integrate' },
        { id: 'api', label: 'REST API' },
    ];

    const noneYet = (
        <div className="panel empty-state">
            <div className="headline">No deployments yet</div>
            <p className="hint max-w-[380px]">Open a workflow in the Studio, then use Deploy in the Builder to publish it as a chat page.</p>
            <button type="button" className="btn mt-2" onClick={() => go('studio')}>Open the Studio</button>
        </div>
    );

    return (
        <>
            <div className="page">
                <div className="page-inner">
                    <div className="page-head">
                        <div>
                            <h1 className="display">Deployments</h1>
                            <p className="lead mt-1 max-w-[680px]">
                                Every workflow you publish becomes a chat page at <span className="mono !text-[13px]">/d/&lt;name&gt;/</span>.
                                Embed it with one script tag, an iframe, or the REST API.
                            </p>
                        </div>
                        <div className="segmented" role="tablist" aria-label="View">
                            {TABS.map((tab) => (
                                <button key={tab.id} type="button" role="tab" aria-selected={activeTab === tab.id} onClick={() => setActiveTab(tab.id)}>
                                    {tab.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {activeTab === 'deployments' && (deployments.length === 0 ? <div className="mt-5">{noneYet}</div> : (
                        <div className="split-layout">
                            <div className="table-box">
                                <table className="mtable">
                                    <thead>
                                        <tr><th>Page</th><th className="hide-narrow">Workflow</th><th className="hide-narrow">Model</th><th>Published</th><th>Status</th></tr>
                                    </thead>
                                    <tbody
                                        onKeyDown={(event) => {
                                            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
                                            event.preventDefault();
                                            const index = deployments.findIndex((d) => d.id === selected?.id);
                                            const next = deployments[Math.max(0, Math.min(deployments.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))];
                                            if (next) {
                                                setSelectedId(next.id);
                                                (event.currentTarget.querySelector(`[data-row="${next.id}"]`) as HTMLElement | null)?.focus();
                                            }
                                        }}
                                    >
                                        {deployments.map((deployment) => (
                                            <tr key={deployment.id} aria-selected={deployment.id === selected?.id} onClick={() => setSelectedId(deployment.id)}>
                                                <td style={{ maxWidth: 0, width: '34%' }}>
                                                    <button type="button" className="row-title" data-row={deployment.id} onFocus={() => setSelectedId(deployment.id)}>{deployment.title}</button>
                                                    <span className="row-sub mono">{deployment.url}</span>
                                                </td>
                                                <td className="mono hide-narrow">{deployment.workflow_id}</td>
                                                <td className="mono hide-narrow">{deployment.model_id || 'Default'}</td>
                                                <td>{new Date(deployment.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</td>
                                                <td>
                                                    <span className="row-status">
                                                        <StatusGlyph shape={deployment.status === 'active' ? 'ok' : 'bad'} />
                                                        {deployment.status === 'active' ? 'Live' : deployment.status}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {selected && (
                                <aside className="inspector">
                                    <div>
                                        <h2 className="title-2">{selected.title}</h2>
                                        <div className="mono text-dim mt-0.5">{selected.url}</div>
                                    </div>
                                    <div className="inspector-status">
                                        <StatusGlyph shape={selected.status === 'active' ? 'ok' : 'bad'} />
                                        {selected.status === 'active' ? 'Live' : selected.status}
                                        <span className="hint font-normal">· {selected.auth_mode === 'public' ? 'anyone with the link' : selected.auth_mode}</span>
                                    </div>
                                    {selected.greeting && (
                                        <p className="text-muted pl-3 text-[13px]" style={{ boxShadow: 'inset 2px 0 0 var(--line-strong)' }}>“{selected.greeting}”</p>
                                    )}
                                    <div>
                                        <a className="btn btn-primary" href={selected.url} target="_blank" rel="noreferrer">
                                            <ExternalLink size={13} /> Open page
                                        </a>
                                    </div>
                                    <div className="rows">
                                        <div><span className="row-k">Workflow</span><span className="row-v mono">{selected.workflow_id}</span></div>
                                        {selected.trigger_id && <div><span className="row-k">Trigger</span><span className="row-v mono">{selected.trigger_id}</span></div>}
                                        <div><span className="row-k">Model</span><span className="row-v mono">{selected.model_id || 'Default'}</span></div>
                                        {selected.theme && <div><span className="row-k">Theme</span><span className="row-v">{selected.theme.replace(/^./, (c) => c.toUpperCase())}</span></div>}
                                    </div>
                                    <div className="flex flex-col gap-2">
                                        <span className="h-section">Embed</span>
                                        <pre className="well mono overflow-x-auto whitespace-pre-wrap p-3 !text-[11px] leading-[1.55]" style={{ color: 'var(--muted)', wordBreak: 'break-all' }}>
                                            {integration?.snippets.widget ?? embedFor(selected)}
                                        </pre>
                                        <div className="flex items-center gap-1.5">
                                            <CopyButton text={integration?.snippets.widget ?? embedFor(selected)} label="Copy" />
                                            <button type="button" className="btn btn-sm" onClick={() => setActiveTab('embed')}>More ways</button>
                                            <span className="flex-1" />
                                            <button
                                                type="button"
                                                className="btn btn-danger btn-sm"
                                                onClick={() => { if (confirm(`Unpublish ${selected.title}? The page stops working for everyone.`)) void deleteDeployment(selected.id); }}
                                            >
                                                Unpublish
                                            </button>
                                        </div>
                                    </div>
                                </aside>
                            )}
                        </div>
                    ))}

                    {activeTab === 'embed' && (deployments.length === 0 ? <div className="mt-5">{noneYet}</div> : (
                        <div className="mt-5 flex max-w-[880px] flex-col gap-6">
                            <label className="flex max-w-[480px] items-center gap-3">
                                <span className="field-label !mb-0 shrink-0">Deployment</span>
                                <select value={selected?.id ?? ''} onChange={(event) => setSelectedId(event.target.value)} className="select">
                                    {deployments.map((deployment) => (
                                        <option key={deployment.id} value={deployment.id}>{deployment.title} — {deployment.url}</option>
                                    ))}
                                </select>
                            </label>

                            {integrationError && <p className="text-[12px]" style={{ color: 'var(--clay)' }}>{integrationError}</p>}

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

                            <div className="panel flex flex-col gap-2 p-4 text-[12.5px]" style={{ color: 'var(--muted)' }}>
                                <p>
                                    Direct link:{' '}
                                    <a href={integration?.snippets.link ?? `${origin}${selected?.url ?? ''}`} target="_blank" rel="noreferrer" className="mono">
                                        {integration?.snippets.link ?? `${origin}${selected?.url ?? ''}`}
                                    </a>
                                </p>
                                {integration?.auth_mode === 'public' && (
                                    <p>
                                        This deployment is <strong style={{ color: 'var(--text)' }}>public</strong>: anyone with the link can chat, and
                                        every message costs model tokens. Tighten <span className="mono">REQUESTS_PER_MINUTE</span> and pin a cheap model before sharing it.
                                    </p>
                                )}
                                <p>Sessions, theming, custom pages and cross-domain setup are covered in <span className="mono">docs/integration.md</span>.</p>
                            </div>
                        </div>
                    ))}

                    {activeTab === 'api' && (
                        <div className="mt-5 flex max-w-[880px] flex-col gap-4">
                            <p className="lead">
                                Talk to a workflow from your own code: create a session, then post messages to it. The full reference is at{' '}
                                <a href="/docs" target="_blank" rel="noreferrer">{origin}/docs</a>.
                            </p>
                            <SnippetBlock title="cURL" hint="Replace the session id with the one the first call returns." code={apiSnippet} />
                        </div>
                    )}
                </div>
            </div>
            <Toolbar
                center={<ActivityCapsule onStatusClick={() => go('studio')} />}
                actions={
                    <>
                        <button type="button" className="btn btn-toolbar btn-icon" onClick={refresh} aria-label="Refresh" title="Refresh">
                            <RefreshCw size={15} strokeWidth={1.8} className={refreshing ? 'animate-spin' : ''} />
                        </button>
                        <MoreMenu />
                    </>
                }
            />
        </>
    );
};
