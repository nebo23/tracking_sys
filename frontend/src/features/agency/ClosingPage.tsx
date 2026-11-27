import { FormattedMessage } from 'react-intl';

import { PageMessage } from '@/components/Main';
import { PageHeading, usePageTitle } from '@/components/PageHeading';

/**
 * The only page of a closing agency (017-A): the API refuses every other route of it, and lists
 * it only to its Owners. Screen B15 of the completion round adds the closing date and keeping it.
 */
export function ClosingPage() {
  usePageTitle('agency.closing.title');
  return (
    <PageMessage>
      <div className="c-empty">
        <PageHeading className="c-empty__title">
          <FormattedMessage id="agency.closing.title" />
        </PageHeading>
        <p className="c-empty__text">
          <FormattedMessage id="agency.closing.text" />
        </p>
      </div>
    </PageMessage>
  );
}
