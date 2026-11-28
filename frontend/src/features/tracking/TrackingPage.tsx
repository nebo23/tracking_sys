import { FormattedMessage } from 'react-intl';

import { useClient } from '@/app/tenant';
import { PageHeading, usePageTitle } from '@/components/PageHeading';

import { DiagnosticsCard } from './DiagnosticsCard';
import { ErasuresCard } from './ErasuresCard';
import { FormsCard } from './FormsCard';
import { SourcesCard } from './SourcesCard';

/**
 * What the client's website and servers send to Connect, with the visitor's consent, and what
 * Connect did with it (specifications 004 and 005). Owners and admins set up the sources and
 * forms and erase visitors; every reader of the client sees the daily counters.
 */
export function TrackingPage() {
  usePageTitle('tracking.title');
  const { manager, client } = useClient();
  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="tracking.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id={manager ? 'tracking.lead' : 'tracking.leadReader'} values={{ client: client.name }} />
          </p>
        </div>
      </div>
      <div className="l-stack l-stack--loose">
        {manager ? <SourcesCard /> : null}
        {manager ? <FormsCard /> : null}
        <DiagnosticsCard />
        {manager ? <ErasuresCard /> : null}
      </div>
    </>
  );
}
