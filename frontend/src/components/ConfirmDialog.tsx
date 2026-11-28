import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import type { MessageId } from '@/i18n';

import { FormDialog } from './FormDialog';
import { ErrorNotice } from './Notice';

interface ConfirmDialogProps {
  title: MessageId;
  /** Arguments of the title, such as the name of what is changed. */
  values?: Record<string, string>;
  text: MessageId;
  submit: MessageId;
  keep: MessageId;
  /** An action that stops something is drawn in the danger tone. */
  danger?: boolean;
  onConfirm: () => Promise<unknown>;
  onClose: () => void;
  /** Sentences that replace the general ones for the codes this action can meet. */
  errors?: Partial<Record<string, MessageId>>;
}

/** Asks before an action that changes what others rely on, and says what follows from it. */
export function ConfirmDialog({
  title,
  values,
  text,
  submit,
  keep,
  danger = false,
  onConfirm,
  onClose,
  errors = {},
}: ConfirmDialogProps) {
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({ mutationFn: onConfirm, onError: (failure) => setProblem(describeError(failure, errors)) });
  return (
    <FormDialog
      isOpen
      alert
      tone={danger ? 'danger' : 'primary'}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id={title} values={values} />}
      submitLabel={<FormattedMessage id={submit} />}
      cancelLabel={<FormattedMessage id={keep} />}
      busy={request.isPending}
      onSubmit={() => {
        setProblem(null);
        request.mutate();
      }}
    >
      <p>
        <FormattedMessage id={text} />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}
