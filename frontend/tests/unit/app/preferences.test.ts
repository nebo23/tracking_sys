import { afterEach, describe, expect, it, vi } from 'vitest';

// The module reads storage and the browser language once, when it is first loaded.
async function load() {
  vi.resetModules();
  return import('@/app/preferences');
}

afterEach(() => {
  const root = document.documentElement;
  root.removeAttribute('data-theme');
  root.removeAttribute('dir');
  root.removeAttribute('lang');
});

const root = () => document.documentElement;

describe('the language', () => {
  it('starts in English for a browser that is not set to Arabic', async () => {
    vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('fr-FR');
    const { applyPreferences, preferences } = await load();
    applyPreferences();
    expect(preferences.get().language).toBe('en');
    expect([root().lang, root().dir]).toEqual(['en', 'ltr']);
  });

  it('starts in Arabic for a browser set to Arabic', async () => {
    vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('ar-EG');
    const { applyPreferences } = await load();
    applyPreferences();
    expect([root().lang, root().dir]).toEqual(['ar', 'rtl']);
  });

  it('starts in the language chosen before, whatever the browser says', async () => {
    vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('ar-EG');
    window.localStorage.setItem('connect.language', 'en');
    const { preferences } = await load();
    expect(preferences.get().language).toBe('en');
  });

  it('ignores a stored value it does not know', async () => {
    vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('en-GB');
    window.localStorage.setItem('connect.language', 'tlh');
    window.localStorage.setItem('connect.theme', 'neon');
    const { preferences } = await load();
    expect(preferences.get()).toEqual({ language: 'en', theme: 'system' });
  });

  it('switches the text direction with the language and remembers the choice', async () => {
    const { preferences } = await load();
    const heard = vi.fn();
    preferences.subscribe(heard);

    preferences.setLanguage('ar');
    expect([root().lang, root().dir]).toEqual(['ar', 'rtl']);
    expect(window.localStorage.getItem('connect.language')).toBe('ar');

    preferences.setLanguage('en');
    expect([root().lang, root().dir]).toEqual(['en', 'ltr']);
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it('formats Arabic with Western digits and the Gregorian calendar (D3)', async () => {
    const { localeTag } = await load();
    expect(localeTag).toEqual({ en: 'en', ar: 'ar-u-ca-gregory-nu-latn' });
  });
});

describe('the theme', () => {
  it('follows the device until the person chooses', async () => {
    const { applyPreferences, preferences } = await load();
    applyPreferences();
    expect(root().hasAttribute('data-theme')).toBe(false);

    preferences.setTheme('dark');
    expect(root().getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem('connect.theme')).toBe('dark');

    preferences.setTheme('light');
    expect(root().getAttribute('data-theme')).toBe('light');

    preferences.setTheme('system');
    expect(root().hasAttribute('data-theme')).toBe(false);
  });

  it('starts in the theme chosen before', async () => {
    window.localStorage.setItem('connect.theme', 'dark');
    const { applyPreferences } = await load();
    applyPreferences();
    expect(root().getAttribute('data-theme')).toBe('dark');
  });
});

describe('without storage', () => {
  it('still applies a choice for the visit', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    const { preferences } = await load();
    preferences.setLanguage('ar');
    preferences.setTheme('dark');
    expect(preferences.get()).toEqual({ language: 'ar', theme: 'dark' });
    expect([root().dir, root().getAttribute('data-theme')]).toEqual(['rtl', 'dark']);
  });
});
