import { useEffect, useState } from 'react';

type Theme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'delaxis-theme';
const THEME_EVENT = 'delaxis-theme-change';

const getInitialTheme = (): Theme => {
    if (typeof window === 'undefined') return 'light';
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const applyTheme = (theme: Theme) => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.documentElement.style.colorScheme = theme;
};

export const useTheme = () => {
    const [theme, setThemeState] = useState<Theme>(getInitialTheme);

    useEffect(() => {
        applyTheme(theme);
    }, [theme]);

    useEffect(() => {
        const onThemeChange = (event: Event) => {
            const nextTheme = (event as CustomEvent<Theme>).detail;
            if (nextTheme === 'light' || nextTheme === 'dark') {
                setThemeState(nextTheme);
            }
        };
        window.addEventListener(THEME_EVENT, onThemeChange);
        return () => window.removeEventListener(THEME_EVENT, onThemeChange);
    }, []);

    const setTheme = (nextTheme: Theme) => {
        window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
        applyTheme(nextTheme);
        window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: nextTheme }));
        setThemeState(nextTheme);
    };

    return {
        theme,
        isDark: theme === 'dark',
        toggleTheme: () => setTheme(theme === 'dark' ? 'light' : 'dark'),
        setTheme,
    };
};
