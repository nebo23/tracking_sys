import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { clientsKey } from '@/api/clients';
import { connectionsKey, disconnect, type Connection } from '@/api/connections';
import { describeError, type ErrorMessage } from '@/api/errors';
import { Checkbox } from '@/components/Choice';
import { FieldError } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';

import { connectionErrors } from './errors';

interface DisconnectDialogProps {
  agencyId: string;
  clientId: string;
  connection: Connection;
  /** The provider and the account, as the person knows them. */
  name: string;
  onClose: () => void;
}

/**
 * Disconnecting stops the reading now and removes what was stored, and it cannot be undone. So
 * it is asked twice: the dialog says what happens, and the person ticks that they understand.
 */
export function DisconnectDialog({ agencyId, clientId, connection, name, onClose }: DisconnectDialogProps) {
  const queryClient = useQueryClient();
  const [understood, setUnderstood] = useState(false);
  const [missing, setMissing] = useState(false);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const boxRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: () => disconnect(agencyId, clientId, connection.id),
    async onSuccess() {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: connectionsKey(agencyId, clientId) }),
        // The list of clients shows the state of each client's connections.
        queryClient.invalidateQueries({ queryKey: clientsKey(agencyId) }),
      ]);
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, connectionErrors)),
  });

  const submit = () => {
    setProblem(null);
    setMissing(!understood);
    if (!understood) boxRef.current?.focus();
    else request.mutate();
  };

  return (
    <FormDialog
      isOpen
      alert
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="connections.disconnect.title" values={{ name }} />}
      submitLabel={<FormattedMessage id="connections.disconnect" />}
      cancelLabel={<FormattedMessage id="connections.disconnect.keep" />}
      tone="danger"
      busy={request.isPending}
      onSubmit={submit}
    >
      <p>
        <FormattedMessage id="connections.disconnect.text" />
      </p>
      <ErrorNotice message={problem} />
      <div className="c-field">
        <Checkbox
          id="disconnect-understood"
          checked={understood}
          onChange={setUnderstood}
          inputRef={boxRef}
          invalid={missing && !understood}
          describedBy={missing && !understood ? 'disconnect-understood-error' : undefined}
        >
          <FormattedMessage id="connections.disconnect.understood" />
        </Checkbox>
        <FieldError id="disconnect-understood-error" error={missing && !understood ? 'connections.disconnect.confirmError' : null} />
      </div>
    </FormDialog>
  );
}
