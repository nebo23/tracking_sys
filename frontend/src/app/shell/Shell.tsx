import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { Link, Outlet, useLocation, useRouter } from '@tanstack/react-router';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { agencyQuery } from '@/api/agencies';
import { clientQuery } from '@/api/clients';
import type { ErrorMessage } from '@/api/errors';
import { sessionQuery } from '@/api/session';
import { Icon } from '@/components/Icon';
import { Logo } from '@/components/Logo';
import { Main } from '@/components/Main';
import { ErrorNotice } from '@/components/Notice';

import { isManager, useCurrentAgency, useTenantAddress } from '../agency';
import { useForgetWhatWasLeft } from '../tenant';
import { useSignOut } from '../useSignOut';

import { AccountMenu } from './AccountMenu';
import {
  accountDestination,
  agencyGroups,
  clientGroups,
  clientsDestination,
  firstAgencyDestination,
  type Destination,
  type DestinationGroup,
} from './navigation';
import { Switcher } from './Switcher';

const active = { className: 'is-active' };

/** The most destinations the phone tab bar holds side by side. */
const PHONE_TABS = 5;

const skipToMain = (event: { preventDefault: () => void }) => {
  event.preventDefault();
  document.getElementById('main')?.focus();
};

function NavLink({ destination }: { destination: Destination }) {
  return (
    <Link className="c-nav__item" {...destination.link} activeOptions={{ exact: destination.exact ?? false }} activeProps={active}>
      <Icon name={destination.icon} />
      <FormattedMessage id={destination.label} />
    </Link>
  );
}

/** The frame of the signed-in application: sidebar, top bar, the page, and a tab bar on phones. */
export function Shell() {
  const intl = useIntl();
  const router = useRouter();
  const { data: session } = useSuspenseQuery(sessionQuery);
  const access = useCurrentAgency();
  const address = useTenantAddress();
  useForgetWhatWasLeft(access?.agency_id);

  const agencyId = access?.agency_id ?? '';
  // The client level exists only inside the agency that the address names.
  const clientId = access && address.agencyId === access.agency_id ? address.clientId : undefined;
  // A client viewer may not read the agency's profile, so its name is not asked for.
  const mayNameAgency = access !== undefined && access.role !== 'client_viewer';
  const agency = useQuery({ ...agencyQuery(agencyId), enabled: mayNameAgency });
  const client = useQuery({ ...clientQuery(agencyId, clientId ?? ''), enabled: clientId !== undefined });

  const pathname = useLocation({ select: (location) => location.pathname });
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const leave = useSignOut(setProblem);
  // Gone for a moment while a session ends and the sign-in screen takes over.
  if (!session) return null;

  let groups: DestinationGroup[] = [{ key: 'start', items: [firstAgencyDestination] }];
  if (access) groups = clientId ? clientGroups(access.agency_id, clientId) : agencyGroups(access.agency_id, isManager(access.role));
  const level = groups.flatMap((group) => group.items);
  // On a phone the way back to the list of clients is a tab of its own. Five tabs share the width;
  // when a level has more, the account is left to the menu in the top bar, which every width shows.
  const tabs = [...(access && clientId ? [clientsDestination(access.agency_id)] : []), ...level];
  if (tabs.length < PHONE_TABS) tabs.push(accountDestination);

  const isHere = (destination: Destination) => {
    const href = router.buildLocation(destination.link).pathname;
    return destination.exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
  };
  const here = [...level, accountDestination].find(isHere);

  const signOut = () => {
    if (leave.isPending) return;
    setProblem(null);
    leave.mutate(false);
  };

  const agencyName = agency.data?.name ?? (mayNameAgency ? <span className="c-skel a-skel--name" /> : null);
  const separator = <Icon name="chevron-right" size="xs" mirror />;

  return (
    <div className="l-app">
      <a className="a-skip" href="#main" onClick={skipToMain}>
        <FormattedMessage id="shell.skip" />
      </a>

      <aside className="l-sidebar" aria-label={intl.formatMessage({ id: 'shell.sidebar' })}>
        {/* The start page is no page of its own: the logo never marks itself as the current page. */}
        <Link className="c-logo" to="/" activeOptions={{ exact: true }} activeProps={{}}>
          <Logo />
        </Link>
        {access ? <Switcher current={access} clientId={clientId} /> : null}
        <nav className="c-nav u-grow" aria-label={intl.formatMessage({ id: 'shell.nav.primary' })}>
          {groups.map((group) => (
            <div
              key={group.key}
              className="c-nav__group"
              role={group.label ? 'group' : undefined}
              aria-labelledby={group.label ? `nav-${group.key}` : undefined}
            >
              {group.label ? (
                <p className="c-nav__label" id={`nav-${group.key}`}>
                  <FormattedMessage id={group.label} />
                </p>
              ) : null}
              {group.items.map((destination) => (
                <NavLink key={destination.key} destination={destination} />
              ))}
            </div>
          ))}
          <div className="c-nav__group a-nav__end">
            <NavLink destination={accountDestination} />
          </div>
        </nav>
      </aside>

      <div className="l-main">
        <header className="l-topbar">
          <Link className="a-phone" to="/" activeOptions={{ exact: true }} activeProps={{}}>
            <Logo variant="mark" height={28} />
          </Link>
          <div className="a-phone u-grow">{access ? <Switcher current={access} clientId={clientId} compact /> : null}</div>
          <nav className="c-crumbs a-desktop" aria-label={intl.formatMessage({ id: 'shell.breadcrumb' })}>
            {access && clientId ? (
              <>
                <Link to="/agencies/$agencyId/clients" params={{ agencyId: access.agency_id }} activeOptions={{ exact: true }} activeProps={{}}>
                  {agency.data?.name ?? (
                    // While the name loads, or for a client viewer who may not read it, the link still has a name.
                    <>
                      {mayNameAgency ? <span className="c-skel a-skel--name" aria-hidden="true" /> : null}
                      <span className={mayNameAgency ? 'u-sr' : undefined}>
                        <FormattedMessage id="shell.nav.clients" />
                      </span>
                    </>
                  )}
                </Link>
                {separator}
                <span>{client.data?.name ?? <span className="c-skel a-skel--name" />}</span>
                {separator}
              </>
            ) : null}
            {access && !clientId && agencyName ? (
              <>
                <span>{agencyName}</span>
                {separator}
              </>
            ) : null}
            <strong aria-current="page">{here ? <FormattedMessage id={here.label} /> : null}</strong>
          </nav>
          <div className="l-cluster u-end">
            <AccountMenu user={session.user} onSignOut={signOut} />
          </div>
        </header>

        <Main className="l-page a-shell__page" id="main" tabIndex={-1}>
          <ErrorNotice message={problem} />
          <Outlet />
        </Main>

        <nav className="c-tabbar a-tabbar" aria-label={intl.formatMessage({ id: 'shell.nav.phone' })}>
          {tabs.map((destination) => (
            <Link
              key={destination.key}
              className="c-tabbar__item"
              {...destination.link}
              activeOptions={{ exact: destination.exact ?? false }}
              activeProps={active}
            >
              <Icon name={destination.icon} size="md" />
              <FormattedMessage id={destination.shortLabel ?? destination.label} />
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
