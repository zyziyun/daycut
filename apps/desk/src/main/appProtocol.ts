// app://desk/<path> -> a file of the built renderer. Pure (unit-tested): the request path is decoded, resolved
// against the renderer folder and must stay inside it on every platform (a Windows "%5C..%5C" is a traversal too),
// and only the renderer's own file types are served. Unknown paths fall back to index.html (the hash router).
import path from 'node:path';

export const APP_MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.json': 'application/json',
};

/** -> the absolute file to serve, 'index' (fall back to index.html) or null (forbidden). */
export function resolveAppFile(root: string, pathname: string, p: typeof path = path): string | 'index' | null {
  let rel: string;
  try {
    rel = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  if (rel.includes('\0')) return null;
  rel = rel.replace(/^[/\\]+/, '');
  if (!rel) return 'index';
  // both separators count, whatever the platform: no segment may climb, no drive / UNC / absolute path
  if (rel.split(/[/\\]+/).some((s) => s === '..') || /^[a-zA-Z]:/.test(rel) || p.isAbsolute(rel)) return null;
  const base = p.resolve(root);
  const file = p.resolve(base, rel);
  if (file !== base && !file.startsWith(base + p.sep)) return null;
  if (!(p.extname(file).toLowerCase() in APP_MIME)) return 'index';
  return file;
}
