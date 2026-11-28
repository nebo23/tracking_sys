import { screen } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';

import { password } from './api';

/** Puts text into a field the way a paste does: one input event, through the real handlers. */
export async function enter(user: UserEvent, field: HTMLElement, text: string): Promise<void> {
  await user.click(field);
  await user.paste(text);
}

export const agreementBox = () => screen.getByRole('checkbox', { name: /I agree/ });

/** Fills in the sign-in form and submits it. */
export async function signIn(user: UserEvent, { tick = true, email = 'mona@lumen.example' } = {}): Promise<void> {
  await enter(user, await screen.findByLabelText('Email'), email);
  await enter(user, screen.getByLabelText('Password'), password);
  if (tick) await user.click(agreementBox());
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
}

/** What the page keeps in the browser's storage, as one string to search. */
export const everythingStored = (): string =>
  JSON.stringify({ ...window.localStorage }) + JSON.stringify({ ...window.sessionStorage });
