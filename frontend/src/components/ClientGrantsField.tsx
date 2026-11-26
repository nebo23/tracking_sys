import { useQuery } from '@tanstack/react-query';
import type { ReactNode, Ref } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { clientsQuery } from '@/api/clients';
import { describeError } from '@/api/errors';
import type { MessageId } from '@/i18n';
import { byName } from '@/lib/sort';

import { FieldError } from './Field';
import { ErrorNotice } from './Notice';
import { Skeleton } from './Skeleton';

/** The clients a person or a key may open, each with whether its financial data is included. */
export type Grants = Record<string, { financials: boolean }>;

/** The grants in the shape the API takes. */
export const toClientGrants = (grants: Grants) =>
  Object.entries(grants).map(([clientId, { financials }]) => ({ client_id: clientId, can_view_financials: financials }));

interface ClientGrantsFieldProps {
  id: string;
  agencyId: string;
  legend: ReactNode;
  hint?: ReactNode;
  value: Grants;
  onChange: (grants: Grants) => void;
  /** False for a grant that can never carry financial data, such as a key that only sends events. */
  financials?: boolean;
  error?: MessageId | null;
  /** The first box, so a failed rule can place focus on it. */
  firstRef?: Ref<HTMLInputElement>;
}

/** A list of the agency's clients to tick, with a second box per client for its financial data. */
export function ClientGrantsField({ id, agencyId, legend, hint, value, onChange, financials = true, error, firstRef }: ClientGrantsFieldProps) {
  const intl = useIntl();
  const clients = useQuery(clientsQuery(agencyId));
  const sorted = [...(clients.data ?? [])].sort(byName(intl.locale));

  const toggle = (clientId: string, granted: boolean) => {
    const next = { ...value };
    if (granted) next[clientId] = { financials: false };
    else delete next[clientId];
    onChange(next);
  };

  return (
    <fieldset className="a-fieldset" aria-describedby={[hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') || undefined}>
      <legend className="c-field__label">{legend}</legend>
      {hint ? (
        <p className="c-field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      {clients.isPending ? <Skeleton /> : null}
      {clients.isError ? <ErrorNotice message={describeError(clients.error)} /> : null}
      {clients.isSuccess && sorted.length === 0 ? (
        <p className="u-secondary">
          <FormattedMessage id="grants.none" />
        </p>
      ) : null}
      {sorted.length > 0 ? (
        <ul className="a-grants">
          {sorted.map((client, index) => {
            const grant = value[client.id];
            return (
              <li key={client.id} className="a-grants__row">
                <label className="c-choice a-grants__client" htmlFor={`${id}-${client.id}`}>
                  <input
                    id={`${id}-${client.id}`}
                    ref={index === 0 ? firstRef : undefined}
                    className="c-check"
                    type="checkbox"
                    checked={grant !== undefined}
                    aria-invalid={error ? true : undefined}
                    onChange={(event) => toggle(client.id, event.target.checked)}
                  />
                  <span className="u-truncate">{client.name}</span>
                </label>
                {financials ? (
                  <label className="c-choice" htmlFor={`${id}-${client.id}-financials`}>
                    <input
                      id={`${id}-${client.id}-financials`}
                      className="c-check"
                      type="checkbox"
                      checked={grant?.financials ?? false}
                      disabled={grant === undefined}
                      aria-label={intl.formatMessage({ id: 'grants.financialsFor' }, { client: client.name })}
                      onChange={(event) => onChange({ ...value, [client.id]: { financials: event.target.checked } })}
                    />
                    <span>
                      <FormattedMessage id="grants.financials" />
                    </span>
                  </label>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      <FieldError id={`${id}-error`} error={error} />
    </fieldset>
  );
}
