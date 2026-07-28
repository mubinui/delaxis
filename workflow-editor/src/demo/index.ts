/**
 * Demo build entry point.
 *
 * `#demo` resolves here only when VITE_DEMO_MODE=true (see vite.config.ts);
 * every other build resolves it to `stub.ts`, so the backend stub and its
 * fixtures never reach the bundle the API server ships.
 */
export { installDemoApi } from './mockApi';
export { DemoBadge } from '../components/DemoBadge';

export const DEMO_ENABLED = true;
