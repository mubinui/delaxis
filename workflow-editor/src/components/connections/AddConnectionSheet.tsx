import { useState } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { api } from '../../api/client';
import { apiDetail } from '../../api/connectors';
import type { Connection } from '../../api/connectors';
import { useConnectorStore } from '../../stores/connectorStore';

const POLL_MS = 2000;
const POLL_LIMIT = 60;

/**
 * Add a connection: pick a connector, fill in what it asks for, and the server
 * verifies the credentials before saving. OAuth connectors (Gmail) open their
 * sign-in in a new window instead and the sheet waits for the account to appear.
 */
export const AddConnectionSheet = ({
    open, connectorId, onClose, onAdded,
}: { open: boolean; connectorId?: string; onClose: () => void; onAdded?: (connection: Connection) => void }) => {
    const { connectors, connections, add, refresh } = useConnectorStore();
    const [chosen, setChosen] = useState(connectorId ?? '');
    const [baseUrl, setBaseUrl] = useState('');
    const [username, setUsername] = useState('');
    const [token, setToken] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    if (!open) return null;
    const connector = connectors.find((item) => item.id === (chosen || connectorId || connectors[0]?.id));

    const save = async () => {
        if (!connector) return;
        setBusy(true);
        setError(null);
        try {
            const connection = await add({
                connector: connector.id,
                base_url: baseUrl.trim() || undefined,
                username: username.trim() || undefined,
                token: token.trim(),
            });
            setToken('');
            onAdded?.(connection);
            onClose();
        } catch (failure) {
            setError(apiDetail(failure));
        } finally {
            setBusy(false);
        }
    };

    const signIn = async () => {
        if (!connector?.auth.oauth_start) return;
        setBusy(true);
        setError(null);
        const before = new Set(connections.filter((item) => item.connector === connector.id).map((item) => item.id));
        try {
            const { auth_url: authUrl } = await api<{ auth_url: string }>(connector.auth.oauth_start);
            window.open(authUrl, '_blank', 'noopener,width=520,height=680');
            for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
                await new Promise((resolve) => setTimeout(resolve, POLL_MS));
                await refresh();
                const added = useConnectorStore.getState().connections.find((item) => item.connector === connector.id && !before.has(item.id));
                if (added) {
                    onAdded?.(added);
                    onClose();
                    return;
                }
            }
            setError('No account appeared. Finish the sign-in in the window that opened, then try again.');
        } catch (failure) {
            setError(apiDetail(failure));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="sheet-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
            <div className="sheet flex w-full max-w-md flex-col gap-4 px-6 pb-6 pt-5" role="dialog" aria-modal="true" aria-label="Add a connection">
                <div className="flex items-center justify-between gap-3">
                    <h2 className="title-2">Add a connection</h2>
                    <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close" title="Close"><X size={15} /></button>
                </div>
                <label className="flex flex-col gap-1">
                    <span className="field-label">Connector</span>
                    <select className="select" value={connector?.id ?? ''} onChange={(event) => { setChosen(event.target.value); setError(null); }} aria-label="Connector">
                        {connectors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                </label>
                {connector && <p className="hint">{connector.description}</p>}
                {connector?.auth.kind === 'oauth' ? (
                    <button type="button" className="btn btn-primary self-start" disabled={busy} onClick={() => void signIn()}>
                        <ExternalLink size={13} /> {busy ? 'Waiting for sign-in…' : `Sign in to ${connector.name}`}
                    </button>
                ) : connector && (
                    <form className="flex flex-col gap-3" onSubmit={(event) => { event.preventDefault(); void save(); }}>
                        {connector.auth.base_url && (
                            <label className="flex flex-col gap-1">
                                <span className="field-label">{connector.auth.base_url_label}</span>
                                <input className="input" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={connector.auth.base_url_default ?? 'https://'} aria-label={connector.auth.base_url_label} />
                            </label>
                        )}
                        {connector.auth.username_label && (
                            <label className="flex flex-col gap-1">
                                <span className="field-label">{connector.auth.username_label}</span>
                                <input className="input" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" aria-label={connector.auth.username_label} />
                            </label>
                        )}
                        <label className="flex flex-col gap-1">
                            <span className="field-label">{connector.auth.token_label}</span>
                            <input className="input" type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" aria-label={connector.auth.token_label} />
                            {connector.auth.token_help && <span className="hint">{connector.auth.token_help}</span>}
                        </label>
                        <button type="submit" className="btn btn-primary self-start" disabled={busy || !token.trim()}>
                            {busy ? 'Checking…' : 'Connect'}
                        </button>
                    </form>
                )}
                {error && <p className="text-[12.5px]" role="alert" style={{ color: 'var(--clay)' }}>{error}</p>}
            </div>
        </div>
    );
};
