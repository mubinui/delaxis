/**
 * Drive the Studio and record it, one shot per narration line.
 *
 * Reads docs/video/build/timeline.json (written by make_narration.py) and holds
 * each shot for exactly as long as its narration runs, so the finished video
 * needs no manual alignment — both halves follow the same list of scenes.
 *
 *     node scripts/video/record.mjs
 *     node scripts/video/record.mjs --only=voice   # just that chapter
 *     DELAXIS_URL=http://localhost:8000 node scripts/video/record.mjs
 *
 * Each chapter is captured separately so the assembler has seams to dissolve,
 * which means each one starts from a blank browser and has to be walked back
 * into position first. That walk is on camera; the lead time is reported per
 * segment and trimmed off during assembly.
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
// The chat page the deploy chapter publishes to and the frontend chapter then
// visits. Served by the same app, so there is no second thing to start.
const DEPLOYMENT = process.env.DELAXIS_DEPLOYMENT ?? '/d/assistant-chat/';
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

// --------------------------------------------------------------------------- //
// Getting into position
// --------------------------------------------------------------------------- //

/** Time left in this scene's slot, so an action never overruns its narration. */
const budget = (scene) => scene.__start + scene.hold_seconds * 1000 - Date.now();

/**
 * Poll until something is true, giving up before the scene runs out.
 *
 * Overrunning is worse than missing the moment: every later line would play
 * against the wrong picture, and the drift never recovers.
 */
const waitWithin = async (scene, check, { reserve = 300, poll = 350 } = {}) => {
    while (budget(scene) > reserve) {
        if (await check().catch(() => false)) return true;
        await sleep(poll);
    }
    return false;
};

const openStudio = async (page) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await sleep(400);
    await closeAnyModal(page);
    await enterStudio(page);
    await sleep(700);
};

const loadWorkflow = async (page, prefer = /research brief|pipeline|triage/i) => {
    const picker = page.locator('select').first();
    if (!(await picker.count())) return;
    const options = await picker.locator('option').allTextContents();
    const wanted = options.find((v) => prefer.test(v));
    if (wanted) {
        await picker.selectOption({ label: wanted }).catch(() => {});
        await sleep(1600);
    }
};

/** Set by the deploy chapter so the frontend chapter can visit what it published. */
let publishedPath = '';

const builderPanel = (page) => page.locator('aside').last();

const openBuilderPanel = async (page) => {
    if (await builderPanel(page).getByRole('button', { name: 'Deploy', exact: true }).count()) return;
    const button = page.getByRole('button', { name: 'Builder' }).first();
    if (await button.count()) await button.click({ timeout: 2500 }).catch(() => {});
    await sleep(800);
};

/**
 * Each chapter is its own capture, so each starts from a blank browser and has
 * to be walked back into position. That walk is recorded too — the assembler
 * trims it off using the lead this reports, which is why nothing here needs to
 * look presentable.
 */
const PRIME = {
    landing: async (page) => {
        await page.goto(BASE, { waitUntil: 'networkidle' });
        await closeAnyModal(page);
        await page.mouse.move(WIDTH * 0.5, HEIGHT * 0.55, { steps: 8 });
    },
    builder: openStudio,
    voice: async (page) => {
        await openStudio(page);
        await openBuilderPanel(page);
        // The Studio remembers the last brief someone typed. Leaving it there
        // puts an unrelated half-written prompt on screen while the narration
        // is talking about starting from nothing.
        const boxes = builderPanel(page).locator('textarea');
        for (let index = 0; index < (await boxes.count()); index += 1) {
            await boxes.nth(index).fill('').catch(() => {});
        }
    },
    canvas: async (page) => {
        await openStudio(page);
        await loadWorkflow(page);
    },
    compose: async (page) => {
        await openStudio(page);
        await loadWorkflow(page);
    },
    inspect: async (page) => {
        await openStudio(page);
        await loadWorkflow(page);
    },
    help: async (page) => {
        await openStudio(page);
        await loadWorkflow(page);
    },
    deploy: async (page) => {
        await openStudio(page);
        // Whatever is published here is what the next chapter opens and talks
        // to, so it has to be a workflow that genuinely answers.
        await loadWorkflow(page, /assistant chatbot|docs q&a/i);
        await openBuilderPanel(page);
    },
    frontend: async (page) => {
        await page.goto(`${BASE}${publishedPath || DEPLOYMENT}`, { waitUntil: 'networkidle' });
        await sleep(1400);
    },
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

    // -- what it is ---------------------------------------------------------

    async landing(page) {
        await page.mouse.move(WIDTH * 0.42, HEIGHT * 0.5, { steps: 20 });
        const heading = page.locator('h1').first();
        if (await heading.count()) await showcase(page, heading, 700);
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

    // -- describing it ------------------------------------------------------

    async open_builder(page) {
        await clickSlowly(page, page.getByRole('button', { name: 'Builder' }).first(), { dwell: 420 });
        await sleep(600);
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
        await showcase(page, builderPanel(page), 900);
    },

    // -- talking to it ------------------------------------------------------

    async voice_open(page) {
        const mic = page.locator('button[title*="out loud" i]').first();
        if (await mic.count()) await point(page, mic, { dwell: 900 });
    },

    async voice_build(page, scene) {
        const mic = page.locator('button[title*="out loud" i]').first();
        if (await mic.count()) await clickSlowly(page, mic, { dwell: 260 });

        // Chromium is playing the instruction into a fake microphone and a real
        // session is listening, so from here it is a matter of waiting for the
        // model to act — never past the end of the line being spoken over it.
        await page.mouse.move(WIDTH * 0.45, HEIGHT * 0.5, { steps: 20 });
        const built = await waitWithin(scene, async () =>
            (await page.locator('.react-flow__node').count()) > 0);
        if (built) await sleep(400);
    },

    async voice_result(page, scene) {
        // The agent may still be arriving; it took about twelve seconds in
        // testing and the previous scene only covers part of that.
        await waitWithin(scene, async () =>
            (await page.locator('.react-flow__node').count()) > 0, { reserve: 2600 });

        const stop = page.locator('button[title*="Stop talking" i]').first();
        if (await stop.count()) await clickSlowly(page, stop, { dwell: 240 });

        const node = page.locator('.react-flow__node').first();
        if (await node.count()) await showcase(page, node, 900);
    },

    // -- the canvas ---------------------------------------------------------

    async show_canvas(page) {
        await closeAnyModal(page);
        const node = page.locator('.react-flow__node').first();
        if (await node.count()) await showcase(page, node, 700);
        const edge = page.locator('.react-flow__edge').first();
        if (await edge.count()) await point(page, edge, { dwell: 500 });
    },

    async run_workflow(page) {
        // The round control at the bottom-right of the canvas starts a run.
        const named = page.getByRole('button', { name: /^(run|execute)/i }).first();
        const target = (await named.count())
            ? named
            : page.locator('.react-flow').locator('..').locator('button').last();

        await clickSlowly(page, target, { dwell: 520 });
        await sleep(1300);

        // Follow the execution rather than the button: the timeline opens and
        // the nodes change state as work moves through the graph.
        const timeline = page.locator('button').filter({ hasText: 'Timeline' }).first();
        if (await timeline.count()) {
            await clickSlowly(page, timeline, { dwell: 320 });
            await sleep(700);
        }
        await showcase(page, page.locator('.react-flow__pane'), 800);
    },

    // -- composing by hand --------------------------------------------------

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

    // -- for the technical audience ----------------------------------------

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

    async inspector_tabs(page, scene) {
        for (const name of ['Model', 'Tools', 'Runtime']) {
            // Stop early rather than push the last tab past the narration; the
            // drift would carry through every later scene in this chapter.
            if (budget(scene) < 1900) break;
            const tab = page.getByRole('button', { name, exact: true }).first();
            if (await tab.count()) {
                await clickSlowly(page, tab, { dwell: 260 });
                await sleep(520);
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

    // -- fixing it ----------------------------------------------------------

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

    // -- shipping it --------------------------------------------------------

    async deploy_open(page) {
        const panel = builderPanel(page);
        await clickSlowly(page, panel.getByRole('button', { name: 'Deploy', exact: true }).first(), { dwell: 420 });
        await sleep(700);

        const title = panel.locator('input:not([type="checkbox"])').first();
        if (await title.count()) {
            await clickSlowly(page, title, { dwell: 200 });
            await title.fill('');
            await title.type('Docs Support Assistant', { delay: 30, timeout: 8000 });
        }

        // Daylight, to match the theme everything else is being recorded in.
        const swatch = panel.locator('button').filter({ hasText: /^Daylight$/i }).first();
        if (await swatch.count()) await clickSlowly(page, swatch, { dwell: 300 });

        // The narration promises the published page has voice in it, so turn
        // it on rather than describing something that is switched off.
        const voice = panel.locator('input[type="checkbox"]').first();
        if (await voice.count() && !(await voice.isChecked().catch(() => true))) {
            await clickSlowly(page, voice, { dwell: 260 });
        }
    },

    async deploy_publish(page, scene) {
        const panel = builderPanel(page);
        const publish = panel.getByRole('button', { name: /Flash Deploy/i }).first();
        if (await publish.count()) {
            await clickSlowly(page, publish, { dwell: 480 });
            await waitWithin(scene, async () =>
                (await page.locator('a[href*="/d/"], code, .font-mono').count()) > 0, { reserve: 4200 });
        }

        // Then the manager, which is where the URL, the embed snippet and the
        // API call actually live.
        const manager = page.locator('header').getByRole('button', { name: /Deploy/i }).first();
        if (await manager.count()) {
            await clickSlowly(page, manager, { dwell: 340 });
            await sleep(600);
        }
        for (const tab of [/Integrate/i, /REST API/i]) {
            if (budget(scene) < 1500) break;
            const button = page.getByRole('button', { name: tab }).last();
            if (await button.count()) {
                await clickSlowly(page, button, { dwell: 260 });
                await sleep(700);
            }
        }

        // Remember what was published; the frontend chapter opens exactly this.
        publishedPath = await fetch(`${BASE}/api/v1/deployments`)
            .then((r) => r.json())
            .then((list) => {
                const match = list.find((d) => /Docs Support Assistant/i.test(d.title || ''));
                return (match || list[list.length - 1] || {}).url || '';
            })
            .catch(() => '');
        if (publishedPath) console.log(`\n      published ${publishedPath}`);
    },

    // -- the thing you shipped ---------------------------------------------

    async frontend_open(page) {
        await page.mouse.move(WIDTH * 0.5, HEIGHT * 0.55, { steps: 16 });
        const header = page.locator('header, h1').first();
        if (await header.count()) await showcase(page, header, 700);
        const suggestion = page.locator('button').filter({ hasText: /\?$/ }).first();
        if (await suggestion.count()) await point(page, suggestion, { dwell: 600 });
    },

    async frontend_chat(page, scene) {
        const box = page.locator('textarea, input[type="text"]').last();
        if (!(await box.count())) return;
        await clickSlowly(page, box, { dwell: 200 });
        // Something the assistant genuinely knows. Asking it about Delaxis was
        // honest and useless: the model has never heard of it, and the shot
        // ended on a paragraph explaining that.
        await box.type('Explain multi-agent orchestration in two sentences.', { delay: 24, timeout: 8000 });
        await page.keyboard.press('Enter');

        // A real workflow is answering, so the wait is genuine — bounded by the
        // line being spoken over it.
        await waitWithin(scene, async () => {
            const text = await page.locator('body').innerText();
            return text.length > 700;
        }, { reserve: 900 });
        await page.mouse.move(WIDTH * 0.45, HEIGHT * 0.4, { steps: 16 });
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

    // One capture per chapter, so the assembler has seams to dissolve: a single
    // continuous recording cannot be crossfaded into itself.
    const segments = [];
    for (const scene of timeline.scenes) {
        const last = segments[segments.length - 1];
        if (last && last.chapter === scene.chapter) last.scenes.push(scene);
        else segments.push({ chapter: scene.chapter, scenes: [scene] });
    }

    // Re-recording a subset keeps the segments it skipped, so iterating on one
    // chapter does not mean driving the whole tour again.
    // --only=voice,frontend re-records just those chapters.
    const only = ((process.argv.find((a) => a.startsWith('--only=')) ?? '').split('=')[1] ?? '')
        .split(',').map((name) => name.trim()).filter(Boolean);
    let previous = [];
    if (only.length) {
        try {
            previous = JSON.parse(readFileSync(join(BUILD, 'segments.json'), 'utf8')).segments;
        } catch {
            throw new Error('--only needs an earlier full recording to keep the other segments from');
        }
    }

    const browser = await chromium.launch({
        args: [
            '--force-device-scale-factor=1',
            // The voice chapter records a real session. Chromium plays this file
            // as if it were a microphone, so the model hears an actual sentence
            // and the build that follows is not staged.
            '--use-fake-ui-for-media-stream',
            '--use-fake-device-for-media-stream',
            `--use-file-for-fake-audio-capture=${join(BUILD, 'voice-input.wav')}`,
            '--autoplay-policy=no-user-gesture-required',
        ],
    });
    const started = Date.now();
    const written = [];

    for (const [index, segment] of segments.entries()) {
        if (only.length && !only.some((name) => segment.chapter.includes(name))) {
            const kept = previous[index];
            if (!kept) throw new Error(`nothing recorded earlier for segment ${index} (${segment.chapter})`);
            written.push(kept);
            console.log(`  ${segment.chapter.padEnd(18)} kept`);
            continue;
        }

        const context = await browser.newContext({
            viewport: { width: WIDTH, height: HEIGHT },
            deviceScaleFactor: 1,
            recordVideo: { dir: BUILD, size: { width: WIDTH, height: HEIGHT } },
            colorScheme: 'light',
            permissions: ['microphone'],
        });
        await context.addInitScript(() => { try { localStorage.setItem('delaxis-theme', 'light'); } catch {} });
        await context.addInitScript(CURSOR_SCRIPT);

        const page = await context.newPage();
        // Well under the shortest scene, so a missed selector costs a beat
        // rather than pushing the shot past its narration.
        page.setDefaultTimeout(3000);

        // Recording starts with the context, so walking into position is on
        // camera. Time it, and the assembler cuts exactly that much off the front.
        const openedAt = Date.now();
        const prime = PRIME[segment.chapter];
        if (prime) {
            process.stdout.write(`  ${segment.chapter.padEnd(18)} priming… `);
            await prime(page).catch((error) => process.stdout.write(`(${error.message.split('\n')[0]}) `));
            console.log(`${((Date.now() - openedAt) / 1000).toFixed(1)}s`);
        }
        const lead = (Date.now() - openedAt) / 1000;

        for (const scene of segment.scenes) {
            scene.__start = Date.now();
            process.stdout.write(`    ${scene.id.padEnd(18)} ${scene.hold_seconds.toFixed(1)}s `);
            try {
                await ACTIONS[scene.action](page, scene);
            } catch (error) {
                process.stdout.write(`(action failed: ${error.message.split('\n')[0]}) `);
            }
            const remaining = scene.hold_seconds * 1000 - (Date.now() - scene.__start);
            if (remaining > 0) await sleep(remaining);
            const took = (Date.now() - scene.__start) / 1000;
            const over = took > scene.hold_seconds + 0.25 ? '  ← OVER' : '';
            process.stdout.write(`✓ ${took.toFixed(1)}s${over}\n`);
        }

        await context.close();

        const newest = readdirSync(BUILD)
            .filter((f) => f.endsWith('.webm') && !f.startsWith('segment-'))
            .map((f) => ({ f, t: statSync(join(BUILD, f)).mtimeMs }))
            .sort((a, b) => b.t - a.t)[0];
        const name = `segment-${String(index).padStart(2, '0')}-${segment.chapter}.webm`;
        if (newest) {
            renameSync(join(BUILD, newest.f), join(BUILD, name));
            written.push({
                file: name,
                chapter: segment.chapter,
                lead_seconds: Number(lead.toFixed(3)),
                scenes: segment.scenes.map((s) => s.id),
            });
        }
    }

    await browser.close();
    writeFileSync(join(BUILD, 'segments.json'), JSON.stringify({ segments: written }, null, 2) + '\n');

    console.log(`\n  recorded ${((Date.now() - started) / 1000).toFixed(1)}s across ${written.length} segment(s)`);
    for (const item of written) {
        console.log(`    ${item.file.padEnd(34)} lead ${String(item.lead_seconds).padStart(6)}s  [${item.scenes.join(', ')}]`);
    }
};

run().catch((error) => {
    console.error(error);
    process.exit(1);
});
