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

/** A vsmedia request: the asked path must be well-formed (absolute, a media extension, no '..') and the file it
 * resolves to (`real`, symlinks followed) must lie in a root. A file asked for through a symlinked folder
 * (/tmp -> /private/tmp, a linked Desktop or drive) is served; a symlink pointing out of a root is not. */
export function allowedMedia(asked: string, real: string, roots: string[], pathImpl: typeof path = path): boolean {
  return isAllowedMediaPath(asked, [pathImpl.parse(asked).root], pathImpl) && isAllowedMediaPath(real, roots, pathImpl);
}

const MEDIA_MIME: Record<string, string> = {
  '.mp4': 'video/mp4',
  '.m4v': 'video/mp4',
  '.mov': 'video/quicktime',
  '.webm': 'video/webm',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
};

export function mediaMime(p: string, pathImpl: typeof path = path): string {
  return MEDIA_MIME[pathImpl.extname(p).toLowerCase()] ?? 'application/octet-stream';
}

/** An HTTP Range header against a file of `size` bytes -> the byte span to send (inclusive), 'invalid' (416), or
 * null (no / unsupported range: send the whole file). Only single ranges; "bytes=-N" is the last N bytes. Video
 * elements need 206 answers to seek in files that are not fully buffered. */
export function parseRange(header: string | null | undefined, size: number): { start: number; end: number } | 'invalid' | null {
  if (!header) return null;
  const m = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!m || (m[1] === '' && m[2] === '')) return null;
  let start: number;
  let end: number;
  if (m[1] === '') {
    const n = Number(m[2]);
    if (!n) return 'invalid';
    start = Math.max(0, size - n);
    end = size - 1;
  } else {
    start = Number(m[1]);
    end = m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
  }
  if (start >= size || end < start) return 'invalid';
  return { start, end };
}
