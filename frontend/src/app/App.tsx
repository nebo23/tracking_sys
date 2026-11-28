import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { I18nProvider } from 'react-aria-components';
import { IntlProvider } from 'react-intl';

import { messages } from '@/i18n';

import { localeTag, usePreferences } from './preferences';
import type { AppRouter } from './router';

interface AppProps {
  router: AppRouter;
  queryClient: QueryClient;
}

/** The language, the server state and the routes, in that order from the outside in. */
export function App({ router, queryClient }: AppProps) {
  const { language } = usePreferences();
  const locale = localeTag[language];
  return (
    <IntlProvider locale={locale} defaultLocale="en" messages={messages[language]}>
      <I18nProvider locale={locale}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nProvider>
    </IntlProvider>
  );
}
