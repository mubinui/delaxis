import { useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
    ArrowRight, ArrowUp, Bot, Check, Copy, Database, Flag, GripVertical, MessageSquare, Mic, Play, ScrollText,
    Server, ShieldCheck, Wrench,
} from 'lucide-react';
import { DelaxisLogo } from './DelaxisLogo';
import { StatusGlyph } from './shell/StatusGlyph';
import { MoreMenu } from './shell/Toolbar';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { useUiStore } from '../stores/uiStore';
import { DEMO_ENABLED } from '#demo';

const REPO_URL = 'https://github.com/mubinui/delaxis';
// The install command is for people who do not have Delaxis yet, so it only
// appears on the public demo site. A copy serving this page is already running.
// `docker run` needs no clone, unlike `docker compose up`.
const COMMAND = 'docker run -p 8000:8000 ghcr.io/mubinui/delaxis:latest';

const lane = (kind: string) => ({ '--lane': `var(--k-${kind})` } as CSSProperties);

const CopyCommand = () => {
    const [copied, setCopied] = useState(false);
    return (
        <div className="inline-flex h-10 items-center gap-2.5 rounded-full pl-4 pr-1.5" style={{ background: 'var(--glass)' }}>
            <code className="mono !text-[13px]" style={{ color: 'var(--text)' }}>
                <span style={{ color: 'var(--dim)' }}>$ </span>{COMMAND}
            </code>
            <button
                type="button"
                className="btn btn-ghost btn-icon"
                aria-label={copied ? 'Copied' : 'Copy the command'}
                title={copied ? 'Copied' : 'Copy'}
                onClick={() => {
                    void navigator.clipboard?.writeText(COMMAND);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1600);
                }}
            >
                {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
        </div>
    );
};

/* ------------------------------------------------------------------ product fragments
   Each chapter is illustrated with the real interface, drawn in its own classes,
   rather than an icon in a card. */

/* The canvas in miniature, drawn with the Studio's own node classes. */
const DesignFragment = () => (
    <div
        className="@container relative h-[440px] overflow-hidden rounded-[28px]"
        style={{ background: 'var(--glass)', backgroundImage: 'radial-gradient(var(--grid-dot) 1px, transparent 1.3px)', backgroundSize: '22px 22px' }}
        aria-hidden="true"
    >
        {/* Where the chapter is narrow the palette steps aside and the canvas
            slides over and scales down, so no node is cut off. */}
        <div className="absolute inset-0 origin-[0_50%] @max-[680px]:-translate-x-[190px] @max-[680px]:scale-[.85]">
        <svg className="absolute inset-0" width="100%" height="100%" style={{ overflow: 'visible' }}>
            <path d="M298 196 C312 196 312 196 326 196" stroke="var(--wire)" strokeWidth="1.5" fill="none" />
            <path d="M558 196 C582 196 588 196 612 196" stroke="var(--text)" strokeWidth="2" fill="none" />
            <path d="M384 318 L384 246" stroke="var(--text)" strokeWidth="1.5" strokeDasharray="4 5" fill="none" />
        </svg>
        <div className="node-shape is-trigger absolute" style={{ ...lane('trigger'), left: 238, top: 166, width: 60, height: 60, borderRadius: '30px 15px 15px 30px' }}>
            <MessageSquare size={22} strokeWidth={1.7} />
            <span className="node-caption"><span className="node-title">On chat</span><span className="node-sub">Chat message</span></span>
        </div>
        <div className="node-card is-agent is-selected absolute" style={{ ...lane('agent'), left: 326, top: 150, width: 232 }}>
            <span className="tile"><Bot size={19} strokeWidth={1.7} /></span>
            <span className="node-text"><span className="node-title">search_assistant</span><span className="node-sub">gemini-3.5-flash-lite</span></span>
            <div className="port-labels"><span style={{ left: '25%' }}>Tools</span><span style={{ left: '50%' }}>Memory</span><span style={{ left: '75%' }}>Knowledge</span></div>
        </div>
        <div className="node-shape is-orb absolute" style={{ ...lane('tool'), left: 358, top: 318, width: 52, height: 52 }}>
            <Wrench size={20} strokeWidth={1.7} />
            <span className="node-caption"><span className="node-title">search_web</span><span className="node-sub">Function</span></span>
        </div>
        <div className="node-shape is-square absolute" style={{ ...lane('output'), left: 612, top: 168, width: 56, height: 56, borderRadius: 14 }}>
            <Flag size={20} strokeWidth={1.7} />
            <span className="node-caption"><span className="node-title">Answer</span><span className="node-sub">Result</span></span>
        </div>
        </div>
        <div className="glass-pane absolute @max-[680px]:hidden" style={{ left: 20, top: 20, bottom: 20, width: 190 }}>
            <div className="headline px-4 pb-2 pt-3.5">Components</div>
            {([
                ['Start', [['trigger', Play, 'Manual'], ['trigger', MessageSquare, 'Chat']]],
                ['Agents', [['agent', Bot, 'Agent']]],
                ['Data', [['data', Database, 'SQL'], ['data', Database, 'MongoDB']]],
                ['Trust', [['trust', ShieldCheck, 'Security scan'], ['trust', ScrollText, 'Audit']]],
            ] as Array<[string, Array<[string, LucideIcon, string]>]>).map(([group, items]) => (
                <div key={group} className="px-2.5 pt-2">
                    <div className="h-section px-2 pb-1">{group}</div>
                    {items.map(([kind, Icon, label]) => (
                        <div key={label} className="pal-row" style={lane(kind)}>
                            <span className="tile is-sm"><Icon size={14} strokeWidth={1.8} /></span>
                            <span>{label}</span>
                            <GripVertical size={13} className="pal-hint" />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    </div>
);

const PROVIDERS = [
    ['OpenRouter', 'ok', 'Set'],
    ['Google Gemini', 'ok', 'Set'],
    ['OpenAI', 'ok', 'Set'],
    ['Anthropic Claude', 'warn', 'Rejected'],
    ['xAI Grok', 'idle', 'No key'],
    ['Ollama (Local)', 'idle', 'Not running'],
] as const;

/* The Test chat beside the model tester. Sized by its own width, not the
   viewport's: the two panes sit side by side only where both fit, and the
   tester steps aside when the chapter is narrow. */
const TestFragment = () => (
    <div className="@container rounded-[28px] p-7" style={{ background: 'var(--glass)' }} aria-hidden="true">
        <div className="grid h-[384px] grid-cols-1 gap-6 @min-[600px]:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-3 rounded-[22px] p-4" style={{ background: 'var(--window)', boxShadow: '0 0 0 .5px var(--lg-edge), var(--shadow-md)' }}>
            <div className="flex items-center gap-2.5 pb-1">
                <span className="text-[14px] font-semibold tracking-[-0.01em]">Test</span>
                <span className="inline-flex min-w-0 items-center gap-1.5 text-[12px]" style={{ color: 'var(--dim)' }}>
                    <StatusGlyph shape="ok" /><span className="truncate">Support Triage</span>
                </span>
            </div>
            <div className="msg-bot" style={{ color: 'var(--muted)' }}>Hi. I can search the web, answer from your documents, or work out the numbers.</div>
            <div className="flex-1" />
            <div className="msg-user">What is 18% of 2,450?</div>
            <div className="trace">
                <div><StatusGlyph shape="ok" /><span>Routed to <b style={{ color: 'var(--text)', fontWeight: 600 }}>calculator_agent</b></span><span className="trace-t">0.3 s</span></div>
                <div><StatusGlyph shape="ok" /><span><span className="mono">calculate</span> · 2450 × 0.18</span><span className="trace-t">4 ms</span></div>
            </div>
            <div className="msg-bot">18% of 2,450 is <b>441</b>.</div>
            <div className="composer mt-1">
                <div className="flex items-center justify-between py-0.5">
                    <span className="hint">Message the workflow</span>
                    <span className="send-btn" style={{ background: 'var(--fill-active)', color: 'var(--dim)' }}><ArrowUp size={14} /></span>
                </div>
            </div>
        </div>
        <div className="hidden min-w-0 flex-col gap-3.5 @min-[600px]:flex">
            <div className="figures rounded-[18px] px-4 py-3.5" style={{ background: 'var(--window)' }}>
                {/* Cells sized by their figures, so a long cost is never squeezed into a third. */}
                <div className="figure" style={{ flex: 'auto' }}><b>872<small>ms</small></b><span>Latency</span></div>
                <div className="figure" style={{ flex: 'auto' }}><b>209</b><span>Tokens</span></div>
                <div className="figure" style={{ flex: 'auto' }}><b>$0.000013</b><span>Cost</span></div>
            </div>
            <div className="table-box flex flex-1 flex-col">
                <table className="mtable">
                    <thead><tr><th>Provider</th><th>Key</th></tr></thead>
                    <tbody>
                        {PROVIDERS.map(([name, shape, text]) => (
                            <tr key={name}>
                                <td><span className="row-title block truncate">{name}</span></td>
                                <td className="whitespace-nowrap"><span className="row-status"><StatusGlyph shape={shape} />{text}</span></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <div className="mt-auto px-3 py-2.5 text-[11.5px]" style={{ color: 'var(--dim)', borderTop: '1px solid var(--line)' }}>
                    Keys stay on the server.
                </div>
            </div>
        </div>
        </div>
    </div>
);

const ShipFragment = () => (
    <div className="flex h-[440px] flex-col gap-4 rounded-[28px] p-7" style={{ background: 'var(--glass)' }} aria-hidden="true">
        <div className="table-box">
            <table className="mtable">
                <thead><tr><th>Page</th><th>Workflow</th><th>Status</th></tr></thead>
                <tbody>
                    <tr><td><span className="row-title">Support Assistant</span><span className="row-sub mono">/d/support-chat/</span></td><td className="mono">demo_multi_agent</td><td><span className="row-status"><StatusGlyph shape="ok" />Live</span></td></tr>
                    <tr><td><span className="row-title">E2E Search Demo</span><span className="row-sub mono">/d/e2e-search-demo/</span></td><td className="mono">e2e_search_demo</td><td><span className="row-status"><StatusGlyph shape="ok" />Live</span></td></tr>
                </tbody>
            </table>
        </div>
        <div className="flex flex-1 flex-col gap-2.5 rounded-2xl p-4" style={{ background: 'var(--window)' }}>
            <span className="h-section">Embed on your site</span>
            <pre className="mono m-0 whitespace-pre-wrap !text-[12.5px] leading-[1.7]" style={{ color: 'var(--muted)' }}>{'<script\n  src="https://delaxis.example.com/d/support-chat/embed.js"\n  defer></script>'}</pre>
        </div>
    </div>
);

const Chapter = ({ n, title, children, fragment }: { n: number; title: string; children: ReactNode; fragment: ReactNode }) => (
    <div className="grid items-center gap-10 lg:grid-cols-[400px_minmax(0,1fr)] lg:gap-16">
        <div>
            <div className="mb-3.5 grid h-6 w-6 place-items-center rounded-full text-[12px] font-semibold" style={{ background: 'var(--fill)' }}>{n}</div>
            <h3 className="landing-h3">{title}</h3>
            <p className="landing-p mt-3.5">{children}</p>
        </div>
        <div className="hidden min-w-0 md:block">{fragment}</div>
    </div>
);

const SPEC: Array<{ hue: string; icon: LucideIcon; title: string; body: string }> = [
    { hue: 'var(--hue-2)', icon: Database, title: 'Data your agents can reach', body: 'Query SQL and MongoDB with schema introspection and read-only enforcement, browse a file tree, and analyse uploaded PDFs, spreadsheets and images.' },
    { hue: 'var(--hue-6)', icon: ShieldCheck, title: 'Guardrails that hold', body: 'Detect prompt injection and leaked credentials, redact personal data, and block or clean content before it moves on.' },
    { hue: 'var(--hue-9)', icon: ScrollText, title: 'A record you can defend', body: 'An append-only, hash-chained audit trail. Alter one entry and verification names it.' },
    { hue: 'var(--hue-3)', icon: Server, title: 'Any model', body: 'OpenAI, Gemini, Grok, Claude, OpenRouter, vLLM and Ollama through LiteLLM, with a different model for each agent if you want one.' },
    { hue: 'var(--hue-4)', icon: Mic, title: 'Live voice', body: 'Talk to a chatbot over Gemini Live, in the Studio or on a deployed page. Audio is relayed server-side, so the key never reaches the browser.' },
    { hue: 'var(--hue-5)', icon: Wrench, title: 'MCP and OpenAPI', body: 'Attach an MCP server, or import a REST API from its Swagger spec. Every endpoint becomes a tool an agent can call.' },
];

/**
 * The front door. Apple-style: one confident headline, the real product on a
 * desktop, three chapters shown with the real interface, and a spec sheet.
 * No gradient text, no icon-in-a-card grids.
 */
export const LandingPage = () => {
    const { go, setAuthOpen } = useUiStore();
    const backend = useBackendStatus();

    const status = backend.up === null
        ? { shape: 'busy' as const, text: 'Checking the backend…' }
        : backend.up
            ? {
                shape: 'ok' as const,
                text: backend.counts
                    ? `Backend online · ${backend.counts.workflows} workflows · ${backend.counts.agents} agents · ${backend.counts.tools} tools`
                    : 'Backend online',
            }
            : { shape: 'bad' as const, text: 'Backend unreachable — start the API server' };

    return (
        <div className="landing fixed inset-0 overflow-y-auto" style={{ background: 'var(--window)' }}>
            <nav className="landing-nav">
                <button type="button" className="app-brand !p-0" onClick={() => window.scrollTo({ top: 0 })}>
                    <DelaxisLogo className="h-6 w-6" />
                    <b>Delaxis</b>
                </button>
                <div className="hidden items-center gap-1 md:flex">
                    <button type="button" className="landing-link" onClick={() => go('studio')}>Studio</button>
                    <button type="button" className="landing-link" onClick={() => go('tester')}>Model tester</button>
                    <button type="button" className="landing-link" onClick={() => go('deploy')}>Deployments</button>
                    <a className="landing-link" href="#included">What’s included</a>
                    <a className="landing-link" href="/docs" target="_blank" rel="noreferrer">API</a>
                </div>
                <div className="flex items-center gap-2 justify-self-end">
                    <button type="button" className="btn btn-ghost hidden sm:inline-flex" onClick={() => setAuthOpen(true)}>Sign in</button>
                    <button type="button" className="btn" onClick={() => go('studio')}>Open Studio</button>
                    <MoreMenu />
                </div>
            </nav>

            <header className="mx-auto flex max-w-[1080px] flex-col items-center px-5 pt-[132px] text-center md:pt-[150px]">
                <div className="inline-flex h-[30px] items-center gap-2.5 rounded-full px-3.5 text-[12.5px]" style={{ background: 'var(--fill)', color: 'var(--muted)' }} role="status">
                    <StatusGlyph shape={status.shape} />
                    <span className="truncate">{status.text}</span>
                </div>
                <h1 className="landing-hero mt-7">Build, test, and ship multi‑agent workflows.</h1>
                <p className="landing-lead mt-6 max-w-[680px]">
                    An open-source studio for CrewAI agents. Design on a canvas, wire in tools, data and guardrails,
                    talk to your agents live, and publish them as chat pages. All in one place, on your own machine.
                </p>
                <div className="mt-9 flex flex-col items-stretch gap-3 sm:flex-row sm:items-center">
                    <button type="button" className="btn btn-primary btn-lg" onClick={() => go('studio')}>Open the Studio</button>
                    <a className="btn btn-lg" href="/docs" target="_blank" rel="noreferrer">
                        API reference <ArrowRight size={15} />
                    </a>
                </div>
                {DEMO_ENABLED && <div className="mt-5"><CopyCommand /></div>}
            </header>

            {/* The product on a desktop: the one place a wallpaper shows, as it
                would behind a real window. */}
            <section className="mx-auto mt-[72px] max-w-[1312px] px-5">
                <div className="landing-desk">
                    <button
                        type="button"
                        className="landing-window"
                        onClick={() => go('studio')}
                        aria-label="Open the Studio"
                    >
                        <img src={`${import.meta.env.BASE_URL}studio-preview-light.jpg`} alt="" className="landing-shot only-light" loading="lazy" />
                        <img src={`${import.meta.env.BASE_URL}studio-preview-dark.jpg`} alt="" className="landing-shot only-dark" loading="lazy" />
                    </button>
                </div>
            </section>

            <section className="mx-auto max-w-[1312px] px-5 pt-32 md:px-16 md:pt-40">
                <div className="max-w-[760px]">
                    <h2 className="landing-h2">From an idea to a live page, in one window.</h2>
                    <p className="landing-p mt-4 !text-[19px]">
                        Most agent projects stall between a notebook and something people can use. Delaxis keeps the
                        design, the test run and the deployment next to each other.
                    </p>
                </div>
                <div className="mt-20 flex flex-col gap-24 md:mt-28 md:gap-28">
                    <Chapter n={1} title="Design on a canvas." fragment={<DesignFragment />}>
                        Drag triggers, agents, tools and guardrails onto one canvas and wire them together. Selector,
                        sequential and parallel topologies, with every setting in an inspector beside the node.
                    </Chapter>
                    <Chapter n={2} title="Test with live models." fragment={<TestFragment />}>
                        Chat with the workflow while you build it, and watch each handoff and tool call as it happens.
                        Check a provider’s key, latency and cost before an agent depends on it.
                    </Chapter>
                    <Chapter n={3} title="Ship a chat page." fragment={<ShipFragment />}>
                        Publish any workflow as a standalone chat page at <span className="mono !text-[15px]">/d/&lt;name&gt;/</span>,
                        with history, starter prompts and voice. Embed it with one script tag, an iframe, or the REST API.
                    </Chapter>
                </div>
            </section>

            <section id="included" className="mx-auto max-w-[1312px] scroll-mt-20 px-5 pt-36 md:px-16 md:pt-44">
                <div className="mb-11 flex flex-col justify-between gap-5 md:flex-row md:items-end">
                    <h2 className="landing-h2">Batteries included.</h2>
                    <p className="landing-p max-w-[520px]">
                        The pieces agent projects usually build by hand are already here, and each of them is a tool
                        your agents can call.
                    </p>
                </div>
                <div className="grid gap-x-10 sm:grid-cols-2 lg:grid-cols-3">
                    {SPEC.map(({ hue, icon: Icon, title, body }) => (
                        <div key={title} className="pb-8 pt-6" style={{ borderTop: '1px solid var(--line)' }}>
                            <Icon size={22} strokeWidth={1.7} style={{ color: hue }} />
                            <h3 className="mt-3.5 text-[17px] font-semibold tracking-[-0.014em]">{title}</h3>
                            <p className="mt-1.5 text-[14px] leading-[1.55]" style={{ color: 'var(--muted)' }}>{body}</p>
                        </div>
                    ))}
                </div>
            </section>

            <section className="mx-auto flex max-w-[1080px] flex-col items-center px-5 pt-32 text-center md:pt-40">
                <h2 className="landing-h2">{DEMO_ENABLED ? 'Run it on your machine.' : 'Everything runs here.'}</h2>
                <p className="landing-p mt-4 max-w-[640px] !text-[19px]">
                    {DEMO_ENABLED
                        ? 'One container serves the API, the Studio and every deployed chatbot. SQLite by default; add Postgres, Qdrant or Redis when you need them.'
                        : 'This one server holds the API, the Studio and every chatbot you deploy.'}
                </p>
                {DEMO_ENABLED && <div className="mt-8"><CopyCommand /></div>}
                <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                    <button type="button" className="btn btn-primary btn-lg" onClick={() => go('studio')}>Open the Studio</button>
                    <a className="btn btn-lg" href={REPO_URL} target="_blank" rel="noreferrer">View on GitHub</a>
                </div>
            </section>

            <footer className="mx-auto mt-32 max-w-[1312px] px-5 pb-9 md:px-16">
                <div className="flex flex-col justify-between gap-3 pt-6 text-[12px] sm:flex-row" style={{ color: 'var(--dim)', borderTop: '1px solid var(--line)' }}>
                    <span className="flex items-center gap-2">
                        <DelaxisLogo className="h-4 w-4" />© {new Date().getFullYear()} Delaxis · MIT License
                    </span>
                    <span className="flex flex-wrap gap-x-5 gap-y-1">
                        <a href={REPO_URL} target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>GitHub</a>
                        <a href="/docs" target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>API reference</a>
                        <span>Open source, self-hosted, and yours to extend.</span>
                    </span>
                </div>
            </footer>
        </div>
    );
};
