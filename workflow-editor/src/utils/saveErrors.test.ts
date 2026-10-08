import { describe, expect, it } from 'vitest';
import { describeSaveError, parseApiError } from './saveErrors';
import type { JsonObject } from '../types/json';

const dependency422 = `API 422: ${JSON.stringify({
    detail: {
        type: 'dependency_error',
        message: "Workflow 'untitled_workflow' references agents that do not exist: crewai_agent",
        dependencies: { missing: ['crewai_agent'], available: ['search_assistant', 'general_assistant'] },
    },
})}`;

describe('parseApiError', () => {
    it('splits status and JSON detail', () => {
        const parsed = parseApiError(dependency422);
        expect(parsed.status).toBe(422);
        expect((parsed.detail as JsonObject).type).toBe('dependency_error');
    });

    it('handles non-JSON bodies', () => {
        const parsed = parseApiError('API 500: internal error');
        expect(parsed.status).toBe(500);
        expect(parsed.raw).toBe('internal error');
    });

    it('handles messages without the API prefix', () => {
        const parsed = parseApiError('network down');
        expect(parsed.status).toBeUndefined();
        expect(parsed.raw).toBe('network down');
    });
});

describe('describeSaveError', () => {
    it('renders a dependency error with missing and available lists', () => {
        const text = describeSaveError(dependency422);
        expect(text).toContain('references agents that do not exist');
        expect(text).toContain('Missing: crewai_agent');
        expect(text).toContain('Available: search_assistant, general_assistant');
        expect(text).toContain('save it to your agent library');
        expect(text).not.toContain('{');
    });

    it('falls back to a plain message shape', () => {
        const text = describeSaveError(`API 400: ${JSON.stringify({ detail: { message: 'Bad name' } })}`);
        expect(text).toBe('Bad name');
    });

    it('returns the raw string when unparseable', () => {
        expect(describeSaveError('boom')).toBe('boom');
    });
});
