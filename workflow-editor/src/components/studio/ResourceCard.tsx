import type { LucideIcon } from 'lucide-react';
import { ChevronRight, GripVertical } from 'lucide-react';
import { useRef, useState } from 'react';
import type { CSSProperties, DragEvent } from 'react';
import type { NodeType } from '../../types/workflow';
import { StatusBadge } from './StatusBadge';

export type ResourceTone =
    | 'agent'
    | 'tool'
    | 'workflow'
    | 'trigger'
    | 'logic'
    | 'output'
    | 'security'
    | 'data'
    | 'connect';

/** The canvas kind colour each tone reads as. */
const TONE_LANE: Record<ResourceTone, string> = {
    agent: 'var(--k-agent)',
    tool: 'var(--k-tool)',
    workflow: 'var(--k-connect)',
    trigger: 'var(--k-trigger)',
    logic: 'var(--k-logic)',
    output: 'var(--k-output)',
    security: 'var(--k-trust)',
    data: 'var(--k-data)',
    connect: 'var(--k-connect)',
};

const laneOf = (tone: ResourceTone) => ({ '--lane': TONE_LANE[tone] } as CSSProperties);

export interface ResourceCardBadge {
    label: string;
    tone?: 'ready' | 'warning' | 'error' | 'running' | 'muted';
}

/**
 * Build the image that follows the cursor during a drag.
 *
 * The browser's default is a screenshot of the source element, which for a
 * 64px rail tile is a tiny, cropped smudge that tells you nothing about what
 * you are placing. This renders a proper labelled chip instead, so the drag
 * reads as "carrying a component" rather than "dragging a picture of a button".
 *
 * The node is positioned off-screen because setDragImage requires it to be in
 * the document and rendered, and is removed once the browser has snapshotted it.
 */
const buildDragGhost = (label: string, tone: ResourceTone): HTMLElement => {
    const ghost = document.createElement('div');
    ghost.style.cssText = [
        'position:fixed',
        'top:-1000px',
        'left:-1000px',
        'display:flex',
        'align-items:center',
        'gap:9px',
        'padding:7px 16px 7px 7px',
        'border-radius:999px',
        'background:var(--glass-raised)',
        'box-shadow:0 0 0 .5px var(--lg-edge), inset 0 1px 0 var(--lg-spec), 0 10px 26px -10px rgba(0,0,0,.3)',
        'font-family:var(--font)',
        'font-size:13px',
        'font-weight:600',
        'color:var(--text)',
        'white-space:nowrap',
        'pointer-events:none',
    ].join(';');

    const dot = document.createElement('span');
    dot.style.cssText = [
        'width:24px',
        'height:24px',
        'border-radius:999px',
        `background:color-mix(in srgb, ${TONE_LANE[tone]} 15%, transparent)`,
        'flex-shrink:0',
    ].join(';');

    const text = document.createElement('span');
    text.textContent = label;

    ghost.append(dot, text);
    document.body.appendChild(ghost);
    return ghost;
};

export const ResourceCard = ({
    type,
    label,
    description,
    icon: Icon,
    tone,
    badges = [],
    config,
    collapsed,
    level = 0,
    expandable = false,
    expanded = false,
    onToggle,
    onClick,
    compact = false,
}: {
    type: NodeType;
    label: string;
    description?: string;
    icon: LucideIcon;
    tone: ResourceTone;
    badges?: ResourceCardBadge[];
    config?: Record<string, any>;
    collapsed: boolean;
    level?: number;
    expandable?: boolean;
    expanded?: boolean;
    onToggle?: () => void;
    onClick?: () => void;
    compact?: boolean;
}) => {
    const [isDragging, setIsDragging] = useState(false);
    const ghostRef = useRef<HTMLElement | null>(null);

    const dragStart = (event: DragEvent) => {
        event.dataTransfer.setData('application/reactflow', type);
        event.dataTransfer.setData('application/reactflow-label', label);
        if (config) event.dataTransfer.setData('application/reactflow-config', JSON.stringify(config));
        event.dataTransfer.effectAllowed = 'move';

        const ghost = buildDragGhost(label, tone);
        ghostRef.current = ghost;
        // Offset so the chip sits under the cursor rather than hanging off it.
        event.dataTransfer.setDragImage(ghost, 20, 18);

        // Defer so the browser captures the drag image before we dim the source card.
        requestAnimationFrame(() => setIsDragging(true));
    };

    const dragEnd = () => {
        setIsDragging(false);
        ghostRef.current?.remove();
        ghostRef.current = null;
    };

    if (collapsed) {
        // Palette row: a kind tile and a name; the hint shows on hover.
        return (
            <button
                type="button"
                draggable
                onDragStart={dragStart}
                onDragEnd={dragEnd}
                onClick={onClick}
                data-dragging={isDragging}
                className="pal-row"
                style={laneOf(tone)}
                title={description ? `${label} — ${description}` : label}
            >
                <span className="tile is-sm"><Icon size={14} strokeWidth={1.8} /></span>
                <span className="min-w-0 truncate">{label}</span>
                <GripVertical size={13} className="pal-hint" />
            </button>
        );
    }

    return (
        <div
            draggable
            onDragStart={dragStart}
            onDragEnd={dragEnd}
            onClick={onClick}
            data-dragging={isDragging}
            className="dlx-draggable group relative mb-1 flex items-center gap-2 rounded-xl px-1.5 py-1.5 hover:bg-[var(--fill)]"
            style={{ marginLeft: `${level * 12}px`, ...laneOf(tone) }}
            title={description}
        >
            <button
                type="button"
                onClick={(event) => {
                    event.stopPropagation();
                    onToggle?.();
                }}
                className={`btn btn-ghost btn-sm btn-icon shrink-0 ${expandable ? '' : 'invisible'}`}
                aria-label={expanded ? 'Collapse' : 'Expand'}
                aria-expanded={expandable ? expanded : undefined}
            >
                <ChevronRight size={12} className={`transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`} />
            </button>

            <span className={`tile ${compact ? 'is-sm' : ''}`}>
                <Icon size={compact ? 14 : 16} strokeWidth={1.8} />
            </span>

            <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] font-medium" style={{ color: 'var(--text)' }}>{label}</span>
                    <GripVertical size={13} className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100" style={{ color: 'var(--dim)' }} />
                </div>
                {description && !compact && (
                    <div className="hint mt-0.5 line-clamp-2">{description}</div>
                )}
                {badges.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                        {badges.slice(0, compact ? 2 : 3).map((badge) => (
                            <StatusBadge key={badge.label} tone={badge.tone ?? 'muted'} label={badge.label} compact={compact} />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
