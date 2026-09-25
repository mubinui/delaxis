interface DelaxisLogoProps {
    className?: string;
    /**
     * `linked` is the in-app mark: three nodes joined along a diagonal axis.
     * `tile` is the same geometry inside a filled rounded square — the app-icon
     * form, kept for the favicon and anywhere the mark needs its own ground.
     */
    variant?: 'linked' | 'tile';
}

/**
 * The Delaxis mark, in Graphite.
 *
 * Geometry comes from the `delaxis-linked-*` and `delaxis-tile-*` pairs in svg/.
 * The accent is monochrome, so the leading node is told apart by weight rather
 * than hue: it is solid ink, and the two nodes behind it step back. Colours come
 * from tokens, so the mark inverts with the theme like the rest of the Studio.
 */
export const DelaxisLogo = ({ className = 'w-8 h-8', variant = 'linked' }: DelaxisLogoProps) => {
    const ink = variant === 'tile' ? 'var(--window)' : 'var(--text)';
    return (
        <svg className={className} viewBox="0 0 100 100" role="img" aria-label="Delaxis" fill="none">
            {variant === 'tile' && <rect width="100" height="100" rx="24" fill="var(--text)" />}

            {/* The axis the three nodes step along. */}
            <line x1="24" y1="76" x2="76" y2="24" stroke={ink} strokeWidth="7" strokeLinecap="round" opacity="0.28" />
            <circle cx="24" cy="76" r="12" fill={ink} opacity="0.42" />
            <circle cx="50" cy="50" r="12" fill={ink} opacity="0.68" />
            {/* The leading node: the live end of the graph. */}
            <circle cx="76" cy="24" r="12" fill={ink} />
        </svg>
    );
};
