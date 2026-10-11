import { useState } from 'react';
import { Play, Plus } from 'lucide-react';
import { apiDetail, runConnectorAction } from '../../api/connectors';
import type { ConnectorAction, ConnectorParam } from '../../api/connectors';
import { useConnectorStore } from '../../stores/connectorStore';
import { AddConnectionSheet } from '../connections/AddConnectionSheet';
import type { JsonObject } from '../../types/json';

type Values = Record<string, string | boolean>;

const parseArg = (param: ConnectorParam, raw: string | boolean): unknown => {
    if (param.type === 'boolean') return Boolean(raw);
    const text = String(raw).trim();
    if (text === '') return undefined;
    if (param.type === 'integer') return Number(text);
    if (param.type === 'array') return text.split(',').map((item) => item.trim()).filter(Boolean);
    if (param.type === 'object') return JSON.parse(text);
    return text;
};

/**
 * A connector node: which account it acts as, its defaults, the actions its
 * agent may call, and a Test that runs one action for real.
 */
export const ConnectorForm = ({ config, onChange }: { config: JsonObject; onChange: (key: string, value: unknown) => void }) => {
    const { connectors, connections } = useConnectorStore();
    const connector = connectors.find((item) => item.id === config.connector);
    const [adding, setAdding] = useState(false);
    const [testAction, setTestAction] = useState('');
    const [values, setValues] = useState<Values>({});
    const [running, setRunning] = useState(false);
    const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);

    if (!connector) {
        return <p className="hint">Unknown connector “{String(config.connector ?? '')}”. It may have been removed from this server.</p>;
    }

    const ticked: string[] = Array.isArray(config.actions) ? config.actions : [];
    const options: JsonObject = (config.options ?? {}) as JsonObject;
    const mine = connections.filter((connection) => connection.connector === connector.id);
    const toggle = (action: ConnectorAction) => {
        const next = ticked.includes(action.id) ? ticked.filter((id) => id !== action.id) : [...ticked, action.id];
        onChange('actions', next);
    };
    const chosen = connector.actions.find((action) => action.id === (testAction || ticked[0]));

    const runTest = async () => {
        if (!chosen || !config.connection_id) return;
        setRunning(true);
        setOutcome(null);
        try {
            const args: JsonObject = {};
            for (const param of chosen.params) {
                const parsed = parseArg(param, values[param.name] ?? '');
                if (parsed !== undefined) args[param.name] = parsed;
            }
            const result = await runConnectorAction(String(config.connection_id), chosen.id, args, options);
            setOutcome({ ok: true, text: typeof result === 'string' ? result : JSON.stringify(result, null, 2) });
        } catch (failure) {
            setOutcome({ ok: false, text: failure instanceof SyntaxError ? `Invalid JSON: ${failure.message}` : apiDetail(failure) });
        } finally {
            setRunning(false);
        }
    };

    const actionGroup = (kind: 'read' | 'write', title: string, hint: string) => (
        <fieldset className="flex flex-col gap-1">
            <legend className="field-label">{title}</legend>
            <span className="hint">{hint}</span>
            {connector.actions.filter((action) => action.kind === kind).map((action) => (
                <label key={action.id} className="flex cursor-pointer items-start gap-2 py-0.5">
                    <input type="checkbox" checked={ticked.includes(action.id)} onChange={() => toggle(action)} aria-label={action.name} className="mt-0.5" />
                    <span className="min-w-0">
                        <span className="block text-[12.5px]">{action.name}</span>
                        <span className="hint block">{action.description}</span>
                    </span>
                </label>
            ))}
        </fieldset>
    );

    return (
        <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1">
                <span className="field-label">Connection</span>
                <div className="flex items-center gap-1.5">
                    <select className="select" value={String(config.connection_id ?? '')} onChange={(event) => onChange('connection_id', event.target.value)} aria-label="Connection">
                        <option value="">Choose an account…</option>
                        {mine.map((connection) => (
                            <option key={connection.id} value={connection.id}>{connection.account_label ?? connection.id}{connection.base_url ? ` · ${connection.base_url}` : ''}</option>
                        ))}
                    </select>
                    <button type="button" className="btn btn-sm" onClick={() => setAdding(true)}><Plus size={12} /> Connect…</button>
                </div>
                {!config.connection_id && <span className="hint" style={{ color: 'var(--clay)' }}>Pick the account this node acts as.</span>}
            </label>

            {connector.options.map((option) => (
                <label key={option.key} className="flex flex-col gap-1">
                    <span className="field-label">{option.label}</span>
                    <input
                        className="input"
                        value={String(options[option.key] ?? '')}
                        onChange={(event) => onChange('options', { ...options, [option.key]: event.target.value })}
                        aria-label={option.label}
                    />
                    {option.help && <span className="hint">{option.help}</span>}
                </label>
            ))}

            {actionGroup('read', 'Read', 'What the agent may look up.')}
            {actionGroup('write', 'Write', `What the agent may change in ${connector.name}. Off until you tick it.`)}
            {ticked.length === 0 && <span className="hint" style={{ color: 'var(--clay)' }}>Tick at least one action.</span>}

            <div className="flex flex-col gap-2">
                <span className="h-section">Test</span>
                <select className="select" value={chosen?.id ?? ''} onChange={(event) => { setTestAction(event.target.value); setValues({}); setOutcome(null); }} aria-label="Action to test">
                    {connector.actions.filter((action) => ticked.includes(action.id)).map((action) => <option key={action.id} value={action.id}>{action.name}</option>)}
                </select>
                {chosen?.params.map((param) => (
                    <label key={param.name} className="flex flex-col gap-1">
                        <span className="field-label">{param.name}{param.required ? ' *' : ''}</span>
                        {param.type === 'boolean' ? (
                            <input type="checkbox" checked={Boolean(values[param.name])} onChange={(event) => setValues({ ...values, [param.name]: event.target.checked })} aria-label={param.name} />
                        ) : param.type === 'object' ? (
                            <textarea className="textarea mono" rows={3} value={String(values[param.name] ?? '')} onChange={(event) => setValues({ ...values, [param.name]: event.target.value })} aria-label={param.name} placeholder="{}" />
                        ) : (
                            <input className="input" value={String(values[param.name] ?? '')} onChange={(event) => setValues({ ...values, [param.name]: event.target.value })} aria-label={param.name} placeholder={param.type === 'array' ? 'comma, separated' : param.default !== null && param.default !== undefined ? String(param.default) : ''} />
                        )}
                        <span className="hint">{param.description}</span>
                    </label>
                ))}
                {chosen?.kind === 'write' && <span className="hint" style={{ color: 'var(--clay)' }}>This changes the real {connector.name}.</span>}
                <button type="button" className="btn btn-sm self-start" disabled={running || !chosen || !config.connection_id} onClick={() => void runTest()}>
                    <Play size={10} fill="currentColor" /> {running ? 'Running…' : 'Run'}
                </button>
                {outcome && (
                    <pre className="well mono max-h-64 overflow-auto whitespace-pre-wrap p-2 text-[11px]" role={outcome.ok ? 'status' : 'alert'} style={{ color: outcome.ok ? 'var(--muted)' : 'var(--clay)' }}>{outcome.text}</pre>
                )}
            </div>

            <AddConnectionSheet open={adding} connectorId={connector.id} onClose={() => setAdding(false)} onAdded={(connection) => onChange('connection_id', connection.id)} />
        </div>
    );
};
