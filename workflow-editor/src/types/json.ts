/**
 * Free-form JSON as the backend stores it: agent, tool and workflow configs,
 * node settings, event payloads. Their shape is owned by the Python models and
 * varies per component type, so the Studio reads them dynamically.
 *
 * This is the one deliberate escape hatch from strict typing. Everything that
 * is not free-form config gets a real type instead of `any`.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- see above
export type JsonObject = Record<string, any>;
