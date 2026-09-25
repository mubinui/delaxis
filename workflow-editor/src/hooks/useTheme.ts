import { useEffect, useState } from 'react';

/** What the person chose. `system` follows the OS and keeps following it. */
export type ThemePreference = 'light' | 'dark' | 'system';
type Theme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'delaxis-theme';
const THEME_EVENT = 'delaxis-theme-change';

const systemQuery = () => window.matchMedia?.('(prefers-color-scheme: dark)');

const readPreference = (): ThemePreference => {
    if (typeof window === 'undefined') return 'system';
    try {
        const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
        if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
    } catch {
        // Storage can be blocked; fall through to the system setting.
    }
    return 'system';
};

const applyTheme = (theme: Theme) => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.documentElement.style.colorScheme = theme;
};

const systemIsDark = () => Boolean(systemQuery()?.matches);

export const useTheme = () => {
    const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
    const [systemDark, setSystemDark] = useState<boolean>(systemIsDark);
    const theme: Theme = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;

    useEffect(() => {
        applyTheme(theme);
    }, [theme]);

    // Match system keeps following the OS while it is chosen.
    useEffect(() => {
        const query = systemQuery();
        if (!query) return;
        const onChange = () => setSystemDark(query.matches);
        query.addEventListener('change', onChange);
        return () => query.removeEventListener('change', onChange);
    }, []);

    // Several components read the theme; keep them in step when one changes it.
    useEffect(() => {
        const onThemeChange = (event: Event) => {
            const next = (event as CustomEvent<ThemePreference>).detail;
            if (next === 'light' || next === 'dark' || next === 'system') setPreferenceState(next);
        };
        window.addEventListener(THEME_EVENT, onThemeChange);
        return () => window.removeEventListener(THEME_EVENT, onThemeChange);
    }, []);

    const setPreference = (next: ThemePreference) => {
        try {
            window.localStorage.setItem(THEME_STORAGE_KEY, next);
        } catch {
            // Not persisted; the choice still applies for this visit.
        }
        window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: next }));
        setPreferenceState(next);
    };

    return {
        theme,
        preference,
        isDark: theme === 'dark',
        setPreference,
        toggleTheme: () => setPreference(theme === 'dark' ? 'light' : 'dark'),
    };
};
