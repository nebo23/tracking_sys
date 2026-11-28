import { getRouteApi } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { Tab, TabList, TabPanel, Tabs } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { useClient } from '@/app/tenant';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { returnErrorMessage } from '@/features/connections/returnErrors';
import { cx } from '@/lib/cx';

import { BookingsTab } from './BookingsTab';
import { integrationTabs, type IntegrationTabId } from './tabs';
import { ConversionsTab } from './ConversionsTab';
import { PaymentsTab } from './PaymentsTab';
import { WhatsappTab } from './WhatsappTab';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/integrations');


/**
 * The client's payment, booking, CRM and messaging tools, and the Meta datasets that verified
 * sales are sent back to (specifications 014 and 015). Every source is set up by the agency's
 * owners and admins; every reader of the client sees what the tools delivered.
 */
export function IntegrationsPage() {
  usePageTitle('integrations.title');
  const intl = useIntl();
  const { manager, client } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const tabs = manager ? integrationTabs : integrationTabs.filter((item) => item !== 'payments');
  const tab = tabs.find((item) => item === search.tab) ?? tabs[0] ?? 'bookings';
  // The return from a provider is said once: the address keeps the tab and drops the outcome.
  const [{ outcome, failed }] = useState(() => ({ outcome: search.outcome, failed: search.failed }));
  const carriesOutcome = Boolean(search.outcome ?? search.failed ?? search.connection);
  useEffect(() => {
    if (carriesOutcome) void navigate({ search: { tab: search.tab }, replace: true });
  }, [carriesOutcome, navigate, search.tab]);

  const choose = (next: IntegrationTabId) => {
    void navigate({ search: next === tabs[0] ? {} : { tab: next }, replace: true });
  };

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="integrations.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="integrations.lead" values={{ client: client.name }} />
          </p>
        </div>
      </div>

      {failed ? <ErrorNotice message={{ id: returnErrorMessage[failed] }} /> : null}
      {!failed && outcome ? (
        <Notice tone="success" title={<FormattedMessage id={`connections.complete.${outcome}`} />}>
          <FormattedMessage id="integrations.conversions.connected" />
        </Notice>
      ) : null}

      <Tabs selectedKey={tab} onSelectionChange={(key) => choose(tabs.find((item) => item === key) ?? 'bookings')}>
        <TabList className="c-tabs" aria-label={intl.formatMessage({ id: 'integrations.tabs' })}>
          {tabs.map((item) => (
            <Tab key={item} id={item} className={({ isSelected }) => cx('c-tab', isSelected && 'is-active')}>
              <FormattedMessage id={`integrations.tab.${item}`} />
            </Tab>
          ))}
        </TabList>
        <div className="a-tabpanels">
          {manager ? (
            <TabPanel id="payments">
              <PaymentsTab />
            </TabPanel>
          ) : null}
          <TabPanel id="bookings">
            <BookingsTab />
          </TabPanel>
          <TabPanel id="whatsapp">
            <WhatsappTab />
          </TabPanel>
          <TabPanel id="conversions">
            <ConversionsTab />
          </TabPanel>
        </div>
      </Tabs>
    </>
  );
}
