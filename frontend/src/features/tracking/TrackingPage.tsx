import { FormattedMessage } from 'react-intl';

import { PageHeading, usePageTitle } from '@/components/PageHeading';

export function TrackingPage() {
  usePageTitle('tracking.title');
  return (
    <div className="c-pagehead">
      <div>
        <PageHeading>
          <FormattedMessage id="tracking.title" />
        </PageHeading>
      </div>
    </div>
  );
}
