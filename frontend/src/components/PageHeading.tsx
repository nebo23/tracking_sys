import { useEffect, type ReactNode } from 'react';
import { useIntl } from 'react-intl';

import type { MessageId } from '@/i18n';
import { cx } from '@/lib/cx';

/** Names the page in the browser tab, in the language of the interface. */
export function usePageTitle(id: MessageId): void {
  const intl = useIntl();
  useEffect(() => {
    document.title = intl.formatMessage({ id: 'app.title' }, { page: intl.formatMessage({ id }) });
  }, [intl, id]);
}

/**
 * The one heading of a page. It can take focus, so that after a move to another page the
 * application can place focus on it (see FocusOnNavigation) and a screen reader reads the new page.
 */
export function PageHeading({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h1 className={cx('c-pagehead__title', className)} tabIndex={-1}>
      {children}
    </h1>
  );
}
