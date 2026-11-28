import type { ReactNode } from 'react';
import { Button, Menu, MenuItem, MenuTrigger, Popover } from 'react-aria-components';

import { cx } from '@/lib/cx';

import { Icon } from './Icon';

export interface RowAction {
  id: string;
  label: ReactNode;
  /** The words a person types to reach the row by keyboard search. */
  text: string;
  onAction: () => void;
  /** An action that removes or pauses something is drawn in the danger tone. */
  danger?: boolean;
}

interface RowMenuProps {
  /** Names the menu for assistive technology, such as "Actions for Olive & Thyme". */
  label: string;
  actions: readonly RowAction[];
}

/** The actions of one row of a table, behind a button with three dots. */
export function RowMenu({ label, actions }: RowMenuProps) {
  return (
    <MenuTrigger>
      <Button className="c-btn c-btn--ghost c-btn--sm c-btn--icon" aria-label={label}>
        <Icon name="ellipsis" size="sm" />
      </Button>
      <Popover className="c-menu" placement="bottom end">
        <Menu className="a-menu" aria-label={label} onAction={(key) => actions.find((action) => action.id === key)?.onAction()}>
          {actions.map((action) => (
            <MenuItem
              key={action.id}
              id={action.id}
              textValue={action.text}
              className={({ isFocused }) => cx('c-menu__item', action.danger && 'c-menu__item--danger', isFocused && 'is-focused')}
            >
              {action.label}
            </MenuItem>
          ))}
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
