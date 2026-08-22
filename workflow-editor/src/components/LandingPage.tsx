import React, { useEffect, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
    ArrowRight, Boxes, Database, FileUp, Layers, Mic, Rocket, ScrollText,
    ShieldCheck, Zap,
} from 'lucide-react';
import { DelaxisLogo } from './DelaxisLogo';
import { api } from '../api/client';

interface LandingPageProps {
    onEnterStudio: () => void;
    onOpenTester: () => void;
    onOpenDeploy: () => void;
    onOpenAuth: () => void;
}

interface StudioState {
    counts?: { workflows?: number; agents?: number; tools?: number };
}

/**
 * A feature the reader can act on. Cards that do something are buttons; cards
 * that only describe something are not, so the pointer never promises an
 * interaction that isn't there.
 */
const FeatureCard = ({
    icon: Icon,
    title,
    description,
    tone,
    onClick,
}: {
    icon: LucideIcon;
    title: string;
    description: string;
    tone: string;
    onClick?: () => void;
}) => {
    const body = (
        <>
            <span className="dlx-glyph h-9 w-9 shrink-0">
                <Icon size={16} />
            </span>
            <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                    <span className="dlx-text text-sm font-semibold">{title}</span>
                    {onClick && (
                        <ArrowRight
                            size={14}
                            className="dlx-faint shrink-0 transition-transform duration-200 group-hover:translate-x-0.5"
                        />
                    )}
                </span>
                <span className="dlx-muted mt-1.5 block text-[13px] leading-relaxed">{description}</span>
            </span>
        </>
    );

    const className = 'dlx-card group flex w-full items-start gap-4 p-4 text-left';

    return onClick ? (
        <button onClick={onClick} data-tone={tone} className={className}>
            {body}
        </button>
    ) : (
        <div data-tone={tone} className={className}>
            {body}
        </div>
    );
};

const Step = ({ index, title, caption }: { index: string; title: string; caption: string }) => (
    <div>
        <div className="font-mono text-xs font-semibold" style={{ color: 'var(--accent-text)' }}>
            {index}
        </div>
        <div className="dlx-text mt-2 text-sm font-semibold">{title}</div>
        <div className="dlx-muted mt-1 text-xs leading-relaxed">{caption}</div>
    </div>
);

const CapabilityPill = ({ icon: Icon, label, tone }: { icon: LucideIcon; label: string; tone: string }) => (
    <span
        data-tone={tone}
        className="dlx-chip px-3 py-1.5 text-xs"
        style={{
            color: 'var(--tone-fg)',
            backgroundColor: 'var(--tone-bg)',
            borderColor: 'var(--tone-border)',
        }}
    >
        <Icon size={13} />
        {label}
    </span>
);

export const LandingPage: React.FC<LandingPageProps> = ({
    onEnterStudio,
    onOpenTester,
    onOpenDeploy,
    onOpenAuth,
}) => {
    const [backendUp, setBackendUp] = useState<boolean | null>(null);
    const [counts, setCounts] = useState<{ workflows: number; agents: number; tools: number } | null>(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                await api('/health');
                if (!cancelled) setBackendUp(true);
                const state = await api<StudioState>('/api/v1/studio/state');
                if (!cancelled && state?.counts) {
                    setCounts({
                        workflows: state.counts.workflows ?? 0,
                        agents: state.counts.agents ?? 0,
                        tools: state.counts.tools ?? 0,
                    });
                }
            } catch {
                if (!cancelled) setBackendUp(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    const statusText = backendUp === null
        ? 'Checking backend…'
        : backendUp
            ? counts
                ? `Backend online · ${counts.workflows} workflows · ${counts.agents} agents · ${counts.tools} tools`
                : 'Backend online'
            : 'Backend unreachable — start the API server';

    const statusColor = backendUp === null
        ? 'var(--status-muted)'
        : backendUp
            ? 'var(--status-ready)'
            : 'var(--status-error)';

    return (
        <div
            className="absolute inset-0 z-30 flex flex-col overflow-y-auto font-sans antialiased"
            style={{ backgroundColor: 'var(--surface-base)', color: 'var(--text-secondary)' }}
        >
            {/* One restrained wash, built from the accent token so it tracks the theme
                instead of being a fixed blue that only works on a dark page. */}
            <div
                className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full"
                style={{
                    background: 'radial-gradient(closest-side, var(--accent-soft), transparent)',
                    filter: 'blur(60px)',
                }}
            />

            {/* Nav */}
            <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between px-8 py-6">
                <div className="flex items-center gap-3">
                    <DelaxisLogo className="h-8 w-8" />
                    <div className="leading-tight">
                        <div className="dlx-text text-sm font-semibold tracking-tight">Delaxis</div>
                        <div className="dlx-muted text-[11px]">Multi-agent development studio</div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={onOpenAuth} className="dlx-btn dlx-btn-ghost px-3 py-2 text-xs">
                        Account
                    </button>
                    <button onClick={onEnterStudio} className="dlx-btn dlx-btn-primary px-4 py-2 text-xs">
                        Enter Studio
                    </button>
                </div>
            </header>

            {/* Hero */}
            <main className="relative z-10 mx-auto w-full max-w-6xl flex-grow px-8 py-12">
                <div
                    className="dlx-chip mb-10 px-3 py-1.5"
                    style={{ borderColor: 'var(--border-default)', backgroundColor: 'var(--surface-2)' }}
                >
                    <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ backgroundColor: statusColor }}
                    />
                    <span className="dlx-muted text-xs font-medium">{statusText}</span>
                </div>

                <div className="grid grid-cols-1 gap-16 lg:grid-cols-12 lg:items-start">
                    <div className="lg:col-span-7">
                        <h1 className="dlx-text text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
                            Build, test, and ship
                            <br />
                            <span style={{ color: 'var(--accent-text)' }}>multi-agent workflows.</span>
                        </h1>

                        <p className="dlx-muted mt-6 max-w-xl text-[15px] leading-relaxed">
                            An open-source studio for CrewAI agents. Design workflows on a visual canvas,
                            wire in tools, data, and guardrails, chat with your agents live, and deploy
                            them as standalone chat pages — all from one place.
                        </p>

                        <div className="mt-10 flex flex-wrap items-center gap-3">
                            <button onClick={onEnterStudio} className="dlx-btn dlx-btn-primary px-5 py-2.5 text-sm">
                                Open the Studio
                            </button>
                            <a
                                href="/docs"
                                target="_blank"
                                rel="noreferrer"
                                className="dlx-btn dlx-btn-secondary px-4 py-2.5 text-sm"
                            >
                                API Reference
                                <ArrowRight size={14} />
                            </a>
                        </div>

                        <div
                            className="mt-14 grid max-w-lg grid-cols-3 gap-8 pt-8"
                            style={{ borderTop: '1px solid var(--border-subtle)' }}
                        >
                            <Step index="01" title="Design" caption="Drag agents onto the canvas" />
                            <Step index="02" title="Test" caption="Chat with live models" />
                            <Step index="03" title="Deploy" caption="One-click chat pages" />
                        </div>
                    </div>

                    <div className="space-y-3 lg:col-span-5">
                        <FeatureCard
                            icon={Layers}
                            tone="agent"
                            title="Visual Workflow Canvas"
                            description="Compose selector, sequential, and parallel topologies with drag-and-drop agents, tools, and triggers."
                            onClick={onEnterStudio}
                        />
                        <FeatureCard
                            icon={Zap}
                            tone="workflow"
                            title="Live Model Tester"
                            description="Send prompts to any LiteLLM-supported model and inspect latency, token usage, and estimated cost."
                            onClick={onOpenTester}
                        />
                        <FeatureCard
                            icon={Rocket}
                            tone="trigger"
                            title="Flash Deployments"
                            description="Publish any workflow as a standalone chat page at /d/<name>/ — embeddable with a single iframe."
                            onClick={onOpenDeploy}
                        />
                    </div>
                </div>

                {/* What comes in the box */}
                <section className="mt-24">
                    <h2 className="dlx-text text-xl font-semibold tracking-tight">Batteries included</h2>
                    <p className="dlx-muted mt-2 max-w-2xl text-sm leading-relaxed">
                        The pieces most agent projects end up building by hand are already here, and every
                        one of them is a tool your agents can call.
                    </p>

                    <div className="mt-6 flex flex-wrap gap-2">
                        <CapabilityPill icon={Boxes} label="MCP servers" tone="tool" />
                        <CapabilityPill icon={Database} label="SQL & MongoDB" tone="data" />
                        <CapabilityPill icon={FileUp} label="File & image analysis" tone="data" />
                        <CapabilityPill icon={ShieldCheck} label="Secret & injection scanning" tone="security" />
                        <CapabilityPill icon={ScrollText} label="Tamper-evident audit trail" tone="security" />
                        <CapabilityPill icon={Mic} label="Live voice" tone="trigger" />
                    </div>

                    <div className="mt-8 grid grid-cols-1 gap-3 md:grid-cols-3">
                        <FeatureCard
                            icon={Database}
                            tone="data"
                            title="Data your agents can reach"
                            description="Query SQL and MongoDB with schema introspection, browse a file tree, and analyse uploaded PDFs, spreadsheets, and images."
                        />
                        <FeatureCard
                            icon={ShieldCheck}
                            tone="security"
                            title="Guardrails that hold"
                            description="Detect prompt injection and leaked credentials, redact personal data, and block or clean content before it moves on."
                        />
                        <FeatureCard
                            icon={ScrollText}
                            tone="security"
                            title="A record you can defend"
                            description="An append-only, hash-chained audit trail. Alter one entry and verification names it."
                        />
                    </div>
                </section>
            </main>

            {/* Footer */}
            <footer className="relative z-10" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <div className="dlx-faint mx-auto flex w-full max-w-6xl flex-col justify-between gap-3 px-8 py-6 text-xs sm:flex-row">
                    <span>© {new Date().getFullYear()} Delaxis · MIT License</span>
                    <span>Open source, self-hosted, and yours to extend.</span>
                </div>
            </footer>
        </div>
    );
};
