import { useSyncExternalStore } from 'react';

export type Language = 'en' | 'ar';
export type ThemeChoice = 'system' | 'light' | 'dark';

export interface Preferences {
  language: Language;
  theme: ThemeChoice;
}

// Arabic keeps Western digits and the Gregorian calendar (D3 of the 018 entry review).
export const localeTag: Record<Language, string> = {
  en: 'en',
  ar: 'ar-u-ca-gregory-nu-latn',
};

const LANGUAGE_KEY = 'connect.language';
const THEME_KEY = 'connect.theme';

// Storage can be unavailable (private modes, blocked cookies). The choice then lasts for the visit.
function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Nothing to do: the choice still applies to this visit.
  }
}

function initialLanguage(): Language {
  const stored = read(LANGUAGE_KEY);
  if (stored === 'en' || stored === 'ar') return stored;
  return navigator.language.toLowerCase().startsWith('ar') ? 'ar' : 'en';
}

function initialTheme(): ThemeChoice {
  const stored = read(THEME_KEY);
  return stored === 'light' || stored === 'dark' ? stored : 'system';
}

let state: Preferences = { language: initialLanguage(), theme: initialTheme() };
const listeners = new Set<() => void>();

/** Writes the language, direction and theme onto the root element. */
export function applyPreferences(current: Preferences = state): void {
  const root = document.documentElement;
  root.lang = current.language;
  root.dir = current.language === 'ar' ? 'rtl' : 'ltr';
  if (current.theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', current.theme);
}

function update(next: Preferences): void {
  state = next;
  applyPreferences(state);
  for (const listener of listeners) listener();
}

export const preferences = {
  get: (): Preferences => state,
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  setLanguage(language: Language): void {
    write(LANGUAGE_KEY, language);
    update({ ...state, language });
  },
  setTheme(theme: ThemeChoice): void {
    write(THEME_KEY, theme);
    update({ ...state, theme });
  },
};

export function usePreferences(): Preferences {
  return useSyncExternalStore(preferences.subscribe, preferences.get);
}

const darkQuery = '(prefers-color-scheme: dark)';

function subscribeToSystemTheme(listener: () => void): () => void {
  const media = window.matchMedia(darkQuery);
  media.addEventListener('change', listener);
  return () => media.removeEventListener('change', listener);
}

/** The theme actually shown, after "system" is resolved against the device setting. */
export function useResolvedTheme(): 'light' | 'dark' {
  const { theme } = usePreferences();
  const systemIsDark = useSyncExternalStore(subscribeToSystemTheme, () => window.matchMedia(darkQuery).matches);
  if (theme === 'system') return systemIsDark ? 'dark' : 'light';
  return theme;
}
