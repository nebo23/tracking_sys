import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { IntlProvider } from 'react-intl';

import { setCsrfToken, setUnauthorizedListener } from '@/api/client';
import { agencyChoice } from '@/app/agency';
import { App } from '@/app/App';
import { applyPreferences, preferences } from '@/app/preferences';
import { createQueryClient } from '@/app/queryClient';
import { createAppRouter } from '@/app/router';
import { watchSession } from '@/app/sessionLifecycle';
import { pendingEmail } from '@/features/auth/pendingEmail';
import { messages } from '@/i18n';
import { captureLinkToken, releaseLinkToken } from '@/lib/linkToken';

/** Opens the whole application at an address, wired as main.tsx wires it. */
export function openApp(address: string) {
  window.history.replaceState(null, '', address);
  captureLinkToken();
  applyPreferences();
  const queryClient = createQueryClient();
  const router = createAppRouter(queryClient);
  watchSession(queryClient, router);
  return { queryClient, router, ...render(<App router={router} queryClient={queryClient} />) };
}

/** Draws one component with English messages. */
export function renderWithMessages(element: ReactElement) {
  return render(
    <IntlProvider locale="en" messages={messages.en}>
      {element}
    </IntlProvider>,
  );
}

/** Returns what lives in module memory to its starting state, so one test cannot feed the next. */
export function forgetEverything(): void {
  setCsrfToken(null);
  setUnauthorizedListener(null);
  agencyChoice.set(null);
  pendingEmail.set(null);
  releaseLinkToken('reset');
  releaseLinkToken('invitation');
  preferences.setLanguage('en');
  preferences.setTheme('system');
  window.localStorage.clear();
  window.history.replaceState(null, '', '/');
}
