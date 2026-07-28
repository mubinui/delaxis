import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { DEMO_ENABLED, DemoBadge, installDemoApi } from '#demo'

// The GitHub Pages build has no backend, so a stub answers /api/v1/* from bundled
// fixtures. `#demo` resolves to src/demo/stub.ts unless VITE_DEMO_MODE=true, which
// keeps the stub and its fixtures out of every other build.

// Must run before any component mounts and fetches.
if (DEMO_ENABLED) {
  installDemoApi()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    {DEMO_ENABLED && <DemoBadge />}
  </StrictMode>,
)
