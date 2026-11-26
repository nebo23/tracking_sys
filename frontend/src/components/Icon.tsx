import { cx } from '@/lib/cx';

// The icons the application uses, out of the set in docs/design/ui/connect-icons.css.
export type IconName =
  | 'activity'
  | 'ban'
  | 'briefcase-business'
  | 'building-2'
  | 'calendar-clock'
  | 'check'
  | 'chevron-down'
  | 'chevron-right'
  | 'chevrons-up-down'
  | 'circle-alert'
  | 'circle-check'
  | 'circle-dashed'
  | 'circle-dot'
  | 'circle-pause'
  | 'circle-slash'
  | 'clock'
  | 'cloud-off'
  | 'copy'
  | 'ellipsis'
  | 'external-link'
  | 'eye'
  | 'eye-off'
  | 'history'
  | 'hourglass'
  | 'info'
  | 'key-round'
  | 'layout-dashboard'
  | 'loader-circle'
  | 'lock'
  | 'log-out'
  | 'mail'
  | 'pencil'
  | 'play'
  | 'plug'
  | 'plus'
  | 'refresh-cw'
  | 'search'
  | 'settings'
  | 'shield-check'
  | 'timer'
  | 'trash-2'
  | 'triangle-alert'
  | 'unplug'
  | 'user'
  | 'user-plus'
  | 'users'
  | 'x';

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
