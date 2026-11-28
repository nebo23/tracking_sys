interface Focusable {
  focus: () => void;
}

/**
 * Moves focus to the first control whose rule failed, so the person lands on what to correct.
 * Returns true when a rule failed.
 */
export function focusFirstInvalid(...checks: Array<[error: unknown, control: { current: Focusable | null }]>): boolean {
  for (const [error, control] of checks) {
    if (error) {
      control.current?.focus();
      return true;
    }
  }
  return false;
}
