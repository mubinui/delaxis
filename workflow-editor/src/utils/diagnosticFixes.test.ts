import { describe, expect, it } from 'vitest';
import type { ApiProvider } from '../api/backendTypes';
import { firstWorkingProvider } from './diagnosticFixes';

const provider = (id: string, extra: Partial<ApiProvider> = {}): ApiProvider => ({
    id,
    name: id,
    type: 'llm',
    description: '',
    enabled: true,
    config: {},
    ...extra,
});

describe('firstWorkingProvider', () => {
    it('prefers an enabled provider the server holds a key for', () => {
        const chosen = firstWorkingProvider([
            provider('keyless', { key_source: 'none' }),
            provider('keyed', { key_source: 'env' }),
        ]);
        expect(chosen?.id).toBe('keyed');
    });

    it('accepts a key from the secret store or inline config too', () => {
        expect(firstWorkingProvider([provider('a', { key_source: 'none' }), provider('b', { key_source: 'secret_store' })])?.id).toBe('b');
        expect(firstWorkingProvider([provider('a', { key_source: 'inline' })])?.id).toBe('a');
    });

    it('skips disabled providers even when they have a key', () => {
        const chosen = firstWorkingProvider([
            provider('off', { key_source: 'env', enabled: false }),
            provider('on', { key_source: 'none' }),
        ]);
        expect(chosen?.id).toBe('on');
    });

    it('returns nothing when every provider is disabled', () => {
        expect(firstWorkingProvider([provider('off', { enabled: false })])).toBeUndefined();
    });
});
