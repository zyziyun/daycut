// Source cleanup after delivery (PRODUCT_V02.md P0-4: 交付后 30 天自动清理原始素材). The engine says which
// sources are due; main moves them to the Trash (recoverable) after these checks - never a hard delete, never
// a top-level or home folder, never something that is not a media file / folder.
import path from 'node:path';

const MEDIA = new Set(['.mp4', '.mov', '.m4v', '.mkv', '.webm', '.wav', '.mp3', '.m4a']);

export function cleanupPathOk(p: string, isDir: boolean, home: string, pathImpl: typeof path = path): boolean {
  if (!p || p.includes('\0') || !pathImpl.isAbsolute(p) || p.split(/[\\/]/).includes('..')) return false;
  const norm = pathImpl.normalize(p).replace(/[\\/]+$/, '');
  const depth = norm.split(/[\\/]/).filter(Boolean).length;
  if (depth < 3) return false; // "/", "/Users", "/Users/me"
  const h = pathImpl.normalize(home).replace(/[\\/]+$/, '');
  if (norm === h) return false;
  for (const top of ['Desktop', 'Documents', 'Downloads', 'Movies', 'Pictures', 'Library']) {
    if (norm === pathImpl.join(h, top)) return false;
  }
  return isDir || MEDIA.has(pathImpl.extname(norm).toLowerCase());
}
