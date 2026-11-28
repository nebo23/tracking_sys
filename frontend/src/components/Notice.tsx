import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { FormattedMessage } from 'react-intl';

import { agenciesQuery } from '@/api/agencies';
import type { ErrorMessage } from '@/api/errors';
import { isManager } from '@/app/agency';
import { cx } from '@/lib/cx';

import { Icon, type IconName } from './Icon';

type Tone = 'info' | 'success' | 'warning' | 'danger';

const icons: Record<Tone, IconName> = {
  info: 'info',
  success: 'circle-check',
  warning: 'triangle-alert',
  danger: 'circle-alert',
};

interface NoticeProps {
  tone?: Tone;
  title?: ReactNode;
  children: ReactNode;
  /** A link or button that resolves the notice. */
  action?: ReactNode;
  /**
   * True for a notice that describes a lasting state of what is on the page, such as a connection
   * that needs attention. It is read in its place and is not announced as news.
   */
  quiet?: boolean;
}

/** A message about the page. Problems are announced at once; other notices wait their turn. */
export function Notice({ tone = 'info', title, children, action, quiet = false }: NoticeProps) {
  const role = tone === 'danger' ? 'alert' : 'status';
  return (
    <div className={cx('c-banner', tone !== 'info' && `c-banner--${tone}`)} role={quiet ? undefined : role}>
      <Icon name={icons[tone]} />
      <div className="c-banner__text">
        {title ? <p className="c-banner__title">{title}</p> : null}
        <p>{children}</p>
        {action ? <p>{action}</p> : null}
      </div>
    </div>
  );
}

/** The way from a plan limit to the agency's Plan and usage (017-A), when the address names an agency. */
function PlanLink() {
  const agencyId = useParams({ strict: false, select: (params) => params.agencyId });
  // Only read from what is loaded: the notice is also drawn outside the pages of an agency.
  const { data: agencies } = useQuery({ ...agenciesQuery, enabled: false });
  const role = agencies?.find((agency) => agency.agency_id === agencyId)?.role;
  // Owners and admins change what uses the plan (018-F, D7).
  if (!agencyId || !isManager(role)) return null;
  return (
    <Link to="/agencies/$agencyId/settings" params={{ agencyId }}>
      <FormattedMessage id="settings.plan.link" />
    </Link>
  );
}

/** The sentence for a failed request, or nothing while there is no failure. */
export function ErrorNotice({ message, action }: { message: ErrorMessage | null; action?: ReactNode }) {
  if (!message) return null;
  const planLimit = message.id.startsWith('error.plan_limit_reached');
  return (
    <Notice tone="danger" action={action ?? (planLimit ? <PlanLink /> : undefined)}>
      <FormattedMessage id={message.id} values={message.values} />
    </Notice>
  );
}
