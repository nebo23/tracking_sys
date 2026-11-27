import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { erasuresQuery, requestErasure, trackingKey, type ErasureRequest } from '@/api/tracking';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { Checkbox } from '@/components/Choice';
import { EmptyState } from '@/components/EmptyState';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { Moment } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { erasureStates, erasureTargets, EVENT_ID, requesterKinds, SUBJECT_TOKEN } from './rules';

type By = 'token' | 'event';

const stateWord = (status: string): MessageId | null => {
  const known = erasureStates.find((item) => item === status);
  return known ? `tracking.erasure.state.${known}` : null;
};
const requesterWord = (kind: string): MessageId | null => {
  const known = requesterKinds.find((item) => item === kind);
  return known ? `tracking.erasure.by.${known}` : null;
};
const targetWord = (target: string): MessageId | null => {
  const known = erasureTargets.find((item) => item === target);
  return known ? `tracking.erasure.target.${known}` : null;
};

/**
 * Erases one visitor of this client, named by their token or by one of their event identifiers.
 * It deletes at once and cannot be undone, so the dialog asks as an alert and says what goes.
 */
function EraseDialog({ onErased, onClose }: { onErased: (request: ErasureRequest) => void; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [by, setBy] = useState<By>('token');
  const [value, setValue] = useState('');
  const [objected, setObjected] = useState(false);
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () =>
      requestErasure(agencyId, clientId, by === 'token' ? { subject_token: value.trim(), objected } : { event_id: value.trim().toLowerCase(), objected }),
    async onSuccess(erased) {
      await queryClient.invalidateQueries({ queryKey: trackingKey(agencyId, clientId, 'erasures') });
      onErased(erased);
    },
    onError: (failure) => setProblem(describeError(failure, { access_denied: 'tracking.erase.error.unknown', validation_failed: 'tracking.erase.error.refused' })),
  });
  const submit = () => {
    const text = value.trim();
    const found: MessageId | null =
      text === '' ? 'field.error.required' : (by === 'token' ? SUBJECT_TOKEN : EVENT_ID).test(text) ? null : by === 'token' ? 'tracking.erase.error.token' : 'tracking.erase.error.event';
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, field])) request.mutate();
  };
  return (
    <FormDialog
      isOpen
      alert
      wide
      tone="danger"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="tracking.erase.title" />}
      submitLabel={<FormattedMessage id="tracking.erase.submit" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <p>
        <FormattedMessage id="tracking.erase.text" />
      </p>
      <ErrorNotice message={problem} />
      <fieldset className="a-fieldset">
        <legend className="c-field__label">
          <FormattedMessage id="tracking.erase.by" />
        </legend>
        <div className="l-cluster">
          {(['token', 'event'] as const).map((option) => (
            <label key={option} className="c-choice">
              <input
                className="c-radio"
                type="radio"
                name="erase-by"
                value={option}
                checked={by === option}
                onChange={() => {
                  setBy(option);
                  setError(null);
                }}
              />
              <span>
                <FormattedMessage id={`tracking.erase.by.${option}`} />
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <Field
        id="erase-value"
        ref={field}
        size="md"
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        label={<FormattedMessage id={by === 'token' ? 'tracking.erase.token' : 'tracking.erase.event'} />}
        hint={<FormattedMessage id={by === 'token' ? 'tracking.erase.tokenHint' : 'tracking.erase.eventHint'} />}
        value={value}
        onChange={setValue}
        error={error}
      />
      <Checkbox id="erase-objected" checked={objected} onChange={setObjected}>
        <FormattedMessage id="tracking.erase.objected" />
      </Checkbox>
    </FormDialog>
  );
}

/** The erasures of the client's visitors, newest first. Owners and admins only. */
export function ErasuresCard() {
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const erasures = useQuery(erasuresQuery(agencyId, clientId));
  const [erasing, setErasing] = useState(false);
  const [erased, setErased] = useState<ErasureRequest | null>(null);
  const rows = erasures.data ?? [];

  return (
    <section className="c-card" aria-labelledby="erasures-title">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id="erasures-title">
            <FormattedMessage id="tracking.erasures.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="tracking.erasures.lead" />
          </p>
        </div>
        {erasures.isSuccess ? (
          <button
            type="button"
            className="c-btn c-btn--secondary c-btn--sm"
            onClick={() => {
              setErased(null);
              setErasing(true);
            }}
          >
            <Icon name="trash-2" size="sm" />
            <FormattedMessage id="tracking.erase.open" />
          </button>
        ) : null}
      </div>
      <div className="c-card__body c-card__body--flush">
        <QueryStates query={erasures} />
        {erased ? (
          <div className="a-pad--x">
            <Notice tone={erased.status === 'completed' ? 'success' : 'info'}>
              <FormattedMessage id={erased.status === 'completed' ? 'tracking.erase.done' : 'tracking.erase.recorded'} />
            </Notice>
          </div>
        ) : null}
        {erasures.isSuccess && rows.length === 0 ? (
          <EmptyState icon="shield-check" title={<FormattedMessage id="tracking.erasures.empty.title" />} level={3}>
            <FormattedMessage id="tracking.erasures.empty.text" />
          </EmptyState>
        ) : null}
        {rows.length > 0 ? (
          <div className="c-table-wrap">
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="tracking.erasures.received" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.erasures.requester" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="team.column.state" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.erasures.what" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => {
                  const state = stateWord(item.status);
                  const requester = requesterWord(item.requester_kind);
                  const targets = Object.entries(item.target_outcomes).filter(([, outcome]) => outcome === 'done');
                  return (
                    <tr key={item.id}>
                      <td>
                        <Moment value={item.received_at} />
                      </td>
                      <td>
                        {requester ? <FormattedMessage id={requester} /> : <span className="u-mono u-ltr">{item.requester_kind}</span>}
                        {item.objected ? (
                          <span className="c-table__sub">
                            <FormattedMessage id="tracking.erasures.objected" />
                          </span>
                        ) : null}
                      </td>
                      <td>
                        <Badge tone={item.status === 'completed' || item.status === 'verified' ? 'success' : 'neutral'} icon={item.status === 'completed' || item.status === 'verified' ? 'circle-check' : 'clock'}>
                          {state ? <FormattedMessage id={state} /> : item.status}
                        </Badge>
                      </td>
                      {targets.length > 0 ? (
                        <td>
                          {targets
                            .map(([target]) => {
                              const word = targetWord(target);
                              return word ? intl.formatMessage({ id: word }) : target;
                            })
                            .join(intl.formatMessage({ id: 'tracking.erasures.join' }))}
                        </td>
                      ) : (
                        <td className="is-absent">
                          <FormattedMessage id="tracking.erasures.nothing" />
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
      {erasing ? (
        <EraseDialog
          onClose={() => setErasing(false)}
          onErased={(result) => {
            setErasing(false);
            setErased(result);
          }}
        />
      ) : null}
    </section>
  );
}
