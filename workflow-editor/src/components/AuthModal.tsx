import React, { useCallback, useEffect, useState } from 'react';
import { X, Shield, Key, CheckCircle2, AlertCircle, RefreshCw, Plus, Trash2, Copy } from 'lucide-react';
import { api } from '../api/client';

interface AuthModalProps {
    isOpen: boolean;
    onClose: () => void;
}

interface ApiKeyInfo {
    id: string;
    name: string;
    role: string;
    active: boolean;
    created_at: string;
    expires_at?: string | null;
}

const TOKEN_KEY = 'delaxis-access-token';

export const getStoredToken = (): string | null => sessionStorage.getItem(TOKEN_KEY);

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose }) => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [status, setStatus] = useState<{ type: 'idle' | 'success' | 'error'; msg: string }>({ type: 'idle', msg: '' });
    const [activeTab, setActiveTab] = useState<'login' | 'keys'>('login');
    const [loggedInUser, setLoggedInUser] = useState<string | null>(null);
    const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
    const [newKeyName, setNewKeyName] = useState('');
    const [createdKey, setCreatedKey] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const authHeaders = useCallback((): Record<string, string> => {
        const token = getStoredToken();
        return token ? { Authorization: `Bearer ${token}` } : {};
    }, []);

    const loadCurrentUser = useCallback(async () => {
        try {
            const me = await api<{ username?: string }>('/api/v1/auth/users/me', { headers: authHeaders() });
            if (me?.username) setLoggedInUser(me.username);
        } catch {
            setLoggedInUser(null);
        }
    }, [authHeaders]);

    const loadKeys = useCallback(async () => {
        try {
            const list = await api<ApiKeyInfo[]>('/api/v1/auth/api-keys', { headers: authHeaders() });
            setKeys(list);
        } catch (e) {
            setKeys([]);
            setStatus({ type: 'error', msg: e instanceof Error ? e.message : String(e) });
        }
    }, [authHeaders]);

    useEffect(() => {
        if (isOpen) {
            void loadCurrentUser();
            if (activeTab === 'keys') void loadKeys();
        }
    }, [isOpen, activeTab, loadCurrentUser, loadKeys]);

    if (!isOpen) return null;

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        setStatus({ type: 'idle', msg: '' });
        try {
            const form = new URLSearchParams({ username, password });
            const response = await fetch('/api/v1/auth/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: form.toString(),
            });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                throw new Error(body?.detail || `Login failed (HTTP ${response.status})`);
            }
            const data = await response.json();
            sessionStorage.setItem(TOKEN_KEY, data.access_token);
            setLoggedInUser(username);
            setStatus({ type: 'success', msg: `Signed in as ${username}.` });
        } catch (err) {
            setStatus({ type: 'error', msg: err instanceof Error ? err.message : String(err) });
        } finally {
            setBusy(false);
        }
    };

    const handleLogout = () => {
        sessionStorage.removeItem(TOKEN_KEY);
        setLoggedInUser(null);
        setStatus({ type: 'success', msg: 'Signed out.' });
    };

    const handleCreateKey = async () => {
        setBusy(true);
        setCreatedKey(null);
        try {
            const created = await api<{ key: string }>('/api/v1/auth/api-keys', {
                method: 'POST',
                headers: authHeaders(),
                body: JSON.stringify({ name: newKeyName || 'studio-key' }),
            });
            setCreatedKey(created.key);
            setNewKeyName('');
            await loadKeys();
            setStatus({ type: 'success', msg: 'API key created. Copy it now — it is shown only once.' });
        } catch (e) {
            setStatus({ type: 'error', msg: e instanceof Error ? e.message : String(e) });
        } finally {
            setBusy(false);
        }
    };

    const handleRevokeKey = async (id: string) => {
        try {
            await api(`/api/v1/auth/api-keys/${id}`, { method: 'DELETE', headers: authHeaders() });
            await loadKeys();
        } catch (e) {
            setStatus({ type: 'error', msg: e instanceof Error ? e.message : String(e) });
        }
    };

    return (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 transition-opacity">
            <div className="bg-white dark:bg-[#0b111b] border border-gray-200 dark:border-slate-800 w-full max-w-md rounded-2xl shadow-2xl overflow-hidden flex flex-col">
                {/* Header */}
                <div className="px-6 py-4 border-b border-gray-100 dark:border-slate-800/80 flex items-center justify-between bg-gray-50/50 dark:bg-slate-900/30">
                    <div className="flex items-center gap-2">
                        <Shield className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                        <span className="text-xs font-bold text-gray-900 dark:text-white uppercase tracking-wider">
                            Account & API Keys
                        </span>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors">
                        <X className="w-4 h-4" />
                    </button>
                </div>

                {/* Tabs Strip */}
                <div className="flex border-b border-gray-100 dark:border-slate-800/60 bg-gray-50/20 dark:bg-slate-950/20 text-xs">
                    {(['login', 'keys'] as const).map((tab) => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={`flex-1 py-2.5 font-semibold text-center border-b-2 transition-all ${activeTab === tab
                                ? 'border-blue-600 text-blue-600 dark:text-blue-400 bg-white dark:bg-slate-900/40'
                                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
                                }`}
                        >
                            {tab === 'login' ? 'Sign In' : 'API Keys'}
                        </button>
                    ))}
                </div>

                {/* Status Message Alert */}
                {status.msg && (
                    <div
                        className={`mx-6 mt-4 p-3 rounded-xl text-xs flex items-start gap-2 border transition-all ${status.type === 'success'
                            ? 'bg-green-50 dark:bg-emerald-950/30 text-green-700 dark:text-emerald-300 border-green-200 dark:border-emerald-800'
                            : 'bg-red-50 dark:bg-rose-950/30 text-red-700 dark:text-rose-300 border-red-200 dark:border-rose-800'
                            }`}
                    >
                        {status.type === 'success' ? (
                            <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                        ) : (
                            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                        )}
                        <span className="leading-relaxed">{status.msg}</span>
                    </div>
                )}

                {/* Tab 1: Sign in with a local account */}
                {activeTab === 'login' && (
                    <form onSubmit={handleLogin} className="p-6 flex flex-col gap-4">
                        {loggedInUser ? (
                            <div className="flex items-center justify-between p-3 rounded-xl border border-gray-200 dark:border-slate-800 text-xs">
                                <span className="text-gray-700 dark:text-gray-300">
                                    Signed in as <strong>{loggedInUser}</strong>
                                </span>
                                <button
                                    type="button"
                                    onClick={handleLogout}
                                    className="px-3 py-1.5 font-semibold text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 rounded-lg"
                                >
                                    Sign out
                                </button>
                            </div>
                        ) : (
                            <>
                                <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                                    Sign in with a local account. The first admin account is created from the
                                    <span className="font-mono"> DELAXIS_ADMIN_USERNAME</span> /
                                    <span className="font-mono"> DELAXIS_ADMIN_PASSWORD</span> environment variables.
                                    In development mode, all endpoints work without signing in.
                                </p>
                                <div>
                                    <label className="text-xs font-semibold text-gray-700 dark:text-gray-300 block mb-1">Username</label>
                                    <input
                                        type="text"
                                        value={username}
                                        onChange={(e) => setUsername(e.target.value)}
                                        required
                                        autoComplete="username"
                                        className="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white focus:outline-none focus:border-blue-500 transition-colors"
                                    />
                                </div>
                                <div>
                                    <label className="text-xs font-semibold text-gray-700 dark:text-gray-300 block mb-1">Password</label>
                                    <input
                                        type="password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        required
                                        autoComplete="current-password"
                                        className="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white focus:outline-none focus:border-blue-500 transition-colors"
                                    />
                                </div>
                                <button
                                    type="submit"
                                    disabled={busy}
                                    className="mt-2 w-full py-2.5 text-xs font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-md shadow-blue-600/10 transition-all disabled:opacity-50"
                                >
                                    {busy ? 'Signing in…' : 'Sign In'}
                                </button>
                            </>
                        )}
                    </form>
                )}

                {/* Tab 2: Real API key management */}
                {activeTab === 'keys' && (
                    <div className="p-6 flex flex-col gap-4">
                        <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40 text-amber-800 dark:text-amber-300 text-xs flex items-start gap-2">
                            <Key className="w-4 h-4 mt-0.5 shrink-0" />
                            <span className="leading-relaxed">
                                API keys authenticate programmatic access (Authorization: Bearer dlx_…). The
                                plaintext key is shown exactly once at creation.
                            </span>
                        </div>

                        {createdKey && (
                            <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 text-xs">
                                <div className="flex items-center justify-between gap-2">
                                    <code className="font-mono text-emerald-800 dark:text-emerald-300 break-all">{createdKey}</code>
                                    <button
                                        onClick={() => navigator.clipboard.writeText(createdKey)}
                                        className="p-1.5 rounded-lg hover:bg-emerald-100 dark:hover:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 shrink-0"
                                        title="Copy key"
                                    >
                                        <Copy className="w-3.5 h-3.5" />
                                    </button>
                                </div>
                            </div>
                        )}

                        <div className="border border-gray-100 dark:border-slate-800 rounded-xl overflow-hidden divide-y divide-gray-50 dark:divide-slate-800/60">
                            {keys.length === 0 && (
                                <div className="p-4 text-center text-xs text-gray-400 dark:text-slate-500">No API keys yet.</div>
                            )}
                            {keys.map((key) => (
                                <div key={key.id} className="p-3 flex items-center justify-between bg-gray-50/50 dark:bg-slate-900/20 text-[11px]">
                                    <div>
                                        <span className="font-bold text-gray-900 dark:text-white block">{key.name}</span>
                                        <span className="text-gray-400 dark:text-slate-500">
                                            {key.role} · created {new Date(key.created_at).toLocaleDateString()}
                                        </span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-green-100 dark:bg-emerald-950 text-green-700 dark:text-emerald-400">
                                            Active
                                        </span>
                                        <button
                                            onClick={() => void handleRevokeKey(key.id)}
                                            className="p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 rounded"
                                            title="Revoke key"
                                        >
                                            <Trash2 className="w-3.5 h-3.5" />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="flex gap-2">
                            <input
                                value={newKeyName}
                                onChange={(e) => setNewKeyName(e.target.value)}
                                placeholder="Key name (e.g. ci-pipeline)"
                                className="flex-1 px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-900 dark:text-white focus:outline-none focus:border-blue-500"
                            />
                            <button
                                onClick={() => void handleCreateKey()}
                                disabled={busy}
                                className="px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors flex items-center gap-1.5 disabled:opacity-50"
                            >
                                {busy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                                Create
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
