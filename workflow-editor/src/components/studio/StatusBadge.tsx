import type { LucideIcon } from 'lucide-react';
import { StatusGlyph } from '../shell/StatusGlyph';
import type { StatusShape } from '../shell/StatusGlyph';

type StatusTone = 'ready' | 'warning' | 'error' | 'running' | 'muted';

const TONE_CHIP: Record<StatusTone, string> = {
    ready: 'chip chip-ok',
    warning: 'chip chip-warn',
    error: 'chip chip-bad',
    running: 'chip',
    muted: 'chip',
};

const TONE_SHAPE: Record<StatusTone, StatusShape | null> = {
    ready: 'ok',
    warning: 'warn',
    error: 'bad',
    running: 'busy',
    muted: null,
};

/**
 * A tinted capsule. A status badge leads with the status shape — disc, ring,
 * diamond or spinning ring — so it reads without its colour; a badge given an
 * icon is a plain label instead.
 */
export const StatusBadge = ({
    tone,
    label,
    icon: Icon,
    className = '',
    compact = false,
}: {
    tone: StatusTone;
    label: string;
    icon?: LucideIcon;
    className?: string;
    compact?: boolean;
}) => {
    const shape = TONE_SHAPE[tone];
    return (
        <span className={`${TONE_CHIP[tone]} ${compact ? '!px-1.5 !text-[10.5px]' : ''} ${className}`}>
            {Icon ? <Icon size={compact ? 10 : 11} /> : shape && <StatusGlyph shape={shape} />}
            {label && <span className="truncate">{label}</span>}
        </span>
    );
};
