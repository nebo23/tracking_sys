import type { ReactNode } from 'react';

/**
 * A wide table that scrolls sideways on a narrow screen. The box takes the keyboard focus, so a
 * person without a pointer can scroll it too, and it is named for assistive technology.
 */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    // A scrollable region must be reachable from the keyboard (WCAG 2.1.1).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="c-table-wrap" tabIndex={0} role="region" aria-label={label}>
      {children}
    </div>
  );
}
