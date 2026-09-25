import type { ReactNode } from 'react';
import { Menu as MenuIcon, MoreHorizontal, PanelLeft } from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import { AppearanceItems, MenuButton } from './Menu';

/**
 * The unified toolbar: one frosted band over the top of the content, which
 * scrolls beneath it. The leading edge holds the sidebar button, the centre the
 * activity capsule, and the trailing edge the Liquid Glass capsules. It never
 * names the page — the large title and the sidebar do that.
 */
export const Toolbar = ({ center, actions, lead }: { center?: ReactNode; actions?: ReactNode; lead?: ReactNode }) => {
    const { toggleSidebar, setNavDrawer, sidebarRail, screen } = useUiStore();
    const rail = sidebarRail ?? screen === 'studio';
    return (
        <header className="app-header">
            <div className="header-lead">
                <button
                    type="button"
                    className="btn btn-toolbar btn-icon hide-narrow"
                    onClick={toggleSidebar}
                    aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}
                    title={rail ? 'Expand sidebar' : 'Collapse sidebar'}
                >
                    <PanelLeft size={16} strokeWidth={1.8} />
                </button>
                <button
                    type="button"
                    className="btn btn-toolbar btn-icon only-narrow"
                    onClick={() => setNavDrawer(true)}
                    aria-label="Open navigation"
                >
                    <MenuIcon size={16} />
                </button>
                {lead}
            </div>
            {center ?? <span />}
            <div className="header-actions">{actions}</div>
        </header>
    );
};

/** The trailing ⋯ capsule. Every screen gets one, if only for Appearance. */
export const MoreMenu = ({ children }: { children?: (close: () => void) => ReactNode }) => (
    <MenuButton
        button={({ open, toggle }) => (
            <button
                type="button"
                className="btn btn-toolbar btn-icon"
                onClick={toggle}
                aria-label="More"
                aria-haspopup="menu"
                aria-expanded={open}
                title="More"
            >
                <MoreHorizontal size={17} />
            </button>
        )}
    >
        {(close) => (
            <>
                {children?.(close)}
                <AppearanceItems close={close} />
            </>
        )}
    </MenuButton>
);
