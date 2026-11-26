import type { ReactNode } from 'react';

import { Icon, type IconName } from './Icon';

interface EmptyStateProps {
  icon: IconName;
  title: ReactNode;
  children: ReactNode;
  /** What the person can do about it. */
  action?: ReactNode;
  /** The heading level under which the state appears. */
  level?: 2 | 3;
}

/** Says that a list or a page has nothing to show yet, why, and what to do next. */
export function EmptyState({ icon, title, children, action, level = 2 }: EmptyStateProps) {
  const Heading = level === 2 ? 'h2' : 'h3';
  return (
    <div className="c-empty">
      <span className="c-empty__icon">
        <Icon name={icon} size="lg" />
      </span>
      <Heading className="c-empty__title">{title}</Heading>
      <p className="c-empty__text">{children}</p>
      {action ? <div className="l-cluster">{action}</div> : null}
    </div>
  );
}
