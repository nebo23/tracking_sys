import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Tab, TabList, TabPanel, Tabs } from 'react-aria-components';
import { FormattedMessage, useIntl } from 'react-intl';

import type { Role } from '@/api/agencies';
import { clientsQuery } from '@/api/clients';
import { describeError, type ErrorMessage } from '@/api/errors';
import { sessionQuery } from '@/api/session';
import { invitationsKey, invitationsQuery, membersKey, membersQuery, revokeInvitation, updateMember, type Invitation, type Member } from '@/api/team';
import { useAgency } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { RowMenu } from '@/components/RowMenu';
import { Skeleton } from '@/components/Skeleton';
import { Day } from '@/components/Time';
import { cx } from '@/lib/cx';
import { initials } from '@/lib/initials';

import { InviteDialog } from './InviteDialog';
import { MemberAccessDialog } from './MemberAccessDialog';
import { clientAccess, mayChange } from './members';

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

interface PauseDialogProps {
  agencyId: string;
  member: Member;
  name: string;
  onPaused: () => void;
  onClose: () => void;
}

/** Pausing access is asked: the person cannot open the agency until an owner or admin restores it. */
function PauseDialog({ agencyId, member, name, onPaused, onClose }: PauseDialogProps) {
  const queryClient = useQueryClient();
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: () => updateMember(agencyId, member.id, { status: 'disabled' }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: membersKey(agencyId) });
      onPaused();
    },
    onError: (failure) => setProblem(describeError(failure, { state_conflict: 'team.member.error.lastOwner' })),
  });
  return (
    <FormDialog
      isOpen
      alert
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="team.member.pause.title" values={{ name }} />}
      submitLabel={<FormattedMessage id="team.member.pause" />}
      cancelLabel={<FormattedMessage id="team.member.pause.keep" />}
      tone="danger"
      busy={request.isPending}
      onSubmit={() => {
        setProblem(null);
        request.mutate();
      }}
    >
      <p>
        <FormattedMessage id="team.member.pause.text" />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}

function MemberState({ member }: { member: Member }) {
  if (member.account === 'closed') {
    return (
      <Badge icon="circle-slash">
        <FormattedMessage id="team.member.state.closed" />
      </Badge>
    );
  }
  if (member.account === 'disabled') {
    return (
      <Badge icon="ban">
        <FormattedMessage id="team.member.state.accountDisabled" />
      </Badge>
    );
  }
  if (member.status !== 'active') {
    return (
      <Badge tone="warning" icon="circle-pause">
        <FormattedMessage id="team.member.state.paused" />
      </Badge>
    );
  }
  return (
    <Badge tone="success" icon="circle-check">
      <FormattedMessage id="team.member.state.active" />
    </Badge>
  );
}

interface MembersTableProps {
  role: Role;
  userId: string;
  members: readonly Member[];
  activeClientIds: readonly string[];
  clientName: (clientId: string) => string | undefined;
  nameOf: (member: Member) => string;
  onChange: (member: Member) => void;
  onPause: (member: Member) => void;
  onRestore: (member: Member) => void;
}

function MembersTable({ role, userId, members, activeClientIds, clientName, nameOf, onChange, onPause, onRestore }: MembersTableProps) {
  const intl = useIntl();
  return (
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
              <FormattedMessage id="team.column.clients" />
            </th>
            <th scope="col">
              <FormattedMessage id="grants.financials" />
            </th>
            <th scope="col">
              <FormattedMessage id="team.column.state" />
            </th>
            <th scope="col">
              <span className="u-sr">
                <FormattedMessage id="clients.column.actions" />
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          {members.map((member) => {
            const name = nameOf(member);
            const access = clientAccess(member, activeClientIds);
            let clientsCell: ReactNode = <FormattedMessage id="team.member.clients.all" />;
            let financialCell: ReactNode = (
              <Badge tone="success" icon="check">
                <FormattedMessage id="team.member.financial.all" />
              </Badge>
            );
            if (access.kind === 'none') {
              clientsCell = (
                <Badge tone="warning" icon="triangle-alert">
                  <FormattedMessage id="team.member.clients.none" />
                </Badge>
              );
              financialCell = <span aria-hidden="true">—</span>;
            } else if (access.kind === 'some') {
              clientsCell = access.onlyClient ? (clientName(access.onlyClient) ?? <FormattedMessage id="team.member.clients.count" values={{ count: 1 }} />) : (
                <FormattedMessage id="team.member.clients.count" values={{ count: access.clients }} />
              );
              if (access.financial === 0) {
                financialCell = (
                  <Badge icon="minus">
                    <FormattedMessage id="team.member.financial.none" />
                  </Badge>
                );
              } else if (access.financial < access.clients) {
                financialCell = (
                  <Badge tone="warning" icon="circle-dot">
                    <FormattedMessage id="team.member.financial.some" values={{ financial: access.financial, clients: access.clients }} />
                  </Badge>
                );
              }
            }
            const actions = mayChange(role, userId, member)
              ? [
                  { id: 'access', label: <FormattedMessage id="team.member.access" />, text: intl.formatMessage({ id: 'team.member.access' }), onAction: () => onChange(member) },
                  member.status === 'active'
                    ? { id: 'pause', label: <FormattedMessage id="team.member.pause" />, text: intl.formatMessage({ id: 'team.member.pause' }), onAction: () => onPause(member), danger: true }
                    : { id: 'restore', label: <FormattedMessage id="team.member.restore" />, text: intl.formatMessage({ id: 'team.member.restore' }), onAction: () => onRestore(member) },
                ]
              : [];
            const closed = member.account === 'closed';
            return (
              <tr key={member.id}>
                <td>
                  <span className="l-cluster a-person">
                    <span className="c-avatar" aria-hidden="true">
                      {closed ? <Icon name="user" size="sm" /> : initials(name)}
                    </span>
                    <span className="u-truncate">
                      <span className={cx('c-table__primary', closed && 'u-tertiary')}>
                        {name}
                        {member.user_id === userId ? (
                          <>
                            {' '}
                            <span className="u-tertiary">
                              <FormattedMessage id="team.member.you" />
                            </span>
                          </>
                        ) : null}
                      </span>
                      {member.email_normalized ? <span className="c-table__sub u-ltr">{member.email_normalized}</span> : null}
                    </span>
                  </span>
                </td>
                <td>
                  <Badge tone={member.role === 'owner' ? 'brand' : 'neutral'}>
                    <FormattedMessage id={`role.${member.role}`} />
                  </Badge>
                </td>
                <td>{clientsCell}</td>
                <td>{financialCell}</td>
                <td>
                  <MemberState member={member} />
                </td>
                <td className="is-num">
                  {actions.length > 0 ? <RowMenu label={intl.formatMessage({ id: 'team.member.actions' }, { name })} actions={actions} /> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Who can open which client, and who can see money: the members of the agency and its invitations. */
export function TeamPage() {
  usePageTitle('team.title');
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, role } = useAgency();
  const { data: session } = useSuspenseQuery(sessionQuery);
  const members = useQuery(membersQuery(agencyId));
  const invitations = useQuery(invitationsQuery(agencyId));
  const clients = useQuery(clientsQuery(agencyId));
  const [tab, setTab] = useState<'members' | 'invitations'>('members');
  const [inviting, setInviting] = useState(false);
  const [withdrawing, setWithdrawing] = useState<Invitation | null>(null);
  const [changing, setChanging] = useState<Member | null>(null);
  const [pausing, setPausing] = useState<Member | null>(null);
  const [notice, setNotice] = useState<ReactNode>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);

  const restore = useMutation({
    mutationFn: (member: Member) => updateMember(agencyId, member.id, { status: 'active' }),
    async onSuccess(_result, member) {
      await queryClient.invalidateQueries({ queryKey: membersKey(agencyId) });
      setNotice(<FormattedMessage id="team.member.restored" values={{ name: nameOf(member) }} />);
    },
    onError: (failure) => setProblem(describeError(failure)),
  });

  if (!session) return null;
  const userId = session.user.id;
  const activeClientIds = (clients.data ?? []).map((client) => client.id);
  const clientName = (clientId: string) => clients.data?.find((client) => client.id === clientId)?.name;
  function nameOf(member: Member): string {
    if (member.account === 'closed') return intl.formatMessage({ id: 'team.member.state.closed' });
    return member.display_name ?? intl.formatMessage({ id: 'team.member.unnamed' });
  }

  // Members as a person reads them: by name, with closed accounts last.
  const collator = new Intl.Collator(intl.locale, { sensitivity: 'base' });
  const sortedMembers = [...(members.data ?? [])].sort(
    (first, second) => Number(first.account === 'closed') - Number(second.account === 'closed') || collator.compare(nameOf(first), nameOf(second)),
  );
  // Newest first: the invitation a person just sent is the one they look for.
  const sortedInvitations = [...(invitations.data ?? [])].sort((first, second) => second.created_at.localeCompare(first.created_at));
  const now = Date.now();
  const waiting = sortedInvitations.filter((invitation) => invitationState(invitation, now) === 'pending').length;
  // Only an owner withdraws an invitation to become an owner.
  const mayWithdraw = (invitation: Invitation) => invitation.role !== 'owner' || role === 'owner';

  const say = (message: ReactNode) => {
    setProblem(null);
    setNotice(message);
  };

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
        <div className="l-cluster">
          <button type="button" className="c-btn c-btn--primary" onClick={() => setInviting(true)}>
            <Icon name="user-plus" size="sm" />
            <FormattedMessage id="team.invite" />
          </button>
        </div>
      </div>

      {notice ? <Notice tone="success">{notice}</Notice> : null}
      <ErrorNotice message={problem} />

      <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(key === 'invitations' ? 'invitations' : 'members')}>
        <TabList className="c-tabs" aria-label={intl.formatMessage({ id: 'team.title' })}>
          <Tab id="members" className={({ isSelected }) => cx('c-tab', isSelected && 'is-active')}>
            <FormattedMessage id="team.tab.members" />
            {members.isSuccess ? <span className="a-tab-count u-num">{intl.formatNumber(members.data.length)}</span> : null}
          </Tab>
          <Tab id="invitations" className={({ isSelected }) => cx('c-tab', isSelected && 'is-active')}>
            <FormattedMessage id="team.tab.invitations" />
            {invitations.isSuccess ? <span className="a-tab-count u-num">{intl.formatNumber(waiting)}</span> : null}
          </Tab>
        </TabList>

        <div className="l-split a-team">
          <div className="a-team__main">
            <TabPanel id="members" className="c-card a-panel">
              <div className="c-card__body c-card__body--flush">
                {members.isPending || clients.isPending ? (
                  <div className="a-pad">
                    <Skeleton lines={4} />
                  </div>
                ) : null}
                {members.isError ? (
                  <div className="a-pad">
                    <ErrorNotice
                      message={describeError(members.error)}
                      action={
                        <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void members.refetch()}>
                          <FormattedMessage id="common.retry" />
                        </button>
                      }
                    />
                  </div>
                ) : null}
                {members.isSuccess && !clients.isPending ? (
                  <MembersTable
                    role={role}
                    userId={userId}
                    members={sortedMembers}
                    activeClientIds={activeClientIds}
                    clientName={clientName}
                    nameOf={nameOf}
                    onChange={(member) => {
                      setNotice(null);
                      setChanging(member);
                    }}
                    onPause={(member) => {
                      setNotice(null);
                      setPausing(member);
                    }}
                    onRestore={(member) => {
                      setNotice(null);
                      setProblem(null);
                      restore.mutate(member);
                    }}
                  />
                ) : null}
              </div>
              <div className="c-card__footer">
                <Icon name="info" size="sm" />
                <FormattedMessage id="team.members.footer" />
              </div>
            </TabPanel>

            <TabPanel id="invitations" className="c-card a-panel">
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
                {invitations.isSuccess && sortedInvitations.length === 0 ? (
                  <EmptyState icon="mail" level={3} title={<FormattedMessage id="team.empty.title" />}>
                    <FormattedMessage id="team.empty.text" />
                  </EmptyState>
                ) : null}
                {sortedInvitations.length > 0 ? (
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
                        {sortedInvitations.map((invitation) => {
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
            </TabPanel>
          </div>

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
      </Tabs>

      {inviting ? (
        <InviteDialog
          agencyId={agencyId}
          role={role}
          onClose={() => setInviting(false)}
          onInvited={async (invitation) => {
            await queryClient.invalidateQueries({ queryKey: invitationsKey(agencyId) });
            setInviting(false);
            setTab('invitations');
            say(
              <FormattedMessage
                id="team.invite.sent"
                values={{ email: <span className="u-ltr">{invitation.email_normalized}</span>, date: <Day value={invitation.expires_at} /> }}
              />,
            );
          }}
        />
      ) : null}
      {withdrawing ? <WithdrawDialog agencyId={agencyId} invitation={withdrawing} onClose={() => setWithdrawing(null)} /> : null}
      {changing ? (
        <MemberAccessDialog
          agencyId={agencyId}
          actorRole={role}
          member={changing}
          name={nameOf(changing)}
          activeClientIds={activeClientIds}
          onClose={() => setChanging(null)}
          onSaved={() => {
            const name = nameOf(changing);
            setChanging(null);
            say(<FormattedMessage id="team.member.saved" values={{ name }} />);
          }}
        />
      ) : null}
      {pausing ? (
        <PauseDialog
          agencyId={agencyId}
          member={pausing}
          name={nameOf(pausing)}
          onClose={() => setPausing(null)}
          onPaused={() => {
            const name = nameOf(pausing);
            setPausing(null);
            say(<FormattedMessage id="team.member.paused" values={{ name }} />);
          }}
        />
      ) : null}
    </>
  );
}
