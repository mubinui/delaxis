import { expect, test } from './fixtures';

/**
 * Run history against the real API. No model key is set (see serve.sh), so a
 * run fails fast — which is still a run: it is recorded with its request, its
 * error and its events, and it can be replayed, played back and deleted.
 */
test('a run is recorded, replayed, played on the canvas and deleted', async ({ page, request }) => {
    const message = `e2e run ${Date.now()}`;
    const session = await request.post('/api/v1/sessions', { data: { workflow_id: 'assistant_chat', user_id: 'e2e' } });
    expect(session.status()).toBe(201);
    const { session_id: sessionId } = await session.json();
    await request.post(`/api/v1/sessions/${sessionId}/messages`, { data: { message } });

    await page.goto('/');
    await page.getByRole('button', { name: 'Open Studio' }).first().click();
    await page.getByRole('button', { name: 'Runs', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Runs' })).toBeVisible();

    const runs = page.getByRole('table', { name: 'Runs' });
    await runs.getByRole('button', { name: message }).click();
    const details = page.getByRole('complementary', { name: 'Run details' });
    await expect(details).toContainText(message);
    await expect(details).toContainText('assistant_chat');
    await expect(details.getByRole('list', { name: 'Events' })).toContainText('start');

    // Replay: a second run of the same request, linked to the first.
    await details.getByRole('button', { name: 'Replay' }).click();
    await expect(details).toContainText('Replay of');
    await expect(runs.getByRole('button', { name: message })).toHaveCount(2);

    // Filters narrow the list and the count follows.
    await page.getByRole('tab', { name: 'Succeeded' }).click();
    await expect(runs.getByRole('button', { name: message })).toHaveCount(0);
    await page.getByRole('tab', { name: 'All' }).click();
    await expect(runs.getByRole('button', { name: message })).toHaveCount(2);

    // Delete the replay; the original stays.
    await runs.getByRole('button', { name: message }).first().click();
    await details.getByRole('button', { name: 'Delete run' }).click();
    await expect(runs.getByRole('button', { name: message })).toHaveCount(1);

    // Play the original back on the canvas: the Studio opens the workflow and
    // the run timeline replays the recorded events.
    await runs.getByRole('button', { name: message }).click();
    await details.getByRole('button', { name: 'Play on canvas' }).click();
    const timeline = page.getByRole('dialog', { name: 'Run timeline' });
    await expect(timeline).toBeVisible();
    await expect(timeline).toContainText('Workflow started');
    await expect(page.getByRole('textbox', { name: 'Workflow name' })).toHaveValue('Assistant Chatbot');
    await expect(timeline).toContainText(/error|failed/i);
});

test('the Runs page explains itself when a filter matches nothing', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open Studio' }).first().click();
    await page.getByRole('button', { name: 'Runs', exact: true }).click();
    await page.getByRole('combobox', { name: 'Workflow' }).selectOption('content_pipeline');
    await page.getByRole('tab', { name: 'Succeeded' }).click();
    await expect(page.getByText('No runs match')).toBeVisible();
});
