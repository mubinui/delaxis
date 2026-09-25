import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { Check, Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from '../../hooks/useTheme';
import type { ThemePreference } from '../../hooks/useTheme';

/**
 * A button that opens a Liquid Glass menu below it. Escape and a click outside
 * close it; choosing an item closes it too.
 */
export const MenuButton = ({
    button,
    children,
    align = 'right',
    width = 250,
}: {
    button: (props: { open: boolean; toggle: () => void }) => ReactNode;
    children: (close: () => void) => ReactNode;
    align?: 'left' | 'right' | 'center';
    width?: number;
}) => {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const onDown = (event: MouseEvent) => {
            if (!ref.current?.contains(event.target as Node)) setOpen(false);
        };
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open]);

    const position =
        align === 'left' ? { left: 0 } : align === 'center' ? { left: '50%', translate: '-50% 0' } : { right: 0 };

    return (
        <div ref={ref} className="relative">
            {button({ open, toggle: () => setOpen((value) => !value) })}
            {open && (
                <div
                    role="menu"
                    className="menu glass-strong"
                    style={{ top: 'calc(100% + 8px)', width, transformOrigin: align === 'left' ? 'top left' : 'top right', ...position }}
                >
                    {children(() => setOpen(false))}
                </div>
            )}
        </div>
    );
};

export const MenuItem = ({
    icon: Icon,
    children,
    onSelect,
    shortcut,
    checked,
    disabled,
}: {
    icon?: LucideIcon;
    children: ReactNode;
    onSelect: () => void;
    shortcut?: string;
    checked?: boolean;
    disabled?: boolean;
}) => (
    <button
        type="button"
        role={checked === undefined ? 'menuitem' : 'menuitemradio'}
        aria-checked={checked}
        className="menu-item"
        onClick={onSelect}
        disabled={disabled}
    >
        {Icon ? <Icon size={14} /> : <span style={{ width: 14 }} />}
        <span className="min-w-0 truncate">{children}</span>
        {(shortcut || checked) && (
            <span className="menu-key">{checked ? <Check size={14} /> : shortcut}</span>
        )}
    </button>
);

export const MenuSeparator = () => <div className="menu-sep" role="separator" />;
export const MenuLabel = ({ children }: { children: ReactNode }) => <div className="menu-label">{children}</div>;

const APPEARANCE: Array<{ id: ThemePreference; label: string; icon: LucideIcon }> = [
    { id: 'light', label: 'Light', icon: Sun },
    { id: 'dark', label: 'Dark', icon: Moon },
    { id: 'system', label: 'Match system', icon: Monitor },
];

/** Light, Dark and Match system, for the bottom of a More menu. */
export const AppearanceItems = ({ close }: { close: () => void }) => {
    const { preference, setPreference } = useTheme();
    return (
        <>
            <MenuLabel>Appearance</MenuLabel>
            {APPEARANCE.map(({ id, label, icon }) => (
                <MenuItem
                    key={id}
                    icon={icon}
                    checked={preference === id}
                    onSelect={() => {
                        setPreference(id);
                        close();
                    }}
                >
                    {label}
                </MenuItem>
            ))}
        </>
    );
};
