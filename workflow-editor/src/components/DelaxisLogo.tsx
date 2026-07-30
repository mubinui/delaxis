import { useId } from 'react';

interface DelaxisLogoProps {
    className?: string;
}

/**
 * Delaxis mark — an axis star: three rays at 120° from a single origin, each
 * capped by an agent node, on an indigo-blue tile with a soft top-light sheen.
 * A coordinate origin that is also a workflow fanning out.
 *
 * The rays are tapered triangles rather than strokes so the mark holds its
 * weight at favicon sizes, and the origin sits at y=28.5 rather than 32 so the
 * two-up/one-down arrangement reads as optically centred.
 *
 * Keep in sync with public/delaxis-logo.svg (the favicon).
 */
export const DelaxisLogo = ({ className = 'w-8 h-8' }: DelaxisLogoProps) => {
    // Header and LandingPage can both be mounted, and duplicate gradient ids in
    // one document are invalid — scope them per instance.
    const uid = useId();
    const tile = `delaxisTile-${uid}`;
    const sheen = `delaxisSheen-${uid}`;

    return (
        <svg className={className} viewBox="0 0 64 64" role="img" aria-label="Delaxis logo">
            <defs>
                <linearGradient id={tile} x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0" stopColor="#60a5fa" />
                    <stop offset="0.5" stopColor="#2563eb" />
                    <stop offset="1" stopColor="#1e3a8a" />
                </linearGradient>
                <radialGradient id={sheen} cx="0.25" cy="0.18" r="0.95">
                    <stop offset="0" stopColor="#ffffff" stopOpacity="0.22" />
                    <stop offset="0.5" stopColor="#ffffff" stopOpacity="0.05" />
                    <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
                </radialGradient>
            </defs>

            {/* Tile */}
            <rect x="3" y="3" width="58" height="58" rx="15" fill={`url(#${tile})`} />
            <rect x="3" y="3" width="58" height="58" rx="15" fill={`url(#${sheen})`} />
            <rect x="3.5" y="3.5" width="57" height="57" rx="14.5" fill="none" stroke="#ffffff" strokeOpacity="0.14" />

            {/* Axis star */}
            <g fill="#ffffff">
                <path d="M29.2 28.5 L34.8 28.5 L32 44 Z" />
                <path d="M33.4 26.08 L30.6 30.92 L18.6 20.75 Z" />
                <path d="M33.4 30.92 L30.6 26.08 L45.4 20.75 Z" />
                <circle cx="32" cy="28.5" r="5.2" />
                <circle cx="32" cy="44" r="6.2" />
                <circle cx="18.6" cy="20.75" r="6.2" />
                <circle cx="45.4" cy="20.75" r="6.2" />
            </g>
        </svg>
    );
};
