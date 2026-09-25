import { describe, expect, it } from 'vitest';
import { errorText } from './apiErrors';

describe('errorText', () => {
    it('passes a plain string detail through', () => {
        expect(errorText('Session not found', 'fallback')).toBe('Session not found');
    });

    it('reads the message out of a structured error object', () => {
        const detail = {
            error_code: 'MESSAGE_PROCESSING_FAILED',
            error_message: 'Failed to send message: Error 61 connecting to localhost:6379. Connection refused.',
            error_type: 'ConnectionError',
        };
        expect(errorText(detail, 'fallback')).toBe(detail.error_message);
    });

    it('falls back through message, error and nested detail', () => {
        expect(errorText({ message: 'Bad key' }, 'x')).toBe('Bad key');
        expect(errorText({ error: 'Timed out' }, 'x')).toBe('Timed out');
        expect(errorText({ detail: { error_message: 'Nested' } }, 'x')).toBe('Nested');
    });

    it('joins FastAPI validation errors', () => {
        const detail = [
            { loc: ['body', 'message'], msg: 'Field required' },
            { loc: ['body', 'max_turns'], msg: 'Input should be a valid integer' },
        ];
        expect(errorText(detail, 'x')).toBe('Field required; Input should be a valid integer');
    });

    it('never returns "[object Object]"', () => {
        expect(errorText({ unexpected: 1 }, 'HTTP 500')).toBe('HTTP 500');
        expect(errorText(null, 'HTTP 502')).toBe('HTTP 502');
        expect(errorText('', 'HTTP 400')).toBe('HTTP 400');
    });
});
