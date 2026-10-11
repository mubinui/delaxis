import { useEffect, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { Toolbar, MoreMenu } from './shell/Toolbar';
import { ActivityCapsule } from './shell/ActivityCapsule';
import { StatusGlyph } from './shell/StatusGlyph';
import { AddConnectionSheet } from './connections/AddConnectionSheet';
import { useUiStore } from '../stores/uiStore';
import { useConnectorStore } from '../stores/connectorStore';
import { apiDetail } from '../api/connectors';
import type { ConnectionTest } from '../api/connectors';

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—');

/** The accounts this installation can act as: add, check and remove them. */
export const ConnectionsPage = () => {
    const go = useUiStore((state) => state.go);
    const { connectors, connections, loaded, error, refresh, remove, test } = useConnectorStore();
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [adding, setAdding] = useState(false);
    const [testResult, setTestResult] = useState<{ id: string; result: ConnectionTest } | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    const selected = connections.find((connection) => connection.id === selectedId) ?? connections[0];
    const nameOf = (id: string) => connectors.find((connector) => connector.id === id)?.name ?? id;
    const shownTest = testResult && selected && testResult.id === selected.id ? testResult.result : null;

    const runTest = async (id: string) => {
        setActionError(null);
        try {
            setTestResult({ id, result: await test(id) });
        } catch (failure) {
            setActionError(apiDetail(failure));
        }
    };

    const removeSelected = async () => {
        if (!selected) return;
        if (!confirm(`Remove the ${nameOf(selected.connector)} connection ${selected.account_label ?? ''}? Workflows using it will stop until you pick another.`)) return;
        setActionError(null);
        try {
            await remove(selected.id);
            setSelectedId(null);
        } catch (failure) {
            setActionError(apiDetail(failure));
        }
    };

    return (
        <>
            <div className="page">
                <div className="page-inner">
                    <div className="page-head">
                        <div>
                            <h1 className="display">Connections</h1>
                            <p className="lead mt-1 max-w-[680px]">
                                Accounts your workflows act as in Jira, GitLab and Gmail. Connect one once; every connector node can use it.
                                Tokens are checked before they are saved and stored encrypted.
                            </p>
                        </div>
                        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
                            <Plus size={13} /> Add connection
                        </button>
                    </div>

                    {error && <p className="mt-4 text-[12.5px]" role="alert" style={{ color: 'var(--clay)' }}>Could not load connections: {error}</p>}

                    {loaded && connections.length === 0 && !error && (
                        <div className="panel empty-state mt-5">
                            <div className="headline">No connections yet</div>
                            <p className="hint max-w-[380px]">Add a Jira or GitLab token, or sign in to Gmail, and connector nodes can use it.</p>
                            <button type="button" className="btn mt-2" onClick={() => setAdding(true)}>Add connection</button>
                        </div>
                    )}

                    {connections.length > 0 && (
                        <div className="split-layout">
                            <div className="table-box">
                                <table className="mtable" aria-label="Connections">
                                    <thead><tr><th>Account</th><th>Connector</th><th className="hide-narrow">Added</th><th>Status</th></tr></thead>
                                    <tbody>
                                        {connections.map((connection) => (
                                            <tr key={connection.id} aria-selected={connection.id === selected?.id} onClick={() => setSelectedId(connection.id)}>
                                                <td style={{ maxWidth: 0, width: '40%' }}>
                                                    <button type="button" className="row-title" onFocus={() => setSelectedId(connection.id)}>{connection.account_label ?? nameOf(connection.connector)}</button>
                                                    {connection.base_url && <span className="row-sub mono">{connection.base_url}</span>}
                                                </td>
                                                <td>{nameOf(connection.connector)}</td>
                                                <td className="hide-narrow">{when(connection.created_at)}</td>
                                                <td>
                                                    <span className="row-status">
                                                        <StatusGlyph shape={connection.last_status === 'failed' ? 'bad' : connection.last_status === 'ok' ? 'ok' : 'idle'} />
                                                        {connection.last_status === 'failed' ? 'Failing' : connection.last_status === 'ok' ? 'Working' : 'Not checked'}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            {selected && (
                                <aside className="inspector" aria-label="Connection details">
                                    <div>
                                        <h2 className="title-2">{selected.account_label ?? nameOf(selected.connector)}</h2>
                                        <div className="text-dim mt-0.5">{nameOf(selected.connector)}</div>
                                    </div>
                                    <div className="rows">
                                        {selected.base_url && <div><span className="row-k">Site</span><span className="row-v mono">{selected.base_url}</span></div>}
                                        <div><span className="row-k">Sign-in</span><span className="row-v">{selected.auth_kind === 'oauth' ? 'Google sign-in' : 'Token'}</span></div>
                                        <div><span className="row-k">Added</span><span className="row-v">{when(selected.created_at)}</span></div>
                                        <div><span className="row-k">Last checked</span><span className="row-v">{when(selected.last_verified_at)}</span></div>
                                    </div>
                                    {selected.last_error && <p className="text-[12px]" style={{ color: 'var(--clay)' }}>{selected.last_error}</p>}
                                    {shownTest && (
                                        <p className="text-[12.5px]" role="status" style={{ color: shownTest.ok ? 'inherit' : 'var(--clay)' }}>
                                            {shownTest.ok ? `Working — signed in as ${shownTest.account_label}` : shownTest.error}
                                        </p>
                                    )}
                                    {actionError && <p className="text-[12px]" role="alert" style={{ color: 'var(--clay)' }}>{actionError}</p>}
                                    <div className="flex items-center gap-1.5">
                                        <button type="button" className="btn btn-sm" onClick={() => void runTest(selected.id)}>Test</button>
                                        <span className="flex-1" />
                                        <button type="button" className="btn btn-danger btn-sm" onClick={() => void removeSelected()}>Remove</button>
                                    </div>
                                </aside>
                            )}
                        </div>
                    )}
                </div>
            </div>
            <AddConnectionSheet open={adding} onClose={() => setAdding(false)} onAdded={(connection) => setSelectedId(connection.id)} />
            <Toolbar
                center={<ActivityCapsule onStatusClick={() => go('studio')} />}
                actions={
                    <>
                        <button type="button" className="btn btn-toolbar btn-icon" onClick={() => void refresh()} aria-label="Refresh" title="Refresh">
                            <RefreshCw size={15} strokeWidth={1.8} />
                        </button>
                        <MoreMenu />
                    </>
                }
            />
        </>
    );
};
