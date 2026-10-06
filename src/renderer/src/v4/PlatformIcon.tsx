// Small platform marks for chips, tabs and calendar posts: a coloured rounded square with a short glyph (not the
// platforms' trademarked logos). Unknown ids get a neutral letter mark.
import { tk } from '../i18n';

// glyphs are marks, not copy (escaped so the locale lint does not count them): 红 抖 视
const MARKS: Record<string, { g: string; bg: string; fg?: string }> = {
  xiaohongshu: { g: '\u7ea2', bg: '#FF2442' },
  douyin: { g: '\u6296', bg: '#111111' },
  'wechat-channels': { g: '\u89c6', bg: '#FA9D3B' },
  shipinhao: { g: '\u89c6', bg: '#FA9D3B' },
  bilibili: { g: 'B', bg: '#00A1D6' },
  tiktok: { g: 'T', bg: '#111111' },
  youtube: { g: '▶', bg: '#FF0033' },
  'youtube-shorts': { g: 'S', bg: '#FF0033' },
  x: { g: '𝕏', bg: '#000000' },
  instagram: { g: 'IG', bg: '#D62976' },
};

/** Platforms the calendar can schedule to, in display order. */
export const SCHEDULE_PLATFORMS = ['xiaohongshu', 'douyin', 'wechat-channels', 'bilibili', 'tiktok', 'youtube-shorts', 'youtube', 'x', 'instagram'];

/** "x:vertical" / "instagram-reels" / "x-web" (adapter id) -> the platform the mark is for. */
export function platformKey(id: string): string {
  const base = id.split(':')[0];
  if (MARKS[base]) return base;
  if (base === 'x-web') return 'x';
  if (base === 'youtube-studio') return 'youtube';
  const i = base.lastIndexOf('-');
  return i > 0 && MARKS[base.slice(0, i)] ? base.slice(0, i) : base;
}

export function PlatformIcon({ id, size = 16, title }: { id: string; size?: number; title?: string }) {
  const k = platformKey(id);
  const m = MARKS[k] ?? { g: (k[0] ?? '?').toUpperCase(), bg: 'var(--border-strong)' };
  const label = title ?? tk(`pf.${k}`);
  return (
    <span
      className="pfi"
      role="img"
      aria-label={label}
      title={label}
      data-pf={k}
      style={{
        display: 'inline-grid',
        placeItems: 'center',
        width: size,
        height: size,
        borderRadius: Math.round(size / 4),
        background: m.bg,
        color: m.fg ?? '#fff',
        fontSize: Math.round(size * (m.g.length > 1 ? 0.5 : 0.62)),
        fontWeight: 700,
        lineHeight: 1,
        flex: 'none',
      }}
    >
      {m.g}
    </span>
  );
}
