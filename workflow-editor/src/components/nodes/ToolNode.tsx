import { memo } from 'react';
import { Handle, Position, useConnection } from '@xyflow/react';
import type { Node, NodeProps } from '@xyflow/react';
import type { LucideIcon } from 'lucide-react';
import { Brain, Database, EyeOff, FileSearch, FileUp, Mail, Network, ScanEye, ScrollText, Server, Wrench } from 'lucide-react';
import type { WorkflowNodeData } from '../../types/workflow';
import { StatusGlyph } from '../shell/StatusGlyph';
import { getToolSummary } from '../../utils/studioDerivedState';
import { kindForTool, laneStyle, nodeStatusShape } from '../../utils/nodeTheme';
import { auxKindForToolType, isAuxHandle } from '../../utils/connectionRules';

const TOOL_TYPE_ICON: Record<string, LucideIcon> = {
    mcp: Server,
    database: Database,
    sql: Database,
    mongodb: Database,
    gmail: Mail,
    memory: Brain,
    knowledge: FileSearch,
};

const TOOL_TYPE_CAPTION: Record<string, string> = {
    mcp: 'MCP server',
    database: 'NL2SQL database',
    sql: 'SQL database',
    mongodb: 'MongoDB',
    gmail: 'Gmail',
    memory: 'Memory',
    knowledge: 'Knowledge',
    function: 'Function',
};

// Built-in function bundles get the icon of what they do rather than a wrench.
const FUNCTION_ICON: Record<string, LucideIcon> = { pii: EyeOff, audit: ScrollText, security: ScanEye, context: Network, files: FileUp, tool: Wrench };
const iconKey = (type: string, ids: string[]): string => {
    if (TOOL_TYPE_ICON[type]) return type;
    if (ids.some((id) => id.includes('pii'))) return 'pii';
    if (ids.some((id) => id.includes('audit'))) return 'audit';
    if (ids.some((id) => id.includes('security') || id.includes('secret') || id.includes('injection'))) return 'security';
    if (ids.some((id) => id.includes('context'))) return 'context';
    if (ids.some((id) => id.includes('file') || id.includes('image'))) return 'files';
    return 'tool';
};
const ALL_ICONS: Record<string, LucideIcon> = { ...FUNCTION_ICON, ...TOOL_TYPE_ICON };

/**
 * A tool, memory or knowledge source: a round sub-node, as n8n draws the things
 * an agent uses, with its name underneath. The diamond on top attaches it to an
 * agent's port.
 */
export const ToolNode = memo(({ data, selected }: NodeProps<Node<WorkflowNodeData>>) => {
    const summary = getToolSummary(data.config);

    // Highlight this tool's attach port when an agent port of the matching kind
    // is being dragged toward it. Selector form avoids re-rendering on every
    // pointer move of an in-progress connection.
    const attachWanted = useConnection(
        (conn) =>
            conn.inProgress &&
            conn.fromNode?.type === 'agent' &&
            isAuxHandle(conn.fromHandle?.id) &&
            conn.fromHandle?.id === auxKindForToolType(summary.type),
    );

    const ids: string[] = Array.isArray(data.config?.tool_ids) ? data.config.tool_ids.map(String) : [];
    const Icon = ALL_ICONS[iconKey(summary.type, ids)];
    const shape = nodeStatusShape(data.status, summary.health);
    const state = data.status === 'error' ? 'is-error' : data.status === 'running' ? 'is-running' : '';

    const caption = summary.issues[0]
        ?? [
            summary.type === 'api' ? `${summary.method} action` : (TOOL_TYPE_CAPTION[summary.type] ?? 'Function'),
            summary.type === 'mcp' && summary.transport ? summary.transport : '',
            summary.type === 'gmail' && summary.accountEmail ? summary.accountEmail : '',
            (summary.type === 'api' || summary.type === 'function') && summary.auth !== 'none' ? summary.auth : '',
        ].filter(Boolean).join(' · ');

    return (
        <div className={`node-shape is-orb ${state} ${selected ? 'is-selected' : ''}`} style={laneStyle(kindForTool(data.config))}>
            <Handle type="target" position={Position.Left} />
            <Handle id="attach" type="source" position={Position.Top} className={`is-port is-attached ${attachWanted ? 'is-wanted' : ''}`} />

            <Icon size={22} strokeWidth={1.7} />
            {shape && <span className="node-badge"><StatusGlyph shape={shape} /></span>}

            <span className="node-caption">
                <span className="node-title" title={data.label}>{data.label}</span>
                <span className="node-sub">{caption}{data.lastOutput ? ' · ran' : ''}</span>
            </span>

            <Handle type="source" position={Position.Right} />
        </div>
    );
});
