import React, { useState, useEffect } from 'react';
import { Plus, Trash2, Wrench, Bot, Save, Loader2, Download, ChevronRight, Globe, Code, Zap, Cpu, Settings2, SlidersHorizontal, Key, FileJson, Search, FunctionSquare, MessageSquareText, ServerCog, Check } from 'lucide-react';
import { useLibraryStore } from '../stores/libraryStore';
import { useUiStore } from '../stores/uiStore';
import type { LibraryTab } from '../stores/uiStore';
import { Toolbar, MoreMenu } from './shell/Toolbar';
import { ActivityCapsule } from './shell/ActivityCapsule';
import { StatusGlyph } from './shell/StatusGlyph';
import type { LibraryItem, ItemType } from '../stores/libraryStore';
import { SwaggerImportModal } from './SwaggerImportModal';
import { AGENT_TYPES, HUMAN_INPUT_MODES } from '../constants/agentOptions';
import { LibraryStore, toStoreEntries } from './studio/LibraryStore';
import type { StoreEntry } from './studio/LibraryStore';

// --- Shared Constants (Matched with PropertiesPanel.tsx) ---
type ResourceTab = LibraryTab;

const TAB_TITLE: Record<ResourceTab, { title: string; lead: string }> = {
    browse: { title: 'Everything', lead: 'Every tool, agent and workflow you can drop onto the canvas. Drag one to the Studio, or open it to edit.' },
    agents: { title: 'Agents', lead: 'Reusable agents your workflows call by name. Pick one to edit it, or create a new one.' },
    tools: { title: 'Tools', lead: 'Functions, REST APIs, MCP servers, databases and mailboxes your agents can call.' },
    functions: { title: 'Functions', lead: 'Small Python functions that become tools. The source runs on the backend.' },
    prompts: { title: 'Prompts', lead: 'Reusable prompt templates with variables, for agents and the Builder.' },
    providers: { title: 'Providers', lead: 'The model providers LiteLLM can reach, and the keys they use.' },
    ops: { title: 'Health and data', lead: 'What the backend reports about itself, and the retrieval collections it holds.' },
};

// A grouped box with a disclosure header.
const Section = ({ title, children, defaultOpen = true, className = "" }: { title: string; icon?: any; children: React.ReactNode; defaultOpen?: boolean; className?: string }) => {
    const [isOpen, setIsOpen] = useState(defaultOpen);
    return (
        <section className={`panel ${className}`}>
            <button
                onClick={() => setIsOpen(!isOpen)}
                type="button"
                aria-expanded={isOpen}
                className="flex w-full items-center gap-2 px-5 py-3.5 text-left"
            >
                <ChevronRight size={13} className={`transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`} style={{ color: 'var(--dim)' }} />
                <span className="headline">{title}</span>
            </button>
            {isOpen && <div className="space-y-4 px-5 pb-5">{children}</div>}
        </section>
    );
};

const FormInput = ({ label, placeholder, value, onChange, type = 'text', mono = false, rows, disabled = false, helpText }: {
    label: string; placeholder?: string; value: string; onChange: (v: string) => void; type?: string; icon?: any; mono?: boolean; rows?: number; disabled?: boolean; helpText?: string;
}) => (
    <label className="block w-full">
        <span className="field-label">{label}</span>
        {rows ? (
            <textarea
                value={value}
                onChange={(e) => onChange(e.target.value)}
                rows={rows}
                disabled={disabled}
                className={`textarea ${mono ? 'mono !text-[12px]' : ''}`}
                placeholder={placeholder}
            />
        ) : (
            <input
                type={type}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                disabled={disabled}
                className={`input ${mono ? 'mono !text-[12px]' : ''}`}
                placeholder={placeholder}
            />
        )}
        {helpText && <span className="hint mt-1 block">{helpText}</span>}
    </label>
);

const FormSelect = ({ label, value, onChange, options, helpText }: {
    label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; icon?: any; helpText?: string;
}) => (
    <label className="block w-full">
        <span className="field-label">{label}</span>
        <select value={value} onChange={(e) => onChange(e.target.value)} className="select">
            {options.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
        {helpText && <span className="hint mt-1 block">{helpText}</span>}
    </label>
);

/**
 * The Library, as a place in the sidebar. The sidebar picks the section; each
 * section is a large-titled page, with a list and an editor where things can be
 * created and changed.
 */
export const LibraryModal = ({ tab }: { tab: ResourceTab }) => {
    const { openLibrary, go } = useUiStore();
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

    const activeTab = tab;
    const setActiveTab = (next: ResourceTab) => openLibrary(next);
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
        fetchLibraryItems();
        fetchOperationsData();
    }, []);


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
            // Workflows are edited on the canvas.
            go('studio');
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

    const items = activeTab === 'tools' ? savedTools : activeTab === 'agents' ? savedAgents : [];
    const filteredItems = items.filter(i => i.name.toLowerCase().includes(searchQuery.toLowerCase()));

    const storeEntries = toStoreEntries(savedTools, savedAgents, savedWorkflows);


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
            <div className="absolute inset-0 flex flex-col" style={{ paddingTop: 'var(--toolbar-h)' }}>
                    <div className="flex shrink-0 flex-wrap items-end justify-between gap-4 px-8 pb-4 pt-5">
                        <div className="min-w-0">
                            <h1 className="display">{TAB_TITLE[activeTab].title}</h1>
                            <p className="lead mt-1 max-w-[680px]">{TAB_TITLE[activeTab].lead}</p>
                        </div>
                    </div>

                    {/* --- Browse: the store view --- */}
                    {activeTab === 'browse' ? (
                        <div className="mx-8 mb-6 flex min-h-0 flex-1 overflow-hidden rounded-[18px]" style={{ boxShadow: '0 0 0 1px var(--line)' }}>
                            <LibraryStore
                                entries={storeEntries}
                                onInspect={handleInspectEntry}
                                onManage={() => setActiveTab('tools')}
                            />
                        </div>
                    ) : (

                    /* --- Master-detail editor --- */
                    <div className="mx-8 mb-6 flex min-h-0 flex-1 gap-5 overflow-hidden">

                        {/* --- The list of saved items, for the two editable kinds --- */}
                        {(activeTab === 'tools' || activeTab === 'agents') && (
                        <div className="panel flex w-[300px] shrink-0 flex-col overflow-hidden">
                            <div className="shrink-0 space-y-2.5 p-3.5">
                                <div className="flex gap-2">

                                    {activeTab === 'tools' && (
                                        <button onClick={() => setIsSwaggerModalOpen(true)} type="button" className="btn" title="Import tools from an OpenAPI or Swagger spec">
                                            <Download size={13} />
                                            OpenAPI
                                        </button>
                                    )}
                                </div>

                                <div className="search-field">
                                    <Search size={13} />
                                    <input
                                        type="text"
                                        placeholder="Filter by name"
                                        aria-label="Filter by name"
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        className="input"
                                    />
                                </div>
                            </div>

                            <div className="scroll-soft flex-1 space-y-px px-2 pb-2" role="listbox" aria-label={TAB_TITLE[activeTab].title}>
                                {filteredItems.length === 0 ? (
                                    <div className="empty-state">
                                        <div className="headline">{searchQuery ? 'No matches' : 'Nothing saved yet'}</div>
                                        <p className="hint">{searchQuery ? 'Try a different name.' : activeTab === 'tools' ? 'Create one with New tool, or import from OpenAPI.' : 'Create one with New agent.'}</p>
                                    </div>
                                ) : (
                                    filteredItems.map(item => (
                                        <div
                                            key={item.id}
                                            role="option"
                                            aria-selected={editingItem?.id === item.id}
                                            tabIndex={0}
                                            onClick={() => handleEdit(item)}
                                            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleEdit(item); } }}
                                            className={`group flex items-center gap-2 rounded-[10px] px-2.5 py-2 transition-colors ${editingItem?.id === item.id ? 'bg-[var(--sidebar-sel)]' : 'hover:bg-[var(--fill)]'}`}
                                        >
                                            <span className="tile is-sm" style={{ ['--lane' as string]: activeTab === 'tools' ? 'var(--k-tool)' : 'var(--k-agent)' }}>
                                                {activeTab === 'tools' ? <Wrench size={13} /> : <Bot size={13} />}
                                            </span>
                                            <div className="min-w-0 flex-1">
                                                <div className={`truncate text-[13px] ${editingItem?.id === item.id ? 'font-semibold' : 'font-medium'}`}>{item.name}</div>
                                                <div className="mono truncate text-dim !text-[11px]">{item.type}</div>
                                            </div>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleDelete(item); }}
                                                type="button"
                                                className="btn btn-ghost btn-sm btn-icon opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                                                aria-label={`Delete ${item.name}`}
                                                title="Delete"
                                            >
                                                <Trash2 size={12} />
                                            </button>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>

                        )}

                        {/* --- The editor --- */}
                        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
                            {activeTab === 'functions' ? (
                                <div className="scroll-soft max-w-[900px] flex-1 space-y-4 pb-4 pt-1">
                                    <Section title="New function" icon={FunctionSquare}>
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Tool ID" value={functionForm.id} onChange={(v) => setFunctionForm({ ...functionForm, id: v })} placeholder="snake_case_tool_id" mono />
                                            <FormInput label="Function name" value={functionForm.name} onChange={(v) => setFunctionForm({ ...functionForm, name: v })} placeholder="my_tool" mono />
                                        </div>
                                        <FormInput label="Description" value={functionForm.description} onChange={(v) => setFunctionForm({ ...functionForm, description: v })} rows={2} />
                                        <FormInput label="Python source" value={functionForm.code} onChange={(v) => setFunctionForm({ ...functionForm, code: v })} rows={10} mono />
                                        <button onClick={handleCreateFunction} disabled={isLoading} type="button" className="btn">
                                            Create function
                                        </button>
                                    </Section>
                                    <Section title="Functions" icon={Code}>
                                        <div className="space-y-2">
                                            {functions.map((fn) => (
                                                <div key={fn.id} className="flex items-center justify-between rounded-[12px] bg-[var(--glass-raised)] px-3.5 py-2.5">
                                                    <div>
                                                        <div className="text-[13px] font-semibold">{fn.name}</div>
                                                        <div className="mono text-dim mt-0.5">{fn.entrypoint}</div>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <button onClick={() => handleViewFunctionSource(fn.id)} type="button" className="btn btn-sm">Source</button>
                                                        <button onClick={() => deleteFunctionTool(fn.id)} type="button" className="btn btn-danger btn-sm">Delete</button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </Section>
                                </div>
                            ) : activeTab === 'prompts' ? (
                                <div className="scroll-soft max-w-[900px] flex-1 space-y-4 pb-4 pt-1">
                                    <Section title="New prompt" icon={MessageSquareText}>
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Prompt id" value={promptForm.id} onChange={(v) => setPromptForm({ ...promptForm, id: v })} mono />
                                            <FormInput label="Name" value={promptForm.name} onChange={(v) => setPromptForm({ ...promptForm, name: v })} />
                                        </div>
                                        <FormInput label="Description" value={promptForm.description} onChange={(v) => setPromptForm({ ...promptForm, description: v })} rows={2} />
                                        <FormInput label="Template" value={promptForm.template} onChange={(v) => setPromptForm({ ...promptForm, template: v })} rows={8} mono />
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Variables" value={promptForm.variables} onChange={(v) => setPromptForm({ ...promptForm, variables: v })} placeholder="name, query, target" />
                                            <FormInput label="Category" value={promptForm.category} onChange={(v) => setPromptForm({ ...promptForm, category: v })} />
                                        </div>
                                        <button onClick={handleCreatePrompt} disabled={isLoading} type="button" className="btn btn-primary">
                                            Save prompt
                                        </button>
                                    </Section>
                                    <Section title="Saved prompts" icon={MessageSquareText}>
                                        <div className="space-y-2">
                                            {prompts.map((prompt) => (
                                                <div key={prompt.id} className="flex items-center justify-between rounded-[12px] bg-[var(--glass-raised)] px-3.5 py-2.5">
                                                    <div>
                                                        <div className="text-[13px] font-semibold">{prompt.name}</div>
                                                        <div className="mono text-dim mt-0.5">{prompt.id} · {prompt.category ?? 'No category'}</div>
                                                    </div>
                                                    <button onClick={() => deletePrompt(prompt.id)} type="button" className="btn btn-danger btn-sm">Delete</button>
                                                </div>
                                            ))}
                                        </div>
                                    </Section>
                                </div>
                            ) : activeTab === 'providers' ? (
                                <div className="scroll-soft max-w-[900px] flex-1 space-y-4 pb-4 pt-1">
                                    <Section title="Add a provider" icon={ServerCog}>
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput label="Provider id" value={providerForm.id} onChange={(v) => setProviderForm({ ...providerForm, id: v })} mono />
                                            <FormInput label="Display name" value={providerForm.name} onChange={(v) => setProviderForm({ ...providerForm, name: v })} />
                                            <FormInput label="Type" value={providerForm.type} onChange={(v) => setProviderForm({ ...providerForm, type: v })} />
                                            <FormInput label="Base URL" value={providerForm.base_url} onChange={(v) => setProviderForm({ ...providerForm, base_url: v })} mono />
                                        </div>
                                        <FormInput label="Description" value={providerForm.description} onChange={(v) => setProviderForm({ ...providerForm, description: v })} rows={2} />
                                        <div className="grid grid-cols-2 gap-5">
                                            <FormInput
                                                label="API key"
                                                value={providerForm.api_key}
                                                onChange={(v) => setProviderForm({ ...providerForm, api_key: v })}
                                                type="password"
                                                helpText="Stored in the config file. Prefer an env var below for shared deployments."
                                            />
                                            <FormInput
                                                label="API key env var"
                                                value={providerForm.api_key_env}
                                                onChange={(v) => setProviderForm({ ...providerForm, api_key_env: v })}
                                                mono
                                                placeholder="MY_PROVIDER_API_KEY"
                                            />
                                        </div>
                                        <FormInput
                                            label="LiteLLM prefix"
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
                                        <FormInput label="Extra config (JSON)" value={providerForm.config} onChange={(v) => setProviderForm({ ...providerForm, config: v })} rows={4} mono />
                                        <button onClick={handleCreateProvider} disabled={isLoading} type="button" className="btn btn-primary">
                                            Add provider
                                        </button>
                                    </Section>
                                    <Section title="Providers" icon={ServerCog}>
                                        <div className="space-y-2">
                                            {providers.map((provider) => (
                                                <div key={provider.id} className="flex items-center justify-between rounded-[12px] bg-[var(--glass-raised)] px-3.5 py-2.5">
                                                    <div>
                                                        <div className="text-[13px] font-semibold">{provider.name}</div>
                                                        <div className="mono text-dim mt-0.5">{provider.id} · {provider.type} · {provider.enabled ? 'on' : 'off'}</div>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <button onClick={() => testProvider(provider.id).then((res) => alert(JSON.stringify(res, null, 2))).catch((e) => alert((e as Error).message))} type="button" className="btn btn-sm">Test</button>
                                                        <button onClick={() => deleteProvider(provider.id)} type="button" className="btn btn-danger btn-sm">Remove</button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </Section>
                                </div>
                            ) : activeTab === 'ops' ? (
                                <div className="scroll-soft max-w-[900px] flex-1 space-y-4 pb-4 pt-1">
                                    {(() => {
                                        const h = (health ?? {}) as Record<string, any>;
                                        const m = (metricsDashboard ?? {}) as Record<string, any>;
                                        const healthy = String(h.status ?? '').toLowerCase() === 'healthy' || String(h.status ?? '').toLowerCase() === 'ok';
                                        const pct = (value: unknown) => (typeof value === 'number' ? `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%` : '—');
                                        const collections: Array<Record<string, any>> = Array.isArray((ragCollections as any)?.collections) ? (ragCollections as any).collections : [];
                                        return (
                                            <>
                                                <div className="panel figures flex-wrap gap-y-3 px-5 py-4">
                                                    <div className="figure">
                                                        <b className="flex h-[25px] items-center gap-2 !text-[15px]"><StatusGlyph shape={h.status ? (healthy ? 'ok' : 'warn') : 'idle'} />{h.status ? String(h.status).replace(/^./, (c) => c.toUpperCase()) : 'Unknown'}</b>
                                                        <span>Backend{h.version ? ` · v${h.version}` : ''}</span>
                                                    </div>
                                                    <div className="figure"><b>{m.active_sessions ?? '—'}</b><span>Active sessions</span></div>
                                                    <div className="figure"><b>{typeof m.total_messages === 'number' ? m.total_messages.toLocaleString() : '—'}</b><span>Messages</span></div>
                                                    <div className="figure"><b>{typeof m.avg_response_time === 'number' ? <>{m.avg_response_time.toFixed(2)}<small>s</small></> : '—'}</b><span>Average reply</span></div>
                                                    <div className="figure"><b>{pct(m.cache_hit_rate)}</b><span>Cache hits</span></div>
                                                    <div className="figure"><b>{pct(m.error_rate)}</b><span>Errors</span></div>
                                                </div>
                                                <Section title="Retrieval collections">
                                                    {collections.length === 0 ? (
                                                        <p className="hint">No collections yet. Upload documents through the RAG API to create one.</p>
                                                    ) : (
                                                        <div className="table-box">
                                                            <table className="mtable">
                                                                <thead><tr><th>Collection</th><th className="num">Documents</th><th className="num">Chunks</th></tr></thead>
                                                                <tbody>
                                                                    {collections.map((c, i) => (
                                                                        <tr key={String(c.name ?? c.id ?? i)}>
                                                                            <td><span className="row-title">{String(c.name ?? c.id ?? 'Collection')}</span>{c.description && <span className="row-sub">{String(c.description)}</span>}</td>
                                                                            <td className="num">{c.document_count ?? c.documents ?? c.files ?? '—'}</td>
                                                                            <td className="num">{c.chunk_count ?? c.chunks ?? '—'}</td>
                                                                        </tr>
                                                                    ))}
                                                                </tbody>
                                                            </table>
                                                        </div>
                                                    )}
                                                </Section>
                                                <Section title="Raw data" defaultOpen={false}>
                                                    <pre className="well mono max-h-96 overflow-auto p-4" style={{ color: 'var(--muted)' }}>{JSON.stringify({ health, metricsDashboard, ragConfig, ragCollections }, null, 2)}</pre>
                                                </Section>
                                            </>
                                        );
                                    })()}
                                </div>
                            ) : (
                                <>
                                    <div className="shrink-0 pb-3">
                                        <h2 className="title-1">
                                            {editingItem ? editingItem.name : `New ${activeTab === 'tools' ? 'tool' : 'agent'}`}
                                        </h2>
                                        <p className="hint mt-1">
                                            {editingItem
                                                ? `Changes are saved to the Library. Workflows that use this ${activeTab === 'tools' ? 'tool' : 'agent'} pick them up.`
                                                : `Saved to the Library. Drag it onto the canvas from the Studio's Saved list.`}
                                        </p>
                                    </div>

                                    <div className="scroll-soft max-w-[900px] flex-1 space-y-4 pb-4 pt-1">
                                        <Section title="Identity" icon={Settings2}>
                                            <div className="grid grid-cols-1 gap-4">
                                                <FormInput
                                                    label="Name"
                                                    placeholder={`e.g. ${activeTab === 'tools' ? 'stock_analyzer_v2' : 'RiskAssessmentAgent'}`}
                                                    value={formData.name}
                                                    onChange={(v) => setFormData({ ...formData, name: v })}
                                                    helpText="The name agents and workflows refer to it by."
                                                />
                                                <FormInput
                                                    label="Description"
                                                    placeholder="What it does, in a sentence."
                                                    value={formData.description}
                                                    onChange={(v) => setFormData({ ...formData, description: v })}
                                                    rows={2}
                                                    helpText="Selectors read this to decide when to hand over, so say what it does."
                                                />
                                            </div>
                                        </Section>

                                        {activeTab === 'tools' && (
                                            <Section title="Connection" icon={Wrench}>
                                                <div className="space-y-5">
                                                    <div className="grid grid-cols-2 gap-4">
                                                        <FormSelect
                                                            label="Tool type"
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
                                                            label="Entrypoint"
                                                            placeholder="src.infrastructure.tools:evaluate_market"
                                                            value={toolConfig.entrypoint}
                                                            onChange={(v) => setToolConfig({ ...toolConfig, entrypoint: v })}
                                                            icon={Code}
                                                            mono
                                                            helpText="module.path:function — the Python callable the tool runs."
                                                        />
                                                    )}

                                                    {formData.type === 'api' && (
                                                        <>
                                                            <div className="grid grid-cols-3 gap-4">
                                                                <div className="col-span-2">
                                                                    <FormInput
                                                                        label="API URL"
                                                                        placeholder="https://api.domain.com/v1/extract"
                                                                        value={toolConfig.api_url}
                                                                        onChange={(v) => setToolConfig({ ...toolConfig, api_url: v })}
                                                                        icon={Globe}
                                                                        mono
                                                                    />
                                                                </div>
                                                                <FormSelect
                                                                    label="Method"
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
                                                                label="Authentication"
                                                                value={toolConfig.auth_type}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, auth_type: v })}
                                                                options={[
                                                                    { value: 'none', label: 'None' },
                                                                    { value: 'bearer', label: 'Bearer token' },
                                                                    { value: 'api_key', label: 'API key header' }
                                                                ]}
                                                                icon={Key}
                                                            />

                                                            <FormInput
                                                                label="Headers (JSON)"
                                                                placeholder='{"Content-Type": "application/json"}'
                                                                value={toolConfig.headers}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, headers: v })}
                                                                mono
                                                                rows={2}
                                                            />

                                                            <FormInput
                                                                label="Body template (JSON)"
                                                                placeholder='{"query": "{{input}}"}'
                                                                value={toolConfig.body_template}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, body_template: v })}
                                                                icon={FileJson}
                                                                mono
                                                                rows={2}
                                                                helpText="Put {{input}} where the agent’s input should go."
                                                            />

                                                            <FormInput
                                                                label="Response path"
                                                                placeholder="data.items"
                                                                value={toolConfig.response_path}
                                                                onChange={(v) => setToolConfig({ ...toolConfig, response_path: v })}
                                                                mono
                                                                helpText="Dot path to the part of the response the agent should see."
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
                                                                    className="h-4 w-4"
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
                                                <Section title="Role and instructions" icon={Bot}>
                                                    <div className="space-y-5">
                                                        <div className="grid grid-cols-2 gap-4">
                                                            <FormSelect
                                                                label="Agent type"
                                                                value={agentConfig.agentType}
                                                                onChange={(v) => setAgentConfig({ ...agentConfig, agentType: v })}
                                                                options={AGENT_TYPES.map(t => ({ value: t.id, label: t.name }))}
                                                                icon={Cpu}
                                                            />
                                                            <FormInput
                                                                label="Output key"
                                                                placeholder="e.g. processed_output"
                                                                value={agentConfig.output_key}
                                                                onChange={(v) => setAgentConfig({ ...agentConfig, output_key: v })}
                                                                mono
                                                                helpText="Later steps read this agent’s answer under this key."
                                                            />
                                                        </div>

                                                        <div className="grid grid-cols-2 gap-4 items-end">
                                                            <FormSelect
                                                                label="Human input"
                                                                value={agentConfig.human_input_mode}
                                                                onChange={(v) => setAgentConfig({ ...agentConfig, human_input_mode: v })}
                                                                options={HUMAN_INPUT_MODES.map(m => ({ value: m.id, label: m.name }))}
                                                            />

                                                            <div className="mb-1.5 flex h-8 items-center gap-2 rounded-[8px] bg-[var(--glass-raised)] px-3">
                                                                <input
                                                                    type="checkbox"
                                                                    checked={agentConfig.is_selector}
                                                                    onChange={(e) => setAgentConfig({ ...agentConfig, is_selector: e.target.checked })}
                                                                    className="h-4 w-4"
                                                                    id="is_selector_chk"
                                                                />
                                                                <label htmlFor="is_selector_chk" className="text-xs font-bold text-slate-700 dark:text-slate-300 cursor-pointer select-none">
                                                                    Routes to other agents (selector)
                                                                </label>
                                                            </div>
                                                        </div>

                                                        {agentConfig.agentType === 'LoopAgent' && (
                                                            <div className="grid grid-cols-2 gap-4">
                                                                <FormInput
                                                                    label="Maximum loops"
                                                                    value={agentConfig.max_loops.toString()}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, max_loops: parseInt(v) || 1 })}
                                                                    type="number"
                                                                />
                                                            </div>
                                                        )}

                                                        <FormInput
                                                            label="Instructions"
                                                            placeholder="You are a support agent for Acme. Answer from the knowledge base, and say when you don’t know."
                                                            value={agentConfig.instruction}
                                                            onChange={(v) => setAgentConfig({ ...agentConfig, instruction: v })}
                                                            rows={4}
                                                            helpText="What the agent is for, and how it should work."
                                                        />
                                                    </div>
                                                </Section>

                                                {(['LlmAgent', 'ReasoningAgent', 'conversable', 'SequentialAgent'].includes(agentConfig.agentType) || agentConfig.is_selector) && (
                                                    <Section title="Model" icon={SlidersHorizontal}>
                                                        <div className="space-y-5">
                                                            <div className="grid grid-cols-2 gap-4">
                                                                <FormSelect
                                                                    label="Provider"
                                                                    value={agentConfig.provider}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, provider: v })}
                                                                    options={llmProviderOptions}
                                                                />
                                                                <FormInput
                                                                    label="Model"
                                                                    placeholder={selectedAgentProviderModels[0] || 'gpt-4o'}
                                                                    value={agentConfig.model}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, model: v })}
                                                                    mono
                                                                    helpText={selectedAgentProviderModels.length ? `Suggested: ${selectedAgentProviderModels.slice(0, 4).join(', ')}` : undefined}
                                                                />
                                                            </div>

                                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                                <FormInput
                                                                    label="Base URL override"
                                                                    placeholder={selectedAgentProvider?.base_url || 'Leave blank for the provider default'}
                                                                    value={agentConfig.base_url}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, base_url: v })}
                                                                    mono
                                                                />
                                                                <FormInput
                                                                    label="API key env var"
                                                                    placeholder={selectedAgentProvider?.api_key_env || 'Leave blank for the provider key'}
                                                                    value={agentConfig.api_key_env}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, api_key_env: v })}
                                                                    mono
                                                                />
                                                            </div>

                                                            <div className="space-y-2">
                                                                <div className="flex justify-between items-center">
                                                                    <label className="text-xs font-bold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Temperature</label>
                                                                    <span className="chip mono">
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
                                                                    className="w-full"
                                                                />
                                                                <div className="flex justify-between text-[10px] font-semibold text-slate-400 dark:text-slate-500">
                                                                    <span>Precise (0.0)</span>
                                                                    <span>Creative (2.0)</span>
                                                                </div>
                                                            </div>

                                                            <div className="grid grid-cols-2 gap-4">
                                                                <FormInput
                                                                    label="Max tokens"
                                                                    value={agentConfig.max_tokens.toString()}
                                                                    onChange={(v) => setAgentConfig({ ...agentConfig, max_tokens: parseInt(v) || 2048 })}
                                                                    type="number"
                                                                />
                                                            </div>
                                                        </div>
                                                    </Section>
                                                )}

                                                <Section title="Tools" icon={Wrench}>
                                                    <div className="well max-h-56 overflow-y-auto p-3">
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
                                                                            className={`flex select-none items-center gap-2.5 rounded-[10px] p-2.5 text-[12.5px] transition-colors ${isChecked ? 'bg-[var(--glass-raised)] font-semibold shadow-[0_0_0_1.5px_var(--text)]' : 'bg-[var(--glass-raised)] hover:bg-[var(--fill)]'}`}
                                                                        >
                                                                            <div className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-[5px] transition-colors ${isChecked ? 'bg-[var(--accent-fill)] text-[var(--on-accent)]' : 'shadow-[inset_0_0_0_1px_var(--field-border)]'}`}>
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
                                    <div className="flex max-w-[900px] shrink-0 items-center justify-end gap-2 pt-3" style={{ boxShadow: '0 -1px 0 var(--line)' }}>
                                        <button onClick={resetForm} type="button" className="btn btn-ghost">
                                            Discard
                                        </button>
                                        <button onClick={handleSave} disabled={isLoading} type="button" className="btn btn-primary">
                                            {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                                            {editingItem ? 'Save changes' : `Create ${activeTab === 'tools' ? 'tool' : 'agent'}`}
                                        </button>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                    )}
            </div>
            <Toolbar
                center={<ActivityCapsule onStatusClick={() => go('studio')} />}
                actions={
                    <>
                        {(activeTab === 'tools' || activeTab === 'agents') && (
                            <button type="button" className="btn btn-toolbar" onClick={resetForm}>
                                <Plus size={14} /> New {activeTab === 'tools' ? 'tool' : 'agent'}
                            </button>
                        )}
                        <MoreMenu />
                    </>
                }
            />
            <SwaggerImportModal isOpen={isSwaggerModalOpen} onClose={() => setIsSwaggerModalOpen(false)} />
        </>
    );
};
