import type { ReactNode } from 'react';
import { FormattedMessage } from 'react-intl';

import { CopyField } from './CopyField';
import { FormDialog } from './FormDialog';
import { Notice } from './Notice';

export interface ShownValue {
  id: string;
  label: ReactNode;
  value: string;
  hint?: ReactNode;
  multiline?: boolean;
}

interface ShownOnceDialogProps {
  title: ReactNode;
  /** Says that the value is shown this once, and what to do with it. */
  notice: ReactNode;
  values: readonly ShownValue[];
  children?: ReactNode;
  onClose: () => void;
}

/**
 * Shows what the API returns once, such as a signing secret or the value of a DNS record. The
 * values live in this component's memory while the dialog is open and nowhere else: not in the
 * query cache, not in storage and not in the address.
 */
export function ShownOnceDialog({ title, notice, values, children, onClose }: ShownOnceDialogProps) {
  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      cancelLabel={<FormattedMessage id="common.shownOnce.done" />}
    >
      <Notice tone="warning" quiet>
        {notice}
      </Notice>
      {values.map((item) => (
        <CopyField key={item.id} id={item.id} label={item.label} value={item.value} hint={item.hint} multiline={item.multiline} />
      ))}
      {children}
    </FormDialog>
  );
}
