import { createContext, useContext } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Shapes } from 'lucide-react';

import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { PropertiesPanel } from './components/PropertiesPanel';
import { ChatPanel } from './components/ChatPanel';
import { LibraryModal } from './components/LibraryModal';
import { LaunchpadPanel } from './components/LaunchpadPanel';
import { HelpPanel } from './components/HelpPanel';
import { ExecutionTimeline } from './components/ExecutionTimeline';
import { LandingPage } from './components/LandingPage';
import { AuthModal } from './components/AuthModal';
import { LiveLlmTester } from './components/LiveLlmTester';
import { DeploymentManager } from './components/DeploymentManager';
import { AppSidebar } from './components/shell/AppSidebar';
import { useUiStore } from './stores/uiStore';
import type { LibraryTab } from './stores/uiStore';
import { useTheme } from './hooks/useTheme';

interface LibraryModalContextType {
    openLibraryModal: (tab?: LibraryTab) => void;
}

// Kept for components that open the Library by tab; it now navigates to the
// Library place in the sidebar rather than stacking a modal over the Studio.
export const LibraryModalContext = createContext<LibraryModalContextType>({
    openLibraryModal: () => { },
});

export const useLibraryModal = () => useContext(LibraryModalContext);

/**
 * The Studio: one full-width canvas. The palette, the inspector, the test chat,
 * the Builder and Help float over it as glass, so the canvas never loses width.
 */
const StudioScreen = () => {
    const { paletteOpen, setPaletteOpen, pane, closePane } = useUiStore();
    return (
        <div className="absolute inset-0">
            <WorkflowCanvas />
            {paletteOpen ? (
                <Sidebar />
            ) : (
                <button
                    type="button"
                    className="btn btn-toolbar absolute left-3.5 z-20"
                    style={{ top: 'calc(var(--toolbar-h) + 14px)' }}
                    onClick={() => setPaletteOpen(true)}
                    title="Show components"
                >
                    <Shapes size={15} strokeWidth={1.8} />
                    Components
                </button>
            )}
            <PropertiesPanel />
            {pane === 'builder' && <LaunchpadPanel onClose={closePane} />}
            {pane === 'help' && <HelpPanel onClose={closePane} />}
            <ChatPanel />
            <ExecutionTimeline />
            <Header />
        </div>
    );
};

function App() {
    const { screen, libraryTab, openLibrary, authOpen, setAuthOpen } = useUiStore();
    // Applies the stored appearance (or the system's) before anything paints.
    useTheme();

    return (
        <LibraryModalContext.Provider value={{ openLibraryModal: openLibrary }}>
            <ReactFlowProvider>
                {screen === 'landing' ? (
                    <LandingPage />
                ) : (
                    <div className="app h-screen w-screen">
                        <AppSidebar />
                        <div className="app-main">
                            <main className="app-content" id="main">
                                {screen === 'studio' && <StudioScreen />}
                                {screen === 'tester' && <LiveLlmTester />}
                                {screen === 'deploy' && <DeploymentManager />}
                                {/* Keyed by section, so each one opens with an empty editor. */}
                                {screen === 'library' && <LibraryModal key={libraryTab} tab={libraryTab} />}
                            </main>
                        </div>
                    </div>
                )}
                <AuthModal isOpen={authOpen} onClose={() => setAuthOpen(false)} />
            </ReactFlowProvider>
        </LibraryModalContext.Provider>
    );
}

export default App;
