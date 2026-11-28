import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { keysKey, keysQuery, revokeKey, type IssuedServiceKey, type ServiceKey } from '@/api/keys';
import { useAgency } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { Skeleton } from '@/components/Skeleton';
import { Day } from '@/components/Time';

import { IssueKeyDialog } from './IssueKeyDialog';

type KeyState = 'active' | 'expired' | 'revoked';

/** A key that was never revoked still stops working when its time has passed. */
export function keyState(key: ServiceKey, now: number): KeyState {
  if (key.status !== 'active') return 'revoked';
  return new Date(key.expires_at).getTime() <= now ? 'expired' : 'active';
}

/**
 * Shows a new key, once. The key lives in this component's memory while the dialog is open and
 * nowhere else: not in the cache, not in storage and not in the address.
 */
function IssuedDialog({ issued, onClose }: { issued: IssuedServiceKey; onClose: () => void }) {
  const intl = useIntl();
  const [copied, setCopied] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  const copy = async () => {
    field.current?.select();
    try {
      await navigator.clipboard.writeText(issued.key);
      setCopied(true);
    } catch {
      // The browser refused. The key is selected, so the person can copy it by hand.
      setCopied(false);
    }
  };

  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="keys.issued.title" values={{ name: issued.credential.name }} />}
      cancelLabel={<FormattedMessage id="keys.issued.done" />}
    >
      <Notice tone="warning" quiet>
        <FormattedMessage id="keys.issued.once" />
      </Notice>
      <div className="c-field">
        <label className="c-field__label" htmlFor="issued-key">
          <FormattedMessage id="keys.issued.key" />
        </label>
        <div className="l-cluster a-copy">
          <input
            id="issued-key"
            ref={field}
            className="c-input u-mono u-grow"
            dir="ltr"
            readOnly
            spellCheck={false}
            autoComplete="off"
            value={issued.key}
            onFocus={(event) => event.target.select()}
          />
          <button type="button" className="c-btn c-btn--secondary" onClick={() => void copy()}>
            <Icon name="copy" size="sm" />
            <FormattedMessage id="common.copy" />
          </button>
        </div>
        <p className="c-field__hint" role="status">
          {copied ? intl.formatMessage({ id: 'common.copied' }) : null}
        </p>
      </div>
    </FormDialog>
  );
}

function RevokeDialog({ agencyId, credential, onClose }: { agencyId: string; credential: ServiceKey; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: () => revokeKey(agencyId, credential.id),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: keysKey(agencyId) });
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
      title={<FormattedMessage id="keys.revoke.title" values={{ name: credential.name }} />}
      submitLabel={<FormattedMessage id="keys.revoke" />}
      cancelLabel={<FormattedMessage id="keys.revoke.keep" />}
      tone="danger"
      busy={request.isPending}
      onSubmit={() => {
        setProblem(null);
        request.mutate();
      }}
    >
      <p>
        <FormattedMessage id="keys.revoke.text" />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}

function StateBadge({ state }: { state: KeyState }) {
  if (state === 'active') {
    return (
      <Badge tone="success" icon="circle-check">
        <FormattedMessage id="keys.state.active" />
      </Badge>
    );
  }
  return (
    <Badge icon={state === 'expired' ? 'clock' : 'ban'}>
      <FormattedMessage id={`keys.state.${state}`} />
    </Badge>
  );
}

/** The keys with which the agency's own systems read a client's data or send events. */
export function KeysPage() {
  usePageTitle('keys.title');
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId } = useAgency();
  const keys = useQuery(keysQuery(agencyId));
  const [issuing, setIssuing] = useState(false);
  const [issued, setIssued] = useState<IssuedServiceKey | null>(null);
  const [revoking, setRevoking] = useState<ServiceKey | null>(null);

  const sorted = [...(keys.data ?? [])].sort((first, second) => second.created_at.localeCompare(first.created_at));
  const now = Date.now();

  const issueButton = (
    <button type="button" className="c-btn c-btn--primary" onClick={() => setIssuing(true)}>
      <Icon name="plus" size="sm" />
      <FormattedMessage id="keys.issue" />
    </button>
  );

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="keys.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="keys.lead" />
          </p>
        </div>
        {sorted.length > 0 ? <div className="l-cluster">{issueButton}</div> : null}
      </div>

      {keys.isPending ? (
        <div className="c-card">
          <div className="c-card__body">
            <Skeleton lines={4} />
          </div>
        </div>
      ) : null}

      {keys.isError ? (
        <ErrorNotice
          message={describeError(keys.error)}
          action={
            <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void keys.refetch()}>
              <FormattedMessage id="common.retry" />
            </button>
          }
        />
      ) : null}

      {keys.isSuccess && sorted.length === 0 ? (
        <div className="c-card">
          <EmptyState icon="key-round" title={<FormattedMessage id="keys.empty.title" />} action={issueButton}>
            <FormattedMessage id="keys.empty.text" />
          </EmptyState>
        </div>
      ) : null}

      {sorted.length > 0 ? (
        <section className="c-card" aria-label={intl.formatMessage({ id: 'keys.title' })}>
          <div className="c-card__body c-card__body--flush">
            <div className="c-table-wrap">
              <table className="c-table">
                <thead>
                  <tr>
                    <th scope="col">
                      <FormattedMessage id="keys.name" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="keys.kind" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="team.column.state" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="keys.column.created" />
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
                  {sorted.map((credential) => {
                    const state = keyState(credential, now);
                    return (
                      <tr key={credential.id}>
                        <td>
                          <span className="c-table__primary">{credential.name}</span>
                        </td>
                        <td>
                          <FormattedMessage id={credential.kind === 'ingest' ? 'keys.kind.ingest' : 'keys.kind.read'} />
                        </td>
                        <td>
                          <StateBadge state={state} />
                        </td>
                        <td>
                          <Day value={credential.created_at} />
                        </td>
                        <td>
                          <Day value={credential.expires_at} />
                        </td>
                        <td className="is-num">
                          {state === 'active' ? (
                            <button
                              type="button"
                              className="c-btn c-btn--ghost c-btn--sm"
                              aria-label={intl.formatMessage({ id: 'keys.revoke.named' }, { name: credential.name })}
                              onClick={() => setRevoking(credential)}
                            >
                              <FormattedMessage id="keys.revoke" />
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="c-card__footer">
            <Icon name="lock" size="sm" />
            <FormattedMessage id="keys.footer" />
          </div>
        </section>
      ) : null}

      {issuing ? (
        <IssueKeyDialog
          agencyId={agencyId}
          onClose={() => setIssuing(false)}
          onIssued={async (result) => {
            await queryClient.invalidateQueries({ queryKey: keysKey(agencyId) });
            setIssuing(false);
            setIssued(result);
          }}
        />
      ) : null}
      {issued ? <IssuedDialog issued={issued} onClose={() => setIssued(null)} /> : null}
      {revoking ? <RevokeDialog agencyId={agencyId} credential={revoking} onClose={() => setRevoking(null)} /> : null}
    </>
  );
}
