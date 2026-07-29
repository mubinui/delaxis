import { describe, expect, it } from 'vitest';
import {
    AGENT_SETTING_FIELDS,
    LLM_PARAM_FIELDS,
    fieldsForProvider,
    unsupportedFields,
} from './agentOptions';

const keys = (specs: { key: string }[]) => specs.map((s) => s.key);

describe('fieldsForProvider', () => {
    it('returns everything when the route is unknown', () => {
        expect(fieldsForProvider(LLM_PARAM_FIELDS)).toHaveLength(LLM_PARAM_FIELDS.length);
    });

    it('offers top_k only on the gemini route', () => {
        expect(keys(fieldsForProvider(LLM_PARAM_FIELDS, 'gemini'))).toContain('top_k');
        expect(keys(fieldsForProvider(LLM_PARAM_FIELDS, 'openai'))).not.toContain('top_k');
    });

    it('hides penalties and seed on anthropic, which ignores them', () => {
        const anthropic = keys(fieldsForProvider(LLM_PARAM_FIELDS, 'anthropic'));
        expect(anthropic).not.toContain('seed');
        expect(anthropic).not.toContain('frequency_penalty');
        expect(anthropic).not.toContain('presence_penalty');
        // ...but the universally supported ones stay
        expect(anthropic).toContain('temperature');
        expect(anthropic).toContain('max_tokens');
        expect(anthropic).toContain('top_p');
    });

    it('keeps every common parameter on openai-compatible routes', () => {
        const openai = keys(fieldsForProvider(LLM_PARAM_FIELDS, 'openai'));
        expect(openai).toEqual(expect.arrayContaining(['temperature', 'max_tokens', 'top_p', 'seed', 'frequency_penalty']));
    });
});

describe('unsupportedFields', () => {
    it('names what a route will discard so the UI can explain the gap', () => {
        expect(unsupportedFields(LLM_PARAM_FIELDS, 'anthropic')).toContain('Seed');
        expect(unsupportedFields(LLM_PARAM_FIELDS, 'openai')).toContain('Top K');
    });

    it('is empty when nothing is dropped', () => {
        expect(unsupportedFields(AGENT_SETTING_FIELDS, 'openai')).toEqual([]);
    });
});

describe('AGENT_SETTING_FIELDS', () => {
    it('exposes max_iter as the iteration control', () => {
        expect(keys(AGENT_SETTING_FIELDS)).toContain('max_iter');
    });

    it('omits agent-level max_tokens, which crewai 1.14.4 never reads', () => {
        expect(keys(AGENT_SETTING_FIELDS)).not.toContain('max_tokens');
    });

    it('omits deprecated crewai params', () => {
        const all = keys(AGENT_SETTING_FIELDS);
        for (const dead of ['reasoning', 'multimodal', 'allow_code_execution']) {
            expect(all).not.toContain(dead);
        }
    });

    it('applies to every route, since these are agent-level not model-level', () => {
        expect(AGENT_SETTING_FIELDS.every((spec) => !spec.providers)).toBe(true);
    });
});
