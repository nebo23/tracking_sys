import { FormattedMessage } from 'react-intl';

import { PageHeading, usePageTitle } from '@/components/PageHeading';

export function IntegrationsPage() {
  usePageTitle('integrations.title');
  return (
    <div className="c-pagehead">
      <div>
        <PageHeading>
          <FormattedMessage id="integrations.title" />
        </PageHeading>
      </div>
    </div>
  );
}
