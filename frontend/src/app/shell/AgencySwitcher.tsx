import { useQueries, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { Button, Menu, MenuItem, MenuTrigger, Popover } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import { agenciesQuery, agencyQuery, type AgencyAccess } from '@/api/agencies';
import { Icon } from '@/components/Icon';
import { cx } from '@/lib/cx';
import { initials } from '@/lib/initials';

import { switchAgency } from '../agency';

import { menuItem } from './menuItem';

interface AgencySwitcherProps {
  current: AgencyAccess;
  /** The one-line form of the phone top bar. */
  compact?: boolean;
}

/** Names the agency a person is working in and lets them move to another of their agencies. */
export function AgencySwitcher({ current, compact = false }: AgencySwitcherProps) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { data: agencies } = useSuspenseQuery(agenciesQuery);
  // The list carries identifiers and roles only; each name is read from its agency.
  const details = useQueries({ queries: agencies.map((agency) => agencyQuery(agency.agency_id)) });
  const nameOf = (agencyId: string) => details[agencies.findIndex((agency) => agency.agency_id === agencyId)]?.data?.name;
  const name = nameOf(current.agency_id);

  return (
    <MenuTrigger>
      <Button className={cx('c-switcher', compact && 'a-switcher--compact')}>
        <span className="c-avatar c-avatar--org" aria-hidden="true">
          {name ? initials(name) : ''}
        </span>
        <span className="u-grow u-truncate">
          <span className="c-switcher__name u-truncate">{name ?? <span className="c-skel a-skel--name" />}</span>
          {compact ? null : (
            <span className="c-switcher__sub">
              <FormattedMessage id={`role.${current.role}`} />
            </span>
          )}
        </span>
        <span className="u-sr">
          <FormattedMessage id="shell.agency.switch" />
        </span>
        <Icon name="chevrons-up-down" size="sm" className="u-tertiary" />
      </Button>
      <Popover className="c-menu" placement="bottom start">
        <Menu
          className="a-menu"
          aria-label={intl.formatMessage({ id: 'shell.agency.label' })}
          selectionMode="single"
          disallowEmptySelection
          selectedKeys={[current.agency_id]}
          onSelectionChange={(keys) => {
            const [key] = keys === 'all' ? [] : keys;
            if (typeof key === 'string' && key !== current.agency_id) switchAgency(queryClient, key);
          }}
        >
          {agencies.map((agency) => {
            const label = nameOf(agency.agency_id) ?? intl.formatMessage({ id: 'common.loading' });
            return (
              <MenuItem key={agency.agency_id} id={agency.agency_id} className={menuItem} textValue={label}>
                {({ isSelected }) => (
                  <>
                    <span className="u-grow u-truncate">{label}</span>
                    {isSelected ? <Icon name="check" size="sm" /> : null}
                  </>
                )}
              </MenuItem>
            );
          })}
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
