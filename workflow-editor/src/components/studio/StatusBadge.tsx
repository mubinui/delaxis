import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';

type StatusTone = 'ready' | 'warning' | 'error' | 'running' | 'muted';

// Status colours come from the token set rather than Tailwind palette steps, so
// one edit changes every badge in the app and light/dark can never drift apart.
const toneVars: Record<StatusTone, { fg: string; bg: string }> = {
    ready: { fg: 'var(--status-ready)', bg: 'var(--status-ready-bg)' },
    warning: { fg: 'var(--status-warning)', bg: 'var(--status-warning-bg)' },
    error: { fg: 'var(--status-error)', bg: 'var(--status-error-bg)' },
    running: { fg: 'var(--status-running)', bg: 'var(--status-running-bg)' },
    muted: { fg: 'var(--status-muted)', bg: 'var(--status-muted-bg)' },
};

const toneIcon: Record<StatusTone, LucideIcon> = {
    ready: CheckCircle2,
    warning: AlertTriangle,
    error: XCircle,
    running: Loader2,
    muted: Circle,
};

export const StatusBadge = ({
    tone,
    label,
    icon,
    className = '',
    compact = false,
}: {
    tone: StatusTone;
    label: string;
    icon?: LucideIcon;
    className?: string;
    compact?: boolean;
}) => {
    const Icon = icon ?? toneIcon[tone];
    const { fg, bg } = toneVars[tone];
    return (
        <span
            className={`dlx-chip max-w-full ${compact ? 'px-1.5 py-px text-[9px]' : 'px-2 py-0.5 text-[10px]'} ${className}`}
            style={{
                color: fg,
                backgroundColor: bg,
                borderColor: `color-mix(in srgb, ${fg} 26%, transparent)`,
            }}
        >
            <Icon size={compact ? 9 : 11} className={tone === 'running' ? 'animate-spin' : ''} />
            <span className="truncate">{label}</span>
        </span>
    );
};
