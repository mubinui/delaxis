/**
 * Captures the Studio images the landing page shows in its hero, in both themes.
 *
 * Run it against the demo build, whose in-browser stub backend has the sample
 * workflow the images are made from:
 *
 *     VITE_DEMO_MODE=true npx vite --port 5199 &
 *     npm run preview:images                      # DELAXIS_URL overrides the address
 */
import { chromium } from 'playwright';

const BASE = process.env.DELAXIS_URL ?? 'http://localhost:5199/';
const OUT = new URL('../public/', import.meta.url).pathname;

const browser = await chromium.launch();
for (const theme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
    await ctx.addInitScript((t) => {
        localStorage.setItem('delaxis-theme', t);
        sessionStorage.setItem('delaxis-demo-intro-seen', '1');
    }, theme);
    const page = await ctx.newPage();
    await page.goto(BASE);
    await page.waitForTimeout(800);
    await page.getByRole('button', { name: 'Open the Studio' }).first().click();
    await page.getByRole('button', { name: 'Open a workflow' }).click();
    await page.getByRole('menuitem', { name: /Demo Multi-Agent/ })
        .or(page.getByRole('menuitemradio', { name: /Demo Multi-Agent/ })).first().click();
    await page.waitForTimeout(800);
    // An agent selected shows the inspector, and the graph pans clear of it.
    await page.locator('.react-flow__node-agent').nth(2).click();
    await page.waitForTimeout(700);
    await page.addStyleTag({ content: 'button[title="About this demo"]{display:none!important}' });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}studio-preview-${theme}.jpg`, type: 'jpeg', quality: 86 });
    await ctx.close();
}
await browser.close();
console.log(`wrote ${OUT}studio-preview-{light,dark}.jpg`);
