import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { FormattedDate, FormattedMessage } from 'react-intl';

import { agencyQuery } from '@/api/agencies';
import { describeError } from '@/api/errors';
import { sessionQuery } from '@/api/session';
import { useCurrentAgency } from '@/app/agency';
import { ErrorNotice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { Skeleton } from '@/components/Skeleton';

/**
 * The first page of the workspace. In this slice it shows what the API already knows: the agency
 * and the person. Clients, connections and reports arrive with their own slices.
 */
export function HomePage() {
  usePageTitle('home.title');
  const { data: session } = useSuspenseQuery(sessionQuery);
  const access = useCurrentAgency();
  const agency = useQuery({ ...agencyQuery(access?.agency_id ?? ''), enabled: access !== undefined });
  if (!session || !access) return null;

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="home.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="home.lead" />
          </p>
        </div>
      </div>

      <div className="l-grid l-grid--2">
        <section className="c-card" aria-labelledby="home-agency">
          <div className="c-card__header">
            <h2 className="c-card__title" id="home-agency">
              <FormattedMessage id="home.agency.title" />
            </h2>
          </div>
          <div className="c-card__body">
            {agency.isPending ? <Skeleton /> : null}
            {agency.isError ? (
              <ErrorNotice
                message={describeError(agency.error)}
                action={
                  <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void agency.refetch()}>
                    <FormattedMessage id="common.retry" />
                  </button>
                }
              />
            ) : null}
            {agency.isSuccess ? (
              <dl className="c-dl">
                <dt>
                  <FormattedMessage id="home.agency.name" />
                </dt>
                <dd className="u-strong">{agency.data.name}</dd>
                <dt>
                  <FormattedMessage id="home.agency.role" />
                </dt>
                <dd>
                  <FormattedMessage id={`role.${access.role}`} />
                </dd>
                <dt>
                  <FormattedMessage id="home.agency.created" />
                </dt>
                <dd>
                  <FormattedDate value={agency.data.created_at} dateStyle="long" />
                </dd>
              </dl>
            ) : null}
          </div>
        </section>

        <section className="c-card" aria-labelledby="home-you">
          <div className="c-card__header">
            <h2 className="c-card__title" id="home-you">
              <FormattedMessage id="home.you.title" />
            </h2>
          </div>
          <div className="c-card__body">
            <dl className="c-dl">
              <dt>
                <FormattedMessage id="account.profile.name" />
              </dt>
              <dd className="u-strong">{session.user.display_name}</dd>
              <dt>
                <FormattedMessage id="account.profile.email" />
              </dt>
              <dd>
                <span className="u-ltr">{session.user.email_normalized}</span>
              </dd>
            </dl>
          </div>
        </section>
      </div>
    </>
  );
}
