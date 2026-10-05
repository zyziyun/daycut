// vsmedia:// - read-only access for the UI to contact sheets, previews and exports inside known batch folders.
// URL form: vsmedia://local/<encodeURIComponent(absolute path)>. Anything outside the engine's roots
// (batch folders, package folders, source folders) or with a non-media extension is refused.
import path from 'node:path';

export const MEDIA_EXT = new Set(['.mp4', '.mov', '.m4v', '.webm', '.jpg', '.jpeg', '.png', '.webp', '.gif']);

export function mediaUrl(p: string): string {
  return `vsmedia://local/${encodeURIComponent(p)}`;
}

export function pathFromMediaUrl(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.protocol !== 'vsmedia:' || u.hostname !== 'local') return null;
    const p = decodeURIComponent(u.pathname.replace(/^\//, ''));
    return p || null;
  } catch {
    return null;
  }
}

export function isAllowedMediaPath(p: string, roots: string[], pathImpl: typeof path = path): boolean {
  if (!p || p.includes('\0') || !pathImpl.isAbsolute(p)) return false;
  if (p.split(/[\\/]/).includes('..')) return false;
  const norm = pathImpl.normalize(p);
  if (!MEDIA_EXT.has(pathImpl.extname(norm).toLowerCase())) return false;
  return roots.some((r) => {
    const root = pathImpl.normalize(r).replace(/[\\/]+$/, '');
    return norm === root || norm.startsWith(root + pathImpl.sep);
  });
}
