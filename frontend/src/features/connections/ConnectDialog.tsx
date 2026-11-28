import { useMutation } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { connect, type ConnectInput } from '@/api/connections';
import { describeError, type ErrorMessage } from '@/api/errors';
import { Badge } from '@/components/Badge';
import { Checkbox } from '@/components/Choice';
import { Field, FieldError } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { connectionErrors } from './errors';
import { leaveForProvider } from './leaveForProvider';
import { ProviderMark } from './ProviderMark';
import type { ConnectionPlace } from './pendingConnection';
import { connectable, type Provider } from './providers';

interface ConnectDialogProps {
  agencyId: string;
  clientId: string;
  clientName: string;
  onClose: () => void;
  /** The providers to choose from: the accounts of a client, or the datasets of its conversions. */
  providers?: readonly Provider[];
  /** The page the return from the provider leads back to. */
  place?: ConnectionPlace;
}

/**
 * Chooses the account to connect and asks for what its provider needs before the person is
 * sent there: the number of an ad account, or the account holder's approval of the agency and
 * the client's members as their agents. It is drawn only while open.
 */
export function ConnectDialog({ agencyId, clientId, clientName, onClose, providers = connectable, place = 'connections' }: ConnectDialogProps) {
  const [provider, setProvider] = useState<Provider | undefined>(providers[0]);
  const [account, setAccount] = useState('');
  const [approved, setApproved] = useState(false);
  const [errors, setErrors] = useState<{ account?: MessageId | null; approval?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const accountRef = useRef<HTMLInputElement>(null);
  const approvalRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: (input: ConnectInput) => connect(agencyId, clientId, input),
    onSuccess: ({ authorization_url: address }) =>
      setProblem(leaveForProvider(address, place === 'integrations' ? { agencyId, clientId, place } : { agencyId, clientId })),
    onError: (failure) => setProblem(describeError(failure, connectionErrors)),
  });

  const choose = (next: Provider) => {
    setProvider(next);
    setErrors({});
    setProblem(null);
  };

  const submit = () => {
    if (!provider) return;
    const number = account.trim();
    const found = {
      account: provider.account && !provider.account.pattern.test(number) ? provider.account.error : null,
      approval: provider.approval !== null && !approved ? ('connections.connect.approvalError' as const) : null,
    };
    setErrors(found);
    setProblem(null);
    if (focusFirstInvalid([found.account, accountRef], [found.approval, approvalRef])) return;
    request.mutate({
      provider: provider.id,
      ...(provider.account ? { account: number } : {}),
      ...(provider.approval !== null ? { agent_approval: { approved: true, disclosure: provider.approval } } : {}),
    });
  };

  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="connections.connect.title" />}
      submitLabel={<FormattedMessage id="connections.connect.submit" />}
      busy={request.isPending}
      onSubmit={submit}
      wide
    >
      <p className="u-secondary">
        {/* A dataset receives what Connect sends; it is not read. */}
        <FormattedMessage id={place === 'integrations' ? 'connections.connect.leadDataset' : 'connections.connect.lead'} values={{ client: clientName }} />
      </p>
      <ErrorNotice message={problem} />
      <fieldset className="a-fieldset">
        <legend className="c-field__label">
          <FormattedMessage id="connections.connect.provider" />
        </legend>
        <div className="l-stack l-stack--tight">
          {providers.map((option) => (
            <label key={option.id} className="c-choice a-choice--card">
              <input
                className="c-radio"
                type="radio"
                name="connect-provider"
                value={option.id}
                checked={option.id === provider?.id}
                onChange={() => choose(option)}
              />
              <ProviderMark provider={option.id} />
              <span className="u-strong">
                <FormattedMessage id={option.name} />
              </span>
              {option.synthetic ? (
                <Badge>
                  <FormattedMessage id="provider.synthetic.badge" />
                </Badge>
              ) : null}
              <span className="u-secondary a-choice__more">
                <FormattedMessage id={option.reads} />
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {provider?.account ? (
        <Field
          id="connect-account"
          ref={accountRef}
          size="md"
          label={<FormattedMessage id={provider.account.label} />}
          hint={<FormattedMessage id={provider.account.hint} />}
          inputMode="numeric"
          autoComplete="off"
          dir="ltr"
          maxLength={32}
          required
          value={account}
          onChange={setAccount}
          error={errors.account}
        />
      ) : null}

      {provider && provider.approval !== null ? (
        <div className="c-field">
          <Checkbox
            id="connect-approval"
            checked={approved}
            onChange={setApproved}
            describedBy={errors.approval ? 'connect-approval-error' : undefined}
            inputRef={approvalRef}
            invalid={Boolean(errors.approval)}
          >
            <FormattedMessage id="connections.connect.approval" values={{ client: clientName }} />
          </Checkbox>
          <FieldError id="connect-approval-error" error={errors.approval} />
        </div>
      ) : null}
    </FormDialog>
  );
}
