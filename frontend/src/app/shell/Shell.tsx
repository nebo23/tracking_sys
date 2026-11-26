import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { Link, Outlet, useLocation } from '@tanstack/react-router';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { agencyQuery } from '@/api/agencies';
import type { ErrorMessage } from '@/api/errors';
import { sessionQuery } from '@/api/session';
import { Icon, type IconName } from '@/components/Icon';
import { Logo } from '@/components/Logo';
import { Main } from '@/components/Main';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';

import { useCurrentAgency } from '../agency';
import { useSignOut } from '../useSignOut';

import { AccountMenu } from './AccountMenu';
import { AgencySwitcher } from './AgencySwitcher';

interface Destination {
  to: '/' | '/welcome' | '/account';
  icon: IconName;
  label: MessageId;
  exact: boolean;
}

// The destinations that exist in this slice. Later slices add theirs; nothing is shown before it works.
const overview: Destination = { to: '/', icon: 'layout-dashboard', label: 'shell.nav.home', exact: true };
const account: Destination = { to: '/account', icon: 'settings', label: 'shell.nav.account', exact: false };
// A person who belongs to no agency still has an account to manage, and one place to go from it.
const firstAgency: Destination = { to: '/welcome', icon: 'plus', label: 'welcome.title', exact: true };

const active = { className: 'is-active' };

const skipToMain = (event: { preventDefault: () => void }) => {
  event.preventDefault();
  document.getElementById('main')?.focus();
};

/** The frame of the signed-in application: sidebar, top bar, the page, and a tab bar on phones. */
export function Shell() {
  const intl = useIntl();
  const { data: session } = useSuspenseQuery(sessionQuery);
  const access = useCurrentAgency();
  const agency = useQuery({ ...agencyQuery(access?.agency_id ?? ''), enabled: access !== undefined });
  const pathname = useLocation({ select: (location) => location.pathname });
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const leave = useSignOut(setProblem);
  // Gone for a moment while a session ends and the sign-in screen takes over.
  if (!session) return null;

  const start = access ? overview : firstAgency;
  const destinations = [start, account];
  const here = destinations.find((place) => (place.exact ? pathname === place.to : pathname.startsWith(place.to)));
  const signOut = () => {
    if (leave.isPending) return;
    setProblem(null);
    leave.mutate(false);
  };

  return (
    <div className="l-app">
      <a className="a-skip" href="#main" onClick={skipToMain}>
        <FormattedMessage id="shell.skip" />
      </a>

      <aside className="l-sidebar" aria-label={intl.formatMessage({ id: 'shell.sidebar' })}>
        <Link className="c-logo" to="/" activeProps={{}}>
          <Logo />
        </Link>
        {access ? <AgencySwitcher current={access} /> : null}
        <nav className="c-nav u-grow" aria-label={intl.formatMessage({ id: 'shell.nav.primary' })}>
          <div className="c-nav__group">
            <Link className="c-nav__item" to={start.to} activeOptions={{ exact: true }} activeProps={active}>
              <Icon name={start.icon} />
              <FormattedMessage id={start.label} />
            </Link>
          </div>
          <div className="c-nav__group a-nav__end">
            <Link className="c-nav__item" to={account.to} activeProps={active}>
              <Icon name={account.icon} />
              <FormattedMessage id={account.label} />
            </Link>
          </div>
        </nav>
      </aside>

      <div className="l-main">
        <header className="l-topbar">
          <Link className="a-phone" to="/" activeProps={{}}>
            <Logo variant="mark" height={28} />
          </Link>
          <div className="a-phone u-grow">{access ? <AgencySwitcher current={access} compact /> : null}</div>
          <nav className="c-crumbs a-desktop" aria-label={intl.formatMessage({ id: 'shell.breadcrumb' })}>
            {access ? (
              <>
                <span>{agency.data?.name ?? <span className="c-skel a-skel--name" />}</span>
                <Icon name="chevron-right" size="xs" mirror />
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
          {destinations.map((place) => (
            <Link key={place.to} className="c-tabbar__item" to={place.to} activeOptions={{ exact: place.exact }} activeProps={active}>
              <Icon name={place.icon} size="md" />
              <FormattedMessage id={place.label} />
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
