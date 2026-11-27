import { useState, type InputHTMLAttributes, type ReactNode, type Ref } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import type { MessageId } from '@/i18n';
import { cx } from '@/lib/cx';

import { Icon } from './Icon';

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'value' | 'onChange' | 'size' | 'className'> {
  id: string;
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  /** The message of the rule the value breaks, shown under the control. */
  error?: MessageId | null;
  hint?: ReactNode;
  size?: 'md' | 'lg';
  /** Content under the control, such as a help link. */
  below?: ReactNode;
  ref?: Ref<HTMLInputElement>;
}

function describedBy(id: string, hint: ReactNode, error: MessageId | null | undefined): string | undefined {
  return [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') || undefined;
}

export function FieldError({ id, error }: { id: string; error?: MessageId | null }) {
  if (!error) return null;
  return (
    <p className="c-field__error" id={id}>
      <Icon name="circle-alert" size="xs" />
      <FormattedMessage id={error} />
    </p>
  );
}

export function Field({ id, label, value, onChange, error, hint, size = 'lg', below, ref, ...input }: FieldProps) {
  return (
    <div className="c-field">
      <label className="c-field__label" htmlFor={id}>
        {label}
      </label>
      <input
        {...input}
        ref={ref}
        id={id}
        className={cx('c-input', size === 'lg' && 'c-input--lg', error && 'is-invalid')}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
      />
      {hint ? (
        <p className="c-field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      <FieldError id={`${id}-error`} error={error} />
      {below}
    </div>
  );
}

/** A password field with a control that shows what was typed. */
export function PasswordField({ id, label, value, onChange, error, hint, size = 'lg', below, ref, ...input }: FieldProps) {
  const intl = useIntl();
  const [shown, setShown] = useState(false);
  return (
    <div className="c-field">
      <label className="c-field__label" htmlFor={id}>
        {label}
      </label>
      <span className="c-input-wrap a-password">
        <input
          {...input}
          ref={ref}
          id={id}
          type={shown ? 'text' : 'password'}
          className={cx('c-input', size === 'lg' && 'c-input--lg', error && 'is-invalid')}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(id, hint, error)}
        />
        <button
          type="button"
          className="c-btn c-btn--ghost c-btn--sm c-btn--icon a-password__toggle"
          aria-label={intl.formatMessage({ id: shown ? 'common.hidePassword' : 'common.showPassword' })}
          onClick={() => setShown((current) => !current)}
        >
          <Icon name={shown ? 'eye-off' : 'eye'} size="sm" />
        </button>
      </span>
      {hint ? (
        <p className="c-field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      <FieldError id={`${id}-error`} error={error} />
      {below}
    </div>
  );
}
