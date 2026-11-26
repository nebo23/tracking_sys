import type { ReactNode, Ref } from 'react';
import { Button, Label, ListBox, ListBoxItem, Popover, Select, SelectValue, type Key } from 'react-aria-components';

import { cx } from '@/lib/cx';

import { Icon } from './Icon';

interface CheckboxProps {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
  describedBy?: string;
  /** True when a rule needs the box ticked and it is not. */
  invalid?: boolean;
  inputRef?: Ref<HTMLInputElement>;
}

/** A tick box with its label. The label is part of the target. */
export function Checkbox({ id, checked, onChange, children, disabled = false, describedBy, invalid = false, inputRef }: CheckboxProps) {
  return (
    <label className="c-choice c-choice--multiline" htmlFor={id}>
      <input
        id={id}
        ref={inputRef}
        className="c-check"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{children}</span>
    </label>
  );
}

export interface Option<Value extends string> {
  value: Value;
  label: string;
  /** A second line that says what the choice means. */
  hint?: string;
}

interface SelectFieldProps<Value extends string> {
  label: ReactNode;
  value: Value;
  onChange: (value: Value) => void;
  options: ReadonlyArray<Option<Value>>;
  hint?: ReactNode;
}

/** One choice out of a short list, opened from a button. */
export function SelectField<Value extends string>({ label, value, onChange, options, hint }: SelectFieldProps<Value>) {
  const choose = (key: Key | null) => {
    const chosen = options.find((option) => option.value === key);
    if (chosen) onChange(chosen.value);
  };
  return (
    <Select className="c-field" selectedKey={value} onSelectionChange={choose}>
      <Label className="c-field__label">{label}</Label>
      <Button className="c-select">
        {/* The button names the choice; what the choice means is said in the list and under the field. */}
        <SelectValue>{({ selectedText }) => selectedText}</SelectValue>
        <Icon name="chevron-down" size="sm" />
      </Button>
      {hint ? <p className="c-field__hint">{hint}</p> : null}
      <Popover className="c-menu a-menu--select">
        <ListBox className="a-menu">
          {options.map((option) => (
            <ListBoxItem
              key={option.value}
              id={option.value}
              textValue={option.label}
              className={({ isSelected, isFocused }) => cx('c-menu__item', isSelected && 'is-selected', isFocused && 'is-focused')}
            >
              {({ isSelected }) => (
                <>
                  <span className="u-grow">
                    <span className="a-option__label">{option.label}</span>
                    {option.hint ? <span className="a-option__hint">{option.hint}</span> : null}
                  </span>
                  {isSelected ? <Icon name="check" size="sm" /> : null}
                </>
              )}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </Select>
  );
}
