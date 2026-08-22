/**
 * Drive the Studio and record it, one shot per narration line.
 *
 * Reads docs/video/build/timeline.json (written by make_narration.py) and holds
 * each shot for exactly as long as its narration runs, so the finished video
 * needs no manual alignment — both halves follow the same list of scenes.
 *
 *     node scripts/video/record.mjs
 *     node scripts/video/record.mjs --only=card    # just the title cards
 *     DELAXIS_URL=http://localhost:8000 node scripts/video/record.mjs
 *
 * A synthetic cursor is drawn into the page, because a capture made this way has
 * no pointer of its own and the viewer cannot otherwise tell what is being
 * pointed at. Every interaction glides to its target and pauses before acting,
 * so the eye arrives before the click does.
 *
 * Every action must match a scene's `action` in scenes.py; an unknown action
 * stops the run rather than silently recording a still frame.
 */

import { mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

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

// --------------------------------------------------------------------------- //
// Synthetic cursor
// --------------------------------------------------------------------------- //

/** Drawn into the page, since a headless capture has no pointer of its own. */
const CURSOR_SCRIPT = () => {
    const install = () => {
        if (document.getElementById('__vidcursor')) return;

        const style = document.createElement('style');
        style.textContent = `
            #__vidcursor {
                position: fixed; left: 0; top: 0; width: 26px; height: 26px;
                z-index: 2147483647; pointer-events: none;
                transform: translate(-3px, -3px);
                transition: transform 40ms linear;
                filter: drop-shadow(0 2px 4px rgba(0,0,0,.45));
            }
            #__vidring {
                position: fixed; left: 0; top: 0; width: 42px; height: 42px;
                margin: -21px 0 0 -21px; border-radius: 50%;
                border: 2.5px solid rgba(91,124,255,.95);
                z-index: 2147483646; pointer-events: none; opacity: 0;
            }
            @keyframes __vidpulse {
                0%   { opacity: .95; transform: scale(.35); }
                100% { opacity: 0;   transform: scale(1.5); }
            }
        `;
        document.head.appendChild(style);

        const cursor = document.createElement('div');
        cursor.id = '__vidcursor';
        cursor.innerHTML = `
            <svg viewBox="0 0 24 24" width="26" height="26">
                <path d="M5 2 L5 19 L9.5 15 L12.5 21.5 L15.5 20 L12.5 13.8 L18.5 13.6 Z"
                      fill="#ffffff" stroke="#0a0d14" stroke-width="1.4" stroke-linejoin="round"/>
            </svg>`;
        document.body.appendChild(cursor);

        const ring = document.createElement('div');
        ring.id = '__vidring';
        document.body.appendChild(ring);

        window.addEventListener('mousemove', (event) => {
            cursor.style.transform = `translate(${event.clientX - 3}px, ${event.clientY - 3}px)`;
        }, true);

        // A click is otherwise invisible in the capture: nothing about a
        // headless page shows the button going down.
        window.addEventListener('mousedown', (event) => {
            ring.style.left = `${event.clientX}px`;
            ring.style.top = `${event.clientY}px`;
            ring.style.animation = 'none';
            void ring.offsetWidth;
            ring.style.animation = '__vidpulse .5s ease-out';
        }, true);
    };

    if (document.body) install();
    else document.addEventListener('DOMContentLoaded', install);
};

// --------------------------------------------------------------------------- //
// Motion helpers
// --------------------------------------------------------------------------- //

/** Ease the pointer along a path rather than teleporting it. */
const glide = async (page, to, steps = 26) => {
    await page.mouse.move(to.x, to.y, { steps });
};

const centreOf = async (locator) => {
    const box = await locator.boundingBox().catch(() => null);
    return box ? { x: box.x + box.width / 2, y: box.y + box.height / 2 } : null;
};

/** Move to the target and let the viewer see it before anything happens. */
const point = async (page, locator, { dwell = 420 } = {}) => {
    const target = await centreOf(locator);
    if (target) {
        await glide(page, target);
        await sleep(dwell);
    }
    return target;
};

const clickSlowly = async (page, locator, options = {}) => {
    await point(page, locator, options);
    await locator.click({ timeout: 3000 }).catch(() => {});
    await sleep(160);
};

/** Sweep the pointer across something worth reading, without clicking it. */
const showcase = async (page, locator, hold = 700) => {
    const box = await locator.boundingBox().catch(() => null);
    if (!box) return;
    await glide(page, { x: box.x + box.width * 0.25, y: box.y + box.height * 0.4 });
    await sleep(hold * 0.4);
    await glide(page, { x: box.x + box.width * 0.75, y: box.y + box.height * 0.6 }, 20);
    await sleep(hold * 0.6);
};

const dropOnCanvas = async (page, tone, fx, fy) => {
    // Take the pointer to the tile first, so the drag reads as intentional.
    const tile = page.locator(`.dlx-tile[data-tone="${tone}"]`).first();
    await point(page, tile, { dwell: 280 });

    const pane = await page.locator('.react-flow__pane').boundingBox().catch(() => null);
    if (pane) await glide(page, { x: pane.x + pane.width * fx, y: pane.y + pane.height * fy });

    await page.evaluate(([t, x, y]) => {
        const source = document.querySelector(`.dlx-tile[data-tone="${t}"]`);
        const target = document.querySelector('.react-flow__pane');
        if (!source || !target) return;
        const dt = new DataTransfer();
        source.dispatchEvent(new DragEvent('dragstart', { dataTransfer: dt, bubbles: true }));
        const r = target.getBoundingClientRect();
        const at = { clientX: r.left + r.width * x, clientY: r.top + r.height * y };
        target.dispatchEvent(new DragEvent('dragenter', { dataTransfer: dt, bubbles: true, ...at }));
        target.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, ...at }));
        target.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, ...at }));
        source.dispatchEvent(new DragEvent('dragend', { dataTransfer: dt, bubbles: true }));
    }, [tone, fx, fy]);
};

const closeAnyModal = async (page) => {
    for (let attempt = 0; attempt < 3; attempt += 1) {
        if (!(await page.locator('div.fixed.inset-0').count())) return;
        await page.keyboard.press('Escape').catch(() => {});
        await sleep(260);
        if (!(await page.locator('div.fixed.inset-0').count())) return;
        const closer = page.locator('div.fixed.inset-0').last()
            .getByRole('button', { name: /close/i }).first();
        if (await closer.count()) await closer.click({ timeout: 1500 }).catch(() => {});
        await sleep(260);
    }
};

const enterStudio = async (page) => {
    const enter = page.getByRole('button', { name: /Open the Studio|Enter Studio/i }).first();
    if (await enter.count()) {
        await clickSlowly(page, enter);
        await sleep(1500);
    }
};

// --------------------------------------------------------------------------- //
// Scene actions
// --------------------------------------------------------------------------- //

const ACTIONS = {
    async title_card(page, scene) {
        const file = pathToFileURL(join(HERE, 'titles', `${scene.card}.html`)).href;
        await page.goto(file, { waitUntil: 'load' });
        // Hide the synthetic pointer outright: moving it off-screen still leaves
        // it clipped at the corner, and a cursor on a title card looks like a slip.
        await page.addStyleTag({ content: '#__vidcursor,#__vidring{display:none!important}' })
            .catch(() => {});
        await page.mouse.move(-50, -50);
    },

    async landing(page) {
        await page.goto(BASE, { waitUntil: 'networkidle' });
        await sleep(500);
        await closeAnyModal(page);
        await page.mouse.move(WIDTH * 0.5, HEIGHT * 0.55, { steps: 10 });
    },

    async landing_features(page) {
        await page.evaluate(async () => {
            const target = document.body.scrollHeight * 0.4;
            const start = window.scrollY;
            for (let i = 0; i <= 60; i += 1) {
                const t = i / 60;
                const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
                window.scrollTo(0, start + (target - start) * eased);
                await new Promise((r) => setTimeout(r, 16));
            }
        });
        const card = page.locator('.dlx-card').first();
        if (await card.count()) await showcase(page, card, 600);
    },

    async open_builder(page) {
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
        await sleep(450);
        await enterStudio(page);
        await clickSlowly(page, page.getByRole('button', { name: 'Builder' }).first());
        await sleep(500);
    },

    async type_brief(page) {
        const box = page.locator('textarea').last();
        if (await box.count()) {
            await clickSlowly(page, box);
            await box.fill('');
            await box.type(
                'A support assistant that answers from our docs and escalates what it cannot handle.',
                // Fast enough to keep pace with the narration, slow enough to read.
                { delay: 24, timeout: 15000 },
            );
        }
    },

    async hold_builder(page) {
        const panel = page.locator('aside').last();
        if (await panel.count()) await showcase(page, panel, 900);
    },

    async show_canvas(page) {
        await closeAnyModal(page);
        const builder = page.getByRole('button', { name: 'Builder' }).first();
        if (await builder.count()) await builder.click({ timeout: 2500 }).catch(() => {});
        await sleep(350);

        const picker = page.locator('select').first();
        if (await picker.count()) {
            await point(page, picker, { dwell: 260 });
            const options = await picker.locator('option').allTextContents();
            const wanted = options.find((v) => /triage|support|pipeline/i.test(v));
            if (wanted) {
                await picker.selectOption({ label: wanted }).catch(() => {});
                await sleep(1500);
            }
        }
        const node = page.locator('.react-flow__node').first();
        if (await node.count()) await showcase(page, node, 650);
    },

    async run_workflow(page) {
        // The round control at the bottom-right of the canvas starts a run.
        const named = page.getByRole('button', { name: /^(run|execute)/i }).first();
        const target = (await named.count())
            ? named
            : page.locator('.react-flow').locator('..').locator('button').last();

        await clickSlowly(page, target, { dwell: 520 });
        await sleep(1400);

        // Follow the execution rather than the button: the timeline opens and
        // the nodes change state as work moves through the graph.
        const timeline = page.locator('button').filter({ hasText: 'Timeline' }).first();
        if (await timeline.count()) {
            await clickSlowly(page, timeline, { dwell: 320 });
            await sleep(800);
        }
        const canvas = page.locator('.react-flow__pane');
        if (await canvas.count()) await showcase(page, canvas, 900);
    },

    async palette_drag(page) {
        await closeAnyModal(page);
        await dropOnCanvas(page, 'security', 0.32, 0.7);
        await sleep(600);
        await dropOnCanvas(page, 'data', 0.6, 0.72);
        await sleep(400);
    },

    async open_store(page) {
        await clickSlowly(page, page.locator('.dlx-tile').last(), { dwell: 340 });
        await sleep(400);
        const browse = page.getByRole('button', { name: /Browse all/i });
        if (await browse.count()) {
            await clickSlowly(page, browse, { dwell: 340 });
            await sleep(800);
        }
        const card = page.locator('.dlx-card').first();
        if (await card.count()) await showcase(page, card, 650);
    },

    async filter_store(page) {
        const rail = page.locator('div.fixed.inset-0').last().locator('aside');
        const privacy = rail.getByRole('button').filter({ hasText: 'Privacy' }).first();
        if (await privacy.count()) {
            await clickSlowly(page, privacy, { dwell: 380 });
            await sleep(700);
            const card = page.locator('div.fixed.inset-0').last().locator('.dlx-card').first();
            if (await card.count()) await showcase(page, card, 650);
        }
    },

    async open_inspector(page) {
        await closeAnyModal(page);
        await sleep(250);
        if (!(await page.locator('.react-flow__node').count())) {
            await dropOnCanvas(page, 'agent', 0.45, 0.45);
            await sleep(600);
        }
        await clickSlowly(page, page.locator('.react-flow__node').first(), { dwell: 380 });
        await sleep(600);
    },

    async inspector_tabs(page) {
        for (const name of ['Model', 'Tools', 'Runtime']) {
            const tab = page.getByRole('button', { name, exact: true }).first();
            if (await tab.count()) {
                await clickSlowly(page, tab, { dwell: 300 });
                await sleep(800);
            }
        }
    },

    async show_tool_families(page) {
        await clickSlowly(page, page.locator('.dlx-tile').last(), { dwell: 280 });
        await sleep(350);
        const browse = page.getByRole('button', { name: /Browse all/i });
        if (await browse.count()) {
            await clickSlowly(page, browse, { dwell: 280 });
            await sleep(600);
        }
        const rail = page.locator('div.fixed.inset-0').last().locator('aside');
        for (const shelf of ['Databases', 'Files', 'Security', 'Audit']) {
            const button = rail.getByRole('button').filter({ hasText: shelf }).first();
            if (await button.count()) {
                await clickSlowly(page, button, { dwell: 240 });
                await sleep(700);
            }
        }
    },

    async open_help(page) {
        await closeAnyModal(page);
        await sleep(250);
        await clickSlowly(page, page.getByRole('button', { name: 'Help' }).first(), { dwell: 340 });
        await sleep(800);
        const finding = page.locator('button').filter({ hasText: /not connected|missing/i }).first();
        if (await finding.count()) await showcase(page, finding, 650);
    },

    async help_fix(page) {
        const fixAll = page.getByRole('button', { name: /Fix all/i });
        const single = page.getByRole('button', { name: /Add a trigger|Remove the/i }).first();
        const target = (await fixAll.count()) ? fixAll : single;
        if (await target.count()) {
            await clickSlowly(page, target, { dwell: 500 });
            await sleep(1300);
        }
    },
};

// --------------------------------------------------------------------------- //

const run = async () => {
    mkdirSync(BUILD, { recursive: true });

    const missing = timeline.scenes.filter((s) => !ACTIONS[s.action]);
    if (missing.length) {
        const names = [...new Set(missing.map((s) => s.action))].join(', ');
        throw new Error(`no action implemented for: ${names}`);
    }

    // Title cards and the app body are recorded separately so the assembler can
    // dissolve between them; a single continuous capture cannot be crossfaded
    // into itself.
    const segments = [];
    for (const scene of timeline.scenes) {
        const kind = scene.card ? `card-${scene.card}` : 'body';
        const last = segments[segments.length - 1];
        if (last && last.kind === kind) last.scenes.push(scene);
        else segments.push({ kind, scenes: [scene] });
    }

    // Re-recording a subset keeps the segments it skipped, so iterating on a
    // title card does not mean driving the whole app tour again.
    const only = (process.argv.find((a) => a.startsWith('--only=')) ?? '').split('=')[1] ?? '';
    let previous = [];
    if (only) {
        try {
            previous = JSON.parse(readFileSync(join(BUILD, 'segments.json'), 'utf8')).segments;
        } catch {
            throw new Error('--only needs an earlier full recording to keep the other segments from');
        }
    }

    const browser = await chromium.launch({ args: ['--force-device-scale-factor=1'] });
    const started = Date.now();
    const written = [];

    for (const [index, segment] of segments.entries()) {
        if (only && !segment.kind.includes(only)) {
            const kept = previous[index];
            if (!kept) throw new Error(`nothing recorded earlier for segment ${index} (${segment.kind})`);
            written.push(kept);
            console.log(`  ${segment.kind.padEnd(18)} kept`);
            continue;
        }

        const context = await browser.newContext({
            viewport: { width: WIDTH, height: HEIGHT },
            deviceScaleFactor: 1,
            recordVideo: { dir: BUILD, size: { width: WIDTH, height: HEIGHT } },
            colorScheme: 'light',
        });
        await context.addInitScript(() => { try { localStorage.setItem('delaxis-theme', 'light'); } catch {} });
        await context.addInitScript(CURSOR_SCRIPT);

        const page = await context.newPage();
        // Well under the shortest scene, so a missed selector costs a beat
        // rather than pushing the shot past its narration.
        page.setDefaultTimeout(3000);

        for (const scene of segment.scenes) {
            const sceneStart = Date.now();
            process.stdout.write(`  ${scene.id.padEnd(18)} ${scene.hold_seconds.toFixed(1)}s `);
            try {
                await ACTIONS[scene.action](page, scene);
            } catch (error) {
                process.stdout.write(`(action failed: ${error.message.split('\n')[0]}) `);
            }
            const remaining = scene.hold_seconds * 1000 - (Date.now() - sceneStart);
            if (remaining > 0) await sleep(remaining);
            process.stdout.write(`✓ ${((Date.now() - sceneStart) / 1000).toFixed(1)}s\n`);
        }

        await context.close();

        const newest = readdirSync(BUILD)
            .filter((f) => f.endsWith('.webm') && !f.startsWith('segment-'))
            .map((f) => ({ f, t: statSync(join(BUILD, f)).mtimeMs }))
            .sort((a, b) => b.t - a.t)[0];
        const name = `segment-${String(index).padStart(2, '0')}-${segment.kind}.webm`;
        if (newest) {
            renameSync(join(BUILD, newest.f), join(BUILD, name));
            written.push({ file: name, kind: segment.kind, scenes: segment.scenes.map((s) => s.id) });
        }
    }

    await browser.close();
    writeFileSync(join(BUILD, 'segments.json'), JSON.stringify({ segments: written }, null, 2) + '\n');

    console.log(`\n  recorded ${((Date.now() - started) / 1000).toFixed(1)}s across ${written.length} segment(s)`);
    for (const item of written) console.log(`    ${item.file}  [${item.scenes.join(', ')}]`);
};

run().catch((error) => {
    console.error('FATAL:', error.message);
    process.exit(1);
});
