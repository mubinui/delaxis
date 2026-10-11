import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 8799);

/**
 * End-to-end suite: the built Studio served by the real API, started from a
 * throwaway copy of the configs (see e2e/serve.sh). No LLM is called; the
 * runtime paths that need one are covered by the backend's own tests.
 */
export default defineConfig({
    testDir: './e2e',
    timeout: 30_000,
    expect: { timeout: 7_500 },
    fullyParallel: false,
    workers: 1,
    retries: process.env.CI ? 1 : 0,
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    use: {
        baseURL: `http://127.0.0.1:${PORT}`,
        trace: 'retain-on-failure',
        viewport: { width: 1512, height: 900 },
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1512, height: 900 } } }],
    webServer: [
        {
            command: `npm run build && E2E_PORT=${PORT} ./e2e/serve.sh`,
            url: `http://127.0.0.1:${PORT}/health`,
            reuseExistingServer: !process.env.CI,
            timeout: 180_000,
        },
        // A stand-in GitLab and Jira, so the connector tests need no account.
        {
            command: 'uv run --project .. --no-sync uvicorn --app-dir ../scripts fake_forge:app --host 127.0.0.1 --port 8797',
            url: 'http://127.0.0.1:8797/health',
            reuseExistingServer: !process.env.CI,
            timeout: 60_000,
        },
    ],
});
