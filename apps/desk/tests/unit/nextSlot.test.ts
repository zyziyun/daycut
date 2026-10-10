import { describe, expect, it } from 'vitest';
import { nextFreeDay } from '../../src/renderer/src/lib/nextSlot';

const now = new Date(2026, 9, 10, 15, 0); // Sat 10 Oct 2026, 15:00

describe('nextFreeDay', () => {
  it('today when it is free and every time is still ahead', () => {
    expect(nextFreeDay([], now, ['19:00', '18:00'])).toBe('2026-10-10');
  });
  it('tomorrow when a time today has passed (or is under half an hour away)', () => {
    expect(nextFreeDay([], now, ['19:00', '09:00'])).toBe('2026-10-11');
    expect(nextFreeDay([], now, ['15:20'])).toBe('2026-10-11');
  });
  it('skips days that already have a post; switched-off rows do not count', () => {
    const posts = [{ at: '2026-10-10T19:00' }, { at: '2026-10-11T12:00' }, { at: '2026-10-12T12:00', enabled: false }];
    expect(nextFreeDay(posts, now, ['19:00'])).toBe('2026-10-12');
  });
});
