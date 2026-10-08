import type { Page } from '@playwright/test';
import { STARTERS, expect, test } from './fixtures';

const openWorkflow = async (page: Page, name: string) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open Studio' }).first().click();
    await page.getByRole('button', { name: 'Open a workflow' }).click();
    await page.getByRole('menuitem', { name }).click();
    await expect(page.getByLabel('Workflow name')).toHaveValue(name);
};

/**
 * Opening a curated workflow and pressing Save used to rewrite it from the
 * canvas: a generated description, deployment reset to private, metadata and
 * task wording gone. A save must keep everything the canvas does not own.
 */
for (const starter of STARTERS) {
    test(`saving ${starter.name} unchanged keeps what the workflow had`, async ({ page, request, dialogs }) => {
        const before = await (await request.get(`/api/v1/workflows/${starter.id}`)).json();

        await openWorkflow(page, starter.name);
        await page.getByTitle('Save to the backend').click();
        await expect.poll(() => dialogs.join('\n')).toContain('saved');

        const after = await (await request.get(`/api/v1/workflows/${starter.id}`)).json();
        expect(after.description).toBe(before.description);
        expect(after.deployment_auth_mode).toBe(before.deployment_auth_mode);
        for (const key of Object.keys(before.metadata ?? {})) {
            if (key === 'visual_canvas') continue;
            expect(after.metadata[key], `metadata.${key}`).toEqual(before.metadata[key]);
        }
        const wording = (workflow: { tasks?: { node_id: string; description: string }[] }) =>
            Object.fromEntries((workflow.tasks ?? []).map((task) => [task.node_id, task.description]));
        const beforeTasks = wording(before);
        const afterTasks = wording(after);
        for (const [nodeId, description] of Object.entries(beforeTasks)) {
            expect(afterTasks[nodeId], `task for ${nodeId}`).toBe(description);
        }
        expect(after.topology.entry_node).toBe(before.topology.entry_node);
        expect(after.topology.nodes.map((n: { agent_id: string }) => n.agent_id).sort())
            .toEqual(before.topology.nodes.map((n: { agent_id: string }) => n.agent_id).sort());
    });
}
