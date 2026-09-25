import { create } from 'zustand';

export type Screen = 'landing' | 'studio' | 'tester' | 'deploy' | 'library';
export type LibraryTab = 'browse' | 'tools' | 'agents' | 'functions' | 'prompts' | 'providers' | 'ops';

/** The Studio's floating panes. Builder and Help share the right edge, so only one is open. */
export type StudioPane = 'builder' | 'help' | null;

interface UiState {
    screen: Screen;
    libraryTab: LibraryTab;
    /**
     * The sidebar as an icon rail. null follows the screen: the Studio takes the
     * rail so the canvas gets the room, every other page the full sidebar. The
     * sidebar button sets it explicitly, and that choice then sticks.
     */
    sidebarRail: boolean | null;
    /** Phone: the sidebar opens as a drawer. */
    navDrawerOpen: boolean;
    paletteOpen: boolean;
    testOpen: boolean;
    /** True while the test chat waits on the workflow, so the activity capsule can say so. */
    testRunning: boolean;
    timelineOpen: boolean;
    pane: StudioPane;
    authOpen: boolean;

    go: (screen: Screen) => void;
    openLibrary: (tab?: LibraryTab) => void;
    toggleSidebar: () => void;
    isRail: () => boolean;
    setNavDrawer: (open: boolean) => void;
    setPaletteOpen: (open: boolean) => void;
    setTestOpen: (open: boolean) => void;
    setTestRunning: (running: boolean) => void;
    setTimelineOpen: (open: boolean) => void;
    togglePane: (pane: Exclude<StudioPane, null>) => void;
    closePane: () => void;
    setAuthOpen: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
    screen: 'landing',
    libraryTab: 'browse',
    sidebarRail: null,
    navDrawerOpen: false,
    paletteOpen: true,
    testOpen: false,
    testRunning: false,
    timelineOpen: false,
    pane: null,
    authOpen: false,

    go: (screen) => set({ screen, navDrawerOpen: false, timelineOpen: false }),
    openLibrary: (tab = 'browse') => set({ screen: 'library', libraryTab: tab, navDrawerOpen: false, timelineOpen: false }),
    isRail: () => get().sidebarRail ?? get().screen === 'studio',
    toggleSidebar: () => set({ sidebarRail: !get().isRail() }),
    setNavDrawer: (navDrawerOpen) => set({ navDrawerOpen }),
    setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
    // The test chat and the Builder/Help panes use the same right edge.
    setTestOpen: (testOpen) => set((state) => ({ testOpen, pane: testOpen ? null : state.pane })),
    setTestRunning: (testRunning) => set({ testRunning }),
    setTimelineOpen: (timelineOpen) => set({ timelineOpen }),
    togglePane: (pane) => set((state) => ({ pane: state.pane === pane ? null : pane, testOpen: state.pane === pane ? state.testOpen : false })),
    closePane: () => set({ pane: null }),
    setAuthOpen: (authOpen) => set({ authOpen }),
}));
