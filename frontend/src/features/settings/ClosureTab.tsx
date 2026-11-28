import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { useRef, useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { agenciesKey } from '@/api/agencies';
import { requestClosure } from '@/api/agencySettings';
import { describeError, type ErrorMessage } from '@/api/errors';
import { Field, PasswordField } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import type { MessageId } from '@/i18n';

// The refusals of a closure request, each in words (017-A, section 5.2 of its design).
export const closureErrors = {
  confirmation_mismatch: 'settings.closure.error.confirmation_mismatch',
  invalid_credentials: 'settings.closure.error.invalid_credentials',
  reauthentication_required: 'settings.closure.error.reauthentication_required',
  closure_in_progress: 'settings.closure.error.closure_in_progress',
  access_denied: 'settings.closure.error.access_denied',
} as const satisfies Record<string, MessageId>;

/**
 * Closing the agency (B14): for Owners only. A closure starts a grace period of 30 days in which an
 * Owner can keep the agency; after it the agency is closed for good.
 */
export function ClosureTab({ agencyId, agencyName }: { agencyId: string; agencyName: string }) {
  const [asking, setAsking] = useState(false);
  return (
    <article className="c-card">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title">
            <FormattedMessage id="settings.closure.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="settings.closure.owners" />
          </p>
        </div>
      </div>
      <div className="c-card__body l-stack">
        <p>
          <FormattedMessage id="settings.closure.lead" values={{ agency: agencyName }} />
        </p>
        <p className="u-secondary">
          <FormattedMessage id="settings.closure.final" />
        </p>
        <div>
          <button type="button" className="c-btn c-btn--danger" onClick={() => setAsking(true)}>
            <FormattedMessage id="settings.closure.open" values={{ agency: agencyName }} />
          </button>
        </div>
      </div>
      {asking ? <ClosureDialog agencyId={agencyId} agencyName={agencyName} onClose={() => setAsking(false)} /> : null}
    </article>
  );
}

function ClosureDialog({ agencyId, agencyName, onClose }: { agencyId: string; agencyName: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [nameError, setNameError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () => requestClosure(agencyId, name, password),
    onSuccess: async () => {
      // The agency is closing now: it is listed as such, and only its closing page opens.
      await queryClient.invalidateQueries({ queryKey: agenciesKey });
      await navigate({ to: '/agencies/$agencyId/closing', params: { agencyId } });
    },
    onError: (error) => setProblem(describeError(error, closureErrors)),
  });
  const submit = () => {
    if (request.isPending) return;
    // The name must be exactly the agency's, as the API compares it.
    const found = name === agencyName ? null : ('settings.closure.error.confirmation_mismatch' as MessageId);
    setNameError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, nameRef])) request.mutate();
  };
  return (
    <FormDialog
      isOpen
      alert
      tone="danger"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="settings.closure.dialog.title" values={{ agency: agencyName }} />}
      submitLabel={<FormattedMessage id="settings.closure.dialog.submit" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <p>
        <FormattedMessage id="settings.closure.dialog.text" />
      </p>
      <ErrorNotice message={problem} />
      <Field
        id="closure-name"
        ref={nameRef}
        size="md"
        label={<FormattedMessage id="settings.closure.dialog.name" />}
        hint={<FormattedMessage id="settings.closure.dialog.nameHint" values={{ agency: agencyName }} />}
        value={name}
        onChange={setName}
        autoComplete="off"
        error={nameError}
      />
      <PasswordField
        id="closure-password"
        size="md"
        label={<FormattedMessage id="settings.closure.dialog.password" />}
        hint={<FormattedMessage id="settings.closure.dialog.passwordHint" />}
        autoComplete="current-password"
        value={password}
        onChange={setPassword}
      />
    </FormDialog>
  );
}
