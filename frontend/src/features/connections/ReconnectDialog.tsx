import { useMutation, useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { clientQuery } from '@/api/clients';
import { reconnect, type Connection } from '@/api/connections';
import { describeError, type ErrorMessage } from '@/api/errors';
import { Checkbox } from '@/components/Choice';
import { FieldError } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';

import { connectionErrors } from './errors';
import { leaveForProvider } from './leaveForProvider';
import { providerOf } from './providers';

interface ReconnectDialogProps {
  agencyId: string;
  clientId: string;
  connection: Connection;
  providerName: string;
  onClose: () => void;
}

/**
 * Reconnecting an account whose provider needs the holder's approval asks for that approval
 * again, as the first connection did (specification 011, D13).
 */
export function ReconnectDialog({ agencyId, clientId, connection, providerName, onClose }: ReconnectDialogProps) {
  const client = useQuery(clientQuery(agencyId, clientId));
  const disclosure = providerOf(connection.provider)?.approval ?? null;
  const [approved, setApproved] = useState(false);
  const [missing, setMissing] = useState(false);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const boxRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: () => reconnect(agencyId, clientId, connection.id, disclosure ? { approved: true, disclosure } : null),
    onSuccess: ({ authorization_url: address }) => setProblem(leaveForProvider(address, { agencyId, clientId })),
    onError: (failure) => setProblem(describeError(failure, connectionErrors)),
  });

  const submit = () => {
    setProblem(null);
    setMissing(!approved);
    if (!approved) boxRef.current?.focus();
    else request.mutate();
  };

  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="connections.reconnect.title" values={{ provider: providerName }} />}
      submitLabel={<FormattedMessage id="connections.connect.submit" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <p className="u-secondary">
        <FormattedMessage id="connections.reconnect.lead" />
      </p>
      <ErrorNotice message={problem} />
      <div className="c-field">
        <Checkbox
          id="reconnect-approval"
          checked={approved}
          onChange={setApproved}
          inputRef={boxRef}
          invalid={missing && !approved}
          describedBy={missing && !approved ? 'reconnect-approval-error' : undefined}
        >
          <FormattedMessage id="connections.connect.approval" values={{ client: client.data?.name ?? '' }} />
        </Checkbox>
        <FieldError id="reconnect-approval-error" error={missing && !approved ? 'connections.connect.approvalError' : null} />
      </div>
    </FormDialog>
  );
}
