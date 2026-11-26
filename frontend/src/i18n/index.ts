import type { Language } from '@/app/preferences';

import ar from './ar.json';
import en from './en.json';

export type MessageId = keyof typeof en;

// English is the reference: a key missing from Arabic is a type error here and a test failure.
export const messages: Record<Language, Record<MessageId, string>> = { en, ar };

export const languages: readonly Language[] = ['en', 'ar'];

// A language is always named in itself, so a person can find it whatever the page shows.
export const languageNames: Record<Language, string> = { en: 'English', ar: 'العربية' };

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace FormatjsIntl {
    interface Message {
      ids: MessageId;
    }
  }
}
