import type { ReactNode } from 'react';

import { cx } from '@/lib/cx';

interface SubmitButtonProps {
  /** True while the request is on its way. The form ignores a second submit meanwhile. */
  busy: boolean;
  children: ReactNode;
  tone?: 'primary' | 'secondary' | 'danger';
  size?: 'md' | 'lg';
  block?: boolean;
}

export function SubmitButton({ busy, children, tone = 'primary', size = 'lg', block = true }: SubmitButtonProps) {
  return (
    <button
      type="submit"
      className={cx('c-btn', `c-btn--${tone}`, size === 'lg' && 'c-btn--lg', block && 'c-btn--block', busy && 'is-loading')}
      aria-busy={busy || undefined}
    >
      {busy ? <span className="c-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}
