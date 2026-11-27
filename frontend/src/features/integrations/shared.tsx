import { useMutation } from '@tanstack/react-query';
import { useRef, useState, type ReactNode } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { apiOrigin } from '@/app/config';
import { Badge } from '@/components/Badge';
import { Field, PasswordField } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon, type IconName } from '@/components/Icon';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

// What the cards of the integrations page share: the address a provider calls, the state of a
// source, the dialogs that rename a source or take a secret, and the rules of those values.

/** The address a provider sends its callbacks to: the API's own origin and the source's path. */
export const callbackAddress = (path: string): string => `${apiOrigin}${path}`;

export const NAME_MAX = 200;
/** A secret a person types: 16 to 256 printable characters without spaces (Paymob HMAC, Cal.com). */
export const SECRET = /^[!-~]{16,256}$/;

export function secretError(value: string): MessageId | null {
  if (value === '') return 'field.error.required';
  return SECRET.test(value) ? null : 'integrations.rule.secret';
}

export function nameError(value: string): MessageId | null {
  const name = value.trim();
  if (name === '') return 'field.error.required';
  return name.length > NAME_MAX ? 'links.rule.labelLong' : null;
}

export function OnOff({ on, onWord = 'integrations.state.on', offWord = 'integrations.state.off' }: { on: boolean; onWord?: MessageId; offWord?: MessageId }) {
  return on ? (
    <Badge tone="success" icon="circle-check">
      <FormattedMessage id={onWord} />
    </Badge>
  ) : (
    <Badge icon="circle-pause">
      <FormattedMessage id={offWord} />
    </Badge>
  );
}

interface CardProps {
  id: string;
  icon?: IconName;
  glyph?: 'caldotcom' | 'whatsapp' | 'meta';
  title: ReactNode;
  lead: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

/** A card of the page with the mark of its provider, its title, what it does and its main action. */
export function IntegrationCard({ id, icon, glyph, title, lead, action, children, footer }: CardProps) {
  return (
    <section className="c-card" aria-labelledby={id}>
      <div className="c-card__header">
        <div className="l-cluster a-person">
          <span className="c-avatar c-avatar--lg c-avatar--provider" aria-hidden="true">
            {glyph ? <span className={`c-glyph c-glyph--${glyph}`} /> : <Icon name={icon ?? 'blocks'} size="md" />}
          </span>
          <div>
            <h2 className="c-card__title" id={id}>
              {title}
            </h2>
            <p className="c-card__subtitle">{lead}</p>
          </div>
        </div>
        {action}
      </div>
      <div className="c-card__body c-card__body--flush">{children}</div>
      {footer ? <div className="c-card__footer">{footer}</div> : null}
    </section>
  );
}

/** A row of figures, such as the totals of bookings. A total the API did not give is never drawn as zero. */
export function Figures({ items }: { items: ReadonlyArray<{ key: string; label: MessageId; value: number | undefined }> }) {
  return (
    <dl className="a-figures">
      {items.map((item) => (
        <div key={item.key} className="a-figures__item">
          <dt>
            <FormattedMessage id={item.label} />
          </dt>
          <dd className="u-num">{item.value === undefined ? <span aria-hidden="true">—</span> : item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface NameDialogProps {
  title: ReactNode;
  initial: string;
  onSave: (name: string) => Promise<unknown>;
  onClose: () => void;
}

/** Renames a source or a number. */
export function NameDialog({ title, initial, onSave, onClose }: NameDialogProps) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const request = useMutation({ mutationFn: () => onSave(name.trim()), onSuccess: onClose, onError: (failure) => setProblem(describeError(failure)) });
  const submit = () => {
    const found = nameError(name);
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, field])) request.mutate();
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      submitLabel={<FormattedMessage id="common.save" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="rename-name"
        ref={field}
        size="md"
        autoComplete="off"
        maxLength={NAME_MAX}
        label={<FormattedMessage id="integrations.name" />}
        // The dialog was opened to change this name.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        required
        value={name}
        onChange={setName}
        error={error}
      />
    </FormDialog>
  );
}

interface SecretDialogProps {
  title: ReactNode;
  label: MessageId;
  hint: MessageId;
  text?: ReactNode;
  onSave: (secret: string) => Promise<unknown>;
  onClose: () => void;
}

/** Takes a secret the client set at its provider. It is sent once and never shown again. */
export function SecretDialog({ title, label, hint, text, onSave, onClose }: SecretDialogProps) {
  const [secret, setSecret] = useState('');
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const request = useMutation({ mutationFn: () => onSave(secret), onSuccess: onClose, onError: (failure) => setProblem(describeError(failure)) });
  const submit = () => {
    const found = secretError(secret);
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, field])) request.mutate();
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      submitLabel={<FormattedMessage id="integrations.secret.save" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      {text ? <p>{text}</p> : null}
      <ErrorNotice message={problem} />
      <PasswordField
        id="secret-value"
        ref={field}
        size="md"
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        maxLength={256}
        label={<FormattedMessage id={label} />}
        hint={<FormattedMessage id={hint} />}
        // The dialog was opened to enter this secret.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        required
        value={secret}
        onChange={setSecret}
        error={error}
      />
    </FormDialog>
  );
}
