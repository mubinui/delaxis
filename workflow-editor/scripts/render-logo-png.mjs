/**
 * Rasterise the Delaxis mark into the PNG favicons.
 *
 * Playwright is already a devDependency (it drives the E2E suite), so this needs
 * no extra tooling and produces the same bytes on any machine. Run with
 * `npm run logo:png` after changing the mark.
 *
 * Source is the brand asset rather than public/delaxis-logo.svg, because that
 * file carries a prefers-color-scheme rule and a rasteriser would bake in
 * whichever scheme it happened to emulate. A PNG cannot adapt anyway, so the
 * dark-tile variant is used: it stays visible on a light tab bar and on an iOS
 * home screen, where a near-white tile would vanish.
 */
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const publicDir = resolve(root, 'public');
const SOURCE = resolve(root, 'svg', 'delaxis-tile-paper-blue-light.svg');

// 64 for the browser tab, 180 for the iOS apple-touch-icon (iOS upscales
// anything smaller and it looks soft on the home screen).
const SIZES = [64, 180];

const svg = await readFile(SOURCE, 'utf8');
const browser = await chromium.launch();

try {
    for (const size of SIZES) {
        const page = await browser.newPage({
            viewport: { width: size, height: size },
            deviceScaleFactor: 1,
        });
        await page.setContent(
            `<style>html,body{margin:0;padding:0}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`,
        );
        const out = resolve(publicDir, `delaxis-logo-${size}.png`);
        await page.screenshot({ path: out, omitBackground: true });
        await page.close();
        console.log(`wrote ${out}`);
    }
} finally {
    await browser.close();
}
