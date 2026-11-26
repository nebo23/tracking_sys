import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import type { Role } from '@/api/agencies';
import { describeError, type ErrorMessage } from '@/api/errors';
import { invitationsKey, invitationsQuery, revokeInvitation, type Invitation } from '@/api/team';
import { useAgency } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { Skeleton } from '@/components/Skeleton';
import { Day } from '@/components/Time';

import { InviteDialog } from './InviteDialog';

const roles: Role[] = ['owner', 'admin', 'analyst', 'client_viewer'];

type InvitationState = 'pending' | 'expired' | 'accepted' | 'revoked';

/** A pending invitation whose time has passed can no longer be accepted. */
export function invitationState(invitation: Invitation, now: number): InvitationState {
  if (invitation.status === 'accepted') return 'accepted';
  if (invitation.status !== 'pending') return 'revoked';
  return new Date(invitation.expires_at).getTime() <= now ? 'expired' : 'pending';
}

function StateBadge({ state }: { state: InvitationState }) {
  if (state === 'accepted') {
    return (
      <Badge tone="success" icon="circle-check">
        <FormattedMessage id="team.invitation.accepted" />
      </Badge>
    );
  }
  if (state === 'pending') {
    return (
      <Badge tone="info" icon="hourglass">
        <FormattedMessage id="team.invitation.pending" />
      </Badge>
    );
  }
  return (
    <Badge icon={state === 'expired' ? 'clock' : 'ban'}>
      <FormattedMessage id={`team.invitation.${state}`} />
    </Badge>
  );
}

interface WithdrawDialogProps {
  agencyId: string;
  invitation: Invitation;
  onClose: () => void;
}

function WithdrawDialog({ agencyId, invitation, onClose }: WithdrawDialogProps) {
  const queryClient = useQueryClient();
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: () => revokeInvitation(agencyId, invitation.id),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: invitationsKey(agencyId) });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  return (
    <FormDialog
      isOpen
      alert
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="team.withdraw.title" />}
      submitLabel={<FormattedMessage id="team.withdraw" />}
      cancelLabel={<FormattedMessage id="team.withdraw.keep" />}
      tone="danger"
      busy={request.isPending}
      onSubmit={() => {
        setProblem(null);
        request.mutate();
      }}
    >
      <p>
        <FormattedMessage id="team.withdraw.text" values={{ email: <span className="u-ltr u-strong">{invitation.email_normalized}</span> }} />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}

/**
 * Who can open which client, and who can see money. In this slice the page holds the
 * invitations; the list of members waits for the API to name them (018-B plan, section 3).
 */
export function TeamPage() {
  usePageTitle('team.title');
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, role } = useAgency();
  const invitations = useQuery(invitationsQuery(agencyId));
  const [inviting, setInviting] = useState(false);
  const [withdrawing, setWithdrawing] = useState<Invitation | null>(null);
  const [sent, setSent] = useState<Invitation | null>(null);

  // Newest first: the invitation a person just sent is the one they look for.
  const sorted = [...(invitations.data ?? [])].sort((first, second) => second.created_at.localeCompare(first.created_at));
  const now = Date.now();
  // Only an owner withdraws an invitation to become an owner.
  const mayWithdraw = (invitation: Invitation) => invitation.role !== 'owner' || role === 'owner';

  const inviteButton = (
    <button type="button" className="c-btn c-btn--primary" onClick={() => setInviting(true)}>
      <Icon name="user-plus" size="sm" />
      <FormattedMessage id="team.invite" />
    </button>
  );

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="team.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="team.lead" />
          </p>
        </div>
        <div className="l-cluster">{inviteButton}</div>
      </div>

      {sent ? (
        <Notice tone="success">
          <FormattedMessage
            id="team.invite.sent"
            values={{ email: <span className="u-ltr">{sent.email_normalized}</span>, date: <Day value={sent.expires_at} /> }}
          />
        </Notice>
      ) : null}

      <div className="l-split">
        <section className="c-card" aria-labelledby="team-invitations">
          <div className="c-card__header">
            <div>
              <h2 className="c-card__title" id="team-invitations">
                <FormattedMessage id="team.invitations" />
              </h2>
              <p className="c-card__subtitle">
                <FormattedMessage id="team.invitations.lead" />
              </p>
            </div>
          </div>
          <div className="c-card__body c-card__body--flush">
            {invitations.isPending ? (
              <div className="a-pad">
                <Skeleton lines={4} />
              </div>
            ) : null}
            {invitations.isError ? (
              <div className="a-pad">
                <ErrorNotice
                  message={describeError(invitations.error)}
                  action={
                    <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void invitations.refetch()}>
                      <FormattedMessage id="common.retry" />
                    </button>
                  }
                />
              </div>
            ) : null}
            {invitations.isSuccess && sorted.length === 0 ? (
              <EmptyState icon="mail" level={3} title={<FormattedMessage id="team.empty.title" />}>
                <FormattedMessage id="team.empty.text" />
              </EmptyState>
            ) : null}
            {sorted.length > 0 ? (
              <div className="c-table-wrap">
                <table className="c-table">
                  <thead>
                    <tr>
                      <th scope="col">
                        <FormattedMessage id="team.column.person" />
                      </th>
                      <th scope="col">
                        <FormattedMessage id="team.role" />
                      </th>
                      <th scope="col">
                        <FormattedMessage id="team.column.state" />
                      </th>
                      <th scope="col">
                        <FormattedMessage id="team.column.sent" />
                      </th>
                      <th scope="col">
                        <FormattedMessage id="team.column.expires" />
                      </th>
                      <th scope="col">
                        <span className="u-sr">
                          <FormattedMessage id="clients.column.actions" />
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((invitation) => {
                      const state = invitationState(invitation, now);
                      return (
                        <tr key={invitation.id}>
                          <td>
                            <span className="c-table__primary u-ltr">{invitation.email_normalized}</span>
                          </td>
                          <td>
                            <Badge tone={invitation.role === 'owner' ? 'brand' : 'neutral'}>
                              <FormattedMessage id={`role.${invitation.role}`} />
                            </Badge>
                          </td>
                          <td>
                            <StateBadge state={state} />
                          </td>
                          <td>
                            <Day value={invitation.created_at} />
                          </td>
                          {state === 'pending' ? (
                            <td>
                              <Day value={invitation.expires_at} />
                            </td>
                          ) : (
                            <td className="is-absent">
                              <span aria-hidden="true">—</span>
                            </td>
                          )}
                          <td className="is-num">
                            {state === 'pending' && mayWithdraw(invitation) ? (
                              <button
                                type="button"
                                className="c-btn c-btn--ghost c-btn--sm"
                                aria-label={intl.formatMessage({ id: 'team.withdraw.named' }, { email: invitation.email_normalized })}
                                onClick={() => setWithdrawing(invitation)}
                              >
                                <FormattedMessage id="team.withdraw" />
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
          <div className="c-card__footer">
            <Icon name="info" size="sm" />
            <FormattedMessage id="team.members.later" />
          </div>
        </section>

        <section className="c-card" aria-labelledby="team-roles">
          <div className="c-card__header">
            <div>
              <h2 className="c-card__title" id="team-roles">
                <FormattedMessage id="team.roles.title" />
              </h2>
            </div>
          </div>
          <div className="c-card__body">
            <dl className="l-stack">
              {roles.map((name) => (
                <div key={name}>
                  <dt className="u-strong">
                    <FormattedMessage id={`role.${name}`} />
                  </dt>
                  <dd className="u-secondary">
                    <FormattedMessage id={`team.roles.${name}`} />
                  </dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="c-card__footer">
            <Icon name="lock" size="sm" />
            <FormattedMessage id="team.roles.audit" />
          </div>
        </section>
      </div>

      {inviting ? (
        <InviteDialog
          agencyId={agencyId}
          role={role}
          onClose={() => setInviting(false)}
          onInvited={async (invitation) => {
            await queryClient.invalidateQueries({ queryKey: invitationsKey(agencyId) });
            setInviting(false);
            setSent(invitation);
          }}
        />
      ) : null}
      {withdrawing ? <WithdrawDialog agencyId={agencyId} invitation={withdrawing} onClose={() => setWithdrawing(null)} /> : null}
    </>
  );
}
