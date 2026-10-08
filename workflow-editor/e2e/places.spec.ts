import { expect, test } from './fixtures';

/** Every place in the sidebar, and text that proves it rendered real content. */
const PLACES: { button: string; shows: RegExp }[] = [
    { button: 'Model tester', shows: /provider|model/i },
    { button: 'Deployments', shows: /deploy/i },
    { button: 'Everything', shows: /calculate|web_search|search_web/i },
    { button: 'Agents', shows: /TriageAgent|GeneralAssistant/ },
    { button: 'Tools', shows: /calculate|search_web/ },
    { button: 'Functions', shows: /function/i },
    { button: 'Prompts', shows: /prompt/i },
    { button: 'Providers', shows: /OpenRouter/i },
    { button: 'Health and data', shows: /health|audit|retrieval|data/i },
];

for (const place of PLACES) {
    test(`${place.button} renders without errors`, async ({ page }) => {
        await page.goto('/');
        await page.getByRole('button', { name: 'Open Studio' }).first().click();
        await page.getByRole('button', { name: place.button, exact: true }).click();
        await expect(page.locator('main, [role="main"], body').first()).toContainText(place.shows);
    });
}

test('the Builder, Help and test chat panes open over the canvas', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open Studio' }).first().click();
    await page.getByRole('button', { name: 'Open a workflow' }).click();
    await page.getByRole('menuitem', { name: 'Assistant Chatbot' }).click();

    await page.getByRole('button', { name: /^Builder/ }).click();
    await expect(page.getByRole('button', { name: 'Close Builder' })).toBeVisible();
    await page.getByRole('button', { name: 'Close Builder' }).click();

    await page.getByRole('button', { name: 'Help', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Close help' })).toBeVisible();
    await page.getByRole('button', { name: 'Close help' }).click();

    await page.getByTitle('Chat with this workflow').click();
    await expect(page.getByRole('button', { name: 'Close test chat' })).toBeVisible();
});
