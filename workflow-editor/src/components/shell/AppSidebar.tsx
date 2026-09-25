import type { CSSProperties } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
    Activity, Bot, Code2, Gauge, LayoutGrid, MessageSquareText, Send, ServerCog, User, Workflow, Wrench,
} from 'lucide-react';
import { DelaxisLogo } from '../DelaxisLogo';
import { StatusGlyph } from './StatusGlyph';
import { useUiStore } from '../../stores/uiStore';
import type { LibraryTab, Screen } from '../../stores/uiStore';
import { useLibraryStore } from '../../stores/libraryStore';
import { useBackendStatus } from '../../hooks/useBackendStatus';

interface Place {
    id: string;
    label: string;
    icon: LucideIcon;
    /** One hue per place; it colours the icon and nothing else. */
    hue: string;
    screen: Screen;
    tab?: LibraryTab;
    count?: number;
}

/**
 * The window's sidebar: flush Liquid Glass over a soft desktop, one coloured
 * icon per place, and a grey pill for the current one.
 */
export const AppSidebar = () => {
    const { screen, libraryTab, sidebarRail, navDrawerOpen, go, openLibrary, setNavDrawer, setAuthOpen } = useUiStore();
    const rail = (sidebarRail ?? screen === 'studio') && !navDrawerOpen;
    const { savedAgents, savedTools, savedWorkflows, functions, prompts, providers, deployments } = useLibraryStore();
    const backend = useBackendStatus();

    const groups: Array<{ label: string; places: Place[] }> = [
        {
            label: 'Workspace',
            places: [
                { id: 'studio', label: 'Studio', icon: Workflow, hue: 'var(--hue-4)', screen: 'studio' },
                { id: 'tester', label: 'Model tester', icon: Gauge, hue: 'var(--hue-6)', screen: 'tester' },
                { id: 'deploy', label: 'Deployments', icon: Send, hue: 'var(--hue-2)', screen: 'deploy', count: deployments.length || undefined },
            ],
        },
        {
            label: 'Library',
            places: [
                { id: 'browse', label: 'Everything', icon: LayoutGrid, hue: 'var(--hue-1)', screen: 'library', tab: 'browse', count: savedAgents.length + savedTools.length + savedWorkflows.length || undefined },
                { id: 'agents', label: 'Agents', icon: Bot, hue: 'var(--hue-3)', screen: 'library', tab: 'agents', count: savedAgents.length || undefined },
                { id: 'tools', label: 'Tools', icon: Wrench, hue: 'var(--hue-5)', screen: 'library', tab: 'tools', count: savedTools.length || undefined },
                { id: 'functions', label: 'Functions', icon: Code2, hue: 'var(--hue-7)', screen: 'library', tab: 'functions', count: functions.length || undefined },
                { id: 'prompts', label: 'Prompts', icon: MessageSquareText, hue: 'var(--hue-8)', screen: 'library', tab: 'prompts', count: prompts.length || undefined },
                { id: 'providers', label: 'Providers', icon: ServerCog, hue: 'var(--hue-9)', screen: 'library', tab: 'providers', count: providers.length || undefined },
            ],
        },
        {
            label: 'System',
            places: [
                { id: 'ops', label: 'Health and data', icon: Activity, hue: 'var(--muted)', screen: 'library', tab: 'ops' },
            ],
        },
    ];

    const isCurrent = (place: Place) =>
        place.screen === screen && (place.screen !== 'library' || place.tab === libraryTab);

    const choose = (place: Place) => {
        if (place.screen === 'library') openLibrary(place.tab);
        else go(place.screen);
    };

    const status = backend.up === null
        ? { shape: 'busy' as const, title: 'Checking backend…', sub: '' }
        : backend.up
            ? { shape: 'ok' as const, title: 'Backend online', sub: backend.version ? `v${backend.version}` : '' }
            : { shape: 'bad' as const, title: 'Backend offline', sub: 'Start the API server' };

    return (
        <>
            {navDrawerOpen && (
                <div className="only-narrow fixed inset-0 z-[85] bg-black/20" onClick={() => setNavDrawer(false)} aria-hidden="true" />
            )}
            <nav
                className="app-nav"
                aria-label="Main"
                data-rail={rail ? '' : undefined}
                data-drawer={navDrawerOpen ? '' : undefined}
            >
                <button type="button" className="app-brand" onClick={() => go('landing')} title="Delaxis home">
                    <DelaxisLogo className="h-[22px] w-[22px] shrink-0" />
                    <b>Delaxis</b>
                </button>

                {groups.map((group) => (
                    <div key={group.label} className="flex flex-col gap-px">
                        <div className="nav-group-label">{group.label}</div>
                        {group.places.map((place) => {
                            const Icon = place.icon;
                            return (
                                <button
                                    key={place.id}
                                    type="button"
                                    className="nav-item"
                                    style={{ '--hue': place.hue } as CSSProperties}
                                    aria-current={isCurrent(place) ? 'page' : undefined}
                                    onClick={() => choose(place)}
                                    title={place.label}
                                >
                                    <Icon size={16} strokeWidth={1.8} />
                                    <span className="nav-text">{place.label}</span>
                                    {place.count !== undefined && <span className="nav-count">{place.count}</span>}
                                </button>
                            );
                        })}
                    </div>
                ))}

                <div className="nav-foot">
                    <div className="nav-status" title={status.title}>
                        <StatusGlyph shape={status.shape} />
                        <div className="min-w-0 leading-tight">
                            <div className="text-[12px] font-medium">{status.title}</div>
                            {status.sub && <div className="text-dim text-[11px]">{status.sub}</div>}
                        </div>
                    </div>
                    <button type="button" className="nav-item" onClick={() => setAuthOpen(true)} title="Account">
                        <span className="avatar"><User size={12} /></span>
                        <span className="nav-text">Account</span>
                    </button>
                </div>
            </nav>
        </>
    );
};
