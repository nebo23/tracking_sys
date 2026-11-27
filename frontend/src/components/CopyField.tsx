import { useRef, useState, type ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { cx } from '@/lib/cx';

import { Icon } from './Icon';

interface CopyFieldProps {
  id: string;
  label: ReactNode;
  value: string;
  hint?: ReactNode;
  /** Several lines, such as the code a website installs. */
  multiline?: boolean;
}

/** Copies text to the clipboard. Returns false when the browser refuses; the text is then selected for a manual copy. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * A value to copy into another system: an address, a key or a piece of code. It is read-only,
 * always left to right, and selected as a whole when it receives focus.
 */
export function CopyField({ id, label, value, hint, multiline = false }: CopyFieldProps) {
  const intl = useIntl();
  const [copied, setCopied] = useState(false);
  const field = useRef<HTMLInputElement & HTMLTextAreaElement>(null);

  const copy = async () => {
    field.current?.select();
    setCopied(await copyText(value));
  };

  const common = {
    id,
    ref: field,
    dir: 'ltr' as const,
    readOnly: true,
    spellCheck: false,
    autoComplete: 'off',
    value,
    onFocus: (event: { target: HTMLInputElement | HTMLTextAreaElement }) => event.target.select(),
    'aria-describedby': hint ? `${id}-hint` : undefined,
  };

  return (
    <div className="c-field">
      <label className="c-field__label" htmlFor={id} id={`${id}-label`}>
        {label}
      </label>
      <div className={cx('l-cluster a-copy', multiline && 'a-copy--block')}>
        {multiline ? (
          <textarea {...common} className="c-textarea u-mono u-grow a-code" rows={Math.min(12, value.split('\n').length + 1)} />
        ) : (
          <input {...common} className="c-input u-mono u-grow" />
        )}
        {/* Named "Copy" and the field's label, so that two copy buttons on a page are told apart. */}
        <button type="button" className="c-btn c-btn--secondary" aria-labelledby={`${id}-copy ${id}-label`} onClick={() => void copy()}>
          <Icon name="copy" size="sm" />
          <span id={`${id}-copy`}>
            <FormattedMessage id="common.copy" />
          </span>
        </button>
      </div>
      {hint ? (
        <p className="c-field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      <p className="c-field__hint" role="status">
        {copied ? intl.formatMessage({ id: 'common.copied' }) : null}
      </p>
    </div>
  );
}
