import React, { useEffect, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { ArrowRight, Layers, Rocket, Zap } from 'lucide-react';
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

const FeatureCard = ({ icon: Icon, title, description, onClick }: {
    icon: LucideIcon;
    title: string;
    description: string;
    onClick: () => void;
}) => (
    <button
        onClick={onClick}
        className="group w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-5 text-left transition-colors hover:border-white/[0.12] hover:bg-white/[0.04]"
    >
        <div className="flex items-start gap-4">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10 text-blue-400">
                <Icon size={16} />
            </div>
            <div className="min-w-0 flex-grow">
                <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-white">{title}</h3>
                    <ArrowRight size={14} className="shrink-0 text-slate-600 transition-all group-hover:translate-x-0.5 group-hover:text-slate-300" />
                </div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{description}</p>
            </div>
        </div>
    </button>
);

const Step = ({ index, title, caption }: { index: string; title: string; caption: string }) => (
    <div>
        <div className="font-mono text-xs text-blue-500/80">{index}</div>
        <div className="mt-2 text-sm font-semibold text-white">{title}</div>
        <div className="mt-1 text-xs leading-relaxed text-slate-500">{caption}</div>
    </div>
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

    return (
        <div className="absolute inset-0 z-30 flex flex-col overflow-y-auto bg-[#0a0e16] font-sans text-slate-300 antialiased">
            {/* Single restrained glow */}
            <div className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full bg-blue-500/[0.07] blur-[160px]" />

            {/* Nav */}
            <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between px-8 py-6">
                <div className="flex items-center gap-3">
                    <DelaxisLogo className="h-8 w-8 rounded-lg" />
                    <div className="leading-tight">
                        <div className="text-sm font-semibold tracking-tight text-white">Delaxis</div>
                        <div className="text-[11px] text-slate-500">Multi-agent development studio</div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={onOpenAuth}
                        className="rounded-lg px-3 py-2 text-xs font-medium text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
                    >
                        Account
                    </button>
                    <button
                        onClick={onEnterStudio}
                        className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-500"
                    >
                        Enter Studio
                    </button>
                </div>
            </header>

            {/* Hero */}
            <main className="relative z-10 mx-auto w-full max-w-6xl flex-grow px-8 py-14">
                <div className="mb-10 inline-flex items-center gap-2 rounded-full border border-white/10 px-3 py-1.5">
                    <span
                        className={`h-1.5 w-1.5 rounded-full ${backendUp === null ? 'bg-slate-500' : backendUp ? 'bg-emerald-400' : 'bg-red-400'}`}
                    />
                    <span className="text-xs text-slate-400">{statusText}</span>
                </div>

                <div className="grid grid-cols-1 gap-16 lg:grid-cols-12 lg:items-start">
                    <div className="lg:col-span-7">
                        <h1 className="text-5xl font-semibold leading-[1.05] tracking-tight text-white md:text-6xl">
                            Build, test, and ship
                            <br />
                            <span className="text-blue-400">multi-agent workflows.</span>
                        </h1>

                        <p className="mt-6 max-w-xl text-[15px] leading-relaxed text-slate-400">
                            An open-source studio for CrewAI agents. Design workflows on a visual canvas,
                            wire in tools and knowledge, chat with your agents live, and deploy them as
                            standalone chat pages — all from one place.
                        </p>

                        <div className="mt-10 flex flex-wrap items-center gap-3">
                            <button
                                onClick={onEnterStudio}
                                className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500"
                            >
                                Open the Studio
                            </button>
                            <a
                                href="/docs"
                                target="_blank"
                                rel="noreferrer"
                                className="rounded-lg px-4 py-2.5 text-sm font-medium text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
                            >
                                API Reference →
                            </a>
                        </div>

                        <div className="mt-16 grid max-w-lg grid-cols-3 gap-8 border-t border-white/5 pt-8">
                            <Step index="01" title="Design" caption="Drag agents onto the canvas" />
                            <Step index="02" title="Test" caption="Chat with live LLMs" />
                            <Step index="03" title="Deploy" caption="One-click chat pages" />
                        </div>
                    </div>

                    <div className="space-y-3 lg:col-span-5">
                        <FeatureCard
                            icon={Layers}
                            title="Visual Workflow Canvas"
                            description="Compose selector, sequential, and parallel agent topologies with drag-and-drop nodes, tools, and triggers."
                            onClick={onEnterStudio}
                        />
                        <FeatureCard
                            icon={Zap}
                            title="Live LLM Tester"
                            description="Send prompts to any LiteLLM-supported model and inspect latency, token usage, and estimated cost."
                            onClick={onOpenTester}
                        />
                        <FeatureCard
                            icon={Rocket}
                            title="Flash Deployments"
                            description="Publish any workflow as a standalone chat page served at /d/<name>/ — embeddable with a single iframe."
                            onClick={onOpenDeploy}
                        />
                    </div>
                </div>
            </main>

            {/* Footer */}
            <footer className="relative z-10 border-t border-white/5">
                <div className="mx-auto flex w-full max-w-6xl flex-col justify-between gap-3 px-8 py-6 text-xs text-slate-500 sm:flex-row">
                    <span>© {new Date().getFullYear()} Delaxis · MIT License</span>
                    <span>Open source, self-hosted, and yours to extend.</span>
                </div>
            </footer>
        </div>
    );
};
