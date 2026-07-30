import { describe, expect, it } from 'vitest';
import { isBuildCommand, narration } from './useBuildNarration';

/**
 * The phrases are spoken, so what matters is that they read as sentences, stay
 * short enough not to overlap the next phase, and never leak a raw model id.
 */
describe('narration phrases', () => {
    it('turns a model id into something speakable', () => {
        expect(narration.modelChosen('anthropic/claude-opus-5')).toBe('Using Claude Opus 5.');
        expect(narration.modelChosen('google/gemini-3.6-flash')).toBe('Using Gemini 3 6 Flash.');
    });

    it('keeps GPT as an acronym rather than saying "Gpt"', () => {
        expect(narration.modelChosen('openai/gpt-5.6-sol')).toContain('GPT');
    });

    it('says nothing when no model was reported', () => {
        expect(narration.modelChosen('')).toBe('');
    });

    it('pluralises the plan summary', () => {
        expect(narration.planned(1, 1)).toBe('Plan ready: 1 agent and 1 tool.');
        expect(narration.planned(3, 2)).toBe('Plan ready: 3 agents and 2 tools.');
    });

    it('omits empty counts instead of saying "0 tools"', () => {
        expect(narration.planned(2, 0)).toBe('Plan ready: 2 agents.');
        expect(narration.planned(0, 0)).toBe('Plan ready.');
    });

    it('distinguishes a real design from the built-in fallback', () => {
        expect(narration.designed(false)).toContain('ready');
        expect(narration.designed(true)).toContain('built-in page');
    });

    it('names the tool when one came back', () => {
        expect(narration.repairedApi('Student Lookup')).toBe('Tool ready: Student Lookup.');
        expect(narration.repairedApi('')).toBe('Tool ready.');
    });

    it('reports failures without reading out a stack trace', () => {
        const spoken = narration.failed('Planning');
        expect(spoken).toBe('Planning failed. Check the message in the panel.');
    });

    it('keeps every fixed phrase short enough to finish before the next phase', () => {
        const fixed = [
            narration.planning,
            narration.applying,
            narration.applied,
            narration.designing,
            narration.repairingApi,
            narration.generatingConfig,
            narration.deploying,
            narration.deployed,
        ];
        for (const phrase of fixed) {
            expect(phrase.length).toBeLessThan(60);
            expect(phrase).toMatch(/\.$/);
        }
    });
});

describe('spoken build command', () => {
    it.each([
        'start building',
        'ok start the build',
        'go ahead and build it',
        'build it',
        "let's build",
        'begin building now',
        'kick off the build',
    ])('fires on %j', (phrase) => {
        expect(isBuildCommand(phrase)).toBe(true);
    });

    it('fires on a phrase assembled from transcript fragments', () => {
        // Deltas arrive split; the panel tests the accumulated turn.
        const accumulated = ' it should answer refund questions  ok start building';
        expect(isBuildCommand(accumulated)).toBe(true);
    });

    it.each([
        'I want to build a chatbot for refunds',
        'what should we build',
        'this is the building I work in',
        'tell me about the builder',
    ])('does not fire on %j', (phrase) => {
        expect(isBuildCommand(phrase)).toBe(false);
    });

    it.each([
        "don't start building yet",
        'do not build it',
        'not yet, start building after we add the tool',
        'wait, build it later',
        'before you start building, add a search tool',
    ])('does not fire on the negation %j', (phrase) => {
        // A false positive builds something nobody asked for, so negations and
        // hypotheticals have to lose.
        expect(isBuildCommand(phrase)).toBe(false);
    });
});
