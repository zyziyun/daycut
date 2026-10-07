// Redaction for feedback / crash reports. A report may carry versions, the OS, error codes and stack traces; it must
// never carry her media file names, folder names, transcripts, prompts, keys or e-mail addresses. Pure functions
// (unit-tested in tests/unit/support.test.ts); the main process and the renderer both use them, and the user reads the
// result before anything leaves the app.

/** Code, runtimes and the app itself: these paths stay (shortened to ~) so a stack trace is still useful. */
const CODE_EXT = /\.(c?js|mjs|tsx?|py|pyc|node|asar|html|css|dylib|so|dll|exe)$/i;
const CODE_DIR = /(node_modules|app\.asar|Reelfold\.app|Electron\.app|Electron Framework|site-packages|desk_engine|vstudio|electron\/js2c|internal\/|node:)/;
const MEDIA_NAME = /[^\s/\\'"`<>()[\]{}:,;|]+\.(mp4|mov|m4v|mkv|webm|avi|mts|wav|mp3|m4a|aac|flac|ogg|opus|jpe?g|png|webp|heic|gif|tiff?|pdf|docx?|pptx?|key|md|txt|srt|vtt|ass|csv|zip|yaml|yml)\b/giu;

const SECRETS: [RegExp, string][] = [
  [/\bsk-ant-[A-Za-z0-9_-]{8,}/g, '<key>'],
  [/\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}/g, '<key>'],
  [/\bAIza[0-9A-Za-z_-]{20,}/g, '<key>'],
  [/\bgh[pousr]_[A-Za-z0-9]{20,}/g, '<key>'],
  [/\bxox[abprs]-[A-Za-z0-9-]{10,}/g, '<key>'],
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, '<token>'],
  [/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}/gi, '$1 <token>'],
  [/\b(api[_-]?key|x-api-key|token|secret|password|passwd|authorization|cookie)(["']?\s*[:=]\s*["']?)[^\s"',;]+/gi, '$1$2<redacted>'],
  [/\b[A-Fa-f0-9]{32,}\b/g, '<hex>'],
  [/(?<![\w/.-])[A-Za-z0-9+_-]{40,}={0,2}/g, '<token>'],
];

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** One path-like token: app / runtime code keeps its (home-shortened) path; anything else is hers -> <path>[.ext]. */
function redactPath(tok: string): string {
  const bare = tok.replace(/^file:\/\//, '').replace(/(:\d+){1,2}$/, '');
  const suffix = tok.slice(tok.replace(/(:\d+){1,2}$/, '').length);
  if (bare === '~' || bare === '/') return tok;
  if (CODE_DIR.test(bare) || CODE_EXT.test(bare)) {
    // keep the code path, but a user folder inside it (a dev checkout inside one of her own folders) goes
    return bare.replace(/^~[\\/](?:[^\\/]+[\\/])*?(?=(?:apps|node_modules|lib|engine|out|src|Contents|resources|site-packages)[\\/])/, '~/…/') + suffix;
  }
  const m = /\.([A-Za-z0-9]{1,5})$/.exec(bare);
  return m ? `<path>.${m[1].toLowerCase()}` : '<path>';
}

/**
 * Redact free text for a report. `home` (the user's home folder) is shortened to ~ first; then every path that is
 * not app code becomes <path>, media / document names become <file>.ext, keys / tokens / e-mails / URL queries go,
 * and long quoted or CJK passages (prompts, transcript lines) become <text>.
 */
export function redact(text: string, home?: string | null): string {
  let s = String(text ?? '');
  if (home && home.length > 2) s = s.replace(new RegExp(escapeRe(home.replace(/[\\/]+$/, '')), 'g'), '~');
  s = s.replace(/(?:\/Users|\/home)\/[^/\s'"`]+/g, '~').replace(/[A-Za-z]:\\Users\\[^\\\s'"`]+/g, '~');
  s = s.replace(/\/(?:private\/)?var\/folders\/[^\s'"`]+/g, '<tmp>');
  s = s.replace(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g, '<email>');
  s = s.replace(/\b(https?:\/\/[^\s?#'"`<>]+)[?#][^\s'"`<>]*/g, '$1?<redacted>');
  for (const [re, by] of SECRETS) s = s.replace(re, by);
  s = s.replace(/https?:\/\/[^\s'"`<>]+|(?<![\w.~/-])((?:file:\/\/)?(?:~|\/(?=[^\s/])|[A-Za-z]:\\)[^\s'"`<>()[\]{},;|]*)/g, (m, p) => (p ? redactPath(p) : m));
  s = s.replace(MEDIA_NAME, (_m, ext: string) => `<file>.${ext.toLowerCase()}`);
  s = s.replace(/(["“「『'])([^"”」』'\n]{40,})(["”」』'])/g, '$1<text>$3');
  s = s.replace(/[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af][\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff00-\uffef\s，。！？、]{9,}/g, '<text>');
  return s;
}

/** Redact + keep at most `max` characters (whole lines first). */
export function redactClip(text: string, max: number, home?: string | null): string {
  const s = redact(text, home);
  if (s.length <= max) return s;
  return s.slice(0, Math.max(0, max - 1)).replace(/\n[^\n]*$/, '') + '\n…';
}

export const _test = { redactPath };
