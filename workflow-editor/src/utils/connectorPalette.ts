import type { LucideIcon } from 'lucide-react';
import { GitMerge, Mail, Plug, SquareKanban } from 'lucide-react';
import type { Connection, ConnectorInfo } from '../api/connectors';
import type { JsonObject } from '../types/json';

// lucide ships no brand marks, so each connector gets a generic glyph that reads as its job.
const ICONS: Record<string, LucideIcon> = { gitlab: GitMerge, jira: SquareKanban, gmail: Mail };

export const connectorIcon = (icon: string): LucideIcon => ICONS[icon] ?? Plug;

/** A freshly dropped connector node: no connection yet, read actions ticked, writes off. */
export const connectorNodeConfig = (connector: ConnectorInfo): JsonObject => ({
    type: 'connector',
    connector: connector.id,
    connection_id: '',
    actions: connector.actions.filter((action) => action.kind === 'read').map((action) => action.id),
    options: {},
});

export interface ConnectorTile {
    type: 'tool';
    label: string;
    icon: LucideIcon;
    tone: 'connect';
    hint: string;
    config: JsonObject;
}

export const connectorTiles = (connectors: ConnectorInfo[]): ConnectorTile[] =>
    connectors.map((connector) => ({
        type: 'tool',
        label: connector.name,
        icon: connectorIcon(connector.icon),
        tone: 'connect',
        hint: connector.description,
        config: connectorNodeConfig(connector),
    }));

const GMAIL_ACTIONS: Record<string, string> = { send: 'send_email', search: 'search_emails', read: 'read_email' };

/** A node saved with the old Gmail tool shape, as a Gmail connector node on the same account. */
export const upgradeLegacyGmail = (config: JsonObject, connections: Connection[]): JsonObject => {
    const capabilities: string[] = Array.isArray(config.capabilities) && config.capabilities.length
        ? config.capabilities
        : ['send', 'search', 'read'];
    const match = connections.find((connection) => connection.connector === 'gmail' && connection.account_label === config.account_email);
    const upgraded: JsonObject = {
        type: 'connector',
        connector: 'gmail',
        connection_id: match?.id ?? '',
        actions: capabilities.map((capability) => GMAIL_ACTIONS[capability]).filter(Boolean),
        options: {},
    };
    if (config.name) upgraded.name = config.name;
    return upgraded;
};
