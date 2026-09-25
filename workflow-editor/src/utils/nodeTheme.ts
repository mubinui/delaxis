// The kind colour of a canvas component. Kind is data coding only: it colours the
// component's icon tile and nothing else — never its border, its selection or its
// state, which are ink, red and the status glyph. Values are CSS variables, so a
// node repaints with the theme instead of freezing whatever it was drawn with.
import type { CSSProperties } from 'react';
import type { StatusShape } from '../components/shell/StatusGlyph';

export type NodeKind = 'trigger' | 'agent' | 'logic' | 'tool' | 'data' | 'trust' | 'connect' | 'output';

export const laneStyle = (kind: NodeKind): CSSProperties => ({ '--lane': `var(--k-${kind})` } as CSSProperties);

const TRUST_TOOLS = ['security_scan', 'scan_for_secrets', 'detect_prompt_injection', 'detect_pii', 'redact_pii', 'record_audit_event', 'query_audit_log'];
const DATA_TOOLS = ['analyze_file', 'analyze_image', 'list_uploaded_files', 'context_tree', 'search_context_tree', 'read_context_file'];

/** Which kind a tool node reads as, from its configuration alone. */
export const kindForTool = (config: Record<string, any> | undefined): NodeKind => {
    const type = String(config?.type ?? 'function');
    if (type === 'memory' || type === 'knowledge') return 'logic';
    if (type === 'sql' || type === 'database' || type === 'mongodb') return 'data';
    if (type === 'mcp' || type === 'gmail') return 'connect';
    const ids: string[] = Array.isArray(config?.tool_ids) ? config.tool_ids.map(String) : [];
    if (ids.length && ids.every((id) => TRUST_TOOLS.includes(id))) return 'trust';
    if (ids.length && ids.every((id) => DATA_TOOLS.includes(id))) return 'data';
    return 'tool';
};

/**
 * The glyph a node shows. A healthy node shows nothing, so the canvas stays
 * quiet; a run, a problem or a failure earns a mark.
 */
export const nodeStatusShape = (status: unknown, health: 'ready' | 'warning' | 'error', ran = false): StatusShape | null => {
    if (status === 'running') return 'busy';
    if (status === 'error' || health === 'error') return 'bad';
    // After a run, a node that produced output says so, as n8n's green tick does.
    if (ran) return 'ok';
    if (health === 'warning') return 'warn';
    return null;
};
