// Shortcut hints follow the OS: ⌘ on the Mac, Ctrl+ on Windows / Linux (the handlers take metaKey || ctrlKey).
import { describe, expect, it } from 'vitest';
import { keyHint } from '../../src/renderer/src/lib/keys';

describe('keyHint', () => {
  it('keeps the Mac glyphs on the Mac', () => {
    expect(keyHint('⌘↵', true)).toBe('⌘↵');
    expect(keyHint('⇧⌘Z', true)).toBe('⇧⌘Z');
  });

  it('spells Ctrl+ elsewhere', () => {
    expect(keyHint('⌘K', false)).toBe('Ctrl+K');
    expect(keyHint('⌘↵', false)).toBe('Ctrl+Enter');
    expect(keyHint('⇧⌘Z', false)).toBe('Ctrl+Shift+Z');
    expect(keyHint('⌘[ · ⌘]', false)).toBe('Ctrl+[ · Ctrl+]');
    expect(keyHint('⌘1 – ⌘4', false)).toBe('Ctrl+1 – Ctrl+4');
  });
});
