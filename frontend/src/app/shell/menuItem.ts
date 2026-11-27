import { cx } from '@/lib/cx';

/** The class of a menu row, with the state React Aria reports for it. */
export const menuItem = ({ isSelected }: { isSelected: boolean }): string => cx('c-menu__item', isSelected && 'is-selected');
