/**
 * The human-readable message in a FastAPI error body's `detail`.
 *
 * `detail` comes in three shapes: a plain string, a structured error object
 * (`{ error_message, error_code, … }` from this API's handlers), or a list of
 * validation errors (`[{ loc, msg }]`). Passing the object straight to
 * `new Error()` is what printed "[object Object]" in the Studio.
 */
export const errorText = (detail: unknown, fallback: string): string => {
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
        const messages = detail
            .map((item) => (item && typeof item === 'object' && 'msg' in item ? String((item as { msg: unknown }).msg) : errorText(item, '')))
            .filter(Boolean);
        return messages.length ? messages.join('; ') : fallback;
    }
    if (detail && typeof detail === 'object') {
        const record = detail as Record<string, unknown>;
        for (const key of ['error_message', 'message', 'error', 'detail']) {
            const text = errorText(record[key], '');
            if (text) return text;
        }
    }
    return fallback;
};
