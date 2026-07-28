/**
 * Post-build step for the GitHub Pages demo.
 *
 * A real install serves a standalone chat page per flash deployment at
 * `/d/<name>/`. Pages only serves static files, so emit one page per seeded
 * deployment plus a 404 fallback — that fallback also covers deployments a
 * visitor creates during their session, which have no build-time entry.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const editorRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const outDir = join(editorRoot, 'dist-demo');
const basePath = process.env.VITE_BASE_PATH ?? '/';

const template = await readFile(join(editorRoot, 'demo-assets', 'deployed-chat.html'), 'utf8');
const seed = JSON.parse(await readFile(join(editorRoot, 'src', 'demo', 'seed.json'), 'utf8'));

const byId = Object.fromEntries(
    seed.deployments.map((deployment) => [
        deployment.id,
        {
            title: deployment.title,
            greeting: deployment.greeting,
            workflow_id: deployment.workflow_id,
            model_id: deployment.model_id,
        },
    ]),
);

const render = () =>
    template
        .replace('/*__DEPLOYMENTS__*/{}', JSON.stringify(byId))
        .replace("/*__STUDIO_URL__*/'/'", JSON.stringify(basePath));

const page = render();

for (const id of Object.keys(byId)) {
    const target = join(outDir, 'd', id);
    await mkdir(target, { recursive: true });
    await writeFile(join(target, 'index.html'), page);
}

// Pages serves 404.html for any unmatched path under the project base, so a
// deployment created during the session still lands on a working chat page.
await writeFile(join(outDir, '404.html'), page);

console.log(
    `emit-demo-pages: wrote ${Object.keys(byId).length} deployed chat page(s) + 404 fallback ` +
    `(base ${basePath})`,
);
