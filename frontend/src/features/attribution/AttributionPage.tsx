import { useQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { Tab, TabList, TabPanel, Tabs } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { modelVersionsQuery, type FunnelGroup, type ReportFamily, type SpendLevel } from '@/api/reports';
import { useClient } from '@/app/tenant';
import { QueryStates } from '@/components/ListStates';
import { usePageTitle } from '@/components/PageHeading';
import { cx } from '@/lib/cx';

import { attributionTabs, type AttributionGroupChoice, type AttributionSearch, type AttributionTab } from '../analyze/search';
import { AnalyzeHead, chosenConnection, reportScope, useSpendConnections } from '../analyze/shared';
import { CreditTab } from './CreditTab';
import { FunnelTab } from './FunnelTab';
import { ModelChoice, orderedVersions } from './parts';
import { RoasTab } from './RoasTab';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/attribution');

/**
 * Attribution (C08 to C10, D6 of the completion entry review): credit, funnel and return on ad
 * spend under one model of the client, each tab and choice kept in the address. Credit is an
 * allocation under that model, not proof of cause.
 */
export function AttributionPage() {
  usePageTitle('attribution.title');
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const { range, scope } = reportScope(agencyId, clientId, search);
  const tab: AttributionTab = search.tab ?? 'credit';
  const group: AttributionGroupChoice = search.group ?? 'campaign';
  const funnelGroup: FunnelGroup = group === 'recipient' ? 'campaign' : group;
  const level: SpendLevel = search.level ?? 'campaign';
  const models = useQuery(modelVersionsQuery(agencyId, clientId));
  const versions = orderedVersions(models.data?.versions);
  const version = versions.find((item) => item.id === search.model) ?? versions[0];
  const spendConnections = useSpendConnections(agencyId, clientId);
  const spendConnection = chosenConnection(spendConnections.data, search.connection);
  const change = (next: Partial<AttributionSearch>) => void navigate({ search: (current) => ({ ...current, ...next }), replace: true });

  const modelParameter: Record<string, string> = version ? { model_version: version.id } : {};
  const csv: { family: ReportFamily; parameters: Record<string, string> } | null =
    tab === 'credit'
      ? { family: 'attribution', parameters: { view: 'groups', group_by: group, ...modelParameter } }
      : tab === 'funnel'
        ? { family: 'funnel', parameters: { group_by: funnelGroup, ...modelParameter } }
        : spendConnection
          ? { family: 'roas', parameters: { connection_id: spendConnection.id, level, ...modelParameter } }
          : null;

  return (
    <>
      <AnalyzeHead
        title={<FormattedMessage id="attribution.title" />}
        lead={<FormattedMessage id="attribution.lead" />}
        range={range}
        compare={scope.compare}
        onRange={(next) => change({ from: next.from, to: next.to })}
        onCompare={(compare) => change({ compare: compare || undefined })}
        csv={csv && version ? { scope, ...csv, name: `${csv.family}-${range.from}-${range.to}.csv` } : null}
      />
      <Tabs selectedKey={tab} onSelectionChange={(key) => change({ tab: key === 'credit' ? undefined : (key as AttributionTab) })}>
        <TabList className="c-tabs" aria-label={intl.formatMessage({ id: 'attribution.tabs' })}>
          {attributionTabs.map((item) => (
            <Tab key={item} id={item} className={({ isSelected }) => cx('c-tab', isSelected && 'is-active')}>
              <FormattedMessage id={`attribution.tab.${item}`} />
            </Tab>
          ))}
        </TabList>
        <div className="l-stack a-tabpanels">
          <QueryStates query={models} />
          {models.data && versions.length === 0 ? (
            <p className="u-secondary">
              <FormattedMessage id="attribution.model.none" />
            </p>
          ) : null}
          <ModelChoice versions={versions} chosen={version} onChange={(id) => change({ model: id === versions[0]?.id ? undefined : id })} />
          <TabPanel id="credit" className="l-stack">
            <CreditTab scope={scope} version={version} group={group} onGroup={(next) => change({ group: next === 'campaign' ? undefined : next })} />
          </TabPanel>
          <TabPanel id="funnel" className="l-stack">
            <FunnelTab scope={scope} version={version} group={funnelGroup} onGroup={(next) => change({ group: next === 'campaign' ? undefined : next })} />
          </TabPanel>
          <TabPanel id="roas" className="l-stack">
            <RoasTab
              scope={scope}
              version={version}
              connection={search.connection}
              level={level}
              onChange={(next) => change({ ...(next.connection ? { connection: next.connection } : {}), ...(next.level ? { level: next.level === 'campaign' ? undefined : next.level } : {}) })}
            />
          </TabPanel>
        </div>
      </Tabs>
    </>
  );
}
