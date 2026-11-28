import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { checkDomain, claimDomain, disableDomain, domainsQuery, issueChallenge, linksKey, type DomainChallenge, type LinkDomain } from '@/api/links';
import { useClient } from '@/app/tenant';
import { Badge, type BadgeTone } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon, type IconName } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import { ShownOnceDialog } from '@/components/ShownOnceDialog';
import { Moment } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { domainError, domainFailureMessage, domainState, HOSTNAME_MAX, type DomainState } from './rules';

const badges: Record<DomainState, { tone: BadgeTone; icon: IconName }> = {
  verified: { tone: 'success', icon: 'circle-check' },
  waiting: { tone: 'info', icon: 'hourglass' },
  unverified: { tone: 'neutral', icon: 'circle-dashed' },
  expired: { tone: 'warning', icon: 'clock' },
  recheck: { tone: 'warning', icon: 'clock' },
  failed: { tone: 'danger', icon: 'circle-alert' },
  off: { tone: 'neutral', icon: 'ban' },
};

const domainErrors: Partial<Record<string, MessageId>> = {
  host_conflict: 'links.domains.error.hostConflict',
  state_conflict: 'links.domains.error.exists',
  validation_failed: 'links.domains.error.refused',
  verification_unavailable: 'links.domains.error.unavailable',
};

/** What a person sees after a check: the domain works, why it does not, or that it changed meanwhile. */
type CheckResult = { hostname: string; outcome: 'verified' | 'stale' } | { hostname: string; outcome: 'failed'; code: string | null };

function ClaimDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [hostname, setHostname] = useState('');
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () => claimDomain(agencyId, clientId, hostname.trim().toLowerCase()),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'domains') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, domainErrors)),
  });
  const submit = () => {
    const found = domainError(hostname.trim().toLowerCase());
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, field])) request.mutate();
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="links.domains.new" />}
      submitLabel={<FormattedMessage id="links.domains.claim" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="domain-hostname"
        ref={field}
        size="md"
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        maxLength={HOSTNAME_MAX}
        placeholder="go.example.com"
        label={<FormattedMessage id="links.domains.hostname" />}
        hint={<FormattedMessage id="links.domains.hostnameHint" />}
        // The dialog was opened to name a domain.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        required
        value={hostname}
        onChange={setHostname}
        error={error}
      />
    </FormDialog>
  );
}

function OffDialog({ domain, onClose }: { domain: LinkDomain; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: () => disableDomain(agencyId, clientId, domain.id),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'domains') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  return (
    <FormDialog
      isOpen
      alert
      tone="danger"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="links.domains.off.title" values={{ host: domain.hostname }} />}
      submitLabel={<FormattedMessage id="links.action.turnOff" />}
      cancelLabel={<FormattedMessage id="links.domains.off.keep" />}
      busy={request.isPending}
      onSubmit={() => {
        setProblem(null);
        request.mutate();
      }}
    >
      <p>
        <FormattedMessage id="links.domains.off.text" />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}

/** The DNS records of a new challenge. The value of the TXT record is in this answer only. */
function RecordDialog({ challenge, onClose }: { challenge: DomainChallenge; onClose: () => void }) {
  const intl = useIntl();
  return (
    <ShownOnceDialog
      title={<FormattedMessage id="links.domains.record.title" values={{ host: challenge.domain.hostname }} />}
      notice={
        <FormattedMessage
          id="links.domains.record.once"
          values={{ date: intl.formatDate(challenge.expires_at, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) }}
        />
      }
      values={[
        { id: 'record-name', label: <FormattedMessage id="links.domains.record.name" values={{ type: challenge.record_type ?? 'TXT' }} />, value: challenge.record_name },
        { id: 'record-value', label: <FormattedMessage id="links.domains.record.value" />, value: challenge.record_value },
        ...(challenge.cname_target
          ? [
              {
                id: 'record-cname',
                label: <FormattedMessage id="links.domains.record.cname" values={{ host: challenge.domain.hostname }} />,
                value: challenge.cname_target,
              },
            ]
          : []),
      ]}
      onClose={onClose}
    >
      <p className="c-field__hint">
        <FormattedMessage id="links.domains.record.next" />
      </p>
    </ShownOnceDialog>
  );
}

/** Custom domains for short links: claim one, prove it with a DNS record, check it, turn it off. */
export function DomainsTab() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const domains = useQuery(domainsQuery(agencyId, clientId));
  const [claiming, setClaiming] = useState(false);
  const [turningOff, setTurningOff] = useState<LinkDomain | null>(null);
  const [challenge, setChallenge] = useState<DomainChallenge | null>(null);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'domains') });

  const record = useMutation({
    mutationFn: (domain: LinkDomain) => issueChallenge(agencyId, clientId, domain.id),
    // The answer holds the record's value. It is handed on and not kept by the request.
    gcTime: 0,
    async onSuccess(issued) {
      setProblem(null);
      setResult(null);
      await refresh();
      setChallenge(issued);
    },
    onError: (failure) => setProblem(describeError(failure, domainErrors)),
  });
  const check = useMutation({
    mutationFn: (domain: LinkDomain) => checkDomain(agencyId, clientId, domain.id),
    async onSuccess(answer) {
      setProblem(null);
      setResult(
        answer.outcome === 'failed'
          ? { hostname: answer.domain.hostname, outcome: 'failed', code: answer.domain.failure_code }
          : { hostname: answer.domain.hostname, outcome: answer.outcome },
      );
      await refresh();
    },
    onError: (failure) => {
      setResult(null);
      setProblem(describeError(failure, domainErrors));
    },
  });

  const now = Date.now();
  const rows = [...(domains.data ?? [])].sort((first, second) => {
    if ((first.status === 'disabled') !== (second.status === 'disabled')) return first.status === 'disabled' ? 1 : -1;
    return second.created_at.localeCompare(first.created_at);
  });

  const claimButton = manager ? (
    <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setClaiming(true)}>
      <Icon name="plus" size="sm" />
      <FormattedMessage id="links.domains.new" />
    </button>
  ) : null;

  return (
    <section className="c-card" aria-labelledby="domains-title">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id="domains-title">
            <FormattedMessage id="links.domains.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="links.domains.lead" />
          </p>
        </div>
        {claimButton}
      </div>
      <div className="c-card__body c-card__body--flush">
        <QueryStates query={domains} />
        <div className="a-pad--x">
          <ErrorNotice message={problem} />
          {result?.outcome === 'verified' ? (
            <Notice tone="success">
              <FormattedMessage id="links.domains.checked.verified" values={{ host: result.hostname }} />
            </Notice>
          ) : null}
          {result?.outcome === 'stale' ? (
            <Notice tone="warning">
              <FormattedMessage id="links.domains.checked.stale" values={{ host: result.hostname }} />
            </Notice>
          ) : null}
          {result?.outcome === 'failed' ? (
            <Notice tone="danger" title={<FormattedMessage id="links.domains.checked.failed" values={{ host: result.hostname }} />}>
              <FormattedMessage id={domainFailureMessage(result.code)} />
            </Notice>
          ) : null}
        </div>
        {domains.isSuccess && rows.length === 0 ? (
          <EmptyState icon="globe" title={<FormattedMessage id="links.domains.empty.title" />} level={3}>
            <FormattedMessage id="links.domains.empty.text" />
          </EmptyState>
        ) : null}
        {rows.length > 0 ? (
          <div className="c-table-wrap">
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="links.domains.hostname" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="team.column.state" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="links.domains.column.when" />
                  </th>
                  <th scope="col">
                    <span className="u-sr">
                      <FormattedMessage id="clients.column.actions" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((domain) => {
                  const state = domainState(domain, now);
                  const actions: RowAction[] =
                    state === 'off'
                      ? []
                      : [
                          {
                            id: 'record',
                            label: <FormattedMessage id="links.domains.action.record" />,
                            text: intl.formatMessage({ id: 'links.domains.action.record' }),
                            onAction: () => record.mutate(domain),
                          },
                          ...(domain.challenge_expires_at
                            ? [
                                {
                                  id: 'check',
                                  label: <FormattedMessage id="links.domains.action.check" />,
                                  text: intl.formatMessage({ id: 'links.domains.action.check' }),
                                  onAction: () => check.mutate(domain),
                                },
                              ]
                            : []),
                          {
                            id: 'off',
                            label: <FormattedMessage id="links.action.turnOff" />,
                            text: intl.formatMessage({ id: 'links.action.turnOff' }),
                            danger: true,
                            onAction: () => setTurningOff(domain),
                          },
                        ];
                  return (
                    <tr key={domain.id}>
                      <td>
                        <span className="c-table__primary u-mono u-ltr">{domain.hostname}</span>
                        {state === 'failed' ? (
                          <span className="c-table__sub">
                            <FormattedMessage id={domainFailureMessage(domain.failure_code)} />
                          </span>
                        ) : null}
                      </td>
                      <td>
                        <Badge tone={badges[state].tone} icon={badges[state].icon}>
                          <FormattedMessage id={`links.domains.state.${state}`} />
                        </Badge>
                      </td>
                      <td>
                        {state === 'verified' && domain.verification_expires_at ? (
                          <FormattedMessage id="links.domains.when.verified" values={{ date: <Moment value={domain.verification_expires_at} /> }} />
                        ) : null}
                        {state === 'waiting' && domain.challenge_expires_at ? (
                          <FormattedMessage id="links.domains.when.waiting" values={{ date: <Moment value={domain.challenge_expires_at} /> }} />
                        ) : null}
                        {state !== 'verified' && state !== 'waiting' && domain.last_checked_at ? (
                          <FormattedMessage id="links.domains.when.checked" values={{ date: <Moment value={domain.last_checked_at} /> }} />
                        ) : null}
                        {state !== 'verified' && state !== 'waiting' && !domain.last_checked_at ? (
                          <span className="u-tertiary">
                            <FormattedMessage id="links.domains.when.never" />
                          </span>
                        ) : null}
                      </td>
                      <td className="is-num">
                        {manager && actions.length > 0 ? (
                          <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: domain.hostname })} actions={actions} />
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
        <FormattedMessage id="links.domains.footer" />
      </div>
      {claiming ? <ClaimDialog onClose={() => setClaiming(false)} /> : null}
      {turningOff ? <OffDialog domain={turningOff} onClose={() => setTurningOff(null)} /> : null}
      {challenge ? (
        <RecordDialog
          challenge={challenge}
          onClose={() => {
            setChallenge(null);
            // The request keeps its answer while the page is open; the value goes with it.
            record.reset();
          }}
        />
      ) : null}
    </section>
  );
}
