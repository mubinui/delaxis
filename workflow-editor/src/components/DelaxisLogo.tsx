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
 * The Delaxis mark.
 *
 * Geometry comes from the `delaxis-linked-paper-blue` and
 * `delaxis-tile-paper-blue` pairs in svg/. Of the four brand colourways
 * (paper-blue, slate-violet, ink-green, umber-amber) only paper-blue agrees
 * with the Studio's blue accent; the others would read as a second, competing
 * brand colour on every screen.
 *
 * The `linked` variant is used in the chrome because the connector line makes
 * the mark read as a connected graph, which is what the product is — and
 * because an open mark sits better against the header than a filled dark tile,
 * which reads as a heavy block at 32px.
 *
 * Colours come from the design tokens rather than the asset's literal hexes, so
 * the mark tracks the theme toggle exactly like the rest of the Studio and
 * cannot drift from the accent again. The brand's leading-node blue and the
 * Studio accent were already a visible half-step apart (#3b7ef5 vs #3355ff).
 */
export const DelaxisLogo = ({ className = 'w-8 h-8', variant = 'linked' }: DelaxisLogoProps) => (
    <svg
        className={className}
        viewBox="0 0 100 100"
        role="img"
        aria-label="Delaxis"
        fill="none"
    >
        {variant === 'tile' && (
            <rect width="100" height="100" rx="24" fill="var(--text-primary)" />
        )}

        {/* The axis the three nodes step along. */}
        <line
            x1="24"
            y1="76"
            x2="76"
            y2="24"
            stroke={variant === 'tile' ? 'var(--surface-1)' : 'var(--text-primary)'}
            strokeWidth="6"
            strokeLinecap="round"
            opacity="0.35"
        />

        <circle cx="24" cy="76" r="11" fill={variant === 'tile' ? 'var(--surface-1)' : 'var(--text-primary)'} />
        <circle cx="50" cy="50" r="11" fill={variant === 'tile' ? 'var(--surface-1)' : 'var(--text-primary)'} />
        {/* The leading node carries the accent — the one element that says
            "this is the live end of the graph". */}
        <circle cx="76" cy="24" r="11" fill="var(--accent)" />
    </svg>
);
