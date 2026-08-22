/**
 * Theme contrast audit.
 *
 * Walks every visible element across the Studio's main views in both themes and
 * reports text that cannot be read against the surface actually painted behind
 * it. Run it against a live server:
 *
 *     npm run audit:theme                       # against http://127.0.0.1:8011
 *     DELAXIS_URL=http://localhost:8000 npm run audit:theme
 *
 * Exits non-zero when anything fails, so it can gate a change.
 */
import { chromium } from 'playwright';
import { writeFileSync, mkdirSync } from 'node:fs';

const BASE = process.env.DELAXIS_URL ?? 'http://127.0.0.1:8011';
const OUT = process.env.AUDIT_OUT ?? new URL('../.theme-audit', import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

/**
 * Walk every visible element and report the ones whose text cannot be read
 * against the surface actually painted behind it.
 *
 * The interesting failure is not "low contrast" in the abstract — it is a
 * component that looks right in one theme and breaks in the other, which is
 * what a half-migrated palette produces. So the same probe runs in both themes
 * and the results are diffed.
 */
const CONTRAST_PROBE = () => {
    // Tailwind v4 emits oklch(), and getComputedStyle hands it back verbatim.
    // A canvas context normalises any colour the browser understands into
    // rgb/rgba, which is the only reliable way to compare them numerically.
    // Two colour sources need different handling. The design tokens are literal
    // rgba() strings, which parse exactly — and must, because un-premultiplying
    // a 14%-alpha tint from canvas bytes is numerically unstable and produces
    // channel values above 255. Tailwind v4's oklch() cannot be parsed by hand,
    // but it is always opaque, so a pixel readback is safe there.
    const _canvas = document.createElement('canvas');
    _canvas.width = _canvas.height = 1;
    const _ctx = _canvas.getContext('2d', { willReadFrequently: true });
    const _cache = new Map();

    const parse = (c) => {
        if (!c || c === 'transparent' || c === 'none') return { r: 0, g: 0, b: 0, a: 0 };
        if (_cache.has(c)) return _cache.get(c);

        let out = null;
        const m = c.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/);
        if (m) {
            const raw = m[4];
            const a = raw === undefined ? 1 : (raw.endsWith('%') ? parseFloat(raw) / 100 : parseFloat(raw));
            out = { r: +m[1], g: +m[2], b: +m[3], a };
        } else {
            // Opaque non-rgb format (oklch, colour keywords, hex).
            _ctx.clearRect(0, 0, 1, 1);
            _ctx.fillStyle = '#000000';
            _ctx.fillStyle = c;
            _ctx.fillRect(0, 0, 1, 1);
            const [r, g, b] = _ctx.getImageData(0, 0, 1, 1).data;
            out = { r, g, b, a: 1 };
        }

        _cache.set(c, out);
        return out;
    };

    const clamp = (v) => Math.max(0, Math.min(255, v));

    const over = (fg, bg) => {
        // Composite a translucent colour onto what is behind it.
        const a = fg.a;
        return {
            r: clamp(fg.r * a + bg.r * (1 - a)),
            g: clamp(fg.g * a + bg.g * (1 - a)),
            b: clamp(fg.b * a + bg.b * (1 - a)),
            a: 1,
        };
    };

    const lum = ({ r, g, b }) => {
        const f = (v) => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };

    const ratio = (a, b) => {
        const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
        return (x + 0.05) / (y + 0.05);
    };

    // Resolve the effective background by walking up until something opaque.
    const effectiveBg = (el) => {
        let node = el;
        let acc = null;
        while (node && node !== document.documentElement) {
            const bg = parse(getComputedStyle(node).backgroundColor);
            if (bg && bg.a > 0) {
                acc = acc === null ? bg : over(acc, bg);
                if (acc.a >= 1 || bg.a >= 1) return acc;
            }
            node = node.parentElement;
        }
        const root = parse(getComputedStyle(document.body).backgroundColor);
        return acc ? over(acc, root ?? { r: 255, g: 255, b: 255, a: 1 }) : (root ?? { r: 255, g: 255, b: 255, a: 1 });
    };

    const describe = (el) => {
        const cls = (el.className && typeof el.className === 'string') ? el.className.trim().slice(0, 90) : '';
        return `${el.tagName.toLowerCase()}${cls ? '.' + cls.split(/\s+/).slice(0, 4).join('.') : ''}`;
    };

    const findings = [];
    const seen = new Set();

    for (const el of document.querySelectorAll('*')) {
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || +style.opacity === 0) continue;

        const rect = el.getBoundingClientRect();
        if (rect.width < 4 || rect.height < 4) continue;

        // Only elements that own visible text.
        const own = [...el.childNodes]
            .filter((n) => n.nodeType === 3)
            .map((n) => n.textContent.trim())
            .join(' ')
            .trim();
        if (!own) continue;

        const fg = parse(style.color);
        if (!fg || fg.a === 0) continue;

        const bg = effectiveBg(el);
        const composited = fg.a < 1 ? over(fg, bg) : fg;
        const r = ratio(composited, bg);

        const size = parseFloat(style.fontSize);
        const bold = +style.fontWeight >= 600;
        const large = size >= 24 || (size >= 18.66 && bold);
        const need = large ? 3.0 : 4.5;

        if (r < need) {
            const key = describe(el) + '|' + own.slice(0, 30);
            if (seen.has(key)) continue;
            seen.add(key);
            findings.push({
                el: describe(el),
                text: own.slice(0, 55),
                ratio: +r.toFixed(2),
                need,
                color: style.color,
                bg: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`,
                size: `${size}px${bold ? ' bold' : ''}`,
            });
        }
    }

    // Also flag surfaces that stayed light while the page went dark: a strong
    // signal of a hardcoded class with no dark counterpart.
    const inverted = [];
    if (document.documentElement.classList.contains('dark')) {
        for (const el of document.querySelectorAll('*')) {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            if (rect.width < 60 || rect.height < 24) continue;
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const bg = parse(style.backgroundColor);
            if (!bg || bg.a < 0.85) continue;
            if (lum(bg) > 0.55) {
                const key = describe(el);
                if (inverted.some((i) => i.el === key)) continue;
                inverted.push({ el: key, bg: style.backgroundColor, size: `${Math.round(rect.width)}x${Math.round(rect.height)}` });
            }
        }
    }

    return { findings, inverted };
};

// Drive the app's own theme mechanism, not just the class. Toggling the class
// directly leaves React state behind, so any component reading `isDark` renders
// the wrong theme and the measurement is of a state no user can reach.
const setTheme = async (page, theme) => {
    await page.evaluate((t) => {
        localStorage.setItem('delaxis-theme', t);
        document.documentElement.classList.toggle('dark', t === 'dark');
        document.documentElement.style.colorScheme = t;
        window.dispatchEvent(new CustomEvent('delaxis-theme-change', { detail: t }));
    }, theme);
    await page.waitForTimeout(500);
};

// Each view: how to reach it from the canvas.
const VIEWS = [
    { name: 'landing', open: async () => {} },
    {
        name: 'canvas',
        open: async (page) => {
            await page.getByRole('button', { name: /Open the Studio/i }).click();
            await page.waitForTimeout(2000);
        },
    },
    {
        name: 'inspector',
        open: async (page) => {
            // Drop a node, then select it to open the properties panel.
            await page.evaluate(() => {
                const tile = document.querySelector('.dlx-tile[data-tone="agent"]');
                const pane = document.querySelector('.react-flow__pane');
                const dt = new DataTransfer();
                tile.dispatchEvent(new DragEvent('dragstart', { dataTransfer: dt, bubbles: true }));
                const r = pane.getBoundingClientRect();
                const at = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
                pane.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, ...at }));
                pane.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, ...at }));
                tile.dispatchEvent(new DragEvent('dragend', { dataTransfer: dt, bubbles: true }));
            });
            await page.waitForTimeout(900);
            await page.locator('.react-flow__node').first().click();
            await page.waitForTimeout(900);
        },
    },
    {
        name: 'library-store',
        open: async (page) => {
            await page.locator('.dlx-tile').last().click();
            await page.waitForTimeout(600);
            await page.getByRole('button', { name: /Browse all/i }).click();
            await page.waitForTimeout(1200);
        },
    },
    {
        name: 'library-tools',
        open: async (page) => {
            await page.locator('div.fixed.inset-0').last().getByRole('button', { name: /^Tools/i }).first().click();
            await page.waitForTimeout(1000);
        },
    },
    {
        name: 'library-ops',
        open: async (page) => {
            await page.locator('div.fixed.inset-0').last().getByRole('button', { name: /^Ops/i }).first().click();
            await page.waitForTimeout(1200);
        },
    },
    {
        name: 'help',
        open: async (page) => {
            // Earlier views leave the library modal open over the header. Rather
            // than guess at a dismiss control, start from a clean page — the
            // only deterministic way to reach the header again.
            await page.goto(BASE, { waitUntil: 'networkidle' });
            await page.getByRole('button', { name: /Open the Studio/i }).click();
            await page.waitForTimeout(2000);
            await page.getByRole('button', { name: 'Help' }).first().click({ timeout: 8000 });
            await page.waitForTimeout(1400);
        },
    },
];

const run = async () => {
    const report = {};
    const browser = await chromium.launch();

    for (const theme of ['light', 'dark']) {
        const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
        await page.goto(BASE, { waitUntil: 'networkidle' });
        await setTheme(page, theme);

        for (const view of VIEWS) {
            try {
                await view.open(page);
            } catch (e) {
                report[`${view.name}:${theme}`] = { error: `could not open: ${e.message.split('\n')[0]}` };
                continue;
            }
            await setTheme(page, theme);
            await page.waitForTimeout(400);

            const result = await page.evaluate(CONTRAST_PROBE);
            report[`${view.name}:${theme}`] = result;
            await page.screenshot({ path: `${OUT}/${view.name}-${theme}.png` });

            const n = result.findings.length;
            const inv = result.inverted.length;
            console.log(`  ${view.name.padEnd(16)} ${theme.padEnd(6)} contrast:${String(n).padStart(3)}  light-surface-in-dark:${inv}`);
        }
        await page.close();
    }

    await browser.close();
    writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2));
    console.log(`\nreport -> ${OUT}/report.json`);

    const failures = Object.values(report).reduce(
        (n, v) => n + (v.findings?.length ?? 0) + (v.inverted?.length ?? 0),
        0,
    );
    const unopened = Object.entries(report).filter(([, v]) => v.error);
    for (const [view, v] of unopened) console.log(`  could not open ${view}: ${v.error}`);

    if (failures) {
        console.log(`\n${failures} contrast failure(s) — see the report`);
        process.exit(1);
    }
    console.log('\nno contrast failures in either theme');
};

run().catch((e) => { console.error('FATAL:', e.message); process.exit(1); });
