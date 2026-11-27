import { cx } from '@/lib/cx';

// The icons the application uses, out of the set in docs/design/ui/connect-icons.css.
export type IconName =
  | 'activity'
  | 'ban'
  | 'blocks'
  | 'briefcase-business'
  | 'building-2'
  | 'calendar'
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
  | 'circle-x'
  | 'clock'
  | 'cloud-off'
  | 'copy'
  | 'credit-card'
  | 'ellipsis'
  | 'external-link'
  | 'eye'
  | 'eye-off'
  | 'file-text'
  | 'globe'
  | 'hash'
  | 'history'
  | 'hourglass'
  | 'info'
  | 'key-round'
  | 'layout-dashboard'
  | 'link'
  | 'list-filter'
  | 'loader-circle'
  | 'lock'
  | 'log-out'
  | 'mail'
  | 'megaphone'
  | 'message-circle'
  | 'minus'
  | 'pencil'
  | 'play'
  | 'plug'
  | 'plus'
  | 'radio-tower'
  | 'refresh-cw'
  | 'rotate-cw'
  | 'scroll-text'
  | 'search'
  | 'send'
  | 'settings'
  | 'shield-check'
  | 'tag'
  | 'timer'
  | 'trash-2'
  | 'triangle-alert'
  | 'unplug'
  | 'user'
  | 'user-plus'
  | 'users'
  | 'webhook'
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
