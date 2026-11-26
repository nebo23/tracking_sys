import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSecondsUntil } from '@/lib/useSecondsUntil';

const start = new Date('2026-11-26T10:00:00Z').getTime();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(start);
});

afterEach(() => {
  vi.useRealTimers();
});

const pass = (milliseconds: number) =>
  act(() => {
    vi.advanceTimersByTime(milliseconds);
  });

describe('the seconds left until a moment', () => {
  it('count down to zero and then stop', () => {
    const { result } = renderHook(() => useSecondsUntil(start + 60_000));
    expect(result.current).toBe(60);
    pass(1000);
    expect(result.current).toBe(59);
    for (let second = 0; second < 58; second += 1) pass(1000);
    expect(result.current).toBe(1);
    pass(1000);
    expect(result.current).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('are zero for a moment that has passed, with no timer running', () => {
    const { result } = renderHook(() => useSecondsUntil(start - 1));
    expect(result.current).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('follow the clock, so a tab that slept shows the right number', () => {
    const { result } = renderHook(() => useSecondsUntil(start + 60_000));
    // The clock moves on by 45 seconds while only one timer fires.
    vi.setSystemTime(start + 44_000);
    pass(1000);
    expect(result.current).toBe(15);
  });

  it('start again when the moment changes', () => {
    const { result, rerender } = renderHook(({ moment }) => useSecondsUntil(moment), { initialProps: { moment: 0 } });
    expect(result.current).toBe(0);
    rerender({ moment: start + 60_000 });
    expect(result.current).toBe(60);
    pass(1000);
    expect(result.current).toBe(59);
  });
});
