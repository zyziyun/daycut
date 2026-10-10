// Shortcut hints for this OS. Hints are written the Mac way (⌘K, ⇧⌘Z, ⌘↵) and shown as Ctrl+K, Ctrl+Shift+Z,
// Ctrl+Enter on Windows / Linux; the key handlers already take metaKey || ctrlKey.

function detectMac(): boolean {
  if (typeof navigator === 'undefined') return true;
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  return /mac|iphone|ipad/i.test(nav.userAgentData?.platform || nav.platform || nav.userAgent || '');
}

export const IS_MAC = detectMac();

/** '⌘K' -> 'Ctrl+K', '⇧⌘Z' -> 'Ctrl+Shift+Z', '⌘↵' -> 'Ctrl+Enter' off the Mac; unchanged on the Mac. */
export function keyHint(mac: string, isMac = IS_MAC): string {
  if (isMac) return mac;
  return mac
    .replace(/⇧⌘/g, 'Ctrl+Shift+')
    .replace(/⌘/g, 'Ctrl+')
    .replace(/↵/g, 'Enter');
}
