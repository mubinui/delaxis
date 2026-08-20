import type { LucideIcon } from 'lucide-react';
import { ChevronRight, GripVertical } from 'lucide-react';
import { useRef, useState } from 'react';
import type { DragEvent } from 'react';
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
    | 'data';

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
    ghost.setAttribute('data-tone', tone);
    ghost.style.cssText = [
        'position:fixed',
        'top:-1000px',
        'left:-1000px',
        'display:flex',
        'align-items:center',
        'gap:8px',
        'padding:8px 14px 8px 10px',
        'border-radius:var(--radius-lg)',
        'background:var(--surface-2)',
        'border:1px solid var(--tone-border)',
        'box-shadow:var(--shadow-lg)',
        'font-family:Inter,system-ui,sans-serif',
        'font-size:12px',
        'font-weight:600',
        'color:var(--text-primary)',
        'white-space:nowrap',
        'pointer-events:none',
    ].join(';');

    const dot = document.createElement('span');
    dot.style.cssText = [
        'width:22px',
        'height:22px',
        'border-radius:var(--radius-sm)',
        'background:var(--tone-bg)',
        'border:1px solid var(--tone-border)',
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
        // Rail tile: a compact, tone-coloured glyph with its name underneath.
        return (
            <button
                draggable
                onDragStart={dragStart}
                onDragEnd={dragEnd}
                onClick={onClick}
                data-tone={tone}
                data-dragging={isDragging}
                className="dlx-tile"
                title={description ? `${label} — ${description}` : label}
            >
                <span className="dlx-glyph h-9 w-9">
                    <Icon size={15} strokeWidth={2.1} />
                </span>
                <span className="dlx-tile-label">{label}</span>
            </button>
        );
    }

    return (
        <div
            draggable
            onDragStart={dragStart}
            onDragEnd={dragEnd}
            onClick={onClick}
            data-tone={tone}
            data-dragging={isDragging}
            className={`dlx-card dlx-draggable group relative mb-1.5 ${compact ? 'p-2' : 'p-2.5'}`}
            style={{ marginLeft: `${level * 12}px` }}
            title={description}
        >
            <div className="flex items-center gap-2">
                <button
                    type="button"
                    onClick={(event) => {
                        event.stopPropagation();
                        onToggle?.();
                    }}
                    className={`dlx-btn-ghost rounded p-0.5 ${expandable ? '' : 'invisible'}`}
                    aria-label={expanded ? 'Collapse resource' : 'Expand resource'}
                >
                    <ChevronRight
                        size={12}
                        className={`transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`}
                    />
                </button>

                <span className={`dlx-glyph ${compact ? 'h-7 w-7' : 'h-8 w-8'}`}>
                    <Icon size={compact ? 14 : 16} strokeWidth={2.2} />
                </span>

                <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                        <span className="dlx-text truncate text-sm font-semibold">{label}</span>
                        <GripVertical
                            size={13}
                            className="dlx-faint shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                        />
                    </div>
                    {description && !compact && (
                        <div className="dlx-muted mt-0.5 line-clamp-2 text-[10px] leading-4">{description}</div>
                    )}
                    {badges.length > 0 && (
                        <div className={`${compact ? 'mt-1' : 'mt-2'} flex flex-wrap gap-1`}>
                            {badges.slice(0, compact ? 2 : 3).map((badge) => (
                                <StatusBadge
                                    key={badge.label}
                                    tone={badge.tone ?? 'muted'}
                                    label={badge.label}
                                    compact={compact}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
