import React, { useState, useEffect } from 'react';
import { X, Plus, Trash2, Wrench, Bot, Save, Loader2, Download, ChevronDown, ChevronRight, Globe, Code, Zap, Cpu, Settings2, Library, SlidersHorizontal, Key, FileJson, Search, FunctionSquare, MessageSquareText, ServerCog, Database, Check } from 'lucide-react';
import { useLibraryStore } from '../stores/libraryStore';
import type { LibraryItem, ItemType } from '../stores/libraryStore';
import { SwaggerImportModal } from './SwaggerImportModal';
import { AGENT_TYPES, HUMAN_INPUT_MODES } from '../constants/agentOptions';
import { LibraryStore, toStoreEntries } from './studio/LibraryStore';
import type { StoreEntry } from './studio/LibraryStore';

// --- Shared Constants (Matched with PropertiesPanel.tsx) ---
interface LibraryModalProps {
    isOpen: boolean;
    onClose: () => void;
    initialTab?: ResourceTab;
}

type ResourceTab = 'browse' | 'tools' | 'agents' | 'functions' | 'prompts' | 'providers' | 'ops';

// --- Premium Reusable Structural Block: Section ---
const Section = ({ title, icon: Icon, children, defaultOpen = true, className = "" }: { title: string; icon: any; children: React.ReactNode; defaultOpen?: boolean; className?: string }) => {
    const [isOpen, setIsOpen] = useState(defaultOpen);
    return (
        <div className={`border border-slate-200/80 dark:border-slate-800/80 rounded-xl overflow-hidden bg-white dark:bg-slate-900 shadow-sm transition-all ${className}`}>
            <button
                onClick={() => setIsOpen(!isOpen)}
                type="button"
                className="w-full flex items-center justify-between px-4 py-3.5 bg-gradient-to-r from-slate-50 to-white hover:from-slate-100/70 hover:to-slate-50 dark:from-slate-900 dark:to-slate-900 dark:hover:from-slate-800/70 dark:hover:to-slate-800/70 transition-all text-left border-b border-slate-100 dark:border-slate-800"
            >
                <div className="flex items-center gap-3">
                    <div className="p-1.5 rounded-lg bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400">
                        <Icon size={15} />
                    </div>
                    <span className="font-bold text-slate-800 dark:text-slate-100 text-xs tracking-wide uppercase">{title}</span>
                </div>
                {isOpen ? <ChevronDown size={14} className="text-slate-400 dark:text-slate-500" /> : <ChevronRight size={14} className="text-slate-400 dark:text-slate-500" />}
            </button>
            {isOpen && (
                <div className="p-5 space-y-5">
                    {children}
                </div>
            )}
        </div>
    );
};

// --- Premium Reusable UI Component: FormInput ---
const FormInput = ({ label, placeholder, value, onChange, type = 'text', icon: Icon, mono = false, rows, disabled = false, helpText }: {
    label: string; placeholder?: string; value: string; onChange: (v: string) => void; type?: string; icon?: any; mono?: boolean; rows?: number; disabled?: boolean; helpText?: string;
}) => (
    <div className="space-y-1.5 w-full">
        <label className="text-xs font-bold text-slate-600 dark:text-slate-300 tracking-wide uppercase flex items-center gap-2">
            {Icon && <Icon size={13} className="text-blue-500" />}
            {label}
        </label>
        {rows ? (
            <textarea
                value={value}
                onChange={(e) => onChange(e.target.value)}
                rows={rows}
                disabled={disabled}
                className={`w-full px-3.5 py-2.5 bg-slate-50/50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-slate-800 dark:text-slate-200
                    focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900
                    transition-all resize-y disabled:bg-slate-100 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-500
                    placeholder:text-slate-400 dark:placeholder:text-slate-500 leading-relaxed
                    ${mono ? 'font-mono text-xs' : ''}`}
                placeholder={placeholder}
            />
        ) : (
            <div className="relative flex items-center">
                <input
                    type={type}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    disabled={disabled}
                    className={`w-full px-3.5 py-2 bg-slate-50/50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-slate-800 dark:text-slate-200
                        focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900
                        transition-all disabled:bg-slate-100 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-500 font-medium
                        placeholder:text-slate-400 dark:placeholder:text-slate-500 h-9
                        ${mono ? 'font-mono text-xs' : ''}`}
                    placeholder={placeholder}
                />
            </div>
        )}
        {helpText && <p className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">{helpText}</p>}
    </div>
);

// --- Premium Reusable UI Component: FormSelect ---
const FormSelect = ({ label, value, onChange, options, icon: Icon, helpText }: {
    label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; icon?: any; helpText?: string;
}) => (
    <div className="space-y-1.5 w-full">
        <label className="text-xs font-bold text-slate-600 dark:text-slate-300 tracking-wide uppercase flex items-center gap-2">
            {Icon && <Icon size={13} className="text-blue-500" />}
            {label}
        </label>
        <div className="relative flex items-center">
            <select
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="w-full pl-3.5 pr-8 py-2 bg-slate-50/50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-slate-800 dark:text-slate-200
                    focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 focus:bg-white dark:focus:bg-slate-900
                    transition-all appearance-none cursor-pointer font-medium h-9"
            >
                {options.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
            <div className="absolute right-3 pointer-events-none text-slate-400 dark:text-slate-500">
                <ChevronDown size={14} />
            </div>
        </div>
        {helpText && <p className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">{helpText}</p>}
    </div>
);

export const LibraryModal = ({ isOpen, onClose, initialTab = 'browse' }: LibraryModalProps) => {
    const {
        savedTools,
        savedAgents,
        savedWorkflows,
        functions,
        prompts,
        providers,
        ragConfig,
        ragCollections,
        health,
        metricsDashboard,
        saveItem,
        updateItem,
        deleteItem,
        createFunctionTool,
        getFunctionSource,
        deleteFunctionTool,
        savePrompt,
        deletePrompt,
        saveProvider,
        deleteProvider,
        testProvider,
        fetchOperationsData,
        isLoading,
        fetchLibraryItems,
    } = useLibraryStore();

    const [activeTab, setActiveTab] = useState<ResourceTab>(initialTab);
    const [editingItem, setEditingItem] = useState<LibraryItem | null>(null);
    const [isSwaggerModalOpen, setIsSwaggerModalOpen] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    const [functionForm, setFunctionForm] = useState({
        id: '',
        name: '',
        description: '',
        code: 'def my_tool(input_text: str) -> str:\n    return input_text\n',
    });

    const [promptForm, setPromptForm] = useState({
        id: '',
        name: '',
        description: '',
        template: '',
        variables: '',
        category: '',
    });

    const [providerForm, setProviderForm] = useState({
        id: '',
        name: '',
        type: 'llm',
        description: '',
        base_url: '',
        api_key: '',
        api_key_env: '',
        litellm_prefix: '',
        models: '',
        config: '{}',
    });

    // Form state - Generalized
    const [formData, setFormData] = useState({
        name: '',
        description: '',
        type: 'function',
        config: {} as Record<string, any>,
    });

    // Tool Config State
    const [toolConfig, setToolConfig] = useState({
        entrypoint: '',
        api_url: '',
        http_method: 'GET',
        auth_type: 'none',
        headers: '',
        body_template: '',
        response_path: '',
        // mcp
        transport: 'stdio',
        command: '',
        args: '',
        url: '',
        auth_env_var: '',
        tool_filter: '',
        // database
        db_source: 'env',
        db_uri: '',
        db_uri_env_var: '',
        tables: '',
        allow_dml: false,
        // gmail
        account_email: '',
        capabilities: 'send, search, read',
        max_results: '10',
    });

    // Agent Config State (Enhanced to match PropertiesPanel.tsx)
    const [agentConfig, setAgentConfig] = useState<{
        agentType: string;
        instruction: string;
        model: string;
        provider: string;
        temperature: number;
        base_url: string;
        api_key_env: string;
        max_tokens: number;
        output_key: string;
        is_selector: boolean;
        human_input_mode: string;
        max_loops: number;
        tools: string[];
    }>({
        agentType: 'LlmAgent',
        instruction: '',
        model: 'gpt-4o',
        provider: 'openai',
        temperature: 0.7,
        base_url: '',
        api_key_env: '',
        max_tokens: 2048,
        output_key: '',
        is_selector: false,
        human_input_mode: 'NEVER',
        max_loops: 5,
        tools: [],
    });

    useEffect(() => {
        if (isOpen) {
            fetchLibraryItems();
            fetchOperationsData();
        }
    }, [isOpen]);

    // Providers come from the backend registry so the studio and the runtime
    // always agree on which providers exist.
    const llmProviders = providers.filter(p => p.type === 'llm' && p.enabled !== false);
    const selectedAgentProvider = llmProviders.find(p => p.id === agentConfig.provider);
    const selectedAgentProviderModels = (selectedAgentProvider?.models ?? [])
        .map(m => String(m.name ?? ''))
        .filter(Boolean);
    const llmProviderOptions = [
        ...llmProviders.map(p => ({ value: p.id, label: p.name })),
        ...(agentConfig.provider && !selectedAgentProvider
            ? [{ value: agentConfig.provider, label: agentConfig.provider }]
            : []),
    ];

    const resetForm = () => {
        setFormData({ name: '', description: '', type: 'function', config: {} });
        setToolConfig({
            entrypoint: '', api_url: '', http_method: 'GET', auth_type: 'none', headers: '', body_template: '', response_path: '',
            transport: 'stdio', command: '', args: '', url: '', auth_env_var: '', tool_filter: '',
            db_source: 'env', db_uri: '', db_uri_env_var: '', tables: '', allow_dml: false,
            account_email: '', capabilities: 'send, search, read', max_results: '10',
        });
        setAgentConfig({
            agentType: 'LlmAgent', instruction: '', model: 'gpt-4o', provider: 'openai', temperature: 0.7,
            base_url: '', api_key_env: '', max_tokens: 2048, output_key: '', is_selector: false, human_input_mode: 'NEVER', max_loops: 5, tools: []
        });
        setEditingItem(null);
    };

    const handleEdit = (item: LibraryItem) => {
        setEditingItem(item);
        setFormData({
            name: item.name,
            description: item.description || '',
            type: item.type || 'function',
            config: item.config || {},
        });

        if (activeTab === 'tools') {
            setToolConfig({
                entrypoint: item.config?.entrypoint || '',
                api_url: item.config?.api_url || '',
                http_method: item.config?.http_method || 'GET',
                auth_type: item.config?.auth_type || 'none',
                headers: item.config?.headers || '',
                body_template: item.config?.body_template || '',
                response_path: item.config?.response_path || '',
                transport: item.config?.transport || 'stdio',
                command: item.config?.command || '',
                args: Array.isArray(item.config?.args) ? item.config.args.join(' ') : '',
                url: item.config?.url || '',
                auth_env_var: item.config?.auth_env_var || '',
                tool_filter: Array.isArray(item.config?.tool_filter) ? item.config.tool_filter.join(', ') : '',
                db_source: item.config?.db_uri_env_var ? 'env' : 'inline',
                db_uri: item.config?.db_uri || '',
                db_uri_env_var: item.config?.db_uri_env_var || '',
                tables: Array.isArray(item.config?.tables) ? item.config.tables.join(', ') : '',
                allow_dml: Boolean(item.config?.allow_dml),
                account_email: item.config?.account_email || '',
                capabilities: Array.isArray(item.config?.capabilities) ? item.config.capabilities.join(', ') : 'send, search, read',
                max_results: String(item.config?.max_results ?? 10),
            });
        } else {
            const config = item.config || {};
            const modelConfig = config.model_config || config.llm_config || {};

            setAgentConfig({
                agentType: config.type || item.type || 'LlmAgent',
                instruction: config.instruction || config.system_message || '',
                model: modelConfig.model || 'gpt-4o',
                provider: modelConfig.provider_id || 'openai',
                temperature: modelConfig.temperature ?? 0.7,
                base_url: modelConfig.base_url || '',
                api_key_env: modelConfig.api_key_env || '',
                max_tokens: modelConfig.max_tokens ?? 2048,
                output_key: config.output_key || '',
                is_selector: config.is_selector || false,
                human_input_mode: config.human_input_mode || 'NEVER',
                max_loops: config.loop_config?.max_loops ?? 5,
                tools: config.tools || [],
            });
        }
    };

    const handleDelete = async (item: LibraryItem) => {
        if (!confirm(`Are you sure you want to delete "${item.name}"?`)) return;
        try {
            await deleteItem(activeTab === 'tools' ? 'tool' : 'agent', item.id);
            if (editingItem?.id === item.id) resetForm();
        } catch (e) {
            alert('Failed to delete: ' + (e as Error).message);
        }
    };

    /** Open a store entry in the editor tab that can actually edit it. */
    const handleInspectEntry = (entry: StoreEntry) => {
        if (entry.kind === 'agent') {
            setActiveTab('agents');
        } else if (entry.kind === 'workflow') {
            // Workflows are edited on the canvas, not in this modal.
            onClose();
            return;
        } else {
            setActiveTab('tools');
        }
        handleEdit(entry.item);
    };

    const handleSave = async () => {
        if (!formData.name.trim()) {
            alert('Name is required');
            return;
        }

        const itemType: ItemType = activeTab === 'tools' ? 'tool' : 'agent';
        let config: Record<string, any> = {};
        let type = formData.type;

        if (activeTab === 'tools') {
            const splitList = (value: string, sep: RegExp) => value.split(sep).map((s) => s.trim()).filter(Boolean);
            if (formData.type === 'mcp') {
                config = {
                    type: 'mcp',
                    transport: toolConfig.transport,
                    ...(toolConfig.transport === 'stdio'
                        ? { command: toolConfig.command, args: splitList(toolConfig.args, /\s+/) }
                        : {
                            url: toolConfig.url,
                            auth_type: toolConfig.auth_env_var ? 'bearer' : 'none',
                            ...(toolConfig.auth_env_var ? { auth_env_var: toolConfig.auth_env_var } : {}),
                        }),
                    tool_filter: splitList(toolConfig.tool_filter, /,/),
                };
            } else if (formData.type === 'database') {
                config = {
                    type: 'database',
                    ...(toolConfig.db_source === 'env'
                        ? { db_uri_env_var: toolConfig.db_uri_env_var }
                        : { db_uri: toolConfig.db_uri }),
                    tables: splitList(toolConfig.tables, /,/),
                    allow_dml: toolConfig.allow_dml,
                };
            } else if (formData.type === 'gmail') {
                config = {
                    type: 'gmail',
                    account_email: toolConfig.account_email,
                    capabilities: splitList(toolConfig.capabilities, /,/),
                    max_results: parseInt(toolConfig.max_results) || 10,
                };
            } else {
                config = {
                    type: formData.type,
                    entrypoint: toolConfig.entrypoint,
                    api_url: toolConfig.api_url,
                    http_method: toolConfig.http_method,
                    auth_type: toolConfig.auth_type,
                    headers: toolConfig.headers,
                    body_template: toolConfig.body_template,
                    response_path: toolConfig.response_path,
                };
            }
        } else {
            type = agentConfig.agentType;
            config = {
                type: agentConfig.agentType,
                instruction: agentConfig.instruction,
                system_message: agentConfig.instruction,
                output_key: agentConfig.output_key,
                is_selector: agentConfig.is_selector,
                human_input_mode: agentConfig.human_input_mode,

                model_config: {
                    provider_id: agentConfig.provider,
                    model: agentConfig.model,
                    temperature: agentConfig.temperature,
                    base_url: agentConfig.base_url,
                    api_key_env: agentConfig.api_key_env,
                    max_tokens: agentConfig.max_tokens,
                },

                loop_config: agentConfig.agentType === 'LoopAgent' ? { max_loops: agentConfig.max_loops } : undefined,
                tools: agentConfig.tools,
            };
        }

        try {
            if (editingItem) {
                await updateItem(itemType, editingItem.id, {
                    name: formData.name, description: formData.description, type, config,
                });
            } else {
                await saveItem(itemType, {
                    name: formData.name, description: formData.description, type, config,
                });
            }
            resetForm();
            alert('Saved successfully!');
        } catch (e) {
            alert('Failed to save: ' + (e as Error).message);
        }
    };

    if (!isOpen) return null;

    const items = activeTab === 'tools' ? savedTools : activeTab === 'agents' ? savedAgents : [];
    const filteredItems = items.filter(i => i.name.toLowerCase().includes(searchQuery.toLowerCase()));

    const storeEntries = toStoreEntries(savedTools, savedAgents, savedWorkflows);

    // Browsing is the common case and editing is the exception, so Browse leads
    // and the per-type editors sit behind it.
    const resourceTabs: Array<{ id: ResourceTab; label: string; count?: number }> = [
        { id: 'browse', label: 'Browse', count: storeEntries.length },
        { id: 'tools', label: 'Tools', count: savedTools.length },
        { id: 'agents', label: 'Agents', count: savedAgents.length },
        { id: 'functions', label: 'Functions', count: functions.length },
        { id: 'prompts', label: 'Prompts', count: prompts.length },
        { id: 'providers', label: 'Providers', count: providers.length },
        { id: 'ops', label: 'Ops' },
    ];

    const handleCreateFunction = async () => {
        try {
            await createFunctionTool(functionForm);
            setFunctionForm({ id: '', name: '', description: '', code: 'def my_tool(input_text: str) -> str:\n    return input_text\n' });
            alert('Function tool created.');
        } catch (e) {
            alert('Failed to create function tool: ' + (e as Error).message);
        }
    };

    const handleViewFunctionSource = async (toolId: string) => {
        try {
            const result = await getFunctionSource(toolId);
            alert(result.source);
        } catch (e) {
            alert('Failed to load source: ' + (e as Error).message);
        }
    };

    const handleCreatePrompt = async () => {
        try {
            await savePrompt({
                id: promptForm.id,
                name: promptForm.name,
                description: promptForm.description,
                template: promptForm.template,
                variables: promptForm.variables.split(',').map((v) => v.trim()).filter(Boolean),
                category: promptForm.category || null,
            });
            setPromptForm({ id: '', name: '', description: '', template: '', variables: '', category: '' });
            alert('Prompt saved.');
        } catch (e) {
            alert('Failed to save prompt: ' + (e as Error).message);
        }
    };

    const handleCreateProvider = async () => {
        try {
            await saveProvider({
                id: providerForm.id,
                name: providerForm.name,
                type: providerForm.type,
                description: providerForm.description,
                base_url: providerForm.base_url || null,
                api_key: providerForm.api_key || undefined,
                api_key_env: providerForm.api_key_env || undefined,
                litellm_prefix: providerForm.litellm_prefix || undefined,
                models: providerForm.models
                    .split(/[\n,]/)
                    .map((m) => m.trim())
                    .filter(Boolean)
                    .map((name) => ({ name })),
                config: JSON.parse(providerForm.config || '{}'),
                enabled: true,
            });
            setProviderForm({ id: '', name: '', type: 'llm', description: '', base_url: '', api_key: '', api_key_env: '', litellm_prefix: '', models: '', config: '{}' });
            alert('Provider saved.');
        } catch (e) {
            alert('Failed to save provider: ' + (e as Error).message);
        }
    };

    return (
        <>
            <div className="fixed inset-0 bg-slate-950/60 backdrop-blur-md flex items-center justify-center z-[100] animate-in fade-in duration-200 p-4">
                <div className="bg-white dark:bg-[#0b111b] rounded-2xl shadow-2xl w-full max-w-6xl h-[88vh] flex flex-col overflow-hidden ring-1 ring-slate-900/10 dark:ring-white/10 antialiased">

                    {/* --- Elite Bespoke Workspace Banner --- */}
                    <div className="h-16 px-6 border-b border-slate-200/80 dark:border-slate-800/80 flex items-center justify-between bg-slate-50/50 dark:bg-slate-900/40 shrink-0 z-20 relative">
                        <div className="flex items-center gap-6">
                            <div className="flex items-center gap-2">
                                <div
                                    className="p-1.5 rounded-lg"
                                    style={{ backgroundColor: 'var(--accent)', color: 'var(--text-on-accent)' }}
                                >
                                    <Library size={16} />
                                </div>
                                <h2 className="dlx-text text-sm font-bold tracking-tight">Library</h2>
                            </div>

                            {/* Seamless Tab Controller Strip */}
                            <div className="flex bg-slate-200/60 dark:bg-slate-800/60 p-1 rounded-xl gap-0.5">
                                {resourceTabs.map((tab) => (
                                    <button
                                        key={tab.id}
                                        onClick={() => { setActiveTab(tab.id); resetForm(); }}
                                        type="button"
                                        className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all
                                            ${activeTab === tab.id
                                                ? 'bg-white dark:bg-slate-900 text-blue-600 shadow-sm'
                                                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white/40 dark:hover:bg-slate-800/40'
                                            }`}
                                    >
                                        {tab.label}
                                        {typeof tab.count === 'number' && (
                                            <span
                                                className="ml-1 rounded-full px-1.5 py-0.2 text-[9px] font-mono font-bold"
                                                style={activeTab === tab.id
                                                    ? { color: 'var(--accent-text)', backgroundColor: 'var(--accent-soft)' }
                                                    : { color: 'var(--text-secondary)', backgroundColor: 'var(--surface-sunken)' }}
                                            >
                                                {tab.count}
                                            </span>
                                        )}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <button onClick={onClose} type="button" className="p-2 text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-200/50 dark:hover:bg-slate-800/50 rounded-xl transition-all">
                            <X size={18} />
                        </button>
                    </div>

                    {/* --- Browse: the store view --- */}
                    {activeTab === 'browse' ? (
                        <div className="flex flex-1 overflow-hidden min-h-0">
                            <LibraryStore
                                entries={storeEntries}
                                onInspect={handleInspectEntry}
                                onManage={() => setActiveTab('tools')}
                            />
                        </div>
                    ) : (

                    /* --- Master-detail editor --- */
                    <div className="flex flex-1 overflow-hidden min-h-0">

                        {/* --- Active Resource Index Sidebar --- */}
                        <div className="w-80 border-r border-slate-200/80 dark:border-slate-800/80 flex flex-col bg-slate-50/30 dark:bg-slate-900/40">
                            <div className="p-4 border-b border-slate-100 dark:border-slate-800 shrink-0 space-y-3">
                                <button
                                    onClick={resetForm}
                                    type="button"
                                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-blue-600/10 hover:-translate-y-0.5"
                                >
                                    <Plus size={15} />
                                    New {activeTab === 'tools' ? 'tool' : 'agent'}
                                </button>

                                {activeTab === 'tools' && (
                                    <button
                                        onClick={() => setIsSwaggerModalOpen(true)}
                                        type="button"
                                        className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-white hover:bg-slate-50 dark:bg-slate-900 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-semibold transition-all border border-slate-200 dark:border-slate-700 shadow-sm"
                                    >
                                        <Download size={13} className="text-blue-500" />
                                        Import OpenAPI / Swagger
                                    </button>
                                )}

                                <div className="relative flex items-center">
                                    <Search size={13} className="absolute left-3 text-slate-400 dark:text-slate-500" />
                                    <input
                                        type="text"
                                        placeholder="Filter by name"
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        className="w-full pl-8 pr-3 py-2 bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-700/80 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-600 transition-all font-medium h-9"
                                    />
                                </div>
                            </div>

                            <div className="flex-1 overflow-y-auto p-3 space-y-2">
                                {filteredItems.length === 0 ? (
                                    <div className="text-center py-12 px-4">
                                        <div className="w-10 h-10 bg-slate-100 dark:bg-slate-800 rounded-xl flex items-center justify-center mx-auto mb-2 border border-slate-200 dark:border-slate-700">
                                            <Search size={16} className="text-slate-400 dark:text-slate-500" />
                                        </div>
                                        <p className="dlx-text-secondary text-xs font-bold">Nothing saved yet</p>
                                        <p className="dlx-faint mt-0.5 text-[11px]">Create one with the button above, or import from OpenAPI.</p>
                                    </div>
                                ) : (
                                    filteredItems.map(item => (
                                        <div
                                            key={item.id}
                                            onClick={() => handleEdit(item)}
                                            className={`p-3 rounded-xl cursor-pointer group transition-all border
                                                ${editingItem?.id === item.id
                                                    ? 'bg-blue-50/50 dark:bg-blue-950/30 border-blue-500/30 shadow-sm ring-1 ring-blue-500/10'
                                                    : 'bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 hover:border-slate-200 dark:hover:border-slate-700 hover:shadow-xs'}`}
                                        >
                                            <div className="flex items-start justify-between gap-2">
                                                <div className="min-w-0 flex-grow">
                                                    <div className={`font-bold text-xs truncate ${editingItem?.id === item.id ? 'text-blue-600' : 'text-slate-800 dark:text-slate-100'}`}>
                                                        {item.name}
                                                    </div>
                                                    <div className="flex items-center gap-1.5 mt-1">
                                                        <span className="h-1.5 w-1.5 rounded-full bg-slate-400 dark:bg-slate-500"></span>
                                                        <span className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 truncate font-mono tracking-wide uppercase">
                                                            {item.type}
                                                        </span>
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); handleDelete(item); }}
                                                    type="button"
                                                    className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 rounded-lg transition-all"
                                                >
                                                    <Trash2 size={13} />
                                                </button>
                                            </div>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>

                        {/* --- Configurator Right Workspace Detail Panel --- */}
                        <div className="flex-1 flex flex-col bg-white dark:bg-slate-900 relative overflow-hidden min-w-0">
                            {activeTab === 'functions' ? (
                                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                                    <Section title="Python Function Tools" icon={FunctionSquare}>
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Tool ID" value={functionForm.id} onChange={(v) => setFunctionForm({ ...functionForm, id: v })} placeholder="snake_case_tool_id" mono />
                                            <FormInput label="Function Name" value={functionForm.name} onChange={(v) => setFunctionForm({ ...functionForm, name: v })} placeholder="my_tool" mono />
                                        </div>
                                        <FormInput label="Description" value={functionForm.description} onChange={(v) => setFunctionForm({ ...functionForm, description: v })} rows={2} />
                                        <FormInput label="Python Source Implementation" value={functionForm.code} onChange={(v) => setFunctionForm({ ...functionForm, code: v })} rows={10} mono />
                                        <button onClick={handleCreateFunction} disabled={isLoading} type="button" className="px-5 py-2.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-bold transition-all shadow-sm">
                                            Compile Python Micro-Tool
                                        </button>
                                    </Section>
                                    <Section title="Active Python Native Functions" icon={Code}>
                                        <div className="space-y-2">
                                            {functions.map((fn) => (
                                                <div key={fn.id} className="flex items-center justify-between bg-slate-50/50 dark:bg-slate-900/40 border border-slate-200/80 dark:border-slate-800/80 rounded-xl p-3">
                                                    <div>
                                                        <div className="text-xs font-bold text-slate-800 dark:text-slate-100">{fn.name}</div>
                                                        <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400 mt-0.5">{fn.entrypoint}</div>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <button onClick={() => handleViewFunctionSource(fn.id)} type="button" className="px-3 py-1 text-xs font-semibold bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 rounded-lg shadow-2xs transition-all">Source</button>
                                                        <button onClick={() => deleteFunctionTool(fn.id)} type="button" className="px-3 py-1 text-xs font-semibold bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-100 dark:border-red-900/50 hover:border-red-200 dark:hover:border-red-800 rounded-lg transition-all">Revoke</button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </Section>
                                </div>
                            ) : activeTab === 'prompts' ? (
                                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                                    <Section title="Dynamic System Prompt Templates" icon={MessageSquareText}>
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Template Identifier" value={promptForm.id} onChange={(v) => setPromptForm({ ...promptForm, id: v })} mono />
                                            <FormInput label="Human Readable Title" value={promptForm.name} onChange={(v) => setPromptForm({ ...promptForm, name: v })} />
                                        </div>
                                        <FormInput label="Objective Summary" value={promptForm.description} onChange={(v) => setPromptForm({ ...promptForm, description: v })} rows={2} />
                                        <FormInput label="Raw Context Payload" value={promptForm.template} onChange={(v) => setPromptForm({ ...promptForm, template: v })} rows={8} mono />
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Substitute Variables" value={promptForm.variables} onChange={(v) => setPromptForm({ ...promptForm, variables: v })} placeholder="name, query, target" />
                                            <FormInput label="Domain Catalog" value={promptForm.category} onChange={(v) => setPromptForm({ ...promptForm, category: v })} />
                                        </div>
                                        <button onClick={handleCreatePrompt} disabled={isLoading} type="button" className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-bold transition-all shadow-sm">
                                            Commit Template
                                        </button>
                                    </Section>
                                    <Section title="Committed System Contexts" icon={MessageSquareText}>
                                        <div className="space-y-2">
                                            {prompts.map((prompt) => (
                                                <div key={prompt.id} className="flex items-center justify-between bg-slate-50/50 dark:bg-slate-900/40 border border-slate-200/80 dark:border-slate-800/80 rounded-xl p-3">
                                                    <div>
                                                        <div className="text-xs font-bold text-slate-800 dark:text-slate-100">{prompt.name}</div>
                                                        <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400 mt-0.5">{prompt.id} · {prompt.category ?? 'Global Scope'}</div>
                                                    </div>
                                                    <button onClick={() => deletePrompt(prompt.id)} type="button" className="px-3 py-1 text-xs font-semibold bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-100 dark:border-red-900/50 hover:border-red-200 dark:hover:border-red-800 rounded-lg transition-all">Delete</button>
                                                </div>
                                            ))}
                                        </div>
                                    </Section>
                                </div>
                            ) : activeTab === 'providers' ? (
                                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                                    <Section title="LLM Backend Handshake Gateways" icon={ServerCog}>
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Provider Key" value={providerForm.id} onChange={(v) => setProviderForm({ ...providerForm, id: v })} mono />
                                            <FormInput label="Display Host Label" value={providerForm.name} onChange={(v) => setProviderForm({ ...providerForm, name: v })} />
                                            <FormInput label="Engine Family" value={providerForm.type} onChange={(v) => setProviderForm({ ...providerForm, type: v })} />
                                            <FormInput label="Base Uniform Resource Locator" value={providerForm.base_url} onChange={(v) => setProviderForm({ ...providerForm, base_url: v })} mono />
                                        </div>
                                        <FormInput label="Scope Documentation" value={providerForm.description} onChange={(v) => setProviderForm({ ...providerForm, description: v })} rows={2} />
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput
                                                label="Private Auth Cipher Token"
                                                value={providerForm.api_key}
                                                onChange={(v) => setProviderForm({ ...providerForm, api_key: v })}
                                                type="password"
                                                helpText="Stored in the config file. Prefer an env var below for shared deployments."
                                            />
                                            <FormInput
                                                label="API Key Env Var"
                                                value={providerForm.api_key_env}
                                                onChange={(v) => setProviderForm({ ...providerForm, api_key_env: v })}
                                                mono
                                                placeholder="MY_PROVIDER_API_KEY"
                                            />
                                        </div>
                                        <FormInput
                                            label="Native Route Prefix"
                                            value={providerForm.litellm_prefix}
                                            onChange={(v) => setProviderForm({ ...providerForm, litellm_prefix: v })}
                                            mono
                                            placeholder="openrouter, ollama, deepseek…"
                                            helpText="Leave blank for any OpenAI-compatible endpoint (LM Studio, Qwen, GLM, Kimi, vLLM, custom gateways)."
                                        />
                                        <FormInput
                                            label="Available Models"
                                            value={providerForm.models}
                                            onChange={(v) => setProviderForm({ ...providerForm, models: v })}
                                            rows={3}
                                            mono
                                            placeholder={'qwen-plus\nqwen-max'}
                                            helpText="One per line (or comma separated). These become suggestions in the agent model picker."
                                        />
                                        <FormInput label="Metadata Headers Structure (JSON)" value={providerForm.config} onChange={(v) => setProviderForm({ ...providerForm, config: v })} rows={4} mono />
                                        <button onClick={handleCreateProvider} disabled={isLoading} type="button" className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-bold transition-all shadow-sm">
                                            Register Handshake Gateway
                                        </button>
                                    </Section>
                                    <Section title="Registered Gateways" icon={ServerCog}>
                                        <div className="space-y-2">
                                            {providers.map((provider) => (
                                                <div key={provider.id} className="flex items-center justify-between bg-slate-50/50 dark:bg-slate-900/40 border border-slate-200/80 dark:border-slate-800/80 rounded-xl p-3">
                                                    <div>
                                                        <div className="text-xs font-bold text-slate-800 dark:text-slate-100">{provider.name}</div>
                                                        <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400 mt-0.5">{provider.id} · {provider.type} · {provider.enabled ? 'Live' : 'Bypassed'}</div>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <button onClick={() => testProvider(provider.id).then((res) => alert(JSON.stringify(res, null, 2))).catch((e) => alert((e as Error).message))} type="button" className="px-3 py-1 text-xs font-semibold bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 rounded-lg shadow-2xs transition-all">Verify Packet</button>
                                                        <button onClick={() => deleteProvider(provider.id)} type="button" className="px-3 py-1 text-xs font-semibold bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-100 dark:border-red-900/50 hover:border-red-200 dark:hover:border-red-800 rounded-lg transition-all">Deregister</button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </Section>
                                </div>
                            ) : activeTab === 'ops' ? (
                                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                                    <Section title="Runtime State Telemetry Matrix" icon={Database}>
                                        <pre className="bg-slate-950 text-emerald-400 font-mono text-[11px] rounded-xl p-4 overflow-auto max-h-64 shadow-inner border border-slate-900 leading-normal">{JSON.stringify({ health, metricsDashboard }, null, 2)}</pre>
                                    </Section>
                                    <Section title="Semantic Search Memory Partitions" icon={Database}>
                                        <pre className="bg-slate-950 text-sky-400 font-mono text-[11px] rounded-xl p-4 overflow-auto max-h-96 shadow-inner border border-slate-900 leading-normal">{JSON.stringify({ ragConfig, ragCollections }, null, 2)}</pre>
                                    </Section>
                                </div>
                            ) : (
                                <>
                                    <div className="p-6 pb-0 shrink-0">
                                        <div className="flex items-center justify-between mb-1.5">
                                            <h1 className="text-base font-black text-slate-900 dark:text-white tracking-tight uppercase">
                                                {editingItem ? `Alter Target: ${activeTab === 'tools' ? 'Tool' : 'Agent'}` : `Initialize New ${activeTab === 'tools' ? 'Tool Blueprint' : 'Agent Unit'}`}
                                            </h1>
                                            <span className="text-[10px] text-slate-500 dark:text-slate-400 font-bold bg-slate-100 dark:bg-slate-800 px-2.5 py-1 rounded-md border border-slate-200 dark:border-slate-700 uppercase tracking-wider">
                                                {editingItem ? 'Update Override' : 'Fresh Stack Allocation'}
                                            </span>
                                        </div>
                                        <p className="text-slate-500 dark:text-slate-400 text-xs font-medium max-w-xl">
                                            Supply properties below. Instantiated profiles link directly to studio node topology triggers on workflow drop actions.
                                        </p>
                                    </div>

                                    <div className="flex-1 overflow-y-auto p-6 space-y-6">
                                        <Section title="Identity Specification" icon={Settings2}>
                                            <div className="grid grid-cols-1 gap-4">
                                                <FormInput
                                                    label="Unique Display Token"
                                                    placeholder={`e.g. ${activeTab === 'tools' ? 'stock_analyzer_v2' : 'RiskAssessmentAgent'}`}
                                                    value={formData.name}
                                                    onChange={(v) => setFormData({ ...formData, name: v })}
                                                    helpText="Systematic string key mapping to node parameters."
                                                />
                                                <FormInput
                                                    label="Behavioral Prompt Goal"
                                                    placeholder="Outline specific boundaries, contextual expectations, and return value constraints..."
                                                    value={formData.description}
                                                    onChange={(v) => setFormData({ ...formData, description: v })}
                                                    rows={2}
                                                    helpText="Provides semantic grounding parameters for parent orchestration switches."
                                                />
                                            </div>
                                        </Section>

                                        {activeTab === 'tools' && (
                                            <Section title="Payload Connectivity Parameters" icon={Wrench}>
                                                <div className="space-y-5">
                                                    <div className="grid grid-cols-2 gap-4">
                                                        <FormSelect
                                                            label="Adapter Execution Layer"
                                                            value={formData.type}
                                                            onChange={(v) => setFormData({ ...formData, type: v })}
                                                            options={[
                                                                { value: 'function', label: 'Python Function' },
                                                                { value: 'api', label: 'REST API' },
                                                                { value: 'mcp', label: 'MCP Server' },
                                                                { value: 'database', label: 'Database (NL2SQL)' },
                                                                { value: 'gmail', label: 'Gmail' }
                                                            ]}
                                                            icon={Zap}
                                                        />
                                                    </div>

                                                    {formData.type === 'function' && (
                                                        <FormInput
                                                            label="Qualified Entrypoint Symbol"
                                                            placeholder="src.infrastructure.tools:evaluate_market"
                                                            value={toolConfig.entrypoint}
                                                            onChange={(v) => setToolConfig({ ...toolConfig, entrypoint: v })}
                                                            icon={Code}
                                                            mono
                                                            helpText="Target import resolution path invoked via thread executors."
                                                        />
                                                    )}

                                                    {formData.type === 'api' && (
                                                        <>
                                                            <div className="grid grid-cols-3 gap-4">
                                                                <div className="col-span-2">
                                                                    <FormInput
                                                                        label="Network Uniform Resource Locator"
                                                                        placeholder="https://api.domain.com/v1/extract"
                                                                        value={toolConfig.api_url}
                                                                        onChange={(v) => setToolConfig({ ...toolConfig, api_url: v })}
                                                                        icon={Globe}
                                                                        mono
                                                                    />
                                                                </div>
                                                                <FormSelect
                                                                    label="HTTP Request Packet verb"
                                                                    value={toolConfig.http_method}
                                                                    onChange={(v) => setToolConfig({ ...toolConfig, http_method: v })}
                                                                    options={[
                                                                        { value: 'GET', label: 'GET' },
                                                                        { value: 'POST', label: 'POST' },
                                                                        { value: 'PUT', label: 'PUT' },
                                                                        { value: 'DELETE', label: 'DELETE' }
                                                                    ]}
                                                                />
                                                            </div>

                                                            <FormSelect
                                                                label="Security Negotiation Filter"
                                                                value={toolConfig.auth_type}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, auth_type: v })}
                                                                options={[
                                                                    { value: 'none', label: 'Public Handshake' },
                                                                    { value: 'bearer', label: 'Authorization Bearer Header' },
                                                                    { value: 'api_key', label: 'Custom Header Injection' }
                                                                ]}
                                                                icon={Key}
                                                            />

                                                            <FormInput
                                                                label="Request Header Injections (JSON)"
                                                                placeholder='{"Content-Type": "application/json"}'
                                                                value={toolConfig.headers}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, headers: v })}
                                                                mono
                                                                rows={2}
                                                            />

                                                            <FormInput
                                                                label="Request Stream Format Wrapper (JSON)"
                                                                placeholder='{"query": "{{input}}"}'
                                                                value={toolConfig.body_template}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, body_template: v })}
                                                                icon={FileJson}
                                                                mono
                                                                rows={2}
                                                                helpText="Supports double handlebars syntax {{input}} replacement."
                                                            />

                                                            <FormInput
                                                                label="Response Struct Dot Selector"
                                                                placeholder="data.items"
                                                                value={toolConfig.response_path}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, response_path: v })}
                                                                mono
                                                                helpText="Pulls highly specific payload arrays out of nested API responses automatically."
                                                            />
                                                        </>
                                                    )}

                                                    {formData.type === 'mcp' && (
                                                        <>
                                                            <FormSelect
                                                                label="Transport"
                                                                value={toolConfig.transport}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, transport: v })}
                                                                options={[
                                                                    { value: 'stdio', label: 'stdio (local command)' },
                                                                    { value: 'sse', label: 'SSE (remote URL)' },
                                                                    { value: 'streamable-http', label: 'Streamable HTTP (remote URL)' }
                                                                ]}
                                                            />
                                                            {toolConfig.transport === 'stdio' ? (
                                                                <>
                                                                    <FormInput
                                                                        label="Command"
                                                                        placeholder="npx"
                                                                        value={toolConfig.command}
                                                                        onChange={(v) => setToolConfig({ ...toolConfig, command: v })}
                                                                        mono
                                                                    />
                                                                    <FormInput
                                                                        label="Arguments (space-separated)"
                                                                        placeholder="-y @modelcontextprotocol/server-filesystem /tmp"
                                                                        value={toolConfig.args}
                                                                        onChange={(v) => setToolConfig({ ...toolConfig, args: v })}
                                                                        mono
                                                                    />
                                                                </>
                                                            ) : (
                                                                <>
                                                                    <FormInput
                                                                        label="Server URL"
                                                                        placeholder="https://mcp.example.com/sse"
                                                                        value={toolConfig.url}
                                                                        onChange={(v) => setToolConfig({ ...toolConfig, url: v })}
                                                                        mono
                                                                    />
                                                                    <FormInput
                                                                        label="Bearer token env var (optional)"
                                                                        placeholder="MY_MCP_TOKEN"
                                                                        value={toolConfig.auth_env_var}
                                                                        onChange={(v) => setToolConfig({ ...toolConfig, auth_env_var: v })}
                                                                        mono
                                                                        helpText="Name of the backend env var holding the token — never the token itself."
                                                                    />
                                                                </>
                                                            )}
                                                            <FormInput
                                                                label="Tool filter (comma-separated, empty = all)"
                                                                placeholder="read_file, list_directory"
                                                                value={toolConfig.tool_filter}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, tool_filter: v })}
                                                                mono
                                                            />
                                                        </>
                                                    )}

                                                    {formData.type === 'database' && (
                                                        <>
                                                            <FormSelect
                                                                label="Connection source"
                                                                value={toolConfig.db_source}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, db_source: v })}
                                                                options={[
                                                                    { value: 'env', label: 'Environment variable (URIs with credentials)' },
                                                                    { value: 'inline', label: 'Inline URI (credential-free, e.g. SQLite)' }
                                                                ]}
                                                            />
                                                            {toolConfig.db_source === 'env' ? (
                                                                <FormInput
                                                                    label="Env var holding the SQLAlchemy URI"
                                                                    placeholder="SALES_DB_URI"
                                                                    value={toolConfig.db_uri_env_var}
                                                                    onChange={(v) => setToolConfig({ ...toolConfig, db_uri_env_var: v })}
                                                                    mono
                                                                    helpText="e.g. SALES_DB_URI=postgresql://user:pass@host:5432/sales in the backend .env"
                                                                />
                                                            ) : (
                                                                <FormInput
                                                                    label="Database URI (no embedded credentials)"
                                                                    placeholder="sqlite:///./data/demo.db"
                                                                    value={toolConfig.db_uri}
                                                                    onChange={(v) => setToolConfig({ ...toolConfig, db_uri: v })}
                                                                    mono
                                                                />
                                                            )}
                                                            <FormInput
                                                                label="Table allowlist (comma-separated, empty = all)"
                                                                placeholder="orders, customers"
                                                                value={toolConfig.tables}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, tables: v })}
                                                                mono
                                                            />
                                                            <label className="flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-400">
                                                                <input
                                                                    type="checkbox"
                                                                    checked={toolConfig.allow_dml}
                                                                    onChange={(e) => setToolConfig({ ...toolConfig, allow_dml: e.target.checked })}
                                                                    className="accent-blue-600 h-4 w-4 rounded"
                                                                />
                                                                Allow write operations (DML) — off means read-only queries
                                                            </label>
                                                        </>
                                                    )}

                                                    {formData.type === 'gmail' && (
                                                        <>
                                                            <FormInput
                                                                label="Connected account email"
                                                                placeholder="support@yourdomain.com"
                                                                value={toolConfig.account_email}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, account_email: v })}
                                                                mono
                                                                helpText="Connect the account first from a Gmail tool node's inspector (Connect Gmail)."
                                                            />
                                                            <FormInput
                                                                label="Capabilities (send, search, read)"
                                                                placeholder="send, search, read"
                                                                value={toolConfig.capabilities}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, capabilities: v })}
                                                            />
                                                            <FormInput
                                                                label="Max search results"
                                                                placeholder="10"
                                                                value={toolConfig.max_results}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, max_results: v })}
                                                            />
                                                        </>
                                                    )}
                                                </div>
                                            </Section>
                                        )}

                                        {activeTab === 'agents' && (
                                            <>
                                                <Section title="CrewAI Topology Role Mapping" icon={Bot}>
                                                    <div className="space-y-5">
                                                        <div className="grid grid-cols-2 gap-4">
                                                            <FormSelect
                                                                label="Inherited Agent Strategy Base"
                                                                value={agentConfig.agentType}
                                                                onChange={(v) => setAgentConfig({ ...agentConfig, agentType: v })}
                                                                options={AGENT_TYPES.map(t => ({ value: t.id, label: t.name }))}
                                                                icon={Cpu}
                                                            />
                                                            <FormInput
                                                                label="Execution Context Stash Key"
                                                                placeholder="e.g. processed_output"
                                                                value={agentConfig.output_key}
                                                                onChange={(v) => setAgentConfig({ ...agentConfig, output_key: v })}
                                                                mono
                                                                helpText="Binds return results into global shared storage state."
                                                            />
                                                        </div>

                                                        <div className="grid grid-cols-2 gap-4 items-end">
                                                            <FormSelect
                                                                label="Human Intervention Interrupt Check"
                                                                value={agentConfig.human_input_mode}
                                                                onChange={(v) => setAgentConfig({ ...agentConfig, human_input_mode: v })}
                                                                options={HUMAN_INPUT_MODES.map(m => ({ value: m.id, label: m.name }))}
                                                            />

                                                            <div className="flex items-center gap-2 px-3.5 py-2 border border-slate-200 dark:border-slate-700 rounded-lg bg-slate-50/50 dark:bg-slate-900/40 h-9 mb-1.5">
                                                                <input
                                                                    type="checkbox"
                                                                    checked={agentConfig.is_selector}
                                                                    onChange={(e) => setAgentConfig({ ...agentConfig, is_selector: e.target.checked })}
                                                                    className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500 accent-blue-600"
                                                                    id="is_selector_chk"
                                                                />
                                                                <label htmlFor="is_selector_chk" className="text-xs font-bold text-slate-700 dark:text-slate-300 cursor-pointer select-none">
                                                                    Mark As Stateful Router Specialist
                                                                </label>
                                                            </div>
                                                        </div>

                                                        {agentConfig.agentType === 'LoopAgent' && (
                                                            <div className="grid grid-cols-2 gap-4">
                                                                <FormInput
                                                                    label="Loop Recursion Limit"
                                                                    value={agentConfig.max_loops.toString()}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, max_loops: parseInt(v) || 1 })}
                                                                    type="number"
                                                                />
                                                            </div>
                                                        )}

                                                        <FormInput
                                                            label="Specialist System Prompt Directives"
                                                            placeholder="You are an expert financial specialist. You must always review ledger tables..."
                                                            value={agentConfig.instruction}
                                                            onChange={(v) => setAgentConfig({ ...agentConfig, instruction: v })}
                                                            rows={4}
                                                            helpText="Establishes definitive behavior models and task-level expertise rules."
                                                        />
                                                    </div>
                                                </Section>

                                                {(['LlmAgent', 'ReasoningAgent', 'conversable', 'SequentialAgent'].includes(agentConfig.agentType) || agentConfig.is_selector) && (
                                                    <Section title="Model Parameters" icon={SlidersHorizontal}>
                                                        <div className="space-y-5">
                                                            <div className="grid grid-cols-2 gap-4">
                                                                <FormSelect
                                                                    label="Target Backend Provider"
                                                                    value={agentConfig.provider}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, provider: v })}
                                                                    options={llmProviderOptions}
                                                                />
                                                                <FormInput
                                                                    label="Model String Slug"
                                                                    placeholder={selectedAgentProviderModels[0] || 'gpt-4o'}
                                                                    value={agentConfig.model}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, model: v })}
                                                                    mono
                                                                    helpText={selectedAgentProviderModels.length ? `Suggested: ${selectedAgentProviderModels.slice(0, 4).join(', ')}` : undefined}
                                                                />
                                                            </div>

                                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                                <FormInput
                                                                    label="Provider Network URL override"
                                                                    placeholder={selectedAgentProvider?.base_url || 'Leave blank for the provider default'}
                                                                    value={agentConfig.base_url}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, base_url: v })}
                                                                    mono
                                                                />
                                                                <FormInput
                                                                    label="API Key Env Var"
                                                                    placeholder={selectedAgentProvider?.api_key_env || 'Leave blank for the provider key'}
                                                                    value={agentConfig.api_key_env}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, api_key_env: v })}
                                                                    mono
                                                                />
                                                            </div>

                                                            <div className="space-y-2">
                                                                <div className="flex justify-between items-center">
                                                                    <label className="text-xs font-bold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Creativity Temperature Factor</label>
                                                                    <span className="text-[11px] font-mono font-bold bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 px-2 py-0.5 rounded border border-blue-100 dark:border-blue-900/50">
                                                                        {agentConfig.temperature}
                                                                    </span>
                                                                </div>
                                                                <input
                                                                    type="range"
                                                                    min="0"
                                                                    max="2"
                                                                    step="0.05"
                                                                    value={agentConfig.temperature}
                                                                    onChange={(e) => setAgentConfig({ ...agentConfig, temperature: parseFloat(e.target.value) })}
                                                                    className="w-full h-1.5 bg-slate-200 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-600"
                                                                />
                                                                <div className="flex justify-between text-[10px] font-semibold text-slate-400 dark:text-slate-500">
                                                                    <span>Absolute Determinism (0.0)</span>
                                                                    <span>Highly Expressive (2.0)</span>
                                                                </div>
                                                            </div>

                                                            <div className="grid grid-cols-2 gap-4">
                                                                <FormInput
                                                                    label="Maximum Burnout Token Budget"
                                                                    value={agentConfig.max_tokens.toString()}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, max_tokens: parseInt(v) || 2048 })}
                                                                    type="number"
                                                                />
                                                            </div>
                                                        </div>
                                                    </Section>
                                                )}

                                                <Section title="Tool Attachments Portfolio" icon={Wrench}>
                                                    <div className="border border-slate-200/80 dark:border-slate-800/80 rounded-xl bg-slate-50/40 dark:bg-slate-900/40 p-4 max-h-56 overflow-y-auto">
                                                        {savedTools.length === 0 ? (
                                                            <div className="text-xs text-slate-400 dark:text-slate-500 text-center py-5 font-medium">
                                                                No tools available yet. Create one in the Tools tab to attach it here.
                                                            </div>
                                                        ) : (
                                                            <div className="grid grid-cols-2 gap-2">
                                                                {savedTools.map(tool => {
                                                                    const isChecked = agentConfig.tools?.includes(tool.name) || false;
                                                                    return (
                                                                        <label
                                                                            key={tool.id}
                                                                            className={`flex items-center gap-2.5 p-2.5 rounded-lg cursor-pointer transition-all border text-xs select-none
                                                                                ${isChecked
                                                                                    ? 'bg-white dark:bg-slate-900 border-blue-600 shadow-2xs font-bold text-blue-600'
                                                                                    : 'bg-white/60 dark:bg-slate-900/60 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 text-slate-600 dark:text-slate-400 font-medium'}`}
                                                                        >
                                                                            <div className={`flex items-center justify-center w-4 h-4 rounded border shrink-0 transition-colors ${isChecked ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700'}`}>
                                                                                {isChecked && <Check size={10} strokeWidth={3} />}
                                                                            </div>
                                                                            <span className="truncate flex-grow">
                                                                                {tool.name}
                                                                            </span>
                                                                        </label>
                                                                    );
                                                                })}
                                                            </div>
                                                        )}
                                                    </div>
                                                </Section>
                                            </>
                                        )}
                                    </div>

                                    {/* Footer save hooks */}
                                    <div className="p-4 border-t border-slate-100 dark:border-slate-800 bg-slate-50/30 dark:bg-slate-900/40 flex items-center justify-between shrink-0">
                                        <button
                                            onClick={resetForm}
                                            type="button"
                                            className="px-5 py-2 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl text-xs font-bold transition-all shadow-2xs"
                                        >
                                            Discard Changes
                                        </button>
                                        <button
                                            onClick={handleSave}
                                            disabled={isLoading}
                                            type="button"
                                            className="flex items-center justify-center gap-2 px-6 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-bold shadow-sm transition-all disabled:opacity-70"
                                        >
                                            {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} className="text-blue-400" />}
                                            {editingItem ? 'Save changes' : 'Create'}
                                        </button>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                    )}
                </div>
            </div>
            <SwaggerImportModal isOpen={isSwaggerModalOpen} onClose={() => setIsSwaggerModalOpen(false)} />
        </>
    );
};
