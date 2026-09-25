import { useState } from 'react';
import { BookOpen, Github, X } from 'lucide-react';

const REPO_URL = 'https://github.com/mubinui/delaxis';
const INTRO_SEEN_KEY = 'delaxis-demo-intro-seen';

const WORKS: string[] = [
    'Drag agents, tools, routers and triggers onto the React Flow canvas',
    'Open the Library to create, edit and delete agents, tools, prompts and providers',
    'Run a workflow live — the timeline streams node, tool and token events',
    'Chat with the demo assistant; maths questions are computed for real',
    'Flash-deploy a workflow and manage triggers, webhooks and API keys',
];

const DOESNT: string[] = [
    'No LLM is called — agent replies are scripted, not generated',
    'The Builder explains itself instead of designing workflows',
    'Changes live in memory only and reset when you reload the page',
];

/**
 * Explains that this build talks to an in-browser stub rather than a real
 * backend. Shown once per tab, then available from a corner pill.
 */
export const DemoBadge = () => {
    const [open, setOpen] = useState(() => sessionStorage.getItem(INTRO_SEEN_KEY) === null);

    const close = () => {
        sessionStorage.setItem(INTRO_SEEN_KEY, '1');
        setOpen(false);
    };

    return (
        <>
            <button
                onClick={() => setOpen(true)}
                className="toast liquid fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 !py-1.5 !pr-4"
                title="About this demo"
            >
                <span className="sg" data-shape="warn" aria-hidden="true" />
                Demo — no backend
            </button>

            {open && (
                <div className="sheet-backdrop !z-[70]">
                    <div className="sheet max-h-[85vh] w-full max-w-lg overflow-y-auto p-6" role="dialog" aria-modal="true" aria-label="About this demo">
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <h2 className="title-1">You’re in the Delaxis demo</h2>
                                <p className="dlx-muted mt-1 text-[13px] leading-relaxed">
                                    This is the real Studio running against an in-browser stub of the API, so
                                    everything is clickable without a server, a database, or an API key.
                                </p>
                            </div>
                            <button onClick={close} className="dlx-btn dlx-btn-ghost shrink-0 p-1.5" title="Close">
                                <X size={16} />
                            </button>
                        </div>

                        <div className="mt-5">
                            <div className="h-section">What works</div>
                            <ul className="mt-2 space-y-1.5">
                                {WORKS.map((item) => (
                                    <li key={item} className="dlx-text-secondary flex gap-2 text-[13px] leading-relaxed">
                                        <span className="sg mt-[5px]" data-shape="ok" />
                                        {item}
                                    </li>
                                ))}
                            </ul>
                        </div>

                        <div className="mt-5">
                            <div className="h-section">What doesn’t</div>
                            <ul className="mt-2 space-y-1.5">
                                {DOESNT.map((item) => (
                                    <li key={item} className="dlx-muted flex gap-2 text-[13px] leading-relaxed">
                                        <span className="sg mt-[5px]" data-shape="idle" />
                                        {item}
                                    </li>
                                ))}
                            </ul>
                        </div>

                        <div className="mt-6 flex flex-wrap gap-2">
                            <button
                                onClick={close}
                                className="dlx-btn dlx-btn-primary flex-grow px-4 py-2.5 text-sm"
                            >
                                Explore the Studio
                            </button>
                            <a
                                href={REPO_URL}
                                target="_blank"
                                rel="noreferrer"
                                className="dlx-btn dlx-btn-secondary items-center gap-2 px-4 py-2.5 text-sm"
                            >
                                <Github size={15} />
                                Source
                            </a>
                            <a
                                href={`${REPO_URL}#installation`}
                                target="_blank"
                                rel="noreferrer"
                                className="dlx-btn dlx-btn-secondary items-center gap-2 px-4 py-2.5 text-sm"
                            >
                                <BookOpen size={15} />
                                Run it for real
                            </a>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};
