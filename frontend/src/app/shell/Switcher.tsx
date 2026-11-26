import { useQueries, useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Button, Header, Menu, MenuItem, MenuSection, MenuTrigger, Popover, Separator, type Selection } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { agenciesQuery, agencyQuery, type AgencyAccess } from '@/api/agencies';
import { clientsQuery } from '@/api/clients';
import { Icon } from '@/components/Icon';
import { cx } from '@/lib/cx';
import { initials } from '@/lib/initials';
import { byName } from '@/lib/sort';

import { menuItem } from './menuItem';

const ALL_CLIENTS = 'all-clients';

const only = (keys: Selection) => (keys === 'all' ? undefined : [...keys][0]);

interface SwitcherProps {
  current: AgencyAccess;
  /** The client whose workspace is open, when the address names one. */
  clientId?: string;
  /** The one-line form of the phone top bar. */
  compact?: boolean;
}

/**
 * Names where a person is working, the agency with all its clients or one client, and lets them
 * move to another client or another of their agencies.
 */
export function Switcher({ current, clientId, compact = false }: SwitcherProps) {
  const intl = useIntl();
  const navigate = useNavigate();
  const { data: agencies } = useSuspenseQuery(agenciesQuery);
  const agencyId = current.agency_id;
  // A client viewer may not read the agency's profile, so its name is not asked for.
  const mayNameAgency = (access: AgencyAccess) => access.role !== 'client_viewer';
  const details = useQueries({
    queries: agencies.map((agency) => ({ ...agencyQuery(agency.agency_id), enabled: mayNameAgency(agency) })),
  });
  const nameOf = (id: string) => details[agencies.findIndex((agency) => agency.agency_id === id)]?.data?.name;
  const clients = useQuery(clientsQuery(agencyId));
  const sorted = [...(clients.data ?? [])].sort(byName(intl.locale));

  const agencyName = nameOf(agencyId);
  const client = clientId ? clients.data?.find((item) => item.id === clientId) : undefined;
  const others = agencies.filter((agency) => agency.agency_id !== agencyId);
  const anyAgency = intl.formatMessage({ id: 'shell.switcher.agency' });

  const title = clientId ? client?.name : (agencyName ?? (mayNameAgency(current) ? undefined : anyAgency));
  const subtitle = clientId ? agencyName : intl.formatMessage({ id: 'shell.switcher.all' });

  const openClients = (keys: Selection) => {
    const key = only(keys);
    if (typeof key !== 'string') return;
    if (key === ALL_CLIENTS) void navigate({ to: '/agencies/$agencyId/clients', params: { agencyId } });
    else void navigate({ to: '/agencies/$agencyId/clients/$clientId', params: { agencyId, clientId: key } });
  };

  return (
    <MenuTrigger>
      <Button className={cx('c-switcher', compact && 'a-switcher--compact')}>
        <span className="c-avatar c-avatar--org" aria-hidden="true">
          {title ? initials(title) : ''}
        </span>
        <span className="u-grow u-truncate">
          <span className="c-switcher__name u-truncate">{title ?? <span className="c-skel a-skel--name" />}</span>
          {compact || !subtitle ? null : <span className="c-switcher__sub u-truncate">{subtitle}</span>}
        </span>
        <span className="u-sr">
          <FormattedMessage id="shell.switcher.open" />
        </span>
        <Icon name="chevrons-up-down" size="sm" className="u-tertiary" />
      </Button>
      <Popover className="c-menu a-menu--tall" placement="bottom start">
        <Menu className="a-menu" aria-label={intl.formatMessage({ id: 'shell.switcher.label' })}>
          <MenuSection
            selectionMode="single"
            disallowEmptySelection
            selectedKeys={[clientId ?? ALL_CLIENTS]}
            onSelectionChange={openClients}
          >
            <Header className="c-menu__label">{agencyName ?? <FormattedMessage id="shell.nav.clients" />}</Header>
            <MenuItem id={ALL_CLIENTS} className={menuItem} textValue={intl.formatMessage({ id: 'shell.switcher.all' })}>
              {({ isSelected }) => (
                <>
                  <Icon name="building-2" size="sm" />
                  <span className="u-grow">
                    <FormattedMessage id="shell.switcher.all" />
                  </span>
                  {isSelected ? <Icon name="check" size="sm" /> : null}
                </>
              )}
            </MenuItem>
            {sorted.map((item) => (
              <MenuItem key={item.id} id={item.id} className={menuItem} textValue={item.name}>
                {({ isSelected }) => (
                  <>
                    <span className="c-avatar c-avatar--org" aria-hidden="true">
                      {initials(item.name)}
                    </span>
                    <span className="u-grow u-truncate">{item.name}</span>
                    {isSelected ? <Icon name="check" size="sm" /> : null}
                  </>
                )}
              </MenuItem>
            ))}
          </MenuSection>
          {others.length > 0 ? (
            <>
              <Separator className="c-menu__sep" />
              <MenuSection>
                <Header className="c-menu__label">
                  <FormattedMessage id="shell.switcher.agencies" />
                </Header>
                {others.map((agency) => {
                  const label = nameOf(agency.agency_id) ?? anyAgency;
                  return (
                    <MenuItem
                      key={agency.agency_id}
                      id={`agency-${agency.agency_id}`}
                      className={menuItem}
                      textValue={label}
                      onAction={() => void navigate({ to: '/agencies/$agencyId/clients', params: { agencyId: agency.agency_id } })}
                    >
                      <span className="c-avatar c-avatar--org" aria-hidden="true">
                        {initials(label)}
                      </span>
                      <span className="u-grow u-truncate">{label}</span>
                      <span className="u-tertiary">
                        <FormattedMessage id={`role.${agency.role}`} />
                      </span>
                    </MenuItem>
                  );
                })}
              </MenuSection>
            </>
          ) : null}
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
