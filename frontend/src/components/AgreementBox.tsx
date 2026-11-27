import { Link } from '@tanstack/react-router';
import type { ReactNode, Ref } from 'react';
import { FormattedMessage } from 'react-intl';

import type { MessageId } from '@/i18n';

import { FieldError } from './Field';

interface AgreementBoxProps {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  error?: MessageId | null;
  ref?: Ref<HTMLInputElement>;
}

// The texts open beside the form, so nothing typed is lost.
function LegalLink({ to, children }: { to: '/terms' | '/privacy'; children: ReactNode }) {
  return (
    <Link to={to} target="_blank" rel="noopener">
      {children}
      <span className="u-sr">
        {' '}
        <FormattedMessage id="common.newTab" />
      </span>
    </Link>
  );
}

/**
 * The box a person ticks to agree to the terms. It starts empty and is never ticked for them.
 * The page sends the versions of GET /auth/agreements with the request, and the API records them
 * (017-A).
 */
export function AgreementBox({ id, checked, onChange, error, ref }: AgreementBoxProps) {
  return (
    <div className="c-field">
      <label className="c-choice c-choice--multiline">
        <input
          ref={ref}
          className="c-check"
          type="checkbox"
          id={id}
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          required
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
        />
        <span>
          <FormattedMessage
            id="agreement.label"
            values={{
              terms: (text) => <LegalLink to="/terms">{text}</LegalLink>,
              privacy: (text) => <LegalLink to="/privacy">{text}</LegalLink>,
            }}
          />
        </span>
      </label>
      <FieldError id={`${id}-error`} error={error} />
    </div>
  );
}
