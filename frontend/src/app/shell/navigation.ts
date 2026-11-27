import { linkOptions, type LinkProps } from '@tanstack/react-router';

import type { IconName } from '@/components/Icon';
import type { MessageId } from '@/i18n';

/** One place a person can go from the sidebar or the phone tab bar. */
export interface Destination {
  key: string;
  icon: IconName;
  label: MessageId;
  /** A shorter label for the phone tab bar, where five destinations share the width. */
  shortLabel?: MessageId;
  /** True when only the address itself counts as "here", not the pages under it. */
  exact?: boolean;
  link: LinkProps;
}

export interface DestinationGroup {
  key: string;
  label?: MessageId;
  items: Destination[];
}

export const accountDestination: Destination = {
  key: 'account',
  icon: 'settings',
  label: 'shell.nav.account',
  link: linkOptions({ to: '/account' }),
};

// A person who belongs to no agency still has an account to manage, and one place to go from it.
export const firstAgencyDestination: Destination = {
  key: 'first-agency',
  icon: 'plus',
  label: 'welcome.title',
  link: linkOptions({ to: '/welcome' }),
};

export const clientsDestination = (agencyId: string): Destination => ({
  key: 'clients',
  icon: 'briefcase-business',
  label: 'shell.nav.clients',
  // A client's pages live under this address and are not the list itself.
  exact: true,
  link: linkOptions({ to: '/agencies/$agencyId/clients', params: { agencyId } }),
});

/**
 * The agency level (D11): the clients, and for the people who manage the agency its team, keys and audit log.
 * Destinations of later slices are absent, not disabled.
 */
export function agencyGroups(agencyId: string, manager: boolean): DestinationGroup[] {
  const groups: DestinationGroup[] = [{ key: 'start', items: [clientsDestination(agencyId)] }];
  if (manager) {
    groups.push({
      key: 'agency',
      label: 'shell.nav.group.agency',
      items: [
        {
          key: 'team',
          icon: 'users',
          label: 'shell.nav.team',
          shortLabel: 'shell.nav.team.short',
          link: linkOptions({ to: '/agencies/$agencyId/team', params: { agencyId } }),
        },
        {
          key: 'keys',
          icon: 'key-round',
          label: 'shell.nav.keys',
          link: linkOptions({ to: '/agencies/$agencyId/keys', params: { agencyId } }),
        },
        {
          key: 'audit',
          icon: 'scroll-text',
          label: 'shell.nav.audit',
          shortLabel: 'shell.nav.audit.short',
          link: linkOptions({ to: '/agencies/$agencyId/audit', params: { agencyId } }),
        },
      ],
    });
  }
  return groups;
}

/** The client level (D11): what the client collects, and what is managed for it. Overview and Analyze follow 018-C. */
export function clientGroups(agencyId: string, clientId: string): DestinationGroup[] {
  const params = { agencyId, clientId };
  return [
    {
      key: 'collect',
      label: 'shell.nav.group.collect',
      items: [
        {
          key: 'links',
          icon: 'link',
          label: 'shell.nav.links',
          link: linkOptions({ to: '/agencies/$agencyId/clients/$clientId/links', params }),
        },
        {
          key: 'tracking',
          icon: 'activity',
          label: 'shell.nav.tracking',
          shortLabel: 'shell.nav.tracking.short',
          link: linkOptions({ to: '/agencies/$agencyId/clients/$clientId/tracking', params }),
        },
        {
          key: 'integrations',
          icon: 'blocks',
          label: 'shell.nav.integrations',
          link: linkOptions({ to: '/agencies/$agencyId/clients/$clientId/integrations', params }),
        },
      ],
    },
    {
      key: 'manage',
      label: 'shell.nav.group.manage',
      items: [
        {
          key: 'connections',
          icon: 'plug',
          label: 'shell.nav.connections',
          link: linkOptions({ to: '/agencies/$agencyId/clients/$clientId/connections', params }),
        },
      ],
    },
  ];
}
