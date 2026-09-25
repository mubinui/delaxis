import type { Connection, Edge } from '@xyflow/react';
import type { VisualNode } from '../types/workflow';

/** Agent-node bottom handles that accept auxiliary attachments. */
export const AUX_HANDLES = ['tools', 'memory', 'knowledge'] as const;
export type AuxHandle = (typeof AUX_HANDLES)[number];

export const isAuxHandle = (handle: string | null | undefined): handle is AuxHandle =>
    AUX_HANDLES.includes(handle as AuxHandle);

/** Which agent handle a tool node belongs on, by its config.type. */
export const auxKindForToolType = (toolType?: string): AuxHandle => {
    if (toolType === 'memory') return 'memory';
    if (toolType === 'knowledge') return 'knowledge';
    return 'tools';
};

/**
 * Aux handles are typed: only a tool node of the matching kind may land on
 * them (Memory Store → memory, Knowledge Source → knowledge, everything else
 * → tools). Flow connections (left/right handles) stay unrestricted so
 * existing canvases keep working.
 */
export const isValidConnection = (
    connection: Connection | Edge,
    nodes: VisualNode[],
): boolean => {
    const source = nodes.find((node) => node.id === connection.source);
    const target = nodes.find((node) => node.id === connection.target);

    // A drag that starts on a tool's top `attach` handle is always an
    // attachment: it may only land on the matching agent aux handle. Without
    // this, dropping near the agent snapped to its left flow handle and
    // silently created a flow edge — which felt like "it won't connect".
    if (connection.sourceHandle === 'attach') {
        if (!source || !target || source.type !== 'tool' || target.type !== 'agent') return false;
        return (
            isAuxHandle(connection.targetHandle) &&
            auxKindForToolType(source.data?.config?.type) === connection.targetHandle
        );
    }

    if (!isAuxHandle(connection.targetHandle)) return true;

    if (!source || !target) return false;
    if (target.type !== 'agent' || source.type !== 'tool') return false;
    return auxKindForToolType(source.data?.config?.type) === connection.targetHandle;
};

/** Distinct look for attachment edges so they read differently from flow edges. */
export const AUX_EDGE_OPTIONS = {
    type: 'straight' as const,
    animated: false,
    style: { strokeWidth: 1.5, strokeDasharray: '4 5', stroke: 'var(--wire)' },
};
