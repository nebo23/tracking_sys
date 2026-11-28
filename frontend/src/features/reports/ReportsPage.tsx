import { getRouteApi } from '@tanstack/react-router';
import { useState } from 'react';
import { Tab, TabList, TabPanel, Tabs } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import type { ReportSchedule } from '@/api/reportDelivery';
import { useClient } from '@/app/tenant';
import { Icon } from '@/components/Icon';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { cx } from '@/lib/cx';

import { ExportsTab } from './ExportsTab';
import { ScheduleDialog } from './ScheduleDialog';
import { SchedulesTab } from './SchedulesTab';
import { reportTabs, type ReportTab } from './tabs';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/reports');

/**
 * Reports of a client (E03, E04; 016-C): exports that keep a report for a few days, and reports
 * that go out on a schedule. Owners and admins create and change schedules; everyone who may read
 * a report can save it as an export from its page.
 */
export function ReportsPage() {
  usePageTitle('reports.title');
  const intl = useIntl();
  const { manager } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const tab: ReportTab = search.tab ?? 'exports';
  const [editing, setEditing] = useState<ReportSchedule | 'new' | null>(null);

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="reports.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="reports.lead" />
          </p>
        </div>
        {manager ? (
          <div className="l-cluster">
            <button type="button" className="c-btn c-btn--primary" onClick={() => setEditing('new')}>
              <Icon name="calendar-clock" size="sm" />
              <FormattedMessage id="reports.schedule.new" />
            </button>
          </div>
        ) : null}
      </div>
      <Tabs selectedKey={tab} onSelectionChange={(key) => void navigate({ search: key === 'exports' ? {} : { tab: key as ReportTab }, replace: true })}>
        <TabList className="c-tabs" aria-label={intl.formatMessage({ id: 'reports.tabs' })}>
          {reportTabs.map((item) => (
            <Tab key={item} id={item} className={({ isSelected }) => cx('c-tab', isSelected && 'is-active')}>
              <FormattedMessage id={`reports.tab.${item}`} />
            </Tab>
          ))}
        </TabList>
        <div className="l-stack a-tabpanels">
          <TabPanel id="exports" className="l-stack">
            <ExportsTab />
          </TabPanel>
          <TabPanel id="schedules" className="l-stack">
            <SchedulesTab onEdit={setEditing} />
          </TabPanel>
        </div>
      </Tabs>
      {editing ? <ScheduleDialog schedule={editing === 'new' ? null : editing} onClose={() => setEditing(null)} /> : null}
    </>
  );
}
