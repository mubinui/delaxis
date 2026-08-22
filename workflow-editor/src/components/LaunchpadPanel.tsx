import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Cable, Code2, ExternalLink, Loader2, Mic, MicOff, PlayCircle, Rocket, Send, Trash2, Volume2, VolumeX, Wand2, Wrench, X } from 'lucide-react';
import { applyBuilderPlan, generateBuilderConfig, generateFrontend, listBuilderModels, normalizeApi, planChatbot, streamBuilderChat } from '../api/builderApi';
import type { BuilderType, ChatMessage, ModelInfo } from '../api/builderApi';
import type { ThemePreset, VoiceProviderInfo, VoiceProvidersResponse } from '../api/backendTypes';
import { api } from '../api/client';
import { useShallow } from 'zustand/react/shallow';
import { isBuildCommand, narration, useBuildNarration } from '../hooks/useBuildNarration';
import { useVoiceSession, type VoiceLevels, type VoiceTranscript } from '../hooks/useVoiceSession';
import { useLibraryStore } from '../stores/libraryStore';
import { useWorkflowStore } from '../stores/workflowStore';
import { workflowToCanvas } from '../utils/workflowToCanvas';

type Tab = 'build' | 'api' | 'triggers' | 'frontend' | 'deploy';
type BuildKind = BuilderType | 'chatbot' | 'api' | 'frontend';

const compactJson = (value: unknown) => JSON.stringify(value, null, 2);
const FRONTEND_MODEL_ID = 'google/gemini-3.6-flash';

const GeneratingBubble = () => (
    <div className="inline-flex items-center gap-2 text-slate-500">
        <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-40 animate-ping" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-blue-500" />
        </span>
        <span className="text-sm">Generating</span>
        <span className="flex gap-0.5" aria-hidden="true">
            <span className="h-1 w-1 rounded-full bg-slate-400 animate-bounce [animation-delay:-0.24s]" />
            <span className="h-1 w-1 rounded-full bg-slate-400 animate-bounce [animation-delay:-0.12s]" />
            <span className="h-1 w-1 rounded-full bg-slate-400 animate-bounce" />
        </span>
    </div>
);

export const LaunchpadPanel = ({ onClose }: { onClose?: () => void }) => {
    const [tab, setTab] = useState<Tab>('build');
    const [buildKind, setBuildKind] = useState<BuildKind>('chatbot');
    const [buildMessages, setBuildMessages] = useState<ChatMessage[]>([]);
    const [buildInput, setBuildInput] = useState('Build a helpful admissions chatbot that can answer student questions and call APIs when needed.');
    const [models, setModels] = useState<ModelInfo[]>([]);
    const [providerId, setProviderId] = useState('openrouter');
    // Empty means auto: the server picks the best model for each build step.
    const [modelId, setModelId] = useState('');
    const [rawApi, setRawApi] = useState('GET https://api.example.com/students/{id}\\nAuthorization: Bearer token\\nReturn student profile by id');
    const [specification, setSpecification] = useState('Create a tool that agents can use safely. Infer path/query params and auth.');
    const [plan, setPlan] = useState<Record<string, any> | null>(null);
    const [normalizedTool, setNormalizedTool] = useState<Record<string, any> | null>(null);
    const [frontendPrompt, setFrontendPrompt] = useState('Create a premium university admissions chatbot UI with a clean welcome panel, suggested questions, and a fast mobile layout.');
    const [frontendMessages, setFrontendMessages] = useState<ChatMessage[]>([]);
    const [frontendHtml, setFrontendHtml] = useState('');
    const [frontendMode, setFrontendMode] = useState<'themed' | 'custom'>('themed');
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState('');
    const [messageIsError, setMessageIsError] = useState(false);
    const [deployTitle, setDeployTitle] = useState('');
    const [deployGreeting, setDeployGreeting] = useState('Hi, how can I help?');
    const [deploySuggestions, setDeploySuggestions] = useState('');
    const [deployTheme, setDeployTheme] = useState('midnight');
    const [themes, setThemes] = useState<ThemePreset[]>([]);
    const [voiceEnabled, setVoiceEnabled] = useState(false);
    const [voiceModel, setVoiceModel] = useState('');
    const [voiceName, setVoiceName] = useState('');
    const [voicePrompt, setVoicePrompt] = useState('');
    const [voiceInfo, setVoiceInfo] = useState<VoiceProviderInfo | null>(null);
    // Spoken build progress. Off until asked for; see useBuildNarration.
    const speech = useBuildNarration();

    // Talking through what to build. What you say lands in the brief box, so the
    // conversation produces the thing the Build button actually consumes —
    // otherwise it would just be a chat that goes nowhere.
    const micRef = useRef<HTMLButtonElement>(null);
    const vizRef = useRef<HTMLDivElement>(null);
    const [voiceReply, setVoiceReply] = useState('');
    // Set when a spoken "start building" is heard; consumed by the effect below
    // so the build runs outside the audio callback.
    const [voiceBuildPending, setVoiceBuildPending] = useState(false);

    // Spoken build commands are detected on the accumulating turn, not on each
    // delta: "start building" almost always arrives split across two or three
    // fragments, so testing a fragment alone would never match.
    const spokenTurn = useRef('');
    const buildRequested = useRef(false);

    const handleVoiceTranscript = useCallback((entry: VoiceTranscript) => {
        if (!entry.text) return;
        if (entry.role === 'user') {
            // Transcript deltas arrive several times a turn; append with a single
            // space so the brief reads as continuous prose.
            setBuildInput((current) => (current ? `${current} ${entry.text}` : entry.text).replace(/\s+/g, ' '));
            spokenTurn.current = `${spokenTurn.current} ${entry.text}`.slice(-240);
            if (!buildRequested.current && isBuildCommand(spokenTurn.current)) {
                // Latch it: the phrase stays in the buffer for a moment and must
                // not launch a second build.
                buildRequested.current = true;
                setVoiceBuildPending(true);
            }
        } else {
            setVoiceReply((current) => current + entry.text);
        }
    }, []);

    const handleVoiceLevels = useCallback(({ level, bands, speaking }: VoiceLevels) => {
        micRef.current?.style.setProperty('--voice-level', level.toFixed(3));
        const viz = vizRef.current;
        if (!viz) return;
        viz.dataset.speaking = String(speaking);
        bands.forEach((value, index) => {
            (viz.children[index] as HTMLElement | undefined)?.style.setProperty('--b', value.toFixed(3));
        });
    }, []);

    const voice = useVoiceSession({
        sessionId: null,
        purpose: 'builder',
        draft: buildInput,
        onTranscript: handleVoiceTranscript,
        onLevels: handleVoiceLevels,
    });

    // Selector-scoped so this panel doesn't re-render on every node/edge change on the canvas.
    const { currentWorkflowId, workflowName } = useWorkflowStore(
        useShallow((state) => ({
            currentWorkflowId: state.currentWorkflowId,
            workflowName: state.workflowName,
        })),
    );
    const loadWorkflow = useWorkflowStore((state) => state.loadWorkflow);
    const addNodeToCanvas = useWorkflowStore((state) => state.addNode);
    const {
        triggers,
        deployments,
        createTrigger,
        deleteTrigger,
        flashDeploy,
        deleteDeployment,
        fetchOperationsData,
        fetchLibraryItems,
        saveItem,
    } = useLibraryStore();

    const workflowId = currentWorkflowId || plan?.workflow?.id || '';
    const workflowLabel = workflowName || plan?.workflow?.name || 'Current workflow';

    useEffect(() => {
        listBuilderModels()
            .then((result) => {
                setModels(result.models);
                // Only seed the provider; the model stays on auto so build steps
                // are routed per task instead of all sharing one pick.
                const preferred = result.models.find((model) => model.model_id === FRONTEND_MODEL_ID) ?? result.models[0];
                if (preferred) setProviderId(preferred.provider_id);
            })
            .catch(() => undefined);
        api<ThemePreset[]>('/api/v1/deployments/themes')
            .then(setThemes)
            .catch(() => undefined);
        api<VoiceProvidersResponse>('/api/v1/voice/providers')
            .then((result) => {
                if (!result.enabled) return;
                setVoiceInfo(result.providers[0] ?? null);
            })
            .catch(() => undefined);
        fetchOperationsData();
    }, []);

    const reportSuccess = (text: string) => {
        setMessageIsError(false);
        setMessage(text);
    };

    const reportError = (text: string) => {
        setMessageIsError(true);
        setMessage(text);
    };

    const providerModels = useMemo(
        () => models.filter((model) => model.provider_id === providerId),
        [models, providerId],
    );

    const readBuilderStream = async (reader: ReadableStreamDefaultReader<Uint8Array>) => {
        const decoder = new TextDecoder();
        let buffer = '';
        let text = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split('\n\n');
            buffer = frames.pop() ?? '';
            for (const frame of frames) {
                const dataLine = frame.split('\n').find((line) => line.startsWith('data: '));
                if (!dataLine) continue;
                const raw = dataLine.slice(6);
                if (raw === '[DONE]') continue;
                const data = JSON.parse(raw);
                text += data.token ?? '';
                setBuildMessages((items) => {
                    const next = [...items];
                    const last = next[next.length - 1];
                    if (last?.role === 'assistant') {
                        next[next.length - 1] = { ...last, content: text };
                    }
                    return next;
                });
            }
        }
        return text;
    };

    // Acting on a spoken "start building". Runs from an effect rather than from
    // inside the audio callback so the build is not kicked off mid-transcript,
    // and closes the mic first: a live session would otherwise keep listening
    // through the whole build and talk over the narration.
    useEffect(() => {
        if (!voiceBuildPending) return;
        setVoiceBuildPending(false);
        voice.stop();
        speech.speak('Starting the build.');
        void runChatBuilder();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [voiceBuildPending]);

    const runChatBuilder = async () => {
        const requestText = buildInput.trim();
        if (!requestText) return;
        setBuildInput('');
        setBusy(true);
        setMessage('');
        const nextMessages: ChatMessage[] = [...buildMessages, { role: 'user', content: requestText }];
        setBuildMessages([...nextMessages, { role: 'assistant', content: '' }]);
        try {
            if (buildKind === 'chatbot') {
                speech.speak(narration.planning);
                const result = await planChatbot({ prompt: requestText, provider_id: providerId, model_id: modelId });
                setPlan(result);
                speech.speak(narration.modelChosen(String(result.model_id ?? '')));
                speech.speak(narration.planned(
                    Array.isArray(result.agents) ? result.agents.length : 0,
                    Array.isArray(result.tools) ? result.tools.length : 0,
                ));
                setBuildMessages([...nextMessages, { role: 'assistant', content: `I built a full chatbot plan.\n\n${compactJson(result)}` }]);
            } else if (buildKind === 'api') {
                speech.speak(narration.repairingApi);
                const result = await normalizeApi({ raw_api: requestText, specification, provider_id: providerId, model_id: modelId });
                setNormalizedTool(result);
                speech.speak(narration.modelChosen(String(result.model_id ?? '')));
                speech.speak(narration.repairedApi(String(result.name ?? result.id ?? '')));
                setBuildMessages([...nextMessages, { role: 'assistant', content: `I normalized this API into a tool config.\n\n${compactJson(result)}` }]);
            } else if (buildKind === 'frontend') {
                if (!workflowId) {
                    setBuildMessages([...nextMessages, { role: 'assistant', content: 'Save or load a workflow first so I know which backend this frontend should talk to.' }]);
                    return;
                }
                speech.speak(narration.designing);
                const result = await generateFrontend({
                    prompt: requestText,
                    workflow_id: workflowId,
                    title: workflowLabel,
                    greeting: 'Hi, I am ready.',
                    provider_id: providerId,
                    model_id: modelId,
                    history: buildMessages,
                    mode: frontendMode,
                });
                setFrontendHtml(result.html);
                speech.speak(narration.modelChosen(result.model_id));
                speech.speak(narration.designed(result.used_fallback));
                setBuildMessages([...nextMessages, { role: 'assistant', content: `${result.summary}\n\nReady to flash deploy from the Frontend tab.` }]);
            } else {
                speech.speak(narration.generatingConfig);
                const reader = await streamBuilderChat({
                    builder_type: buildKind,
                    message: requestText,
                    history: buildMessages,
                    provider_id: providerId,
                    model_id: modelId,
                });
                await readBuilderStream(reader);
            }
        } catch (error) {
            speech.say(narration.failed('The build'));
            setBuildMessages([...nextMessages, { role: 'assistant', content: (error as Error).message }]);
        } finally {
            setBusy(false);
        }
    };

    const finalizeChatBuilder = async () => {
        if (!['agent', 'tool', 'function', 'workflow'].includes(buildKind)) {
            setMessage('Use Generate for agent, tool, function, or workflow conversations. Chatbot, API, and frontend modes already create structured output directly.');
            return;
        }
        setBusy(true);
        setMessage('');
        try {
            const result = await generateBuilderConfig({
                builder_type: buildKind as BuilderType,
                history: buildMessages,
                provider_id: providerId,
                model_id: modelId,
            });
            // A Python function is source code, not a config — there is no node
            // for it, so it stays as text for the user to review.
            if (typeof result.config === 'string' || buildKind === 'function') {
                setMessage(typeof result.config === 'string' ? result.config : compactJson(result.config));
                return;
            }

            const config = result.config as Record<string, any>;
            if (buildKind === 'workflow') {
                // Route through the plan applier so its agents are created too,
                // then the workflow opens on the canvas.
                setPlan({ workflow: config });
                reportSuccess('Workflow config ready. Press Apply to create it and open it on the canvas.');
                return;
            }

            // Agents and tools are saved to the library and dropped on the canvas,
            // rather than being printed as JSON the user has to copy by hand.
            const kind = buildKind === 'agent' ? 'agent' : 'tool';
            const saved = await saveItem(kind, {
                name: String(config.name ?? config.id ?? `New ${kind}`),
                description: String(config.description ?? ''),
                config,
            });
            addNodeToCanvas({
                id: `${kind}-${Date.now()}`,
                type: kind,
                position: { x: 420, y: 220 },
                data: {
                    label: saved.name,
                    description: saved.description ?? '',
                    config: { ...config, id: saved.id },
                },
            } as any);
            reportSuccess(`Saved "${saved.name}" to the library and added it to the canvas.`);
            onClose?.();
        } catch (error) {
            reportError((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    const runPlan = async () => {
        setBusy(true);
        setMessage('');
        try {
            const seed = buildInput.trim() || 'Build a helpful admissions chatbot that can answer student questions and call APIs when needed.';
            speech.speak(narration.planning);
            const result = await planChatbot({ prompt: seed, provider_id: providerId, model_id: modelId });
            setPlan(result);
            // The server may have escalated to a stronger model; say which, so the
            // choice is not invisible.
            speech.speak(narration.modelChosen(String(result.model_id ?? '')));
            speech.speak(narration.planned(
                Array.isArray(result.agents) ? result.agents.length : 0,
                Array.isArray(result.tools) ? result.tools.length : 0,
            ));
            setMessage('Build plan ready. Review it, then apply when it looks right.');
        } catch (error) {
            speech.say(narration.failed('Planning'));
            setMessage((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    /** Put a saved workflow config on the canvas so it can be seen and edited. */
    const openOnCanvas = async (config: Record<string, any>, name?: string) => {
        // Refresh first: the agents and tools the plan just created are what the
        // canvas reads model settings and tool details from.
        await fetchLibraryItems().catch(() => undefined);
        const { savedAgents, savedTools } = useLibraryStore.getState();
        const { nodes, edges } = workflowToCanvas({ config, agents: savedAgents, tools: savedTools });
        loadWorkflow(String(config.id ?? ''), String(name ?? config.name ?? 'Generated workflow'), nodes, edges);
        onClose?.();
    };

    const applyPlan = async () => {
        if (!plan) return;
        setBusy(true);
        try {
            speech.speak(narration.applying);
            const result = await applyBuilderPlan(plan);
            await fetchOperationsData();

            const describe = (bucket: Record<string, string[]>, verb: string) =>
                Object.entries(bucket ?? {})
                    .filter(([, ids]) => Array.isArray(ids) && ids.length > 0)
                    .map(([kind, ids]) => `${verb} ${ids.length} ${kind}`)
                    .join(', ');
            const summary = [
                describe(result.created as Record<string, string[]>, 'created'),
                describe(result.updated as Record<string, string[]>, 'updated'),
            ].filter(Boolean).join(', ');
            const failures = (result.errors ?? []) as string[];

            // The whole point of applying is to end up with something editable —
            // previously this only printed JSON and left the canvas untouched.
            const workflowConfig = result.workflow as Record<string, any> | null;
            if (workflowConfig) {
                await openOnCanvas(workflowConfig);
                reportSuccess(
                    `Applied the plan (${summary || 'no changes'}) and opened the workflow on the canvas.`
                    + (failures.length ? ` ${failures.length} item(s) failed: ${failures.join('; ')}` : ''),
                );
            } else if (failures.length) {
                reportError(`Nothing was created: ${failures.join('; ')}`);
            } else {
                reportSuccess(`Applied the plan: ${summary || 'no changes'}.`);
            }
        } catch (error) {
            reportError((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    const runNormalizeApi = async () => {
        setBusy(true);
        setMessage('');
        try {
            speech.speak(narration.repairingApi);
            const result = await normalizeApi({ raw_api: rawApi, specification, provider_id: providerId, model_id: modelId });
            setNormalizedTool(result);
            speech.speak(narration.modelChosen(String(result.model_id ?? '')));
            speech.speak(narration.repairedApi(String(result.name ?? result.id ?? '')));
            setMessage('API normalized. You can copy this config or apply it through the builder plan flow.');
        } catch (error) {
            speech.say(narration.failed('Building the tool'));
            setMessage((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    const useGeminiFrontendModel = () => {
        const gemini = models.find((model) => model.model_id === FRONTEND_MODEL_ID);
        setProviderId(gemini?.provider_id ?? 'openrouter');
        setModelId(FRONTEND_MODEL_ID);
    };

    const runFrontendGenerate = async () => {
        if (!workflowId) {
            setMessage('Save or load a workflow first.');
            return;
        }
        const requestText = frontendPrompt.trim();
        if (!requestText) return;
        const nextMessages: ChatMessage[] = [...frontendMessages, { role: 'user', content: requestText }];
        setFrontendMessages([...nextMessages, { role: 'assistant', content: '' }]);
        setFrontendPrompt('');
        setBusy(true);
        setMessage('');
        try {
            speech.speak(narration.designing);
            const result = await generateFrontend({
                prompt: requestText,
                workflow_id: workflowId,
                title: workflowLabel,
                greeting: 'Hi, I am ready.',
                provider_id: providerId,
                model_id: modelId,
                history: frontendMessages,
                mode: frontendMode,
            });
            setFrontendHtml(result.html);
            speech.speak(narration.modelChosen(result.model_id));
            speech.speak(narration.designed(result.used_fallback));
            setFrontendMessages([
                ...nextMessages,
                {
                    role: 'assistant',
                    content: result.used_fallback
                        ? `${result.summary} Add an OpenRouter API key to use ${result.model_id}.`
                        : `${result.summary} Ready to flash deploy.`,
                },
            ]);
        } catch (error) {
            speech.say(narration.failed('Designing the interface'));
            setFrontendMessages([...nextMessages, { role: 'assistant', content: (error as Error).message }]);
        } finally {
            setBusy(false);
        }
    };

    const createChatTrigger = async () => {
        if (!workflowId) {
            setMessage('Save or load a workflow first.');
            return;
        }
        setBusy(true);
        try {
            await createTrigger({
                workflow_id: workflowId,
                type: 'chat',
                name: `${workflowLabel} chat`,
                auth_mode: 'public',
                provider_id: providerId,
                model_id: modelId,
                greeting: 'Hi, how can I help?',
            });
            await fetchOperationsData();
            setMessage('Chat trigger created.');
        } catch (error) {
            setMessage((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    const createWebhookTrigger = async () => {
        if (!workflowId) {
            setMessage('Save or load a workflow first.');
            return;
        }
        setBusy(true);
        try {
            await createTrigger({
                workflow_id: workflowId,
                type: 'webhook',
                name: `${workflowLabel} webhook`,
                auth_mode: 'api_key',
                provider_id: providerId,
                model_id: modelId,
                input_mapping: { message: '$.message' },
                response_mapping: { response: '$.response' },
            });
            await fetchOperationsData();
            setMessage('Webhook trigger created with a secret.');
        } catch (error) {
            setMessage((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    const deployBranding = () => ({
        title: deployTitle.trim() || workflowLabel,
        greeting: deployGreeting.trim() || 'Hi, how can I help?',
        // Starter chips on an empty conversation; the backend keeps the first four.
        suggestions: deploySuggestions.split('\n').map((line) => line.trim()).filter(Boolean),
        theme: deployTheme,
        // The model, voice and persona are stored on the deployment record and
        // resolved server-side — the served page only learns that voice is on.
        voice: {
            enabled: voiceEnabled && Boolean(voiceInfo?.key_available),
            provider_id: voiceInfo?.provider_id || 'gemini',
            model: voiceModel,
            voice_name: voiceName,
            system_prompt: voicePrompt.trim(),
        },
    });

    const runFlashDeploy = async () => {
        if (!workflowId) {
            reportError('Save or load a workflow first.');
            return;
        }
        setBusy(true);
        try {
            speech.speak(narration.deploying);
            const deployment = await flashDeploy({
                workflow_id: workflowId,
                name: workflowId,
                ...deployBranding(),
                provider_id: providerId,
                model_id: modelId,
                auth_mode: 'public',
            });
            speech.speak(narration.deployed);
            reportSuccess(`Flash deployed at ${deployment.url}`);
        } catch (error) {
            speech.say(narration.failed('Deploying'));
            reportError((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    const runGeneratedFlashDeploy = async () => {
        if (!workflowId) {
            reportError('Save or load a workflow first.');
            return;
        }
        if (!frontendHtml) {
            reportError('Generate a frontend first.');
            return;
        }
        setBusy(true);
        try {
            speech.speak(narration.deploying);
            const deployment = await flashDeploy({
                workflow_id: workflowId,
                name: `${workflowId}-custom-frontend`,
                ...deployBranding(),
                provider_id: providerId,
                model_id: modelId,
                auth_mode: 'public',
                frontend_html: frontendHtml,
                frontend_source: 'ai_frontend_builder',
            });
            speech.speak(narration.deployed);
            reportSuccess(`Generated frontend deployed at ${deployment.url}`);
        } catch (error) {
            speech.say(narration.failed('Deploying'));
            reportError((error as Error).message);
        } finally {
            setBusy(false);
        }
    };

    const tabs = [
        { id: 'build' as const, label: 'Build', icon: Wand2 },
        { id: 'api' as const, label: 'API Fix', icon: Wrench },
        { id: 'triggers' as const, label: 'Triggers', icon: Cable },
        { id: 'frontend' as const, label: 'Frontend', icon: Code2 },
        { id: 'deploy' as const, label: 'Deploy', icon: Rocket },
    ];

    return (
        // Floating window over the canvas — toggled from the Builder button in the header.
        <aside
            className="absolute top-4 right-4 bottom-24 z-40 flex w-[400px] flex-col overflow-hidden animate-in slide-in-from-right-4 fade-in duration-200"
            style={{
                backgroundColor: 'var(--surface-1)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-xl)',
                boxShadow: 'var(--shadow-xl)',
            }}
        >
            <div
                className="shrink-0 px-4 py-3.5"
                style={{ borderBottom: '1px solid var(--border-subtle)', backgroundColor: 'var(--surface-2)' }}
            >
                <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                        <div className="dlx-text flex items-center gap-2 text-sm font-bold">
                            <span className="dlx-glyph h-7 w-7" data-tone="agent">
                                <Bot size={15} />
                            </span>
                            Builder
                        </div>
                        <div className="dlx-muted mt-1 truncate text-[11px]">{workflowId ? `Building into ${workflowId}` : 'No saved workflow selected'}</div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                        {speech.supported && (
                            <button
                                onClick={speech.toggle}
                                className={`dlx-btn p-2 ${speech.enabled ? 'dlx-btn-secondary' : 'dlx-btn-ghost'}`}
                                style={speech.enabled ? { color: 'var(--accent-text)', backgroundColor: 'var(--accent-soft)' } : undefined}
                                title={
                                    speech.enabled
                                        ? 'Spoken progress on — click to mute'
                                        : 'Speak progress aloud while building'
                                }
                                aria-pressed={speech.enabled}
                            >
                                {speech.enabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
                            </button>
                        )}
                        <button onClick={onClose} className="dlx-btn dlx-btn-ghost p-2" title="Close Builder">
                            <X size={16} />
                        </button>
                    </div>
                </div>
            </div>

            <div
                className="grid grid-cols-5 gap-0.5 p-2"
                style={{ borderBottom: '1px solid var(--border-subtle)' }}
            >
                {tabs.map(({ id, label, icon: Icon }) => (
                    <button
                        key={id}
                        onClick={() => setTab(id)}
                        className="flex h-12 flex-col items-center justify-center gap-1 rounded-lg text-[10.5px] font-semibold transition-colors duration-150"
                        style={tab === id
                            ? { backgroundColor: 'var(--accent)', color: 'var(--text-on-accent)' }
                            : { color: 'var(--text-muted)' }}
                    >
                        <Icon size={16} />
                        {label}
                    </button>
                ))}
            </div>

            <div className="p-3 border-b border-[var(--border-default)] space-y-2">
                <select
                    value={providerId}
                    disabled={models.length === 0}
                    onChange={(event) => {
                        setProviderId(event.target.value);
                        // Back to auto for the new provider rather than silently
                        // pinning its first model.
                        setModelId('');
                    }}
                    className="dlx-input px-3 py-2 text-xs disabled:opacity-60"
                >
                    {models.length === 0 && <option value="">No providers — backend offline</option>}
                    {[...new Set(models.map((model) => model.provider_id))].map((provider) => (
                        <option key={provider} value={provider}>{provider}</option>
                    ))}
                </select>
                <select
                    value={modelId}
                    disabled={providerModels.length === 0}
                    onChange={(event) => setModelId(event.target.value)}
                    className="dlx-input px-3 py-2 text-xs disabled:opacity-60"
                >
                    {/* Empty asks the server to pick per task — a plan and a
                        colour palette do not want the same model. */}
                    <option value="">Auto — best model per task</option>
                    {providerModels.map((model) => (
                        <option key={`${model.provider_id}:${model.model_id}`} value={model.model_id}>{model.model_id}</option>
                    ))}
                </select>
                {!modelId && (
                    <p className="text-[11px] leading-snug text-slate-500 dark:text-slate-400">
                        Each step is routed to the strongest model you have a key for — planning and
                        code generation get the most capable one, small JSON steps get a fast one.
                    </p>
                )}
            </div>

            <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {tab === 'build' && (
                    <>
                        <select
                            value={buildKind}
                            onChange={(event) => setBuildKind(event.target.value as BuildKind)}
                            className="w-full border border-[var(--border-default)] rounded-md px-3 py-2 text-sm dlx-surface-2 text-slate-900 dark:text-slate-200"
                        >
                            <option value="chatbot">Complete chatbot</option>
                            <option value="agent">Agent</option>
                            <option value="tool">Tool</option>
                            <option value="function">Function tool</option>
                            <option value="workflow">Workflow</option>
                            <option value="api">Raw API to tool</option>
                            <option value="frontend">Chatbot frontend</option>
                        </select>
                        <div className="border border-[var(--border-default)] rounded-md dlx-sunken h-64 overflow-y-auto p-3 space-y-3">
                            {buildMessages.length === 0 && (
                                <div className="text-sm text-slate-500 dark:text-slate-400">
                                    Tell the builder what to create. Switch the type above for agents, tools, functions, workflows, APIs, full chatbots, or frontend.
                                </div>
                            )}
                            {buildMessages.map((chatMessage, index) => (
                                <div
                                    key={`${chatMessage.role}-${index}`}
                                    className={`text-sm rounded-md p-3 whitespace-pre-wrap ${
                                        chatMessage.role === 'user'
                                            ? 'bg-[var(--color-primary)] text-white ml-5'
                                            : 'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 mr-5'
                                    }`}
                                >
                                    {chatMessage.content || <GeneratingBubble />}
                                </div>
                            ))}
                        </div>
                        <textarea
                            value={buildInput}
                            onChange={(event) => setBuildInput(event.target.value)}
                            className="w-full min-h-24 border border-[var(--border-default)] rounded-md p-3 text-sm dlx-surface-2 text-slate-900 dark:text-slate-200"
                            placeholder="Describe what you want to build..."
                        />

                        {/* Talk it through. Speech lands in the brief above, so
                            the conversation produces what Build consumes. */}
                        <div className="flex items-center gap-2">
                            <button
                                ref={micRef}
                                onClick={() => {
                                    if (!voice.isActive) {
                                        setVoiceReply('');
                                        spokenTurn.current = '';
                                        buildRequested.current = false;
                                    }
                                    voice.toggle();
                                }}
                                title={voice.isActive ? 'Stop talking' : 'Describe it out loud'}
                                className={`relative shrink-0 h-9 w-9 rounded-full flex items-center justify-center transition-colors ${
                                    voice.isActive
                                        ? 'bg-[var(--color-primary)] text-white'
                                        : 'bg-slate-100 dark:bg-slate-900 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
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
                                        <span className="voice-ring-ambient" />
                                        <span className="voice-ring-live" />
                                    </>
                                )}
                            </button>
                            <div
                                ref={vizRef}
                                aria-hidden="true"
                                className={`voice-viz ${voice.isActive ? 'is-on' : ''}`}
                            >
                                {[0, 1, 2, 3, 4].map((bar) => (
                                    <i key={bar} />
                                ))}
                            </div>
                            <span className="text-[11px] leading-snug text-slate-500 dark:text-slate-400">
                                {voice.error
                                    ? voice.error
                                    : voice.state === 'speaking'
                                        ? 'Answering…'
                                        : voice.isActive
                                            ? 'Listening — what you say goes into the brief above'
                                            : 'Talk it through instead of typing'}
                            </span>
                        </div>
                        {voiceReply && (
                            <div className="rounded-md border border-[var(--border-default)] dlx-sunken/50 p-2 text-[12px] leading-snug text-slate-600 dark:text-slate-300">
                                <span className="font-semibold">Assistant: </span>
                                {voiceReply.slice(-400)}
                            </div>
                        )}

                        <div className="grid grid-cols-3 gap-2">
                            <button onClick={runChatBuilder} disabled={busy} className="dlx-btn dlx-btn-primary col-span-2 py-2 text-sm">
                                <Send size={15} /> Send
                            </button>
                            <button onClick={finalizeChatBuilder} disabled={busy || buildMessages.length === 0} className="bg-slate-900 dark:bg-slate-700 text-white rounded-md py-2 text-sm font-semibold disabled:opacity-50">
                                Generate
                            </button>
                            <button onClick={runPlan} disabled={busy} className="bg-white dark:bg-slate-800 border border-[var(--border-default)] text-slate-700 dark:text-slate-300 rounded-md py-2 text-xs font-semibold disabled:opacity-50">
                                Quick Plan
                            </button>
                            <button onClick={applyPlan} disabled={busy || !plan} className="col-span-2 bg-slate-900 dark:bg-slate-700 text-white rounded-md py-2 text-sm font-semibold disabled:opacity-50">
                                Apply
                            </button>
                        </div>
                        {plan && <pre className="text-xs bg-slate-950 text-slate-100 p-3 rounded-md overflow-auto max-h-96">{compactJson(plan)}</pre>}
                    </>
                )}

                {tab === 'api' && (
                    <>
                        <textarea value={specification} onChange={(event) => setSpecification(event.target.value)} className="w-full min-h-20 border border-[var(--border-default)] rounded-md p-3 text-sm dlx-surface-2 text-slate-900 dark:text-slate-200" />
                        <textarea value={rawApi} onChange={(event) => setRawApi(event.target.value)} className="w-full min-h-44 border border-[var(--border-default)] rounded-md p-3 text-sm font-mono dlx-surface-2 text-slate-900 dark:text-slate-200" />
                        <button onClick={runNormalizeApi} disabled={busy} className="dlx-btn dlx-btn-primary w-full py-2 text-sm">
                            Normalize API
                        </button>
                        {normalizedTool && <pre className="text-xs bg-slate-950 text-slate-100 p-3 rounded-md overflow-auto max-h-96">{compactJson(normalizedTool)}</pre>}
                    </>
                )}

                {tab === 'triggers' && (
                    <>
                        <div className="grid grid-cols-2 gap-2">
                            <button onClick={createChatTrigger} disabled={busy} className="dlx-btn dlx-btn-primary py-2 text-sm">Chat Trigger</button>
                            <button onClick={createWebhookTrigger} disabled={busy} className="bg-slate-900 dark:bg-slate-700 text-white rounded-md py-2 text-sm font-semibold disabled:opacity-50">Webhook</button>
                        </div>
                        {triggers.map((trigger) => (
                            <div key={trigger.id} className="border border-[var(--border-default)] rounded-md p-3 dlx-sunken">
                                <div className="flex items-start justify-between gap-2">
                                    <div>
                                        <div className="text-sm font-semibold text-slate-900 dark:text-white">{trigger.name}</div>
                                        <div className="text-xs text-slate-500 dark:text-slate-400">{trigger.type} · {trigger.workflow_id}</div>
                                        {trigger.public_slug && <div className="text-xs font-mono mt-1">/api/v1/webhooks/{trigger.public_slug}</div>}
                                    </div>
                                    <button onClick={() => deleteTrigger(trigger.id)} className="text-red-600 p-1"><Trash2 size={14} /></button>
                                </div>
                            </div>
                        ))}
                    </>
                )}

                {tab === 'frontend' && (
                    <>
                        <div className="rounded-md border border-[var(--border-default)] p-2.5 space-y-2">
                            <div className="text-xs font-semibold text-slate-600 dark:text-slate-300">Generation mode</div>
                            <div className="grid grid-cols-2 gap-2">
                                {([
                                    ['themed', 'Styled', 'Restyles the built-in page. Chat, history and buttons are the tested ones.'],
                                    ['custom', 'Custom HTML', 'The model writes the whole page. Any layout, but it can come back broken.'],
                                ] as const).map(([value, label, hint]) => (
                                    <button
                                        key={value}
                                        type="button"
                                        onClick={() => setFrontendMode(value)}
                                        className={`rounded-md border p-2 text-left transition-all ${frontendMode === value
                                            ? 'border-[var(--color-primary)] ring-2 ring-[var(--color-primary)]/25'
                                            : 'border-[var(--border-default)]'}`}
                                    >
                                        <div className="text-xs font-bold text-slate-800 dark:text-slate-200">{label}</div>
                                        <div className="mt-0.5 text-[11px] leading-snug text-slate-500 dark:text-slate-400">{hint}</div>
                                    </button>
                                ))}
                            </div>
                            {frontendMode === 'custom' && (
                                <p className="text-[11px] leading-snug text-amber-700 dark:text-amber-400">
                                    A generated page that cannot reach the API or has no working send button is
                                    rejected, and the styled page is used instead.
                                </p>
                            )}
                        </div>
                        <button onClick={useGeminiFrontendModel} className="w-full bg-slate-900 dark:bg-slate-700 text-white rounded-md py-2 text-sm font-semibold">
                            Use Gemini Pro
                        </button>
                        <div className="border border-[var(--border-default)] rounded-md dlx-sunken h-72 overflow-y-auto p-3 space-y-3">
                            {frontendMessages.length === 0 && (
                                <div className="text-sm text-slate-500 dark:text-slate-400">
                                    Describe the look you want — colours, tone, starter questions. The workflow behind it is untouched.
                                </div>
                            )}
                            {frontendMessages.map((chatMessage, index) => (
                                <div
                                    key={`${chatMessage.role}-${index}`}
                                    className={`text-sm rounded-md p-3 whitespace-pre-wrap ${
                                        chatMessage.role === 'user'
                                            ? 'bg-[var(--color-primary)] text-white ml-6'
                                            : 'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 mr-6'
                                    }`}
                                >
                                    {chatMessage.content || <GeneratingBubble />}
                                </div>
                            ))}
                        </div>
                        <textarea
                            value={frontendPrompt}
                            onChange={(event) => setFrontendPrompt(event.target.value)}
                            className="w-full min-h-28 border border-[var(--border-default)] rounded-md p-3 text-sm dlx-surface-2 text-slate-900 dark:text-slate-200"
                            placeholder="Ask Gemini to build or revise the chatbot frontend..."
                        />
                        <div className="grid grid-cols-2 gap-2">
                            <button onClick={runFrontendGenerate} disabled={busy} className="dlx-btn dlx-btn-primary py-2 text-sm">
                                Generate UI
                            </button>
                            <button onClick={runGeneratedFlashDeploy} disabled={busy || !frontendHtml} className="bg-slate-900 dark:bg-slate-700 text-white rounded-md py-2 text-sm font-semibold disabled:opacity-50">
                                Flash Deploy
                            </button>
                        </div>
                        {frontendHtml && (
                            <div className="space-y-3">
                                <div className="overflow-hidden rounded-lg border border-[var(--border-default)] dlx-surface-2">
                                    <div className="flex items-center justify-between border-b border-[var(--border-default)] dlx-sunken px-3 py-2">
                                        <div>
                                            <div className="text-sm font-semibold text-slate-900 dark:text-white">Live Preview</div>
                                            <div className="text-xs text-slate-500 dark:text-slate-400">Rendered custom chatbot frontend</div>
                                        </div>
                                        <a
                                            href={`data:text/html;charset=utf-8,${encodeURIComponent(frontendHtml)}`}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-primary)]"
                                        >
                                            Open Preview <ExternalLink size={12} />
                                        </a>
                                    </div>
                                    <iframe
                                        key={frontendHtml}
                                        title="Generated chatbot frontend preview"
                                        srcDoc={frontendHtml}
                                        sandbox="allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
                                        className="h-[28rem] w-full bg-white"
                                    />
                                </div>
                                <details className="rounded-lg border border-slate-200 bg-slate-950 text-slate-100">
                                    <summary className="cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-300">
                                        View HTML Source
                                    </summary>
                                    <pre className="max-h-96 overflow-auto border-t border-slate-800 p-3 text-xs">{frontendHtml}</pre>
                                </details>
                            </div>
                        )}
                    </>
                )}

                {tab === 'deploy' && (
                    <>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                            Deployments are served by this app at <span className="font-mono">/d/&lt;name&gt;/</span> — same origin, no extra ports.
                        </p>
                        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">
                            Chatbot title
                            <input
                                value={deployTitle}
                                onChange={(event) => setDeployTitle(event.target.value)}
                                placeholder={workflowLabel}
                                className="mt-1 w-full border border-[var(--border-default)] rounded-md px-2 py-1.5 text-sm font-normal dlx-surface-2 text-slate-900 dark:text-white"
                            />
                        </label>
                        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">
                            Greeting
                            <input
                                value={deployGreeting}
                                onChange={(event) => setDeployGreeting(event.target.value)}
                                placeholder="Hi, how can I help?"
                                className="mt-1 w-full border border-[var(--border-default)] rounded-md px-2 py-1.5 text-sm font-normal dlx-surface-2 text-slate-900 dark:text-white"
                            />
                        </label>
                        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">
                            Starter prompts
                            <textarea
                                value={deploySuggestions}
                                onChange={(event) => setDeploySuggestions(event.target.value)}
                                rows={3}
                                placeholder={'One per line, up to four\nWhat can you do?\nSummarise this week\'s releases'}
                                className="mt-1 w-full border border-[var(--border-default)] rounded-md px-2 py-1.5 text-sm font-normal dlx-surface-2 text-slate-900 dark:text-white resize-y"
                            />
                            <span className="mt-1 block font-normal text-[11px] text-slate-500 dark:text-slate-400">
                                Shown as chips on an empty conversation, so visitors know what to ask.
                            </span>
                        </label>
                        <div className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                            Theme
                            <div className="mt-1.5 grid grid-cols-3 gap-2">
                                {(themes.length ? themes : [{ id: 'midnight', label: 'Midnight', vars: {} } as ThemePreset]).map((preset) => (
                                    <button
                                        key={preset.id}
                                        type="button"
                                        onClick={() => setDeployTheme(preset.id)}
                                        className={`rounded-md border px-2 py-1.5 text-[11px] font-semibold transition-all ${deployTheme === preset.id ? 'border-[var(--color-primary)] ring-2 ring-[var(--color-primary)]/25' : 'border-[var(--border-default)]'}`}
                                        style={preset.vars?.bg ? { background: preset.vars.bg, color: preset.vars.text } : undefined}
                                    >
                                        <span className="flex items-center gap-1.5">
                                            {preset.vars?.accent && (
                                                <span className="h-2.5 w-2.5 rounded-full" style={{ background: preset.vars.accent }} />
                                            )}
                                            {preset.label}
                                        </span>
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div className="border border-[var(--border-default)] rounded-md p-3 space-y-2.5">
                            <label className="flex items-start gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
                                <input
                                    type="checkbox"
                                    checked={voiceEnabled}
                                    disabled={!voiceInfo?.key_available}
                                    onChange={(event) => setVoiceEnabled(event.target.checked)}
                                    className="mt-0.5"
                                />
                                <span>
                                    <span className="flex items-center gap-1.5">
                                        <Mic size={13} /> Live voice
                                    </span>
                                    <span className="mt-1 block font-normal text-[11px] text-slate-500 dark:text-slate-400">
                                        {voiceInfo === null
                                            ? 'No provider on this server advertises live voice.'
                                            : voiceInfo.key_available
                                                ? `Adds a mic to the deployed page, powered by ${voiceInfo.name}.`
                                                : `Set ${voiceInfo.key_env_var} on the server to enable ${voiceInfo.name} voice.`}
                                    </span>
                                </span>
                            </label>

                            {voiceEnabled && voiceInfo?.key_available && (
                                <div className="space-y-2.5 pl-5">
                                    <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                                        Realtime model
                                        <select
                                            value={voiceModel}
                                            onChange={(event) => setVoiceModel(event.target.value)}
                                            className="mt-1 w-full border border-[var(--border-default)] rounded-md px-2 py-1.5 text-sm font-normal dlx-surface-2 text-slate-900 dark:text-white"
                                        >
                                            <option value="">Server default</option>
                                            {voiceInfo.models.map((model) => (
                                                <option key={model} value={model}>{model}</option>
                                            ))}
                                        </select>
                                    </label>
                                    {voiceInfo.voices.length > 0 && (
                                        <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                                            Voice
                                            <select
                                                value={voiceName}
                                                onChange={(event) => setVoiceName(event.target.value)}
                                                className="mt-1 w-full border border-[var(--border-default)] rounded-md px-2 py-1.5 text-sm font-normal dlx-surface-2 text-slate-900 dark:text-white"
                                            >
                                                <option value="">Default</option>
                                                {voiceInfo.voices.map((voice) => (
                                                    <option key={voice} value={voice}>{voice}</option>
                                                ))}
                                            </select>
                                        </label>
                                    )}
                                    <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                                        Voice persona
                                        <textarea
                                            value={voicePrompt}
                                            onChange={(event) => setVoicePrompt(event.target.value)}
                                            rows={3}
                                            placeholder="Leave blank to reuse the entry agent's own system message."
                                            className="mt-1 w-full border border-[var(--border-default)] rounded-md px-2 py-1.5 text-sm font-normal dlx-surface-2 text-slate-900 dark:text-white resize-y"
                                        />
                                    </label>
                                    <p className="text-[11px] leading-snug text-amber-700 dark:text-amber-400">
                                        Voice replies come straight from the realtime model using this persona.
                                        Your canvas workflow, its tools and its routing do not run in voice mode —
                                        so a spoken answer can differ from a typed one.
                                    </p>
                                </div>
                            )}
                        </div>
                        <button onClick={runFlashDeploy} disabled={busy} className="dlx-btn dlx-btn-primary w-full py-2 text-sm">
                            <PlayCircle size={16} /> Flash Deploy
                        </button>
                        {deployments.map((deployment) => (
                            <div key={deployment.id} className="border border-[var(--border-default)] rounded-md p-3 dlx-sunken">
                                <div className="flex items-start justify-between gap-2">
                                    <div>
                                        <div className="text-sm font-semibold text-slate-900 dark:text-white">{deployment.title}</div>
                                        <div className="text-xs text-slate-500 dark:text-slate-400">{deployment.status} · {deployment.workflow_id}</div>
                                        {deployment.status === 'error' ? (
                                            <div className="text-xs text-red-600 dark:text-red-400 mt-1">{deployment.error || 'Generation failed.'}</div>
                                        ) : (
                                            <a href={deployment.url} target="_blank" rel="noreferrer" className="text-xs text-[var(--color-primary)] inline-flex items-center gap-1 mt-1">
                                                {deployment.url}<ExternalLink size={11} />
                                            </a>
                                        )}
                                    </div>
                                    <button onClick={() => deleteDeployment(deployment.id)} className="text-red-600 p-1"><Trash2 size={14} /></button>
                                </div>
                            </div>
                        ))}
                    </>
                )}

                {message && (
                    <div className={`text-xs rounded-md p-3 whitespace-pre-wrap border ${messageIsError
                        ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800/50 text-red-900 dark:text-red-300'
                        : 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800/50 text-amber-900 dark:text-amber-300'}`}>
                        {message}
                    </div>
                )}
            </div>
        </aside>
    );
};
