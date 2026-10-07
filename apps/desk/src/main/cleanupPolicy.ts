// Source cleanup after delivery: off by default, never for the own workspace, and only after the creator confirms
// the exact file list in a dialog (v02.ts registerCleanupIpc). The engine says which sources are due; main moves them to the Trash (recoverable) after these checks - never a hard delete, never
// a top-level or home folder, never something that is not a media file / folder.
import path from 'node:path';

const MEDIA = new Set(['.mp4', '.mov', '.m4v', '.mkv', '.webm', '.wav', '.mp3', '.m4a']);

// home folders that are never trashed as a whole (macOS + the Windows / OneDrive known folders)
const TOP = ['Desktop', 'Documents', 'Downloads', 'Movies', 'Pictures', 'Library', 'Videos', 'Music', 'OneDrive', 'AppData'];

export function cleanupPathOk(p: string, isDir: boolean, home: string, pathImpl: typeof path = path): boolean {
  if (!p || p.includes('\0') || !pathImpl.isAbsolute(p) || p.split(/[\\/]/).includes('..')) return false;
  // Windows paths compare case-insensitively ("c:\users\me" is the home folder too)
  const win = pathImpl.sep === '\\';
  const key = (s: string) => (win ? s.toLowerCase() : s);
  const norm = pathImpl.normalize(p).replace(/[\\/]+$/, '');
  const depth = norm.split(/[\\/]/).filter(Boolean).length;
  if (depth < 3) return false; // "/", "/Users", "/Users/me" (Windows: "C:\", "C:\Users")
  const h = pathImpl.normalize(home).replace(/[\\/]+$/, '');
  if (key(norm) === key(h)) return false;
  for (const top of TOP) {
    if (key(norm) === key(pathImpl.join(h, top))) return false;
  }
  return isDir || MEDIA.has(pathImpl.extname(norm).toLowerCase());
}
