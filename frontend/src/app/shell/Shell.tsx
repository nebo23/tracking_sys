import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { Link, Outlet, useLocation } from '@tanstack/react-router';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { agencyQuery } from '@/api/agencies';
import type { ErrorMessage } from '@/api/errors';
import { sessionQuery } from '@/api/session';
import { Icon, type IconName } from '@/components/Icon';
import { Logo } from '@/components/Logo';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';

import { useCurrentAgency } from '../agency';
import { useSignOut } from '../useSignOut';

import { AccountMenu } from './AccountMenu';
import { AgencySwitcher } from './AgencySwitcher';

// The destinations that exist in this slice. Later slices add theirs; nothing is shown before it works.
const destinations: ReadonlyArray<{ to: '/' | '/account'; icon: IconName; label: MessageId; exact: boolean }> = [
  { to: '/', icon: 'layout-dashboard', label: 'shell.nav.home', exact: true },
  { to: '/account', icon: 'settings', label: 'shell.nav.account', exact: false },
];

const active = { className: 'is-active' };

/** The frame of the signed-in application: sidebar, top bar, the page, and a tab bar on phones. */
export function Shell() {
  const intl = useIntl();
  const { data: session } = useSuspenseQuery(sessionQuery);
  const access = useCurrentAgency();
  const agency = useQuery({ ...agencyQuery(access?.agency_id ?? ''), enabled: access !== undefined });
  const pathname = useLocation({ select: (location) => location.pathname });
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const leave = useSignOut(setProblem);
  // Both are gone for a moment while a session ends and the sign-in screen takes over.
  if (!session || !access) return null;

  const [home, account] = destinations;
  const here = destinations.find((destination) => (destination.exact ? pathname === destination.to : pathname.startsWith(destination.to)));
  const signOut = () => {
    if (leave.isPending) return;
    setProblem(null);
    leave.mutate(false);
  };

  return (
    <div className="l-app">
      <a className="a-skip" href="#main">
        <FormattedMessage id="shell.skip" />
      </a>

      <aside className="l-sidebar" aria-label={intl.formatMessage({ id: 'shell.sidebar' })}>
        <Link className="c-logo" to="/" activeProps={{}}>
          <Logo />
        </Link>
        <AgencySwitcher current={access} />
        <nav className="c-nav u-grow" aria-label={intl.formatMessage({ id: 'shell.nav.primary' })}>
          {home ? (
            <div className="c-nav__group">
              <Link className="c-nav__item" to={home.to} activeOptions={{ exact: true }} activeProps={active}>
                <Icon name={home.icon} />
                <FormattedMessage id={home.label} />
              </Link>
            </div>
          ) : null}
          {account ? (
            <div className="c-nav__group a-nav__end">
              <Link className="c-nav__item" to={account.to} activeProps={active}>
                <Icon name={account.icon} />
                <FormattedMessage id={account.label} />
              </Link>
            </div>
          ) : null}
        </nav>
      </aside>

      <div className="l-main">
        <header className="l-topbar">
          <Link className="a-phone" to="/" activeProps={{}}>
            <Logo variant="mark" height={28} />
          </Link>
          <div className="a-phone u-grow">
            <AgencySwitcher current={access} compact />
          </div>
          <nav className="c-crumbs a-desktop" aria-label={intl.formatMessage({ id: 'shell.breadcrumb' })}>
            <span>{agency.data?.name ?? <span className="c-skel a-skel--name" />}</span>
            <Icon name="chevron-right" size="xs" mirror />
            <strong aria-current="page">{here ? <FormattedMessage id={here.label} /> : null}</strong>
          </nav>
          <div className="l-cluster u-end">
            <AccountMenu user={session.user} onSignOut={signOut} />
          </div>
        </header>

        <main className="l-page a-shell__page" id="main" tabIndex={-1}>
          <ErrorNotice message={problem} />
          <Outlet />
        </main>

        <nav className="c-tabbar a-tabbar" aria-label={intl.formatMessage({ id: 'shell.nav.phone' })}>
          {destinations.map((destination) => (
            <Link
              key={destination.to}
              className="c-tabbar__item"
              to={destination.to}
              activeOptions={{ exact: destination.exact }}
              activeProps={active}
            >
              <Icon name={destination.icon} size="md" />
              <FormattedMessage id={destination.label} />
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
