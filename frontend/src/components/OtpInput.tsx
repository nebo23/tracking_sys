import { useImperativeHandle, useRef, type KeyboardEvent, type Ref } from 'react';
import { useIntl } from 'react-intl';

import { cx } from '@/lib/cx';
import { CODE_LENGTH } from '@/lib/validation';

export interface OtpHandle {
  /** Moves focus to a cell, counted from zero. */
  focus: (index?: number) => void;
}

interface OtpInputProps {
  /** The digits typed so far, from the first cell on. */
  value: string;
  onChange: (value: string) => void;
  /** The id of the element that names the group. */
  labelledBy: string;
  describedBy?: string;
  invalid?: boolean;
  ref?: Ref<OtpHandle>;
}

const cells = Array.from({ length: CODE_LENGTH }, (_, index) => index);

/**
 * A one-time code in separate cells. A code pasted or filled in by the device lands in all cells;
 * Backspace in an empty cell goes back one cell.
 */
export function OtpInput({ value, onChange, labelledBy, describedBy, invalid = false, ref }: OtpInputProps) {
  const intl = useIntl();
  const inputs = useRef<Array<HTMLInputElement | null>>([]);

  const focusCell = (index: number) => {
    const cell = inputs.current[Math.max(0, Math.min(index, CODE_LENGTH - 1))];
    cell?.focus();
    cell?.select();
  };
  useImperativeHandle(ref, () => ({ focus: (index = 0) => focusCell(index) }), []);

  const write = (index: number, text: string) => {
    const digits = text.replace(/\D/g, '');
    const at = Math.min(index, value.length);
    if (digits === '') {
      onChange(value.slice(0, at) + value.slice(at + 1));
      return;
    }
    onChange((value.slice(0, at) + digits + value.slice(at + digits.length)).slice(0, CODE_LENGTH));
    focusCell(at + digits.length);
  };

  const onKeyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Backspace' && event.currentTarget.value === '' && index > 0) {
      event.preventDefault();
      onChange(value.slice(0, index - 1) + value.slice(index));
      focusCell(index - 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      focusCell(index - 1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      focusCell(index + 1);
    }
  };

  return (
    <div className="c-otp" role="group" aria-labelledby={labelledBy} aria-describedby={describedBy}>
      {cells.map((index) => (
        <input
          key={index}
          ref={(element) => {
            inputs.current[index] = element;
          }}
          className={cx('c-otp__cell', value[index] !== undefined && 'is-filled')}
          value={value[index] ?? ''}
          onChange={(event) => write(index, event.target.value)}
          onKeyDown={(event) => onKeyDown(index, event)}
          onFocus={(event) => event.currentTarget.select()}
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete={index === 0 ? 'one-time-code' : 'off'}
          aria-label={intl.formatMessage({ id: 'verify.digit' }, { position: index + 1 })}
          aria-invalid={invalid || undefined}
        />
      ))}
    </div>
  );
}
