import React, { useEffect, useState } from 'react';
import { X, Trash2, Save, ChevronDown, ChevronRight, Check, Activity, ArrowLeftRight, FlaskConical, Gauge, Settings2, Cpu, Wrench, Layers, Mail, Server, BookmarkPlus, ExternalLink } from 'lucide-react';
import { useStoreWithEqualityFn } from 'zustand/traditional';
import { useShallow } from 'zustand/react/shallow';
import { useWorkflowStore } from '../stores/workflowStore';
import { useLibraryStore } from '../stores/libraryStore';
import { InspectorTabs } from './studio/InspectorTabs';
import { StatusBadge } from './studio/StatusBadge';
import { DataPreview } from './studio/DataPreview';
import { getAgentSummary, getToolSummary } from '../utils/studioDerivedState';
import { api } from '../api/client';
import type { FieldSpec } from '../constants/agentOptions';
import { AGENT_SETTING_FIELDS, AGENT_TYPES, HUMAN_INPUT_MODES, LLM_PARAM_FIELDS, fieldsForProvider, unsupportedFields } from '../constants/agentOptions';

interface GmailStatus {
    configured: boolean;
    connected: boolean;
    accounts: Array<{ account_email: string }>;
}

// CrewAI & Model Definitions
export const PropertiesPanel = () => {
    // Custom equality (not just useShallow) because a node being *dragged* gets a new
    // object reference every frame via applyNodeChanges (position updates), even while
    // its `data`/`type`/`id` stay referentially the same. Comparing on those three only
    // means this panel — and its many form fields — no longer re-renders on every
    // mousemove while the currently-selected node is being moved around the canvas.
    const selectedNode = useStoreWithEqualityFn(
        useWorkflowStore,
        (state) => state.nodes.find((n) => n.selected),
        (a, b) => a?.id === b?.id && a?.type === b?.type && a?.data === b?.data,
    );
    const { updateNodeData, onNodesChange } = useWorkflowStore(
        useShallow((state) => ({
            updateNodeData: state.updateNodeData,
            onNodesChange: state.onNodesChange,
        })),
    );
    const isNodeDragging = useWorkflowStore((state) => state.isNodeDragging);
    const { savedTools, executeTool, saveItem, updateItem, providers, fetchProviderModels } = useLibraryStore();
    const [liveModels, setLiveModels] = useState<Record<string, string[]>>({});
    const [capabilities, setCapabilities] = useState<Record<string, any>>({});
    const [loadingModels, setLoadingModels] = useState(false);

    // Integration state (gmail tools)
    const [gmailStatus, setGmailStatus] = useState<GmailStatus | null>(null);
    const [gmailConnecting, setGmailConnecting] = useState(false);
    // MCP inspection + library persistence state
    const [mcpInspection, setMcpInspection] = useState<string>('');
    const [isInspecting, setIsInspecting] = useState(false);
    const [librarySaveState, setLibrarySaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

    const refreshGmailStatus = async () => {
        try {
            const status = await api<GmailStatus>('/api/v1/integrations/gmail/status');
            setGmailStatus(status);
            return status;
        } catch {
            setGmailStatus(null);
            return null;
        }
    };

    // Core State
    const [label, setLabel] = useState('');
    const [description, setDescription] = useState('');

    // Dynamic Configuration State
    const [config, setConfig] = useState<Record<string, any>>({});

    // UI State
    const [activeSection, setActiveSection] = useState<string>('basic');
    const [activeInspectorTab, setActiveInspectorTab] = useState('overview');
    const [testArgs, setTestArgs] = useState('{\n  "input": "hello"\n}');
    const [testResult, setTestResult] = useState('');
    const [isTesting, setIsTesting] = useState(false);

    // Sync state when selection changes
    useEffect(() => {
        if (selectedNode) {
            setLabel((selectedNode.data?.label as string) || '');
            setDescription((selectedNode.data?.description as string) || '');
            const initialConfig = (selectedNode.data?.config as Record<string, any>) || {};
            if (!initialConfig.tools) initialConfig.tools = [];
            setConfig(initialConfig);
            setActiveInspectorTab('overview');
            setTestResult('');
            setMcpInspection('');
            setLibrarySaveState('idle');
            if (initialConfig.type === 'gmail') {
                refreshGmailStatus();
            }
        }
    }, [selectedNode?.id]);

    // Which sampling fields are worth showing depends on the route that will
    // actually run. Must sit above the early return — hooks cannot be conditional.
    const activeProviderId = config.model_config?.provider_id || config.llm_config?.provider_id || '';
    useEffect(() => {
        if (!activeProviderId || capabilities[activeProviderId]) return;
        let cancelled = false;
        api<any>(`/api/v1/api-providers/${activeProviderId}/capabilities`)
            .then((caps) => {
                if (!cancelled) setCapabilities((prev) => ({ ...prev, [activeProviderId]: caps }));
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, [activeProviderId, capabilities]);

    // Stay out of the way while a node is mid-drag: the inspector only appears once the
    // drag is released, so moving a component never opens or resizes UI around it.
    if (!selectedNode || isNodeDragging) return null;

    const handleSave = () => {
        if (selectedNode) {
            updateNodeData(selectedNode.id, {
                label,
                description,
                config
            });
        }
    };

    const updateConfig = (key: string, value: any) => {
        setConfig(prev => ({ ...prev, [key]: value }));
    };

    const updateNestedConfig = (parent: string, key: string, value: any) => {
        setConfig(prev => ({
            ...prev,
            [parent]: {
                ...prev[parent],
                [key]: value
            }
        }));
    };

    const toggleTool = (toolName: string) => {
        const currentTools = config.tools || [];
        if (currentTools.includes(toolName)) {
            updateConfig('tools', currentTools.filter((t: string) => t !== toolName));
        } else {
            updateConfig('tools', [...currentTools, toolName]);
        }
    };

    const handleDelete = () => {
        if (selectedNode) {
            // @ts-ignore
            onNodesChange([{ id: selectedNode.id, type: 'remove' }]);
        }
    };

    // --- New tool-type integrations -------------------------------------------

    const connectGmail = async () => {
        setGmailConnecting(true);
        try {
            const { auth_url } = await api<{ auth_url: string }>('/api/v1/integrations/gmail/auth-url');
            window.open(auth_url, '_blank', 'noopener,width=520,height=680');
            // Poll until the callback lands (or give up after ~2 minutes).
            for (let attempt = 0; attempt < 40; attempt++) {
                await new Promise((resolve) => setTimeout(resolve, 3000));
                const status = await refreshGmailStatus();
                if (status?.connected) {
                    // Convenience: adopt the first connected account if none typed yet.
                    if (!config.account_email && status.accounts[0]) {
                        updateConfig('account_email', status.accounts[0].account_email);
                    }
                    break;
                }
            }
        } catch (error) {
            setGmailStatus(null);
            console.error('Gmail connect failed', error);
        } finally {
            setGmailConnecting(false);
        }
    };

    const inspectMcpServer = async () => {
        setIsInspecting(true);
        setMcpInspection('');
        try {
            const result = await api<{ status: string; latency_ms: number; tools: Array<{ name: string; description: string }> }>(
                '/api/v1/tools/mcp/inspect',
                { method: 'POST', body: JSON.stringify({ settings: config }) },
            );
            const lines = result.tools.map((t) => `• ${t.name}`).join('\n');
            setMcpInspection(`Connected in ${result.latency_ms}ms — ${result.tools.length} tools:\n${lines}`);
        } catch (error) {
            setMcpInspection(`Connection failed: ${(error as Error).message}`);
        } finally {
            setIsInspecting(false);
        }
    };

    const saveToolToLibrary = async () => {
        const toolName = String(config.name || label || 'untitled_tool');
        const toolId = String(config.id || toolName).toLowerCase().replace(/[^a-z0-9_]+/g, '_');
        setLibrarySaveState('saving');
        try {
            const item = {
                id: toolId,
                name: toolName,
                description: description || `${config.type} tool`,
                config: { ...config, id: toolId, name: toolName },
            };
            const exists = savedTools.some((t) => t.id === toolId || t.name === toolName);
            if (exists) {
                await updateItem('tool', toolId, item);
            } else {
                await saveItem('tool', item);
            }
            updateConfig('id', toolId);
            setLibrarySaveState('saved');
            setTimeout(() => setLibrarySaveState('idle'), 2500);
        } catch (error) {
            console.error('Save to library failed', error);
            setLibrarySaveState('error');
            setTimeout(() => setLibrarySaveState('idle'), 4000);
        }
    };

    const runToolTest = async () => {
        const toolId = String(config.id || config.name || selectedNode.data?.label || '');
        if (!toolId) return;
        setIsTesting(true);
        setTestResult('');
        try {
            const parsedArgs = JSON.parse(testArgs || '{}');
            const result = await executeTool(toolId, parsedArgs);
            setTestResult(JSON.stringify(result, null, 2));
        } catch (error) {
            setTestResult((error as Error).message);
        } finally {
            setIsTesting(false);
        }
    };

    const renderStudioSummary = () => {
        if (selectedNode.type === 'agent') {
            const summary = getAgentSummary(config);
            return (
                <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-gradient-to-b from-white to-slate-50/50 dark:from-slate-900/60 dark:to-slate-950/40 p-4 shadow-xs">
                    <div className="mb-3.5 flex items-start justify-between gap-3">
                        <div>
                            <div className="text-xs font-black text-slate-800 dark:text-slate-200 tracking-wide uppercase">Agent Diagnostics</div>
                            <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium mt-0.5">Strategy layer verification logic</div>
                        </div>
                        <StatusBadge tone={summary.health} label={summary.health === 'ready' ? 'Ready' : 'Needs setup'} />
                    </div>
                    <div className="grid grid-cols-2 gap-2.5 text-xs">
                        <div className="rounded-lg bg-white dark:bg-slate-900/80 border border-slate-100 dark:border-slate-800 p-2.5 shadow-2xs">
                            <div className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Strategy</div>
                            <div className="font-extrabold text-slate-700 dark:text-slate-300 mt-0.5 truncate">{summary.strategy}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900/80 border border-slate-100 dark:border-slate-800 p-2.5 shadow-2xs">
                            <div className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Engine</div>
                            <div className="font-extrabold text-slate-700 dark:text-slate-300 mt-0.5 truncate">{summary.model}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900/80 border border-slate-100 dark:border-slate-800 p-2.5 shadow-2xs">
                            <div className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Tool Cap</div>
                            <div className="font-extrabold text-blue-600 dark:text-blue-400 mt-0.5">{summary.toolCount} Hooked</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900/80 border border-slate-100 dark:border-slate-800 p-2.5 shadow-2xs">
                            <div className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Human Loop</div>
                            <div className="font-extrabold text-slate-700 dark:text-slate-300 mt-0.5 truncate">{summary.humanInput}</div>
                        </div>
                    </div>
                    {summary.issues.length > 0 && (
                        <div className="mt-3 text-[11px] font-medium bg-amber-50/80 dark:bg-amber-950/30 border border-amber-200/60 dark:border-amber-900/50 text-amber-800 dark:text-amber-400 rounded-lg p-2.5">
                            {summary.issues.join(' · ')}
                        </div>
                    )}
                </div>
            );
        }

        if (selectedNode.type === 'tool') {
            const summary = getToolSummary(config);
            return (
                <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-gradient-to-b from-white to-slate-50/50 dark:from-slate-900/60 dark:to-slate-950/40 p-4 shadow-xs">
                    <div className="mb-3.5 flex items-start justify-between gap-3">
                        <div>
                            <div className="text-xs font-black text-slate-800 dark:text-slate-200 tracking-wide uppercase">Tool Interface</div>
                            <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium mt-0.5">Connectivity protocol summary</div>
                        </div>
                        <StatusBadge tone={summary.health} label={summary.enabled ? 'Live Link' : 'Disabled'} />
                    </div>
                    <div className="space-y-2 text-xs">
                        <div className="flex items-center justify-between rounded-lg bg-white dark:bg-slate-900/80 border border-slate-100 dark:border-slate-800 p-2.5 shadow-2xs">
                            <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Type protocol</span>
                            <span className="font-extrabold text-slate-800 dark:text-slate-200 font-mono text-[11px]">{summary.type}</span>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-white dark:bg-slate-900/80 border border-slate-100 dark:border-slate-800 p-2.5 shadow-2xs">
                            <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Authentication</span>
                            <span className="font-extrabold text-slate-800 dark:text-slate-200 font-mono text-[11px]">{summary.auth}</span>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900/80 border border-slate-100 dark:border-slate-800 p-2.5 shadow-2xs">
                            <div className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Resolution Target</div>
                            <div className="truncate font-mono text-[11px] text-blue-600 dark:text-blue-400 font-bold mt-0.5">{summary.endpoint || 'Not configured'}</div>
                        </div>
                    </div>
                    {summary.issues.length > 0 && (
                        <div className="mt-3 text-[11px] font-medium bg-amber-50/80 dark:bg-amber-950/30 border border-amber-200/60 dark:border-amber-900/50 text-amber-800 dark:text-amber-400 rounded-lg p-2.5">
                            {summary.issues.join(' · ')}
                        </div>
                    )}
                </div>
            );
        }

        return (
            <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-slate-50/60 dark:bg-slate-900/40 p-4 text-xs text-slate-500 dark:text-slate-400 font-medium text-center">
                Configure pipeline bindings via the runtime sub-inspector.
            </div>
        );
    };

    const renderToolTest = () => (
        <div className="space-y-3">
            <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900/60 p-4 shadow-xs">
                <div className="mb-2.5 text-xs font-black text-slate-800 dark:text-slate-200 uppercase tracking-wide">Payload Harness Injection</div>
                <textarea
                    value={testArgs}
                    onChange={(event) => setTestArgs(event.target.value)}
                    className="min-h-28 w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 p-3 font-mono text-xs text-slate-900 dark:text-slate-100 focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 transition-all"
                />
                <button
                    onClick={runToolTest}
                    disabled={isTesting}
                    type="button"
                    className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-slate-900 dark:bg-slate-800 hover:bg-slate-800 dark:hover:bg-slate-700 py-2.5 text-xs font-bold text-white transition-all shadow-sm disabled:opacity-60"
                >
                    <FlaskConical size={14} className="text-blue-400" />
                    {isTesting ? 'Evaluating Sandboxed Hook...' : 'Trigger Sandbox Execution'}
                </button>
            </div>
            {testResult && (
                <div className="rounded-xl bg-slate-950 p-4 shadow-inner border border-slate-900">
                    <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2 flex items-center justify-between">
                        <span>Output Stream</span>
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                    </div>
                    <pre className="max-h-72 overflow-auto font-mono text-[11px] text-emerald-400 leading-normal">{testResult}</pre>
                </div>
            )}
        </div>
    );

    // --- Premium Glassmorphic Embedded Section Wrappers ---
    const renderSection = (title: string, id: string, children: React.ReactNode) => (
        <div className="border border-slate-200/80 dark:border-slate-800/80 rounded-xl overflow-hidden bg-white dark:bg-slate-900/40 shadow-2xs mb-3.5 transition-all">
            <button
                onClick={() => setActiveSection(activeSection === id ? '' : id)}
                type="button"
                className="w-full flex items-center justify-between px-3.5 py-3 bg-gradient-to-r from-slate-50/80 to-white dark:from-slate-900/80 dark:to-slate-900/30 hover:from-slate-100/50 dark:hover:from-slate-800/50 transition-all text-left border-b border-slate-100/60 dark:border-slate-800/60"
            >
                <span className="font-bold text-slate-800 dark:text-slate-200 text-xs tracking-wide uppercase">{title}</span>
                {activeSection === id ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronRight size={14} className="text-slate-400" />}
            </button>
            {activeSection === id && (
                <div className="p-4 space-y-4 bg-white dark:bg-slate-900/20">
                    {children}
                </div>
            )}
        </div>
    );

    const fieldCls = 'w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9';
    const labelCls = 'text-[10px] font-extrabold text-slate-500 uppercase tracking-wider';

    const renderModelConfig = () => {
        let providerId = config.model_config?.provider_id || config.llm_config?.provider_id || '';
        const modelName = config.model_config?.model || config.llm_config?.model || '';

        if (!providerId && modelName.includes('/')) {
            providerId = modelName.split('/')[0];
        }

        const llmProviders = providers.filter(p => p.type === 'llm' && p.enabled !== false);
        const selectedProvider = llmProviders.find(p => p.id === providerId);
        const configuredModels = (selectedProvider?.models ?? [])
            .map(m => String(m.name ?? ''))
            .filter(Boolean);
        const providerModels = liveModels[providerId] ?? configuredModels;
        const caps = capabilities[providerId];
        // Gate on the route that will actually run: a native SDK that isn't
        // installed falls back to the OpenAI-compatible route, which accepts a
        // different parameter set.
        const effectiveRoute = caps?.effective_provider;
        const samplingFields = fieldsForProvider(LLM_PARAM_FIELDS, effectiveRoute);
        const droppedFields = unsupportedFields(LLM_PARAM_FIELDS, effectiveRoute);
        const keyPresent = Boolean(selectedProvider?.api_key_masked);
        const keySource = String((selectedProvider as any)?.key_source ?? 'none');

        const loadLiveModels = async () => {
            if (!providerId) return;
            setLoadingModels(true);
            try {
                const result = await fetchProviderModels(providerId);
                const names = (result.models as Array<{ name: string }> | undefined)?.map(m => m.name) ?? [];
                setLiveModels(prev => ({ ...prev, [providerId]: names }));
            } catch {
                // Keep the configured list; the field stays free text either way
            } finally {
                setLoadingModels(false);
            }
        };

        const numberValue = (key: string) => {
            const raw = config.model_config?.[key];
            return raw === undefined || raw === null ? '' : String(raw);
        };
        const writeNumber = (key: string, raw: string) => {
            if (raw === '') { updateNestedConfig('model_config', key, undefined); return; }
            const parsed = Number(raw);
            if (!Number.isNaN(parsed)) updateNestedConfig('model_config', key, parsed);
        };

        const renderField = (spec: FieldSpec) => {
            if (spec.kind === 'toggle') {
                const checked = Boolean(config.model_config?.[spec.key]);
                return (
                    <label key={spec.key} className="flex items-start gap-2.5 cursor-pointer py-1">
                        <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => updateNestedConfig('model_config', spec.key, e.target.checked)}
                            className="mt-0.5 w-3.5 h-3.5 accent-blue-600"
                        />
                        <span className="min-w-0">
                            <span className="block text-[11px] font-bold text-slate-700 dark:text-slate-200">{spec.label}</span>
                            <span className="block text-[9px] text-slate-400 font-medium leading-relaxed">{spec.help}</span>
                        </span>
                    </label>
                );
            }
            if (spec.kind === 'slider') {
                const value = config.model_config?.[spec.key] ?? config.llm_config?.[spec.key];
                return (
                    <div key={spec.key} className="space-y-1.5 pt-1">
                        <div className="flex justify-between items-center">
                            <label className={labelCls}>{spec.label}</label>
                            <span className="text-[11px] font-mono font-bold bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-sky-400 px-1.5 rounded border border-blue-100 dark:border-blue-900/40">
                                {value ?? '—'}
                            </span>
                        </div>
                        <input
                            type="range"
                            min={spec.min} max={spec.max} step={spec.step}
                            value={value ?? spec.min ?? 0}
                            onChange={(e) => updateNestedConfig('model_config', spec.key, parseFloat(e.target.value))}
                            className="w-full h-1.5 bg-slate-200 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-600"
                        />
                        <p className="text-[9px] text-slate-400 font-medium">{spec.help}</p>
                    </div>
                );
            }
            return (
                <div key={spec.key} className="space-y-1.5">
                    <label className={labelCls}>{spec.label}</label>
                    <input
                        type="number"
                        min={spec.min} max={spec.max}
                        value={numberValue(spec.key)}
                        onChange={(e) => writeNumber(spec.key, e.target.value)}
                        placeholder={spec.placeholder}
                        className={fieldCls}
                    />
                    <p className="text-[9px] text-slate-400 font-medium">{spec.help}</p>
                </div>
            );
        };

        return (
            <>
                {renderSection('Model', 'model_config', (
                    <div className="space-y-4">
                        <div className="space-y-1.5">
                            <label className={labelCls}>Provider</label>
                            <select
                                value={providerId}
                                onChange={(e) => updateNestedConfig('model_config', 'provider_id', e.target.value)}
                                className={fieldCls}
                            >
                                <option value="">Select a provider...</option>
                                {llmProviders.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                {providerId && !selectedProvider && <option value={providerId}>{providerId}</option>}
                            </select>
                        </div>

                        <div className="space-y-1.5">
                            <div className="flex items-center justify-between">
                                <label className={labelCls}>Model</label>
                                <button
                                    type="button"
                                    onClick={loadLiveModels}
                                    disabled={!providerId || loadingModels}
                                    className="text-[10px] font-bold text-blue-600 dark:text-blue-400 disabled:opacity-40 hover:underline"
                                >
                                    {loadingModels ? 'Loading…' : 'Refresh models'}
                                </button>
                            </div>
                            <input
                                type="text"
                                list="delaxis-provider-models"
                                value={modelName}
                                onChange={(e) => updateNestedConfig('model_config', 'model', e.target.value)}
                                className={fieldCls}
                                placeholder={providerModels[0] || 'model id'}
                            />
                            <datalist id="delaxis-provider-models">
                                {providerModels.map(name => <option key={name} value={name} />)}
                            </datalist>
                        </div>

                        {/* Key status. Paste goes to the gitignored secret store,
                            never to the tracked provider config. */}
                        {providerId && (
                            <div className="space-y-1.5">
                                <label className={labelCls}>API key</label>
                                <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${keyPresent
                                    ? 'border-emerald-200 dark:border-emerald-900/60 bg-emerald-50/60 dark:bg-emerald-950/30'
                                    : 'border-amber-200 dark:border-amber-900/60 bg-amber-50/60 dark:bg-amber-950/30'}`}>
                                    <span className={`text-[10px] font-bold ${keyPresent ? 'text-emerald-700 dark:text-emerald-400' : 'text-amber-800 dark:text-amber-400'}`}>
                                        {keyPresent
                                            ? (keySource === 'env'
                                                ? `Using ${selectedProvider?.api_key_env ?? 'environment key'}`
                                                : 'Key saved for this provider')
                                            : `No key — set ${selectedProvider?.api_key_env ?? 'an API key'}`}
                                    </span>
                                </div>
                                <p className="text-[9px] text-slate-400 font-medium">
                                    Manage keys under Library → Providers. Deployments use the environment key.
                                </p>
                            </div>
                        )}

                        {droppedFields.length > 0 && (
                            <p className="text-[9px] text-slate-400 font-medium">
                                {effectiveRoute} ignores: {droppedFields.join(', ')} — hidden below.
                            </p>
                        )}

                        {samplingFields.map(renderField)}

                        <details className="pt-1">
                            <summary className="cursor-pointer text-[10px] font-bold text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
                                Advanced
                            </summary>
                            <div className="space-y-3 pt-2.5">
                                <div className="space-y-1.5">
                                    <label className={labelCls}>Base URL override</label>
                                    <input
                                        type="text"
                                        value={config.model_config?.base_url || ''}
                                        onChange={(e) => updateNestedConfig('model_config', 'base_url', e.target.value)}
                                        className={`${fieldCls} font-mono`}
                                        placeholder={selectedProvider?.base_url || 'provider default'}
                                    />
                                    <p className="text-[9px] text-slate-400 font-medium">Only needed for a self-hosted or custom endpoint.</p>
                                </div>
                                <div className="space-y-1.5">
                                    <label className={labelCls}>API key env var</label>
                                    <input
                                        type="text"
                                        value={config.model_config?.api_key_env || ''}
                                        onChange={(e) => updateNestedConfig('model_config', 'api_key_env', e.target.value)}
                                        className={`${fieldCls} font-mono`}
                                        placeholder={selectedProvider?.api_key_env || 'provider default'}
                                    />
                                    <p className="text-[9px] text-slate-400 font-medium">Override which variable this agent reads its key from.</p>
                                </div>
                            </div>
                        </details>
                    </div>
                ))}

                {renderSection('Agent limits', 'agent_limits', (
                    <div className="space-y-4">
                        {AGENT_SETTING_FIELDS.map(renderField)}
                    </div>
                ))}
            </>
        );
    };

    const renderToolsSelector = () => {
        const assignedTools = config.tools || [];
        return renderSection('Tool Chain Attachments', 'tools_selector', (
            <div className="space-y-3">
                <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">Toggle capability slots visible to parent node logic:</div>
                <div className="max-h-48 overflow-y-auto space-y-1.5 border border-slate-200/60 dark:border-slate-800/60 rounded-xl p-2.5 bg-slate-50/40 dark:bg-slate-950/40">
                    {savedTools.map(tool => {
                        const isSelected = assignedTools.includes(tool.name);
                        return (
                            <div
                                key={tool.id}
                                onClick={() => toggleTool(tool.name)}
                                className={`flex items-center gap-2.5 p-2 rounded-lg cursor-pointer transition-all text-xs select-none
                                    ${isSelected ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 border border-blue-600/40 font-bold shadow-2xs' : 'hover:bg-white dark:hover:bg-slate-900 text-slate-600 dark:text-slate-400 font-medium border border-transparent'}`}
                            >
                                <div className={`w-4 h-4 rounded flex items-center justify-center border shrink-0 transition-colors ${isSelected ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700'}`}>
                                    {isSelected && <Check size={10} strokeWidth={3} />}
                                </div>
                                <span className="truncate">{tool.name}</span>
                            </div>
                        );
                    })}
                    {savedTools.length === 0 && (
                        <div className="text-xs text-slate-400 font-medium text-center py-4">Registry completely void. Define sub-blocks first.</div>
                    )}
                </div>
            </div>
        ));
    };

    const renderAgentConfig = () => {
        const agentType = config.type || 'LlmAgent';
        const isLlmAgent = agentType === 'LlmAgent' || agentType === 'ReasoningAgent' || agentType === 'conversable';

        return (
            <>
                {renderSection('Strategy Role Specs', 'agent_settings', (
                    <>
                        <div className="space-y-1.5">
                            <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Executor Base Strategy</label>
                            <select
                                value={config.type || 'LlmAgent'}
                                onChange={(e) => updateConfig('type', e.target.value)}
                                className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                            >
                                {AGENT_TYPES.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                            </select>
                        </div>

                        <div className="space-y-1.5">
                            <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Output State Variable Key</label>
                            <input
                                type="text"
                                value={config.output_key || ''}
                                onChange={(e) => updateConfig('output_key', e.target.value)}
                                className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                placeholder="e.g. summarized_analysis"
                            />
                            <p className="text-[9px] text-slate-400 font-medium">Binds computed stream output into standard state cache dictionary.</p>
                        </div>

                        <div className="flex items-center justify-between p-2.5 bg-slate-50 dark:bg-slate-950/40 rounded-lg border border-slate-200/80 dark:border-slate-800/80">
                            <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Router Switch Subagent</span>
                            <input
                                type="checkbox"
                                checked={config.is_selector || false}
                                onChange={(e) => updateConfig('is_selector', e.target.checked)}
                                className="accent-blue-600 w-4 h-4 rounded text-blue-600 focus:ring-blue-500"
                            />
                        </div>

                        {agentType === 'LoopAgent' && (
                            <div className="space-y-1.5">
                                <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Cyclic Upper Bounds</label>
                                <input
                                    type="number"
                                    value={config.loop_config?.max_loops || 5}
                                    onChange={(e) => updateNestedConfig('loop_config', 'max_loops', parseInt(e.target.value) || 1)}
                                    className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                />
                            </div>
                        )}

                        {(isLlmAgent || config.is_selector) && (
                            <div className="space-y-1.5">
                                <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">System Directives / Behavioral Boundaries</label>
                                <textarea
                                    value={config.instruction || config.system_message || ''}
                                    onChange={(e) => {
                                        updateConfig('instruction', e.target.value);
                                        updateConfig('system_message', e.target.value);
                                    }}
                                    className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all min-h-[140px] leading-relaxed"
                                    placeholder="Define objective criteria, operational personas, constraints, and explicit formatted formats..."
                                />
                            </div>
                        )}

                        <div className="space-y-1.5">
                            <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Human Overrule Interruption Mode</label>
                            <select
                                value={config.human_input_mode || 'NEVER'}
                                onChange={(e) => updateConfig('human_input_mode', e.target.value)}
                                className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                            >
                                {HUMAN_INPUT_MODES.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                            </select>
                        </div>
                    </>
                ))}
            </>
        );
    };

    const renderTriggerConfig = () => {
        const triggerType = config.trigger_type || 'manual';

        return (
            <>
                {renderSection('Trigger Handlers', 'trigger_settings', (
                    <>
                        <div className="space-y-1.5">
                            <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Entry Interface</label>
                            <select
                                value={triggerType}
                                onChange={(e) => updateConfig('trigger_type', e.target.value)}
                                className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                            >
                                <option value="manual">Manual Push Trigger</option>
                                <option value="chat">Conversational State Catch</option>
                                <option value="webhook">RESTful Webhook Receiver</option>
                            </select>
                        </div>

                        {triggerType === 'webhook' && (
                            <>
                                <div className="space-y-1.5">
                                    <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Public Webhook URL String</label>
                                    <input
                                        type="text"
                                        value={config.public_slug || ''}
                                        onChange={(e) => updateConfig('public_slug', e.target.value)}
                                        className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                        placeholder="customer-support-ingest"
                                    />
                                    <p className="text-[9px] text-slate-400 font-mono">Hook: /api/v1/webhooks/{config.public_slug || '{slug}'}</p>
                                </div>
                                <div className="space-y-1.5">
                                    <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">JSON Pointer Extraction Map</label>
                                    <textarea
                                        value={config.input_mapping_text || JSON.stringify(config.input_mapping || { message: '$.message' }, null, 2)}
                                        onChange={(e) => updateConfig('input_mapping_text', e.target.value)}
                                        className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all min-h-[90px]"
                                    />
                                </div>
                            </>
                        )}

                        {(triggerType === 'chat' || triggerType === 'webhook') && (
                            <>
                                <div className="space-y-1.5">
                                    <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Session Token Filter</label>
                                    <select
                                        value={config.auth_mode || 'public'}
                                        onChange={(e) => updateConfig('auth_mode', e.target.value)}
                                        className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                    >
                                        <option value="public">Fully Permissive</option>
                                        <option value="api_key">Shared Application Key Check</option>
                                        <option value="jwt">JSON Web Token Signing Proof</option>
                                    </select>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Provider</label>
                                        <input
                                            type="text"
                                            value={config.provider_id || 'openrouter'}
                                            onChange={(e) => updateConfig('provider_id', e.target.value)}
                                            className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Fallback Model</label>
                                        <input
                                            type="text"
                                            value={config.model_id || 'openai/gpt-4o'}
                                            onChange={(e) => updateConfig('model_id', e.target.value)}
                                            className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                        />
                                    </div>
                                </div>
                                <div className="space-y-1.5">
                                    <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Initial Greeting Header</label>
                                    <textarea
                                        value={config.greeting || 'Hi, how can I help?'}
                                        onChange={(e) => updateConfig('greeting', e.target.value)}
                                        className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all min-h-[70px]"
                                    />
                                </div>
                            </>
                        )}

                        <div className="space-y-1.5">
                            <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Downstream Cascade Execution Slug</label>
                            <input
                                type="text"
                                value={config.workflow_id || ''}
                                onChange={(e) => updateConfig('workflow_id', e.target.value)}
                                className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                placeholder="e.g. main_orchestration"
                            />
                        </div>
                    </>
                ))}
            </>
        );
    };

    /** Memory Store and Knowledge Source are tool nodes bound to typed agent
     *  handles rather than callable tools, so they get their own fields instead
     *  of the protocol picker — which used to show them as "Python Function". */
    const renderAttachmentConfig = () => {
        if (config.type === 'memory') {
            return renderSection('Memory Store', 'tool_details', (
                <div className="space-y-4">
                    <div className="space-y-1.5">
                        <label className={labelCls}>Retention</label>
                        <select
                            value={config.retention || 'session'}
                            onChange={(e) => updateConfig('retention', e.target.value)}
                            className={fieldCls}
                        >
                            <option value="session">Session — cleared when the chat ends</option>
                            <option value="persistent">Persistent — kept across sessions</option>
                        </select>
                    </div>
                    <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
                        Attach to an agent&apos;s <strong>memory</strong> handle. Without this node the
                        workflow saves with memory off.
                    </p>
                </div>
            ));
        }

        return renderSection('Knowledge Source', 'tool_details', (
            <div className="space-y-4">
                <div className="space-y-1.5">
                    <label className={labelCls}>Collections (comma-separated)</label>
                    <input
                        type="text"
                        value={(config.collections || []).join(', ')}
                        onChange={(e) =>
                            updateConfig(
                                'collections',
                                e.target.value.split(',').map((v) => v.trim()).filter(Boolean),
                            )
                        }
                        className={`${fieldCls} font-mono`}
                        placeholder="handbook, product_docs"
                    />
                </div>
                <div className="space-y-1.5">
                    <label className={labelCls}>Passages per query (top_k)</label>
                    <input
                        type="number"
                        min={1}
                        max={50}
                        value={config.top_k ?? 5}
                        onChange={(e) => updateConfig('top_k', Number(e.target.value))}
                        className={fieldCls}
                    />
                </div>
                <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
                    The agent gets a <code>search_knowledge</code> tool pinned to these collections.
                    Needs <code>RAG_PIPELINE_ENABLED=true</code>; with no collection named, no search
                    tool is created.
                </p>
            </div>
        ));
    };

    /** Flow Router and Guardrail both live on `router` nodes and had no
     *  inspector at all, so their settings could never be edited. */
    const renderRouterConfig = () => {
        if (config.type === 'guardrail') {
            return renderSection('Guardrail', 'router_details', (
                <div className="space-y-4">
                    <div className="space-y-1.5">
                        <label className={labelCls}>Output schema</label>
                        <select
                            value={config.output_schema || 'text'}
                            onChange={(e) => updateConfig('output_schema', e.target.value)}
                            className={fieldCls}
                        >
                            <option value="text">Text — reject an empty answer</option>
                            <option value="json">JSON — the answer must parse as JSON</option>
                        </select>
                    </div>
                    <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-300">
                        <input
                            type="checkbox"
                            checked={Boolean(config.human_review)}
                            onChange={(e) => updateConfig('human_review', e.target.checked)}
                            className="h-3.5 w-3.5 rounded border-slate-300 dark:border-slate-700"
                        />
                        Flag the result for human review
                    </label>
                    <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
                        Checks the <strong>final</strong> output wherever this node sits, and makes the
                        agent retry twice when it does not conform. Remove the node to turn guardrails
                        off.
                    </p>
                </div>
            ));
        }

        return renderSection('Flow Router', 'router_details', (
            <div className="space-y-4">
                <div className="space-y-1.5">
                    <label className={labelCls}>Routing mode</label>
                    <select
                        value={config.routing_mode || 'conditional'}
                        onChange={(e) => updateConfig('routing_mode', e.target.value)}
                        className={fieldCls}
                    >
                        <option value="conditional">Conditional — the upstream agent picks a branch</option>
                        <option value="broadcast">Broadcast — every branch receives the result</option>
                    </select>
                </div>
                <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
                    On save the router is compiled into direct connections and the agent feeding it is
                    marked a router, so it can delegate to the branches. Wire it to at least two agents
                    — with one it is just a hand-off.
                </p>
            </div>
        ));
    };

    const renderToolConfig = () => (
        <>
            {renderSection('Protocol Payload Parameters', 'tool_details', (
                <>
                    <div className="space-y-1.5">
                        <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Interface Mechanism</label>
                        <select
                            value={config.type || 'function'}
                            onChange={(e) => updateConfig('type', e.target.value)}
                            className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                        >
                            <option value="function">Python Function</option>
                            <option value="api">REST API</option>
                            <option value="mcp">MCP Server</option>
                            <option value="database">Database (NL2SQL)</option>
                            <option value="gmail">Gmail</option>
                        </select>
                    </div>

                    {config.type === 'function' && (
                        <div className="space-y-1.5">
                            <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Target Resolution Import Path</label>
                            <input
                                type="text"
                                value={config.entrypoint || ''}
                                onChange={(e) => updateConfig('entrypoint', e.target.value)}
                                className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                placeholder="package.module:function_name"
                            />
                        </div>
                    )}

                    {config.type === 'api' && (
                        <div className="space-y-4">
                            <div className="space-y-1.5">
                                <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Endpoint URL String</label>
                                <input
                                    type="text"
                                    value={config.api_url || ''}
                                    onChange={(e) => updateConfig('api_url', e.target.value)}
                                    className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                    placeholder="https://api.example.com/v1/data"
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1.5">
                                    <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Verb</label>
                                    <select
                                        value={config.http_method || 'GET'}
                                        onChange={(e) => updateConfig('http_method', e.target.value)}
                                        className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                    >
                                        <option>GET</option>
                                        <option>POST</option>
                                        <option>PUT</option>
                                        <option>DELETE</option>
                                    </select>
                                </div>
                                <div className="space-y-1.5">
                                    <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Negotiation Token</label>
                                    <select
                                        value={config.auth_type || 'none'}
                                        onChange={(e) => updateConfig('auth_type', e.target.value)}
                                        className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                    >
                                        <option value="none">Public</option>
                                        <option value="bearer">Bearer Auth</option>
                                        <option value="api_key">API Custom Header</option>
                                    </select>
                                </div>
                            </div>
                        </div>
                    )}

                    {config.type === 'mcp' && renderMcpConfig()}
                    {config.type === 'database' && renderDatabaseConfig()}
                    {config.type === 'gmail' && renderGmailConfig()}

                    {['mcp', 'database', 'gmail'].includes(config.type) && (
                        <button
                            onClick={saveToolToLibrary}
                            disabled={librarySaveState === 'saving'}
                            type="button"
                            className="flex w-full items-center justify-center gap-2 rounded-xl border border-blue-500/40 py-2.5 text-xs font-bold text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30 transition-all disabled:opacity-60"
                        >
                            <BookmarkPlus size={14} />
                            {librarySaveState === 'saving' ? 'Saving to library…'
                                : librarySaveState === 'saved' ? 'Saved — attachable to agents'
                                    : librarySaveState === 'error' ? 'Save failed — check backend'
                                        : 'Save to Library (registers on backend)'}
                        </button>
                    )}
                </>
            ))}
        </>
    );

    function renderMcpConfig() {
        const transport = config.transport || 'stdio';
        return (
            <div className="space-y-4">
                <div className="space-y-1.5">
                    <label className={labelCls}>Transport</label>
                    <select value={transport} onChange={(e) => updateConfig('transport', e.target.value)} className={fieldCls}>
                        <option value="stdio">stdio (local command)</option>
                        <option value="sse">SSE (remote URL)</option>
                        <option value="streamable-http">Streamable HTTP (remote URL)</option>
                    </select>
                </div>

                {transport === 'stdio' ? (
                    <>
                        <div className="space-y-1.5">
                            <label className={labelCls}>Command</label>
                            <input type="text" value={config.command || ''} onChange={(e) => updateConfig('command', e.target.value)} className={`${fieldCls} font-mono`} placeholder="npx" />
                        </div>
                        <div className="space-y-1.5">
                            <label className={labelCls}>Arguments (space-separated)</label>
                            <input
                                type="text"
                                value={(config.args || []).join(' ')}
                                onChange={(e) => updateConfig('args', e.target.value.split(/\s+/).filter(Boolean))}
                                className={`${fieldCls} font-mono`}
                                placeholder="-y @modelcontextprotocol/server-filesystem /tmp"
                            />
                        </div>
                    </>
                ) : (
                    <>
                        <div className="space-y-1.5">
                            <label className={labelCls}>Server URL</label>
                            <input type="text" value={config.url || ''} onChange={(e) => updateConfig('url', e.target.value)} className={`${fieldCls} font-mono`} placeholder="https://mcp.example.com/sse" />
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-1.5">
                                <label className={labelCls}>Auth</label>
                                <select value={config.auth_type || 'none'} onChange={(e) => updateConfig('auth_type', e.target.value)} className={fieldCls}>
                                    <option value="none">None</option>
                                    <option value="bearer">Bearer token</option>
                                </select>
                            </div>
                            {config.auth_type === 'bearer' && (
                                <div className="space-y-1.5">
                                    <label className={labelCls}>Token env var</label>
                                    <input type="text" value={config.auth_env_var || ''} onChange={(e) => updateConfig('auth_env_var', e.target.value)} className={`${fieldCls} font-mono`} placeholder="MY_MCP_TOKEN" />
                                </div>
                            )}
                        </div>
                    </>
                )}

                <div className="space-y-1.5">
                    <label className={labelCls}>Tool filter (comma-separated, empty = all)</label>
                    <input
                        type="text"
                        value={(config.tool_filter || []).join(', ')}
                        onChange={(e) => updateConfig('tool_filter', e.target.value.split(',').map((t) => t.trim()).filter(Boolean))}
                        className={`${fieldCls} font-mono`}
                        placeholder="read_file, list_directory"
                    />
                </div>

                <button
                    onClick={inspectMcpServer}
                    disabled={isInspecting}
                    type="button"
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-slate-900 dark:bg-slate-800 hover:bg-slate-800 dark:hover:bg-slate-700 py-2.5 text-xs font-bold text-white transition-all disabled:opacity-60"
                >
                    <Server size={14} className="text-blue-400" />
                    {isInspecting ? 'Connecting to server…' : 'Inspect Server (list tools)'}
                </button>
                {mcpInspection && (
                    <pre className="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-[11px] text-emerald-400 leading-relaxed whitespace-pre-wrap">{mcpInspection}</pre>
                )}
            </div>
        );
    }

    function renderDatabaseConfig() {
        const useEnvVar = config.db_uri_env_var !== undefined && config.db_uri === undefined
            ? true
            : Boolean(config.db_uri_env_var) || !config.db_uri;
        return (
            <div className="space-y-4">
                <div className="space-y-1.5">
                    <label className={labelCls}>Connection source</label>
                    <select
                        value={useEnvVar ? 'env' : 'inline'}
                        onChange={(e) => {
                            if (e.target.value === 'env') {
                                setConfig((prev) => ({ ...prev, db_uri: undefined, db_uri_env_var: prev.db_uri_env_var || '' }));
                            } else {
                                setConfig((prev) => ({ ...prev, db_uri_env_var: undefined, db_uri: prev.db_uri || '' }));
                            }
                        }}
                        className={fieldCls}
                    >
                        <option value="env">Environment variable (for URIs with credentials)</option>
                        <option value="inline">Inline URI (credential-free, e.g. SQLite)</option>
                    </select>
                </div>

                {useEnvVar ? (
                    <div className="space-y-1.5">
                        <label className={labelCls}>Env var holding the SQLAlchemy URI</label>
                        <input type="text" value={config.db_uri_env_var || ''} onChange={(e) => updateConfig('db_uri_env_var', e.target.value)} className={`${fieldCls} font-mono`} placeholder="SALES_DB_URI" />
                        <p className="text-[9px] text-slate-400 font-medium">e.g. SALES_DB_URI=postgresql://user:pass@host:5432/sales in the backend .env</p>
                    </div>
                ) : (
                    <div className="space-y-1.5">
                        <label className={labelCls}>Database URI (no embedded credentials)</label>
                        <input type="text" value={config.db_uri || ''} onChange={(e) => updateConfig('db_uri', e.target.value)} className={`${fieldCls} font-mono`} placeholder="sqlite:///./data/demo.db" />
                    </div>
                )}

                <div className="space-y-1.5">
                    <label className={labelCls}>Table allowlist (comma-separated, empty = all)</label>
                    <input
                        type="text"
                        value={(config.tables || []).join(', ')}
                        onChange={(e) => updateConfig('tables', e.target.value.split(',').map((t) => t.trim()).filter(Boolean))}
                        className={`${fieldCls} font-mono`}
                        placeholder="orders, customers"
                    />
                </div>

                <div className="flex items-center justify-between p-2.5 bg-slate-50 dark:bg-slate-950/40 rounded-lg border border-slate-200/80 dark:border-slate-800/80">
                    <div>
                        <span className="text-xs font-bold text-slate-700 dark:text-slate-300 block">Allow write operations (DML)</span>
                        <span className="text-[9px] text-slate-400">Off = read-only SELECT queries only (recommended)</span>
                    </div>
                    <input
                        type="checkbox"
                        checked={config.allow_dml || false}
                        onChange={(e) => updateConfig('allow_dml', e.target.checked)}
                        className="accent-blue-600 w-4 h-4 rounded"
                    />
                </div>
            </div>
        );
    }

    function renderGmailConfig() {
        const connectedAccounts = gmailStatus?.accounts ?? [];
        const isAccountConnected = connectedAccounts.some((a) => a.account_email === config.account_email);
        const capabilities: string[] = config.capabilities || ['send', 'search', 'read'];
        const toggleCapability = (cap: string) => {
            const next = capabilities.includes(cap) ? capabilities.filter((c) => c !== cap) : [...capabilities, cap];
            if (next.length > 0) updateConfig('capabilities', next);
        };

        return (
            <div className="space-y-4">
                {/* Connection state */}
                <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-slate-50/60 dark:bg-slate-900/40 p-3 space-y-2.5">
                    <div className="flex items-center justify-between">
                        <span className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Google account</span>
                        {gmailStatus === null ? (
                            <StatusBadge tone="muted" label="Status unknown" compact />
                        ) : !gmailStatus.configured ? (
                            <StatusBadge tone="error" label="Not configured" compact />
                        ) : isAccountConnected ? (
                            <StatusBadge tone="ready" label="Connected" compact />
                        ) : (
                            <StatusBadge tone="warning" label="Not connected" compact />
                        )}
                    </div>

                    {gmailStatus !== null && !gmailStatus.configured ? (
                        <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
                            Set <code className="font-mono">GOOGLE_OAUTH_CLIENT_ID</code>, <code className="font-mono">GOOGLE_OAUTH_CLIENT_SECRET</code> and{' '}
                            <code className="font-mono">ENCRYPTION_KEY</code> in the backend .env, then restart the API.
                        </p>
                    ) : (
                        <button
                            onClick={connectGmail}
                            disabled={gmailConnecting}
                            type="button"
                            className="flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] py-2 text-xs font-bold text-white transition-all disabled:opacity-60"
                        >
                            <Mail size={13} />
                            {gmailConnecting ? 'Waiting for Google consent…' : isAccountConnected ? 'Reconnect account' : 'Connect Gmail'}
                            <ExternalLink size={11} />
                        </button>
                    )}

                    {connectedAccounts.length > 0 && (
                        <div className="space-y-1">
                            {connectedAccounts.map((account) => (
                                <button
                                    key={account.account_email}
                                    onClick={() => updateConfig('account_email', account.account_email)}
                                    type="button"
                                    className={`w-full truncate rounded-lg border px-2.5 py-1.5 text-left text-[11px] font-mono transition-colors ${config.account_email === account.account_email
                                        ? 'border-blue-500/50 bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-400'
                                        : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                                        }`}
                                >
                                    {account.account_email}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                <div className="space-y-1.5">
                    <label className={labelCls}>Account email</label>
                    <input type="text" value={config.account_email || ''} onChange={(e) => updateConfig('account_email', e.target.value)} className={`${fieldCls} font-mono`} placeholder="support@yourdomain.com" />
                </div>

                <div className="space-y-1.5">
                    <label className={labelCls}>Capabilities</label>
                    <div className="flex gap-2">
                        {['send', 'search', 'read'].map((cap) => (
                            <button
                                key={cap}
                                onClick={() => toggleCapability(cap)}
                                type="button"
                                className={`flex-1 rounded-lg border py-2 text-xs font-bold capitalize transition-colors ${capabilities.includes(cap)
                                    ? 'border-blue-500/50 bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-400'
                                    : 'border-slate-200 dark:border-slate-800 text-slate-400 dark:text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-900'
                                    }`}
                            >
                                {cap}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="space-y-1.5">
                    <label className={labelCls}>Max search results</label>
                    <input type="number" value={config.max_results || 10} onChange={(e) => updateConfig('max_results', parseInt(e.target.value) || 10)} className={fieldCls} />
                </div>
            </div>
        );
    }

    return (
        <div className="w-[400px] shrink-0 h-full bg-white dark:bg-[#0b111b] border-l border-[var(--color-ui-border)] shadow-xl flex flex-col antialiased animate-in slide-in-from-right duration-200">
            {/* Docked Inspector Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-slate-800 bg-gradient-to-r from-slate-50/60 to-white dark:from-[#0f1723]/80 dark:to-[#0b111b] shrink-0">
                <div className="flex items-center gap-2.5">
                    <div className="p-1.5 bg-blue-600 text-white rounded-lg shadow-2xs">
                        <Settings2 size={15} />
                    </div>
                    <div>
                        <h3 className="font-extrabold text-slate-800 dark:text-slate-200 text-xs tracking-wide uppercase">Node Parameters</h3>
                        <div className="flex items-center gap-2 mt-0.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse"></span>
                            <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 font-mono uppercase tracking-wider">
                                Type: {selectedNode.type}
                            </span>
                        </div>
                    </div>
                </div>
                <button
                    onClick={() => {
                        // @ts-ignore
                        onNodesChange([{ id: selectedNode.id, type: 'select', selected: false }]);
                    }}
                    type="button"
                    className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/60 p-1.5 rounded-xl transition-all"
                >
                    <X size={15} />
                </button>
            </div>

            {/* Seamless Tab Strips & Field Scrollable View */}
            <div className="p-5 overflow-y-auto flex-1 custom-scrollbar min-h-0 space-y-4">
                <InspectorTabs
                    activeTab={activeInspectorTab}
                    onChange={setActiveInspectorTab}
                    tabs={[
                        { id: 'overview', label: 'Overview', icon: Activity },
                        { id: 'model', label: 'Model', icon: Cpu, disabled: selectedNode.type !== 'agent' },
                        { id: 'tools', label: selectedNode.type === 'tool' || selectedNode.type === 'router' ? 'Config' : 'Tools', icon: Wrench, disabled: selectedNode.type === 'trigger' },
                        { id: 'runtime', label: 'Runtime', icon: Layers },
                        { id: 'data', label: 'Data', icon: ArrowLeftRight, disabled: selectedNode.type !== 'agent' && selectedNode.type !== 'tool' },
                        {
                            id: 'test',
                            label: 'Test',
                            icon: Gauge,
                            // Nothing to invoke on a terminator, a router, or an
                            // attachment node — they have no callable surface.
                            disabled:
                                selectedNode.type === 'output' ||
                                selectedNode.type === 'router' ||
                                (selectedNode.type === 'tool' && ['memory', 'knowledge'].includes(config.type)),
                        },
                    ]}
                />

                {/* Core Overview Diagnostics */}
                {activeInspectorTab === 'overview' && (
                    <div className="space-y-4 animate-in fade-in duration-200">
                        {renderStudioSummary()}

                        <div className="space-y-4 rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900/40 p-4 shadow-2xs">
                            <div className="text-xs font-black text-slate-800 dark:text-slate-200 tracking-wide uppercase mb-1">Canvas Identifiers</div>
                            <div className="space-y-1.5">
                                <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Label Title</label>
                                <input
                                    type="text"
                                    value={label}
                                    onChange={(e) => setLabel(e.target.value)}
                                    onBlur={handleSave}
                                    className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-bold text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all h-9"
                                />
                            </div>

                            <div className="space-y-1.5">
                                <label className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Semantic Description Note</label>
                                <textarea
                                    value={description}
                                    onChange={(e) => setDescription(e.target.value)}
                                    onBlur={handleSave}
                                    className="w-full px-3 py-2 bg-slate-50/50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-medium text-slate-700 dark:text-slate-300 resize-y min-h-[60px] focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900 transition-all leading-relaxed"
                                />
                            </div>
                        </div>
                    </div>
                )}

                {/* Switchable Inspectors */}
                <div className="space-y-4 animate-in fade-in duration-200">
                    {selectedNode.type === 'agent' && activeInspectorTab === 'model' && renderModelConfig()}
                    {selectedNode.type === 'agent' && activeInspectorTab === 'tools' && renderToolsSelector()}
                    {selectedNode.type === 'agent' && activeInspectorTab === 'runtime' && renderAgentConfig()}
                    {selectedNode.type === 'tool' && activeInspectorTab === 'tools' && (
                        ['memory', 'knowledge'].includes(config.type) ? renderAttachmentConfig() : renderToolConfig()
                    )}
                    {selectedNode.type === 'tool' && activeInspectorTab === 'test' && !['memory', 'knowledge'].includes(config.type) && renderToolTest()}
                    {selectedNode.type === 'trigger' && activeInspectorTab === 'runtime' && renderTriggerConfig()}
                    {selectedNode.type === 'router' && (activeInspectorTab === 'tools' || activeInspectorTab === 'runtime') && renderRouterConfig()}

                    {activeInspectorTab === 'data' && (selectedNode.type === 'agent' || selectedNode.type === 'tool') && (
                        <div className="space-y-4">
                            <div className="space-y-2 rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900/40 p-4 shadow-2xs">
                                <div className="flex items-center justify-between">
                                    <div className="text-xs font-black text-emerald-700 dark:text-emerald-400 tracking-wide uppercase">Input</div>
                                    {selectedNode.data.lastInput && (
                                        <span className="text-[9px] font-semibold text-slate-400 dark:text-slate-500">
                                            {new Date(selectedNode.data.lastInput.timestamp).toLocaleTimeString()}
                                        </span>
                                    )}
                                </div>
                                <DataPreview
                                    value={selectedNode.data.lastInput?.data}
                                    emptyMessage="No run data yet — press Run Live in the Execution timeline to populate."
                                />
                            </div>
                            <div className="space-y-2 rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900/40 p-4 shadow-2xs">
                                <div className="flex items-center justify-between">
                                    <div className="text-xs font-black text-sky-700 dark:text-sky-400 tracking-wide uppercase">Output</div>
                                    {selectedNode.data.lastOutput && (
                                        <span className="text-[9px] font-semibold text-slate-400 dark:text-slate-500">
                                            {new Date(selectedNode.data.lastOutput.timestamp).toLocaleTimeString()}
                                        </span>
                                    )}
                                </div>
                                <DataPreview
                                    value={selectedNode.data.lastOutput?.data}
                                    emptyMessage="No run data yet — press Run Live in the Execution timeline to populate."
                                />
                            </div>
                        </div>
                    )}
                    
                    {activeInspectorTab === 'test' && selectedNode.type === 'agent' && (
                        <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-slate-50/60 dark:bg-slate-900/40 p-4 text-xs text-slate-500 dark:text-slate-400 font-medium text-center">
                            Trigger full canvas traversal from control playback hub to track agent-level sequential reasoning outputs.
                        </div>
                    )}
                    {activeInspectorTab === 'test' && selectedNode.type === 'trigger' && (
                        <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-slate-50/60 dark:bg-slate-900/40 p-4 text-xs text-slate-500 dark:text-slate-400 font-medium text-center">
                            Trigger hooks can be activated directly via interactive testing push endpoints.
                        </div>
                    )}
                    {activeInspectorTab !== 'overview' && selectedNode.type === 'output' && (
                        <div className="rounded-xl border border-slate-200/80 dark:border-slate-800/80 bg-slate-50/60 dark:bg-slate-900/40 p-4 text-xs text-slate-500 dark:text-slate-400 font-medium text-center">
                            Terminal node. Imposes hard pipeline exit blocks upon data pipeline traversal success.
                        </div>
                    )}
                </div>
            </div>

            {/* Bottom Actions Controls */}
            <div className="p-4 border-t border-slate-100 dark:border-slate-800 bg-slate-50/30 dark:bg-slate-950/30 flex gap-3 shrink-0">
                <button
                    onClick={handleDelete}
                    type="button"
                    className="flex-1 flex items-center justify-center gap-1.5 py-2.5 bg-white dark:bg-slate-900 border border-red-200 dark:border-red-900/40 text-red-600 dark:text-red-400 rounded-xl text-xs font-bold hover:bg-red-50/60 dark:hover:bg-red-950/30 transition-all shadow-2xs"
                >
                    <Trash2 size={13} />
                    Unlink
                </button>
                <button
                    onClick={handleSave}
                    type="button"
                    className="flex-[2] flex items-center justify-center gap-1.5 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-500 shadow-sm transition-all"
                >
                    <Save size={13} />
                    Persist Payload Specs
                </button>
            </div>
        </div>
    );
};
