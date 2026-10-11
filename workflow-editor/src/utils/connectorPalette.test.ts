import { describe, expect, it } from 'vitest';
import { connectorNodeConfig, connectorTiles, upgradeLegacyGmail } from './connectorPalette';
import type { Connection, ConnectorInfo } from '../api/connectors';

const auth = {
    kind: 'token', base_url: true, base_url_default: null, base_url_label: 'URL', username_label: null,
    username_required: false, token_label: 'Token', token_help: '', oauth_start: null,
} as const;

const jira: ConnectorInfo = {
    id: 'jira', name: 'Jira', icon: 'jira', description: 'Issues', auth, options: [],
    actions: [
        { id: 'search_issues', name: 'Search', kind: 'read', description: '', params: [] },
        { id: 'add_comment', name: 'Comment', kind: 'write', description: '', params: [] },
    ],
};

describe('connector palette', () => {
    it('ticks read actions only on a new node', () => {
        expect(connectorNodeConfig(jira)).toEqual({
            type: 'connector', connector: 'jira', connection_id: '', actions: ['search_issues'], options: {},
        });
    });

    it('makes one tool tile per connector', () => {
        const [tile] = connectorTiles([jira]);
        expect(tile.label).toBe('Jira');
        expect(tile.type).toBe('tool');
        expect(tile.tone).toBe('connect');
        expect(tile.config.connector).toBe('jira');
        expect(tile.icon).toBeTruthy();
    });

    it('upgrades a legacy Gmail node onto its connection', () => {
        const connections: Connection[] = [{
            id: 'c9', connector: 'gmail', account_label: 'ops@acme.test', base_url: null, auth_kind: 'oauth',
            options: {}, created_at: null, last_status: null, last_error: null, last_verified_at: null,
        }];
        expect(upgradeLegacyGmail({ type: 'gmail', account_email: 'ops@acme.test', capabilities: ['send', 'read'], name: 'mail' }, connections)).toEqual({
            type: 'connector', connector: 'gmail', connection_id: 'c9', actions: ['send_email', 'read_email'], options: {}, name: 'mail',
        });
        expect(upgradeLegacyGmail({ type: 'gmail', account_email: 'other@acme.test' }, connections).connection_id).toBe('');
        expect(upgradeLegacyGmail({ type: 'gmail' }, []).actions).toEqual(['send_email', 'search_emails', 'read_email']);
    });
});
