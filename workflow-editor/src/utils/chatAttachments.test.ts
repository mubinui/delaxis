import { describe, it, expect, vi, afterEach } from 'vitest';
import {
    CONTEXT_BUDGET,
    attachAndCompose,
    collectionForSession,
    composeMessage,
    retrievePassages,
    uploadAttachments,
} from './chatAttachments';

const passage = (text: string, source = 'policy.md') => ({ text, score: 0.4, source });

afterEach(() => vi.unstubAllGlobals());

describe('collectionForSession', () => {
    it('scopes uploads to one conversation', () => {
        expect(collectionForSession('abc')).toBe('chat-abc');
        expect(collectionForSession('abc')).not.toBe(collectionForSession('def'));
    });
});

describe('composeMessage', () => {
    it('leaves a message without attachments alone', () => {
        expect(composeMessage('hello', [], [])).toBe('hello');
    });

    it('carries the retrieved text, not just the filename', () => {
        // The whole point: a model told only the filename invents the contents.
        const out = composeMessage('what is the refund window?', ['policy.md'],
            [passage('Refunds are issued within 14 days of purchase.')]);
        expect(out).toContain('Refunds are issued within 14 days');
        expect(out).toContain('policy.md');
    });

    it('says the file could not be read when nothing was retrieved', () => {
        const out = composeMessage('summarise', ['scan.png'], []);
        expect(out).toContain('could not be read');
        expect(out).not.toContain('extracts follow');
    });

    it('supplies a question when the user sent only a file', () => {
        expect(composeMessage('', ['a.md'], [passage('body')])).toMatch(/^Please read the attached/);
    });

    it('stops adding passages once the budget is spent', () => {
        const long = passage('x'.repeat(4000));
        const out = composeMessage('q', ['a.md'], [long, long, long], CONTEXT_BUDGET);
        expect(out.split('--- policy.md ---').length - 1).toBe(1);
    });

    it('still sends something when the first passage alone exceeds the budget', () => {
        const out = composeMessage('q', ['a.md'], [passage('y'.repeat(9000))], 100);
        expect(out).toContain('--- policy.md ---');
        expect(out.length).toBeLessThan(1000);
    });
});

describe('uploadAttachments', () => {
    it('posts multipart without setting Content-Type', async () => {
        // Setting it by hand omits the boundary and the server rejects the body.
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true, json: async () => ({ files: [{ file: 'a.md', indexed: true }] }),
        });
        vi.stubGlobal('fetch', fetchMock);

        await uploadAttachments('', 'chat-1', [new File(['x'], 'a.md')]);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toContain('/api/v1/rag/collections/chat-1/files');
        expect(init.body).toBeInstanceOf(FormData);
        expect(init.headers).toBeUndefined();
    });

    it('does not call the server for an empty list', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        expect(await uploadAttachments('', 'chat-1', [])).toEqual([]);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('raises when the upload is rejected', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 413 }));
        await expect(uploadAttachments('', 'c', [new File(['x'], 'a.md')])).rejects.toThrow('413');
    });
});

describe('retrievePassages', () => {
    it('falls back to an empty list rather than throwing', async () => {
        // Retrieval failing must not stop the message being sent.
        vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
        expect(await retrievePassages('', 'c', 'q')).toEqual([]);
    });

    it('asks for a summary when the user typed nothing', async () => {
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [] }) });
        vi.stubGlobal('fetch', fetchMock);
        await retrievePassages('', 'c', '');
        expect(JSON.parse(fetchMock.mock.calls[0][1].body).query).toBe('summarise this document');
    });
});

describe('attachAndCompose', () => {
    it('uploads, retrieves, and returns a message carrying the text', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({ ok: true, json: async () => ({ files: [{ file: 'policy.md', indexed: true }] }) })
            .mockResolvedValueOnce({ ok: true, json: async () => ({ results: [passage('Refunds within 14 days.')] }) });
        vi.stubGlobal('fetch', fetchMock);

        const { message, uploaded } = await attachAndCompose(
            '', 'sess-1', 'refund window?', [new File(['x'], 'policy.md')]);
        expect(uploaded[0].indexed).toBe(true);
        expect(message).toContain('Refunds within 14 days.');
    });

    it('does not query when nothing indexed', async () => {
        const fetchMock = vi.fn().mockResolvedValueOnce({
            ok: true,
            json: async () => ({ files: [{ file: 'scan.png', indexed: false, error: 'no text' }] }),
        });
        vi.stubGlobal('fetch', fetchMock);

        const { message } = await attachAndCompose('', 's', 'read this', [new File(['x'], 'scan.png')]);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(message).toContain('could not be read');
    });
});
