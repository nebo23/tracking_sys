import { useQuery } from '@tanstack/react-query';
import { FormattedMessage, useIntl } from 'react-intl';

import { AUDIT_LIMIT, auditQuery, type AuditEvent } from '@/api/audit';
import { archivedClientsQuery, clientsQuery } from '@/api/clients';
import { describeError } from '@/api/errors';
import { keysQuery } from '@/api/keys';
import { invitationsQuery, membersQuery, type Member } from '@/api/team';
import { useAgency } from '@/app/tenant';
import { EmptyState } from '@/components/EmptyState';
import { Icon } from '@/components/Icon';
import { ErrorNotice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { Skeleton } from '@/components/Skeleton';
import { Moment } from '@/components/Time';

import { auditAction } from './actions';

/**
 * The newest changes made in the agency, as the API records them: who did what, to which client,
 * and when. The API keeps identifiers only; names are read from the agency's own lists.
 */
export function AuditPage() {
  usePageTitle('audit.title');
  const intl = useIntl();
  const { agencyId } = useAgency();
  const audit = useQuery(auditQuery(agencyId));
  const members = useQuery(membersQuery(agencyId));
  const invitations = useQuery(invitationsQuery(agencyId));
  const keys = useQuery(keysQuery(agencyId));
  const clients = useQuery(clientsQuery(agencyId));
  const archived = useQuery(archivedClientsQuery(agencyId));
  const lookups = [members, invitations, keys, clients, archived];

  const personName = (member: Member | undefined): string => {
    if (!member) return intl.formatMessage({ id: 'audit.someone' });
    if (member.account === 'closed') return intl.formatMessage({ id: 'team.member.state.closed' });
    return member.display_name ?? intl.formatMessage({ id: 'team.member.unnamed' });
  };
  const clientName = (clientId: string | null | undefined): string | undefined =>
    clientId ? [...(clients.data ?? []), ...(archived.data ?? [])].find((client) => client.id === clientId)?.name : undefined;

  const who = (event: AuditEvent): string => {
    // A change the platform operator made has no member behind it (017-A, actor_kind).
    if (event.actor_kind === 'platform_operator') return intl.formatMessage({ id: 'audit.operator' });
    if (!event.actor_user_id) return intl.formatMessage({ id: 'audit.someone' });
    return personName(members.data?.find((member) => member.user_id === event.actor_user_id));
  };

  const what = (event: AuditEvent): { text: string; known: boolean } => {
    const found = auditAction(event.action);
    if (!found) return { text: intl.formatMessage({ id: 'audit.action.unknown' }), known: false };
    let name = '';
    if (found.subject === 'member') name = personName(members.data?.find((member) => member.id === event.resource_id));
    if (found.subject === 'invitation') {
      name = invitations.data?.find((invitation) => invitation.id === event.resource_id)?.email_normalized ?? intl.formatMessage({ id: 'audit.someone' });
    }
    if (found.subject === 'key') name = keys.data?.find((key) => key.id === event.resource_id)?.name ?? intl.formatMessage({ id: 'audit.aKey' });
    if (found.subject === 'client') name = clientName(event.resource_id) ?? intl.formatMessage({ id: 'audit.aClient' });
    return { text: intl.formatMessage({ id: found.message }, { name }), known: true };
  };

  const loading = audit.isPending || lookups.some((query) => query.isPending);
  const events = audit.data ?? [];

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="audit.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="audit.lead" values={{ count: AUDIT_LIMIT }} />
          </p>
        </div>
      </div>

      {audit.isError ? (
        <ErrorNotice
          message={describeError(audit.error)}
          action={
            <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void audit.refetch()}>
              <FormattedMessage id="common.retry" />
            </button>
          }
        />
      ) : null}

      {loading && !audit.isError ? (
        <div className="c-card">
          <div className="c-card__body">
            <Skeleton lines={5} />
          </div>
        </div>
      ) : null}

      {!loading && audit.isSuccess && events.length === 0 ? (
        <div className="c-card">
          <EmptyState icon="scroll-text" title={<FormattedMessage id="audit.empty.title" />}>
            <FormattedMessage id="audit.empty.text" />
          </EmptyState>
        </div>
      ) : null}

      {!loading && events.length > 0 ? (
        <section className="c-card" aria-label={intl.formatMessage({ id: 'audit.title' })}>
          <div className="c-card__body c-card__body--flush">
            <div className="c-table-wrap">
              <table className="c-table">
                <thead>
                  <tr>
                    <th scope="col">
                      <FormattedMessage id="audit.column.when" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="audit.column.who" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="audit.column.what" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="clients.column.client" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => {
                    const sentence = what(event);
                    const client = clientName(event.client_id);
                    return (
                      <tr key={event.id}>
                        <td className="a-nowrap">
                          <Moment value={event.occurred_at} />
                        </td>
                        <td>
                          <span className="c-table__primary">{who(event)}</span>
                        </td>
                        <td>
                          {sentence.text}
                          {sentence.known ? null : (
                            <>
                              {' '}
                              <span className="u-mono u-ltr u-tertiary">{event.action}</span>
                            </>
                          )}
                        </td>
                        {client ? (
                          <td>{client}</td>
                        ) : (
                          <td className="is-absent">
                            <span aria-hidden="true">—</span>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="c-card__footer">
            <Icon name="lock" size="sm" />
            <FormattedMessage id="audit.footer" values={{ count: events.length }} />
          </div>
        </section>
      ) : null}
    </>
  );
}
