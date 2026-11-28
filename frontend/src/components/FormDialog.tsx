import type { FormEvent, ReactNode } from 'react';
import { Button, Dialog, Heading, Modal, ModalOverlay } from 'react-aria-components';
import { FormattedMessage } from 'react-intl';

import { cx } from '@/lib/cx';

import { SubmitButton } from './SubmitButton';

interface FormDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  children: ReactNode;
  /** The label of the action. Without one the dialog only informs and has a single button. */
  submitLabel?: ReactNode;
  tone?: 'primary' | 'danger';
  /** True while the request is on its way. A second submit is ignored meanwhile. */
  busy?: boolean;
  onSubmit?: () => void;
  /** The label of the button that leaves without acting. */
  cancelLabel?: ReactNode;
  /** An action that cannot be undone asks as an alert. */
  alert?: boolean;
  wide?: boolean;
}

/**
 * A dialog over the page that holds one form. Focus stays inside it, Escape and the cancel
 * button leave it, and focus returns to the control that opened it.
 */
export function FormDialog({
  isOpen,
  onOpenChange,
  title,
  children,
  submitLabel,
  tone = 'primary',
  busy = false,
  onSubmit,
  cancelLabel,
  alert = false,
  wide = false,
}: FormDialogProps) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!busy) onSubmit?.();
  };
  return (
    <ModalOverlay className="c-scrim a-overlay" isOpen={isOpen} onOpenChange={onOpenChange} isDismissable>
      <Modal className={cx('a-modal', wide && 'a-modal--wide')}>
        <Dialog className="c-dialog" role={alert ? 'alertdialog' : 'dialog'}>
          <form className="a-contents" noValidate onSubmit={submit}>
            <div className="c-dialog__header">
              <Heading slot="title" className="c-dialog__title">
                {title}
              </Heading>
            </div>
            <div className="c-dialog__body">{children}</div>
            <div className="c-dialog__footer">
              <Button className={cx('c-btn', submitLabel ? 'c-btn--secondary' : 'c-btn--primary')} onPress={() => onOpenChange(false)}>
                {cancelLabel ?? <FormattedMessage id={submitLabel ? 'common.cancel' : 'common.done'} />}
              </Button>
              {submitLabel ? (
                <SubmitButton tone={tone} size="md" block={false} busy={busy}>
                  {submitLabel}
                </SubmitButton>
              ) : null}
            </div>
          </form>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
