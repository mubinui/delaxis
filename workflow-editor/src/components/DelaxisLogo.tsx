interface DelaxisLogoProps {
    className?: string;
}

/**
 * The Delaxis mark — three nodes stepping along a diagonal axis on a rounded
 * tile, with the leading node in the brand blue.
 *
 * Geometry is the `delaxis-tile-paper-blue` pair from svg/ (the brand asset
 * set); both colourways are inlined here and swapped by the `dark:` variant so
 * the mark follows the Studio's theme toggle without a hook or a re-render.
 * Keep in sync with public/delaxis-logo.svg (the favicon).
 */
export const DelaxisLogo = ({ className = 'w-8 h-8' }: DelaxisLogoProps) => (
    <svg className={className} viewBox="0 0 100 100" role="img" aria-label="Delaxis logo">
        {/* Light theme: dark tile, light nodes */}
        <g className="dark:hidden">
            <rect width="100" height="100" rx="24" fill="#1d2530" />
            <circle cx="24" cy="76" r="9" fill="#f6f5f2" />
            <circle cx="50" cy="50" r="9" fill="#f6f5f2" />
            <circle cx="76" cy="24" r="9" fill="#3b7ef5" />
        </g>
        {/* Dark theme: light tile, dark nodes */}
        <g className="hidden dark:block">
            <rect width="100" height="100" rx="24" fill="#f6f5f2" />
            <circle cx="24" cy="76" r="9" fill="#1d2530" />
            <circle cx="50" cy="50" r="9" fill="#1d2530" />
            <circle cx="76" cy="24" r="9" fill="#3b7ef5" />
        </g>
    </svg>
);
