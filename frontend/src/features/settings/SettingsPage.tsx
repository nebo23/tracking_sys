import { useQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { Tab, TabList, TabPanel, Tabs } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { agencyQuery } from '@/api/agencies';
import { useAgency } from '@/app/tenant';
import { QueryStates } from '@/components/ListStates';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { cx } from '@/lib/cx';

import { BrandingTab } from './BrandingTab';
import { ClosureTab } from './ClosureTab';
import { PlanTab } from './PlanTab';
import { settingsTabsFor, type SettingsTab } from './tabs';

const route = getRouteApi('/workspace/agencies/$agencyId/settings');

/**
 * Agency settings (B13 and B14, D7 of the completion entry review): the plan and its use, the
 * branding profile, and closing the agency. Client viewers have no settings page; closing is
 * for Owners only. The API decides in any case; this only hides what it would refuse.
 */
export function SettingsPage() {
  usePageTitle('settings.title');
  const intl = useIntl();
  const { agencyId, role, manager } = useAgency();
  const agency = useQuery(agencyQuery(agencyId));
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const tabs = settingsTabsFor(role);
  const tab: SettingsTab = tabs.find((item) => item === search.tab) ?? 'plan';
  const choose = (next: SettingsTab) => void navigate({ search: next === 'plan' ? {} : { tab: next }, replace: true });

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="settings.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="settings.lead" values={{ agency: agency.data?.name ?? '' }} />
          </p>
        </div>
      </div>
      <Tabs selectedKey={tab} onSelectionChange={(key) => choose(key as SettingsTab)}>
        <TabList className="c-tabs" aria-label={intl.formatMessage({ id: 'settings.tabs' })}>
          {tabs.map((item) => (
            <Tab key={item} id={item} className={({ isSelected }) => cx('c-tab', isSelected && 'is-active')}>
              <FormattedMessage id={`settings.tab.${item}`} />
            </Tab>
          ))}
        </TabList>
        <div className="l-stack a-tabpanels">
          <TabPanel id="plan" className="l-stack">
            <PlanTab agencyId={agencyId} />
          </TabPanel>
          <TabPanel id="branding" className="l-stack">
            <BrandingTab agencyId={agencyId} editable={manager} />
          </TabPanel>
          {tabs.includes('closure') ? (
            <TabPanel id="closure" className="l-stack">
              {/* The name to type is the agency's own, so the tab waits for it. */}
              {agency.data ? <ClosureTab agencyId={agencyId} agencyName={agency.data.name} /> : <QueryStates query={agency} />}
            </TabPanel>
          ) : null}
        </div>
      </Tabs>
    </>
  );
}
