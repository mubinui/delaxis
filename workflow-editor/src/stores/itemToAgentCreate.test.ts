import { describe, expect, it } from 'vitest';
import { itemToAgentCreate } from './libraryStore';

describe('itemToAgentCreate', () => {
    it('maps a blank canvas agent to a valid backend payload', () => {
        // Mirrors the palette "CrewAI Agent" node dragged onto the canvas.
        const payload = itemToAgentCreate({
            name: 'CrewAI Agent',
            config: { id: 'crewai_agent', type: 'LlmAgent', role: '', goal: '', tools: [] },
        });
        expect(payload.id).toBe('crewai_agent');
        // 'LlmAgent' is not a backend enum → coerced to conversable
        expect(payload.type).toBe('conversable');
        // empty model config → null, not {} (which fails backend validation)
        expect(payload.llm_config).toBeNull();
        expect(payload.name).toBe('CrewAI_Agent');
    });

    it('keeps a valid backend type and a real model config', () => {
        const payload = itemToAgentCreate({
            name: 'Assistant',
            config: {
                type: 'assistant',
                model_config: { provider_id: 'openrouter', model: 'openai/gpt-4o-mini', temperature: 0.5 },
            },
        });
        expect(payload.type).toBe('assistant');
        expect(payload.llm_config).toEqual({ provider_id: 'openrouter', model: 'openai/gpt-4o-mini', temperature: 0.5 });
    });

    it('sends null when a model config lacks provider or model', () => {
        const payload = itemToAgentCreate({
            name: 'Half',
            config: { type: 'conversable', model_config: { provider_id: 'openrouter' } },
        });
        expect(payload.llm_config).toBeNull();
    });
});

describe('agent execution settings', () => {
    it('splits CrewAI execution knobs out of model_config into agent_settings', () => {
        // The canvas keeps everything in one model_config bag; the API wants the
        // execution knobs separately from the sampling params.
        const payload = itemToAgentCreate({
            name: 'Limited',
            type: 'conversable',
            config: {
                id: 'limited',
                model_config: {
                    provider_id: 'gemini',
                    model: 'gemini-3.5-flash',
                    temperature: 0.3,
                    max_tokens: 512,
                    max_iter: 3,
                    max_execution_time: 45,
                    respect_context_window: false,
                },
            },
        }) as any;

        expect(payload.agent_settings).toEqual({
            max_iter: 3,
            max_execution_time: 45,
            respect_context_window: false,
        });
        // Sampling params stay on llm_config
        expect(payload.llm_config.temperature).toBe(0.3);
        expect(payload.llm_config.max_tokens).toBe(512);
    });

    it('sends null rather than an empty object when no limits are set', () => {
        const payload = itemToAgentCreate({
            name: 'Plain',
            type: 'conversable',
            config: { id: 'plain', model_config: { provider_id: 'gemini', model: 'm' } },
        }) as any;
        expect(payload.agent_settings).toBeNull();
    });

    it('carries is_selector through, which the API used to drop', () => {
        const payload = itemToAgentCreate({
            name: 'Router',
            type: 'conversable',
            config: { id: 'router', is_selector: true, model_config: { provider_id: 'g', model: 'm' } },
        }) as any;
        expect(payload.is_selector).toBe(true);
    });
});
