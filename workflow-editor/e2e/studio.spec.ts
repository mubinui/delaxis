import type { Page } from '@playwright/test';
import { STARTERS, expect, test } from './fixtures';

const openStudio = async (page: Page) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open Studio' }).first().click();
    await expect(page.getByLabel('Workflow name')).toBeVisible();
};

const openWorkflow = async (page: Page, name: string) => {
    await page.getByRole('button', { name: 'Open a workflow' }).click();
    await page.getByRole('menuitem', { name }).click();
    await expect(page.getByLabel('Workflow name')).toHaveValue(name);
};

test('the landing page reports a live backend with the shipped content', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText(/Backend online/)).toBeVisible();
    await expect(page.getByText(/6 workflows/)).toBeVisible();
});

test('the Studio opens on an empty canvas', async ({ page }) => {
    await openStudio(page);
    await expect(page.getByText('Start with a trigger')).toBeVisible();
});

for (const starter of STARTERS) {
    test(`opening ${starter.name} draws its agents on the canvas`, async ({ page, request }) => {
        const workflow = await (await request.get(`/api/v1/workflows/${starter.id}`)).json();
        const agentIds: string[] = workflow.topology.nodes.map((node: { agent_id: string }) => node.agent_id);
        const agents = await (await request.get('/api/v1/agents')).json();
        const names = agentIds.map((id) => agents.find((agent: { id: string }) => agent.id === id).name as string);

        await openStudio(page);
        await openWorkflow(page, starter.name);
        for (const name of names) {
            await expect(page.locator('.react-flow__node').filter({ hasText: name }).first()).toBeVisible();
        }
    });
}
