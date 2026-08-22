/**
 * Drive the Studio and record it, one shot per narration line.
 *
 * Reads docs/video/build/timeline.json (written by make_narration.py) and holds
 * each shot for exactly as long as its narration runs, so the finished video
 * needs no manual alignment — both halves follow the same list of scenes.
 *
 *     node scripts/video/record.mjs                       # against :8011
 *     DELAXIS_URL=http://localhost:8000 node scripts/video/record.mjs
 *
 * Every action below must match a scene's `action` in scenes.py; an unknown
 * action stops the run rather than silently recording a still frame.
 */

import { mkdirSync, readFileSync, readdirSync, renameSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..');

// Playwright is a devDependency of the Studio, not of the repo root, so it is
// resolved from there rather than duplicated into a second package.json.
const require = createRequire(join(ROOT, 'workflow-editor', 'package.json'));
const { chromium } = require('playwright');
const BUILD = join(ROOT, 'docs', 'video', 'build');
const BASE = process.env.DELAXIS_URL ?? 'http://127.0.0.1:8011';

const WIDTH = 1920;
const HEIGHT = 1080;

const timeline = JSON.parse(readFileSync(join(BUILD, 'timeline.json'), 'utf8'));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Move the pointer along a path so the cursor reads as deliberate, not teleporting. */
const glide = async (page, to, steps = 22) => {
    await page.mouse.move(to.x, to.y, { steps });
};

const centreOf = async (locator) => {
    const box = await locator.boundingBox();
    return box ? { x: box.x + box.width / 2, y: box.y + box.height / 2 } : null;
};

const clickSlowly = async (page, locator) => {
    const point = await centreOf(locator);
    if (point) await glide(page, point);
    await sleep(320);
    await locator.click();
};

const dropOnCanvas = async (page, tone, fx, fy) => {
    await page.evaluate(([t, x, y]) => {
        const tile = document.querySelector(`.dlx-tile[data-tone="${t}"]`);
        const pane = document.querySelector('.react-flow__pane');
        if (!tile || !pane) return;
        const dt = new DataTransfer();
        tile.dispatchEvent(new DragEvent('dragstart', { dataTransfer: dt, bubbles: true }));
        const r = pane.getBoundingClientRect();
        const at = { clientX: r.left + r.width * x, clientY: r.top + r.height * y };
        pane.dispatchEvent(new DragEvent('dragenter', { dataTransfer: dt, bubbles: true, ...at }));
        pane.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, ...at }));
        pane.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, ...at }));
        tile.dispatchEvent(new DragEvent('dragend', { dataTransfer: dt, bubbles: true }));
    }, [tone, fx, fy]);
};

const closeAnyModal = async (page) => {
    for (let attempt = 0; attempt < 3; attempt += 1) {
        const modal = page.locator('div.fixed.inset-0');
        if (!(await modal.count())) return;
        await page.keyboard.press('Escape').catch(() => {});
        await sleep(300);
        if (!(await page.locator('div.fixed.inset-0').count())) return;
        const closer = modal.last().getByRole('button', { name: /close/i }).first();
        if (await closer.count()) await closer.click({ timeout: 2000 }).catch(() => {});
        await sleep(300);
    }
};

const enterStudio = async (page) => {
    const enter = page.getByRole('button', { name: /Open the Studio|Enter Studio/i }).first();
    if (await enter.count()) {
        await clickSlowly(page, enter);
        await sleep(1800);
    }
};

// --------------------------------------------------------------------------- //
// One function per scene action
// --------------------------------------------------------------------------- //

const ACTIONS = {
    async landing(page) {
        await page.goto(BASE, { waitUntil: 'networkidle' });
        await sleep(800);
        await closeAnyModal(page);
    },

    async landing_features(page) {
        // Ease down to the capability section rather than jumping.
        await page.evaluate(async () => {
            const target = document.body.scrollHeight * 0.42;
            const start = window.scrollY;
            const frames = 90;
            for (let i = 0; i <= frames; i += 1) {
                const t = i / frames;
                const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
                window.scrollTo(0, start + (target - start) * eased);
                await new Promise((r) => setTimeout(r, 16));
            }
        });
    },

    async open_builder(page) {
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
        await sleep(700);
        await enterStudio(page);
        await clickSlowly(page, page.getByRole('button', { name: 'Builder' }).first());
        await sleep(900);
    },

    async type_brief(page) {
        const box = page.locator('textarea').last();
        if (await box.count()) {
            await clickSlowly(page, box);
            await box.fill('');
            // Typed at reading speed so the viewer can follow the sentence.
            await box.type(
                'A customer support assistant that answers from our product documentation '
                + 'and hands anything it cannot resolve to a human.',
                // Deliberately slow so the sentence is readable on screen; the
                // guard timeout is for missed selectors, not for this.
                { delay: 38, timeout: 15000 },
            );
        }
    },

    async hold_builder(page) {
        // Let the composed brief sit on screen while the narration explains the
        // inventory behind it. No new interaction — the point is what is already
        // visible.
        await sleep(200);
    },

    async show_canvas(page) {
        await closeAnyModal(page);
        const builder = page.getByRole('button', { name: 'Builder' }).first();
        if (await builder.count()) await builder.click().catch(() => {});
        await sleep(600);

        // Load a workflow that already has a shape worth reading.
        const picker = page.locator('select').first();
        if (await picker.count()) {
            const values = await picker.locator('option').allTextContents();
            const wanted = values.find((v) => /triage|support|pipeline/i.test(v));
            if (wanted) {
                await picker.selectOption({ label: wanted }).catch(() => {});
                await sleep(1800);
            }
        }
    },

    async palette_drag(page) {
        await dropOnCanvas(page, 'security', 0.34, 0.66);
        await sleep(900);
        await dropOnCanvas(page, 'data', 0.62, 0.68);
        await sleep(700);
    },

    async open_store(page) {
        const library = page.locator('.dlx-tile').last();
        await clickSlowly(page, library);
        await sleep(700);
        const browse = page.getByRole('button', { name: /Browse all/i });
        if (await browse.count()) {
            await clickSlowly(page, browse);
            await sleep(1200);
        }
    },

    async filter_store(page) {
        const modal = page.locator('div.fixed.inset-0').last();
        const rail = modal.locator('aside');
        const privacy = rail.getByRole('button').filter({ hasText: 'Privacy' }).first();
        if (await privacy.count()) {
            await clickSlowly(page, privacy);
            await sleep(1000);
        }
    },

    async open_inspector(page) {
        await closeAnyModal(page);
        await sleep(400);
        if (!(await page.locator('.react-flow__node').count())) {
            await dropOnCanvas(page, 'agent', 0.45, 0.45);
            await sleep(900);
        }
        const node = page.locator('.react-flow__node').first();
        if (await node.count()) {
            await node.click({ timeout: 3000 }).catch(() => {});
            await sleep(900);
        }
    },

    async inspector_tabs(page) {
        // Walk the inspector tabs so each group of settings is actually seen.
        for (const name of ['Model', 'Tools', 'Runtime']) {
            const tab = page.getByRole('button', { name, exact: true }).first();
            if (await tab.count()) {
                await clickSlowly(page, tab);
                await sleep(1500);
            }
        }
    },

    async show_tool_families(page) {
        const library = page.locator('.dlx-tile').last();
        await clickSlowly(page, library);
        await sleep(600);
        const browse = page.getByRole('button', { name: /Browse all/i });
        if (await browse.count()) {
            await clickSlowly(page, browse);
            await sleep(1000);
        }
        const modal = page.locator('div.fixed.inset-0').last();
        const rail = modal.locator('aside');
        for (const shelf of ['Databases', 'Files', 'Security', 'Audit']) {
            const button = rail.getByRole('button').filter({ hasText: shelf }).first();
            if (await button.count()) {
                await clickSlowly(page, button);
                await sleep(1500);
            }
        }
    },

    async open_help(page) {
        await closeAnyModal(page);
        await sleep(400);
        await clickSlowly(page, page.getByRole('button', { name: 'Help' }).first());
        await sleep(1200);
    },

    async help_fix(page) {
        const fixAll = page.getByRole('button', { name: /Fix all/i });
        if (await fixAll.count()) {
            await sleep(900);
            await clickSlowly(page, fixAll);
            await sleep(1600);
        } else {
            const fix = page.getByRole('button', { name: /Add a trigger|Remove the/i }).first();
            if (await fix.count()) {
                await clickSlowly(page, fix);
                await sleep(1400);
            }
        }
    },

    async help_components(page) {
        const tab = page.getByRole('button', { name: /Components/i }).first();
        if (await tab.count()) {
            await clickSlowly(page, tab);
            await sleep(1100);
            const first = page.locator('button').filter({ hasText: /Agent|Trigger|Tool/ }).nth(2);
            if (await first.count()) await first.click().catch(() => {});
            await sleep(900);
        }
    },

    async closing(page) {
        await closeAnyModal(page);
        await sleep(500);
        const deploy = page.getByRole('button', { name: /^Deploy/i }).first();
        if (await deploy.count()) {
            await clickSlowly(page, deploy);
            await sleep(2200);
        }
    },
};

// --------------------------------------------------------------------------- //

const run = async () => {
    mkdirSync(BUILD, { recursive: true });

    const missing = timeline.scenes.filter((s) => !ACTIONS[s.action]);
    if (missing.length) {
        throw new Error(`no action implemented for: ${missing.map((s) => s.action).join(', ')}`);
    }

    const browser = await chromium.launch({ args: ['--force-device-scale-factor=1'] });
    const context = await browser.newContext({
        viewport: { width: WIDTH, height: HEIGHT },
        deviceScaleFactor: 1,
        recordVideo: { dir: BUILD, size: { width: WIDTH, height: HEIGHT } },
        colorScheme: 'light',
    });
    const page = await context.newPage();
    // Well under the shortest scene, so a missed selector costs a beat rather
    // than pushing the shot past its narration.
    page.setDefaultTimeout(4000);

    // A visible theme choice up front, so the recording does not open on the
    // system default and change on the first interaction.
    await page.addInitScript(() => {
        try { localStorage.setItem('delaxis-theme', 'light'); } catch {}
    });

    const started = Date.now();
    for (const scene of timeline.scenes) {
        const sceneStart = Date.now();
        process.stdout.write(`  ${scene.id.padEnd(18)} hold ${scene.hold_seconds.toFixed(1)}s `);

        try {
            await ACTIONS[scene.action](page);
        } catch (error) {
            process.stdout.write(`(action failed: ${error.message.split('\n')[0]}) `);
        }

        // Hold the shot for whatever the narration still needs.
        const remaining = scene.hold_seconds * 1000 - (Date.now() - sceneStart);
        if (remaining > 0) await sleep(remaining);
        process.stdout.write(`✓ ${((Date.now() - sceneStart) / 1000).toFixed(1)}s\n`);
    }

    await context.close();
    await browser.close();

    // Playwright names the file by an internal id; give it a predictable name.
    const recorded = readdirSync(BUILD).filter((f) => f.endsWith('.webm'));
    const newest = recorded
        .map((f) => ({ f, t: statSync(join(BUILD, f)).mtimeMs }))
        .sort((a, b) => b.t - a.t)[0];
    if (newest) {
        renameSync(join(BUILD, newest.f), join(BUILD, 'screen.webm'));
    }

    console.log(`\n  recorded ${((Date.now() - started) / 1000).toFixed(1)}s -> ${join(BUILD, 'screen.webm')}`);
};

run().catch((error) => {
    console.error('FATAL:', error.message);
    process.exit(1);
});
