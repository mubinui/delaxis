import { test as base, expect } from '@playwright/test';

/**
 * Every page test fails on an uncaught page error or a console error, so a
 * component that throws while rendering cannot pass by looking fine. Native
 * alert/confirm dialogs (the Studio still uses them for save results) are
 * recorded and accepted.
 */
export const test = base.extend<{ dialogs: string[] }>({
    dialogs: async ({ page }, use) => {
        const dialogs: string[] = [];
        page.on('dialog', async (dialog) => {
            dialogs.push(dialog.message());
            await dialog.accept();
        });
        await use(dialogs);
    },
    page: async ({ page }, use) => {
        const problems: string[] = [];
        page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
        page.on('console', (message) => {
            if (message.type() !== 'error') return;
            const text = message.text();
            // The browser logs failed favicon fetches itself; they are not app errors.
            if (/favicon/i.test(text)) return;
            problems.push(`console.error: ${text}`);
        });
        await use(page);
        expect(problems, 'the page logged errors').toEqual([]);
    },
});

export { expect };

/** The six workflows the repository ships, by id and display name. */
export const STARTERS = [
    { id: 'assistant_chat', name: 'Assistant Chatbot' },
    { id: 'web_research_chat', name: 'Web Research Chatbot' },
    { id: 'research_brief', name: 'Research Brief Pipeline' },
    { id: 'docs_qa', name: 'Docs Q&A' },
    { id: 'support_triage', name: 'Support Triage' },
    { id: 'content_pipeline', name: 'Content Pipeline' },
] as const;
