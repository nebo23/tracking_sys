import type { ReactNode } from 'react';

import { cx } from '@/lib/cx';

import { Icon, type IconName } from './Icon';

export type BadgeTone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'info' | 'plain';

interface BadgeProps {
  tone?: BadgeTone;
  /** A state is carried by an icon and a word, never by color alone. */
  icon?: IconName;
  children: ReactNode;
}

export function Badge({ tone = 'neutral', icon, children }: BadgeProps) {
  return (
    <span className={cx('c-badge', tone !== 'neutral' && `c-badge--${tone}`)}>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </span>
  );
}
