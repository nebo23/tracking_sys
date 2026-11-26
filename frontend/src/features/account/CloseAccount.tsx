import { useMutation } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Button, Dialog, DialogTrigger, Heading, Modal, ModalOverlay } from 'react-aria-components';
import { FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { closeAccount } from '@/api/session';
import { useEndSession } from '@/app/sessionLifecycle';
import { PasswordField } from '@/components/Field';
import { ErrorNotice } from '@/components/Notice';
import { SubmitButton } from '@/components/SubmitButton';
import { PASSWORD_MAX } from '@/lib/validation';

/**
 * Closing an account cannot be undone, so it is asked twice: the button opens a dialog that says
 * what happens and asks for the password. An account without a password leaves the field empty
 * and needs a Google sign-in from the last ten minutes; the API decides.
 */
export function CloseAccount() {
  const end = useEndSession();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [problem, setProblem] = useState<ErrorMessage | null>(null);

  const request = useMutation({
    mutationFn: () => closeAccount(password),
    onSuccess: () => end('closed'),
    onError(error) {
      setProblem(
        describeError(error, {
          invalid_credentials: 'account.close.error.password',
          state_conflict: 'account.close.error.lastOwner',
        }),
      );
    },
  });

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    setPassword('');
    setProblem(null);
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (request.isPending) return;
    setProblem(null);
    request.mutate();
  };

  return (
    <DialogTrigger isOpen={open} onOpenChange={onOpenChange}>
      <Button className="c-btn c-btn--danger-quiet">
        <FormattedMessage id="account.close.open" />
      </Button>
      <ModalOverlay className="c-scrim a-overlay" isDismissable>
        <Modal className="a-modal">
          <Dialog className="c-dialog" role="alertdialog">
            <form className="a-contents" noValidate onSubmit={onSubmit}>
              <div className="c-dialog__header">
                <Heading slot="title" className="c-dialog__title">
                  <FormattedMessage id="account.close.dialog.title" />
                </Heading>
              </div>
              <div className="c-dialog__body">
                <p>
                  <FormattedMessage id="account.close.dialog.text" />
                </p>
                <ErrorNotice message={problem} />
                <PasswordField
                  id="close-password"
                  size="md"
                  label={<FormattedMessage id="common.password" />}
                  autoComplete="current-password"
                  maxLength={PASSWORD_MAX}
                  value={password}
                  onChange={setPassword}
                  hint={<FormattedMessage id="account.close.dialog.passwordHint" />}
                />
              </div>
              <div className="c-dialog__footer">
                <Button className="c-btn c-btn--secondary" onPress={() => onOpenChange(false)}>
                  <FormattedMessage id="common.cancel" />
                </Button>
                <SubmitButton tone="danger" size="md" block={false} busy={request.isPending}>
                  <FormattedMessage id="account.close.dialog.confirm" />
                </SubmitButton>
              </div>
            </form>
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}
