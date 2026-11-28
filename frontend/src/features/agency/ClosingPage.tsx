import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { agenciesKey, agencyQuery } from '@/api/agencies';
import { closureQuery, keepAgency } from '@/api/agencySettings';
import { describeError, type ErrorMessage } from '@/api/errors';
import { useAgency } from '@/app/tenant';
import { QueryStates } from '@/components/ListStates';
import { PageMessage } from '@/components/Main';
import { ErrorNotice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { dayFormat } from '@/components/Time';
import type { MessageId } from '@/i18n';

// The refusals of keeping a closing agency, each in words (017-A, section 5.2 of its design).
export const keepErrors = {
  closure_not_open: 'closing.error.closure_not_open',
  grace_period_ended: 'closing.error.grace_period_ended',
  access_denied: 'closing.error.access_denied',
} as const satisfies Record<string, MessageId>;

/**
 * The page of a closing agency (B15, D7 of the completion entry review): who asked to close it and
 * when it closes for good, and keeping it during the grace period. The API lists a closing agency
 * only to its Owners and refuses every other route of it.
 */
export function ClosingPage() {
  usePageTitle('agency.closing.title');
  const intl = useIntl();
  const { agencyId } = useAgency();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  // The API refuses every other route of a closing agency, its profile and members included: its
  // name is shown only when it was read before the closure.
  const agency = useQuery({ ...agencyQuery(agencyId), enabled: false });
  const closure = useQuery(closureQuery(agencyId));
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const keep = useMutation({
    mutationFn: () => keepAgency(agencyId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agenciesKey });
      await navigate({ to: '/agencies/$agencyId/clients', params: { agencyId } });
    },
    onError: (error) => setProblem(describeError(error, keepErrors)),
  });
  const open = closure.data?.closure;
  const day = (value: string) => intl.formatDate(new Date(value), dayFormat);

  return (
    <PageMessage>
      <div className="c-empty a-closing">
        <PageHeading className="c-empty__title">
          {agency.data ? <FormattedMessage id="closing.title" values={{ agency: agency.data.name }} /> : <FormattedMessage id="agency.closing.title" />}
        </PageHeading>
        <QueryStates query={closure} />
        {open ? (
          <p className="c-empty__text">
            <FormattedMessage id="closing.text" values={{ asked: day(open.requested_at), closes: <strong>{day(open.closes_at)}</strong> }} />
          </p>
        ) : null}
        <p className="c-empty__text u-secondary">
          <FormattedMessage id="closing.owners" />
        </p>
        <ErrorNotice message={problem} />
        <div className="l-cluster">
          {open ? (
            <button type="button" className="c-btn c-btn--primary" disabled={keep.isPending} onClick={() => keep.mutate()}>
              <FormattedMessage id="closing.keep" />
            </button>
          ) : null}
          <Link className="c-btn c-btn--secondary" to="/account">
            <FormattedMessage id="closing.account" />
          </Link>
        </div>
      </div>
    </PageMessage>
  );
}
