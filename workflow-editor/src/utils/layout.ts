import dagre from 'dagre';
import type { Node, Edge } from '@xyflow/react';

const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

// Reserve the real rendered footprint of the largest node type (agent cards run
// ~250px wide and ~140px tall with badges), plus generous rank/node gaps —
// undersizing these is what made auto-formatted nodes touch each other.
const NODE_WIDTH = 290;
const NODE_HEIGHT = 170;

/** Left-to-right dagre auto-layout, shared by the Format button and workflow drops. */
export const getLayoutedElements = (nodes: Node[], edges: Edge[]) => {
    dagreGraph.setGraph({ rankdir: 'LR', ranksep: 140, nodesep: 90 });

    nodes.forEach((node) => {
        dagreGraph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    });

    edges.forEach((edge) => {
        dagreGraph.setEdge(edge.source, edge.target);
    });

    dagre.layout(dagreGraph);

    const layoutedNodes = nodes.map((node) => {
        const nodeWithPosition = dagreGraph.node(node.id);
        return {
            ...node,
            position: {
                x: nodeWithPosition.x - NODE_WIDTH / 2,
                y: nodeWithPosition.y - NODE_HEIGHT / 2,
            },
        };
    });

    return { nodes: layoutedNodes, edges };
};

/**
 * True when a set of node positions is unusable for display: absent, or all crammed
 * into a tiny bounding box (stacked on top of each other). Workflows imported from
 * topology JSON often carry no positions at all.
 */
export const positionsAreDegenerate = (positions: Array<{ x?: number; y?: number } | undefined>) => {
    if (positions.length < 2) return false;
    const xs = positions.map((p) => p?.x ?? 0);
    const ys = positions.map((p) => p?.y ?? 0);
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);
    return spanX < 40 && spanY < 40;
};

type Px = `${number}px`;

/**
 * Framing for fitView that keeps the graph clear of the floating chrome: the
 * toolbar band above, the palette on the left while it is open, and the
 * capsules along the bottom. Zoom stops at 1 so a small graph is not blown up.
 */
export const canvasFit = (paletteOpen: boolean, duration?: number) => ({
    padding: {
        top: '80px' as Px,
        bottom: '64px' as Px,
        right: '48px' as Px,
        left: (paletteOpen ? '282px' : '48px') as Px,
    },
    maxZoom: 1,
    duration,
});
