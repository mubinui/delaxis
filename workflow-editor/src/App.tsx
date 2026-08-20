import { useState } from 'react';
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

import { ReactFlowProvider } from '@xyflow/react';
import '@xyflow/react/dist/style.css'; // Ensure styles are available

// Create context for library modal
import { createContext, useContext } from 'react';

interface LibraryModalContextType {
  openLibraryModal: (tab?: 'browse' | 'tools' | 'agents' | 'functions' | 'prompts' | 'providers' | 'ops') => void;
}

export const LibraryModalContext = createContext<LibraryModalContextType>({
  openLibraryModal: () => { },
});

export const useLibraryModal = () => useContext(LibraryModalContext);

function App() {
  const [libraryModalOpen, setLibraryModalOpen] = useState(false);
  const [libraryModalTab, setLibraryModalTab] = useState<'browse' | 'tools' | 'agents' | 'functions' | 'prompts' | 'providers' | 'ops'>('browse');

  // Navigation views state: 'landing' | 'canvas' | 'tester' | 'deploy'
  const [currentScreen, setCurrentScreen] = useState<'landing' | 'canvas' | 'tester' | 'deploy'>('landing');
  const [authModalOpen, setAuthModalOpen] = useState(false);
  // The Builder lives behind a header button as a floating window — it no longer
  // consumes permanent layout width next to the canvas.
  const [builderOpen, setBuilderOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const openLibraryModal = (tab: 'browse' | 'tools' | 'agents' | 'functions' | 'prompts' | 'providers' | 'ops' = 'browse') => {
    setLibraryModalTab(tab);
    setLibraryModalOpen(true);
  };

  // The studio workspace (canvas, panels, palettes) only makes sense on the 'canvas'
  // screen. Landing/tester/deploy are full-screen overlays (each `absolute inset-0 z-30`);
  // mounting the studio underneath them let its higher z-index panels (chat, inspector,
  // execution timeline) visually punch through. Unmounting it entirely when inactive
  // fixes that at the source instead of chasing z-index values.
  const isStudioActive = currentScreen === 'canvas';

  return (
    <LibraryModalContext.Provider value={{ openLibraryModal }}>
      <ReactFlowProvider>
        <div className="flex h-screen w-screen bg-[var(--color-canvas-bg)] overflow-hidden flex-col relative">
          {/* Studio toolbar — only meaningful on the canvas screen. Landing, tester, and
              deploy are full-screen views with their own chrome (nav / close buttons),
              so the workflow toolbar must not bleed into them. */}
          {isStudioActive && (
            <Header
              onOpenLanding={() => setCurrentScreen('landing')}
              onOpenTester={() => setCurrentScreen('tester')}
              onOpenDeploy={() => setCurrentScreen('deploy')}
              builderOpen={builderOpen}
              onToggleBuilder={() => { setBuilderOpen((open) => !open); setHelpOpen(false); }}
              helpOpen={helpOpen}
              onToggleHelp={() => { setHelpOpen((open) => !open); setBuilderOpen(false); }}
            />
          )}

          {/* Active Workspaces Wrapper */}
          <div className="flex flex-grow h-full overflow-hidden relative">
            {/* Standard Canvas/Studio layout */}
            {isStudioActive && (
              <>
                <Sidebar />
                <main className="flex-grow h-full relative flex min-w-0">
                  <div className="flex-1 relative min-w-0">
                    <WorkflowCanvas />
                    {builderOpen && <LaunchpadPanel onClose={() => setBuilderOpen(false)} />}
                    {helpOpen && <HelpPanel onClose={() => setHelpOpen(false)} />}
                    <ChatPanel />
                    <ExecutionTimeline />
                  </div>
                  <PropertiesPanel />
                </main>
              </>
            )}

            {/* View Overlay 1: Welcome Premium Landing Page */}
            {currentScreen === 'landing' && (
              <LandingPage
                onEnterStudio={() => setCurrentScreen('canvas')}
                onOpenTester={() => setCurrentScreen('tester')}
                onOpenDeploy={() => setCurrentScreen('deploy')}
                onOpenAuth={() => setAuthModalOpen(true)}
              />
            )}

            {/* View Overlay 2: Live LLM Real-time Validation Sandbox */}
            {currentScreen === 'tester' && (
              <LiveLlmTester onClose={() => setCurrentScreen('canvas')} />
            )}

            {/* View Overlay 3: Deployment Manager / Export Hub */}
            {currentScreen === 'deploy' && (
              <DeploymentManager onClose={() => setCurrentScreen('canvas')} />
            )}
          </div>
        </div>

        {/* Global Access Modals */}
        <LibraryModal
          isOpen={libraryModalOpen}
          onClose={() => setLibraryModalOpen(false)}
          initialTab={libraryModalTab}
        />

        <AuthModal
          isOpen={authModalOpen}
          onClose={() => setAuthModalOpen(false)}
        />
      </ReactFlowProvider>
    </LibraryModalContext.Provider>
  );
}

export default App;
