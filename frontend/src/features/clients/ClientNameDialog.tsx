import { useMutation } from '@tanstack/react-query';
import { useRef, useState, type ReactNode } from 'react';
import { FormattedMessage } from 'react-intl';

import type { Client } from '@/api/clients';
import { describeError, type ErrorMessage } from '@/api/errors';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { NAME_MAX, nameError } from '@/lib/validation';

interface ClientNameDialogProps {
  title: ReactNode;
  submitLabel: ReactNode;
  /** The name the field starts with: empty for a new client, the present name for a rename. */
  initial: string;
  /** Sends the trimmed name to the API. */
  save: (name: string) => Promise<Client>;
  onSaved: (client: Client) => void;
  onClose: () => void;
}

/** Asks for a client's name, to add the client or to rename it. It is drawn only while open. */
export function ClientNameDialog({ title, submitLabel, initial, save, onSaved, onClose }: ClientNameDialogProps) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: () => save(name.trim()),
    onSuccess: onSaved,
    onError: (failure) => setProblem(describeError(failure)),
  });

  const submit = () => {
    const found = nameError(name);
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, nameRef])) request.mutate();
  };

  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      submitLabel={submitLabel}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="client-name"
        ref={nameRef}
        size="md"
        label={<FormattedMessage id="clients.name" />}
        autoComplete="off"
        maxLength={NAME_MAX}
        required
        // The dialog was opened to type this name.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        value={name}
        onChange={setName}
        error={error}
        hint={<FormattedMessage id="clients.nameHint" />}
      />
    </FormDialog>
  );
}
