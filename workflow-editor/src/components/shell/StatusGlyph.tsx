export type StatusShape = 'ok' | 'warn' | 'bad' | 'idle' | 'busy';

/**
 * A status mark. The shape carries the meaning and the hue confirms it, so status
 * still reads in greyscale: ready is a filled disc, attention a ring, error a
 * diamond, idle a thin ring, busy a spinning ring.
 */
export const StatusGlyph = ({ shape, className = '', label }: { shape: StatusShape; className?: string; label?: string }) => (
    <span
        className={`sg ${className}`}
        data-shape={shape}
        role={label ? 'img' : undefined}
        aria-label={label}
        aria-hidden={label ? undefined : true}
    />
);
