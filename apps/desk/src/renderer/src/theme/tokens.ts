// Design tokens (v0.4). Two themes x two accents. Warm neutral greys with three surface levels; ONE accent used for
// the primary action, focus and the active nav only; status colours are desaturated and only appear on small dots
// and pills; thumbnails and video are the most colourful thing on screen. Text pairs are WCAG AA (see tokens test).

export type ThemeName = 'studio-dark' | 'notebook-light';
export type AccentName = 'teal' | 'red';

export interface Tokens {
  bg: string;
  surface: string;
  surface2: string;
  surface3: string;
  border: string;
  borderStrong: string;
  text: string;
  textMuted: string;
  textFaint: string;
  accent: string;
  accentText: string;
  accentSoft: string;
  run: string;
  you: string;
  ok: string;
  danger: string;
  warn: string;
  highlight: string;
  scrim: string;
  radius: string;
  radiusLg: string;
  font: string;
  fontMono: string;
  shadow: string;
}

const FONT = '"PingFang SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Hiragino Sans GB", "Segoe UI", "Microsoft YaHei", sans-serif';
const MONO = '"SF Mono", ui-monospace, Menlo, Consolas, monospace';

const base: Record<ThemeName, Omit<Tokens, 'accent' | 'accentText' | 'accentSoft' | 'highlight'>> = {
  'studio-dark': {
    bg: '#151413',
    surface: '#1C1B19',
    surface2: '#242220',
    surface3: '#2E2B28',
    border: 'rgba(255, 240, 220, 0.08)',
    borderStrong: 'rgba(255, 240, 220, 0.16)',
    text: '#EDE9E4',
    textMuted: '#A39C94',
    textFaint: '#7D766F',
    run: '#7AA7D6',
    you: '#D8A951',
    ok: '#78BE92',
    danger: '#E07A72',
    warn: '#D8A951',
    scrim: 'rgba(10, 9, 8, 0.72)',
    radius: '8px',
    radiusLg: '12px',
    font: FONT,
    fontMono: MONO,
    shadow: '0 12px 32px rgba(0, 0, 0, 0.35)',
  },
  'notebook-light': {
    bg: '#F7F4EF',
    surface: '#FFFFFF',
    surface2: '#F1EDE6',
    surface3: '#E8E2D9',
    border: 'rgba(60, 40, 20, 0.10)',
    borderStrong: 'rgba(60, 40, 20, 0.20)',
    text: '#26221E',
    textMuted: '#6B635A',
    textFaint: '#8C8379',
    run: '#2F6AA6',
    you: '#8F620B',
    ok: '#2C7A4B',
    danger: '#B93A2F',
    warn: '#8F620B',
    scrim: 'rgba(38, 34, 30, 0.45)',
    radius: '8px',
    radiusLg: '12px',
    font: FONT,
    fontMono: MONO,
    shadow: '0 10px 28px rgba(80, 60, 30, 0.12)',
  },
};

const accents: Record<ThemeName, Record<AccentName, Pick<Tokens, 'accent' | 'accentText' | 'accentSoft' | 'highlight'>>> = {
  'studio-dark': {
    teal: { accent: '#4FBFAE', accentText: '#0B1F1C', accentSoft: 'rgba(79, 191, 174, 0.14)', highlight: 'rgba(79, 191, 174, 0.12)' },
    red: { accent: '#F0435B', accentText: '#1F0508', accentSoft: 'rgba(240, 67, 91, 0.14)', highlight: 'rgba(240, 67, 91, 0.12)' },
  },
  'notebook-light': {
    teal: { accent: '#0F7A6C', accentText: '#FFFFFF', accentSoft: 'rgba(15, 122, 108, 0.10)', highlight: 'rgba(15, 122, 108, 0.09)' },
    red: { accent: '#D81E3A', accentText: '#FFFFFF', accentSoft: 'rgba(216, 30, 58, 0.09)', highlight: 'rgba(216, 30, 58, 0.08)' },
  },
};

export function tokens(theme: ThemeName = 'studio-dark', accent: AccentName = 'teal'): Tokens {
  const th = base[theme] ? theme : 'studio-dark';
  return { ...base[th], ...(accents[th][accent] ?? accents[th].teal) };
}

/** Kept for older imports: the full token set per theme with the default accent. */
export const themes: Record<ThemeName, Tokens> = {
  'studio-dark': tokens('studio-dark'),
  'notebook-light': tokens('notebook-light'),
};

const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()).replace(/(\d)/, '-$1');

export function applyTheme(name: ThemeName, root: HTMLElement = document.documentElement, accent: AccentName = 'teal') {
  const tk = tokens(name, accent);
  for (const [k, v] of Object.entries(tk)) root.style.setProperty(`--${kebab(k)}`, v);
  root.dataset.theme = name;
  root.dataset.accent = accent;
  root.style.colorScheme = name === 'studio-dark' ? 'dark' : 'light';
}

// ---------------------------------------------------------------- contrast (WCAG 2.x), used by the tokens test
function lum(hex: string): number {
  const v = hex.replace('#', '');
  const c = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

export function contrast(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
