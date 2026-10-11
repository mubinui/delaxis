import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

const FORGE = 'http://127.0.0.1:8797';

const openPlace = async (page: Page, name: RegExp) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open Studio' }).first().click();
    await page.getByRole('button', { name }).click();
};

const addGitLab = async (page: Page, token: string) => {
    await page.getByRole('button', { name: 'Add connection' }).first().click();
    const sheet = page.getByRole('dialog', { name: 'Add a connection' });
    await sheet.getByLabel('Connector').selectOption('gitlab');
    await sheet.getByLabel('Base URL').fill(FORGE);
    await sheet.getByLabel('Personal access token').fill(token);
    await sheet.getByRole('button', { name: 'Connect', exact: true }).click();
    return sheet;
};

/** Drop a palette tile on the canvas the way a mouse drag does: a real DataTransfer through the real handlers. */
const dropTile = async (page: Page, label: string) => {
    const tile = page.getByTitle(new RegExp(`^${label}`)).first();
    const pane = page.locator('.react-flow__pane');
    const transfer = await page.evaluateHandle('new DataTransfer()');
    await tile.dispatchEvent('dragstart', { dataTransfer: transfer });
    const box = await pane.boundingBox();
    if (!box) throw new Error('canvas not visible');
    const at = { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 };
    await pane.dispatchEvent('dragover', { dataTransfer: transfer, ...at });
    await pane.dispatchEvent('drop', { dataTransfer: transfer, ...at });
};

test('a wrong token is refused and nothing is saved', async ({ page, allowConsole }) => {
    // The API answers the wrong token with a 400, which Chrome reports as a console error.
    allowConsole.push(/status of 400/);
    await openPlace(page, /^Connections/);
    const sheet = await addGitLab(page, 'wrong-token');
    await expect(sheet.getByRole('alert')).toContainText('rejected the token');
    await sheet.getByRole('button', { name: 'Close' }).click();
    await expect(page.getByRole('table', { name: 'Connections' })).toHaveCount(0);
});

test('a GitLab connection is verified, used by a node, and its action runs', async ({ page }) => {
    await openPlace(page, /^Connections/);
    await addGitLab(page, 'fake-token');
    const table = page.getByRole('table', { name: 'Connections' });
    await expect(table).toContainText('forge-bot');
    await page.getByRole('button', { name: 'Test', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('Working — signed in as forge-bot');

    await page.getByRole('button', { name: 'Studio', exact: true }).click();
    await dropTile(page, 'GitLab');
    await page.locator('.react-flow__node').filter({ hasText: 'GitLab' }).first().click();
    await page.getByRole('tab', { name: 'Config' }).click();
    // The tool settings sit in a collapsed section, as for every tool kind.
    await page.getByRole('button', { name: 'Protocol Payload Parameters' }).click();

    await page.getByLabel('Connection', { exact: true }).selectOption({ label: `forge-bot · ${FORGE}` });
    await page.getByLabel('Default project').fill('group/app');
    await expect(page.getByLabel('Create an issue')).not.toBeChecked();
    await expect(page.getByLabel('List merge requests')).toBeChecked();

    await page.getByLabel('Action to test').selectOption('list_merge_requests');
    await page.getByRole('button', { name: 'Run', exact: true }).click();
    await expect(page.getByRole('status').last()).toContainText('Fix login redirect');
});
