import { useQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useState } from 'react';
import { Tab, TabList, TabPanel, Tabs } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { managedLinksQuery } from '@/api/links';
import { useClient } from '@/app/tenant';
import { Icon } from '@/components/Icon';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { cx } from '@/lib/cx';

import { DomainsTab } from './DomainsTab';
import { LinksTab } from './LinksTab';
import { CampaignsTab, ContentTab, SitesTab, TemplatesTab } from './SettingsTabs';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/links');

/** The tabs of the page. The first is the default and is left out of the address. */
export const linksTabs = ['links', 'campaigns', 'content', 'templates', 'sites', 'domains'] as const;
export type LinksTabId = (typeof linksTabs)[number];

/**
 * The short links of a client, and what a link is made of: its campaign, the content it appears
 * in, its UTM template, the sites it may lead to and the domains it may use (specification 005).
 * Every reader of the client sees them; owners and admins change them.
 */
export function LinksPage() {
  usePageTitle('links.title');
  const intl = useIntl();
  const { agencyId, clientId, manager } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const tab: LinksTabId = search.tab ?? 'links';
  const [creating, setCreating] = useState(false);
  const links = useQuery(managedLinksQuery(agencyId, clientId));

  const choose = (next: LinksTabId) => {
    void navigate({ search: next === 'links' ? {} : { tab: next }, replace: true });
  };

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="links.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="links.lead" />
          </p>
        </div>
        {manager && tab === 'links' && !creating && (links.data?.length ?? 0) > 0 ? (
          <div className="l-cluster">
            <button type="button" className="c-btn c-btn--primary" onClick={() => setCreating(true)}>
              <Icon name="plus" size="sm" />
              <FormattedMessage id="links.create" />
            </button>
          </div>
        ) : null}
      </div>

      <Tabs selectedKey={tab} onSelectionChange={(key) => choose(linksTabs.find((item) => item === key) ?? 'links')}>
        <TabList className="c-tabs" aria-label={intl.formatMessage({ id: 'links.tabs' })}>
          {linksTabs.map((item) => (
            <Tab key={item} id={item} className={({ isSelected }) => cx('c-tab', isSelected && 'is-active')}>
              <FormattedMessage id={`links.tab.${item}`} />
            </Tab>
          ))}
        </TabList>
        <div className="l-stack a-tabpanels">
          <TabPanel id="links">
            <LinksTab creating={creating} onCreate={() => setCreating(true)} onCloseCreate={() => setCreating(false)} onGoTo={choose} />
          </TabPanel>
          <TabPanel id="campaigns">
            <CampaignsTab />
          </TabPanel>
          <TabPanel id="content">
            <ContentTab />
          </TabPanel>
          <TabPanel id="templates">
            <TemplatesTab />
          </TabPanel>
          <TabPanel id="sites">
            <SitesTab />
          </TabPanel>
          <TabPanel id="domains">
            <DomainsTab />
          </TabPanel>
        </div>
      </Tabs>
    </>
  );
}
