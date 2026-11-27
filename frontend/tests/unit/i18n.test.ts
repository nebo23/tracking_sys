import type { ReactNode } from 'react';
import { createIntl, createIntlCache } from 'react-intl';
import { describe, expect, it } from 'vitest';

import { localeTag, type Language } from '@/app/preferences';
import { languages, messages, type MessageId } from '@/i18n';

const ids = Object.keys(messages.en) as MessageId[];

const intlFor = (language: Language) =>
  createIntl(
    {
      locale: localeTag[language],
      messages: messages[language],
      onError(error) {
        throw error;
      },
    },
    createIntlCache(),
  );

// One value for every argument a message may name, and a function for every tag.
const sample = {
  email: 'name@agency.example',
  name: 'Mona Hassan',
  page: 'Account',
  position: 3,
  seconds: 5,
  bucket: 'youtube_data',
  clients: 3,
  financial: 1,
  known: 'yes',
  client: 'Olive & Thyme',
  count: 4,
  date: '26 November 2026',
  days: 30,
  from: '1 March 2026',
  of: 100,
  provider: 'Instagram',
  search: 'olive',
  shown: 2,
  through: '30 March 2026',
  time: '16:00',
  total: 6,
  used: 38,
  address: 'go.olive.example/r/ramadan-reel',
  sites: 'shop.olive.example',
  host: 'go.olive.example',
  type: 'TXT',
  site: 'shop.olive.example',
  digest: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  version: '0.6.0',
  collector: 'https://api.connect.example',
  header: 'X-Tracking-Signature',
  terms: (text: ReactNode[]) => text,
  privacy: (text: ReactNode[]) => text,
};

const argumentsOf = (text: string) => [...text.matchAll(/\{\s*([A-Za-z_]\w*)\s*[,}]/g)].map((match) => match[1]).sort();
const tagsOf = (text: string) => [...text.matchAll(/<([A-Za-z]\w*)>/g)].map((match) => match[1]).sort();

describe('the messages', () => {
  it('exist under the same keys in English and Arabic', () => {
    expect(Object.keys(messages.ar).sort()).toEqual(Object.keys(messages.en).sort());
  });

  it.each(languages)('are never empty in %s', (language) => {
    const empty = ids.filter((id) => messages[language][id].trim() === '');
    expect(empty).toEqual([]);
  });

  it('name the same arguments and tags in both languages', () => {
    const different = ids.filter(
      (id) =>
        argumentsOf(messages.en[id]).join() !== argumentsOf(messages.ar[id]).join() ||
        tagsOf(messages.en[id]).join() !== tagsOf(messages.ar[id]).join(),
    );
    expect(different).toEqual([]);
  });

  it.each(languages)('all format without an error in %s', (language) => {
    const intl = intlFor(language);
    for (const id of ids) {
      const text = intl.formatMessage({ id }, sample);
      expect(String(text), id).not.toBe('');
    }
  });

  it('handle every Arabic plural form', () => {
    const intl = intlFor('ar');
    for (const seconds of [0, 1, 2, 3, 11, 100]) {
      expect(intl.formatMessage({ id: 'verify.resendWait' }, { seconds }), String(seconds)).toMatch(/\S/);
      expect(intl.formatMessage({ id: 'error.rate_limitedSeconds' }, { seconds }), String(seconds)).toMatch(/\S/);
    }
    for (const count of [0, 1, 2, 3, 11, 100]) {
      expect(intl.formatMessage({ id: 'clients.count' }, { count }), String(count)).toMatch(/\S/);
      expect(intl.formatMessage({ id: 'clients.countFiltered' }, { shown: 1, total: count }), String(count)).toMatch(/\S/);
      expect(intl.formatMessage({ id: 'clients.status.reconnectMany' }, { count }), String(count)).toMatch(/\S/);
      expect(intl.formatMessage({ id: 'keys.lifetime.days' }, { days: count }), String(count)).toMatch(/\S/);
    }
  });
});

describe('Arabic numbers and dates', () => {
  const intl = intlFor('ar');

  it('use Western digits (D3)', () => {
    const text = intl.formatMessage({ id: 'verify.resendWait' }, { seconds: 37 });
    expect(text).toContain('37');
    expect(text).not.toMatch(/[٠-٩]/);
    expect(intl.formatNumber(1234.5)).toMatch(/^1[,.٬]?234[.,٫]5$/);
  });

  it('use the Gregorian calendar with Arabic month names', () => {
    const text = intl.formatDate('2026-11-26T10:00:00Z', { dateStyle: 'long', timeZone: 'UTC' });
    expect(text).toContain('2026');
    expect(text).toContain('26');
    expect(text).toContain('نوفمبر');
    expect(text).not.toMatch(/[٠-٩]/);
  });
});
