import { cx } from '@/lib/cx';

// The icons the application uses, out of the set in docs/design/ui/connect-icons.css.
export type IconName =
  | 'check'
  | 'chevron-right'
  | 'chevrons-up-down'
  | 'circle-alert'
  | 'circle-check'
  | 'circle-pause'
  | 'eye'
  | 'eye-off'
  | 'info'
  | 'layout-dashboard'
  | 'log-out'
  | 'play'
  | 'settings'
  | 'triangle-alert'
  | 'user';

interface IconProps {
  name: IconName;
  size?: 'xs' | 'sm' | 'md' | 'lg';
  /** Turns an icon that points in a direction when the page reads right to left. */
  mirror?: boolean;
  className?: string;
}

/** A decorative icon. The text beside it, or the label of its control, carries the meaning. */
export function Icon({ name, size, mirror = false, className }: IconProps) {
  return (
    <span
      className={cx('c-icon', size && `c-icon--${size}`, `c-icon--${name}`, mirror && 'c-icon--mirror', className)}
      aria-hidden="true"
    />
  );
}
