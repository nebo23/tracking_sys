import { useEffect, useState } from 'react';

/**
 * Whole seconds left until a moment, counted against the clock rather than by ticks, so a tab
 * that slept shows the right number when it wakes. Zero once the moment has passed.
 */
export function useSecondsUntil(moment: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (moment <= now) return;
    const timer = window.setTimeout(() => setNow(Date.now()), 1000);
    return () => window.clearTimeout(timer);
  }, [moment, now]);
  return Math.max(0, Math.ceil((moment - now) / 1000));
}
