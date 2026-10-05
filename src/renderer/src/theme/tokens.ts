// Design tokens (DESIGN.md §3). One file for every theme: "Studio Dark" (desktop default) is complete;
// "Notebook Light" (小红书手账) is a starting point to finish later. Components only use the CSS variables.

export type ThemeName = 'studio-dark' | 'notebook-light';

export interface Tokens {
  bg: string;
  surface: string;
  surface2: string;
  border: string;
  text: string;
  textMuted: string;
  accent: string; // primary action / focus
  accentText: string;
  danger: string; // destructive / red QC
  ok: string; // green QC
  warn: string;
  highlight: string; // emphasis marker (Notebook Light: 荧光黄)
  radius: string;
  radiusLg: string;
  font: string;
  fontMono: string;
  shadow: string;
}

export const themes: Record<ThemeName, Tokens> = {
  'studio-dark': {
    bg: '#0E1113',
    surface: '#161A1D',
    surface2: '#1E2327',
    border: '#2A3035',
    text: '#E7ECEF',
    textMuted: '#8B969E',
    accent: '#2DD4BF',
    accentText: '#04201C',
    danger: '#F2555A',
    ok: '#34D399',
    warn: '#FBBF24',
    highlight: '#2DD4BF33',
    radius: '6px',
    radiusLg: '10px',
    font: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Segoe UI", sans-serif',
    fontMono: '"SF Mono", Menlo, Consolas, monospace',
    shadow: '0 8px 24px rgba(0,0,0,.35)',
  },
  // TODO(theme): finish Notebook Light (paper texture, hand-drawn underline, rounder cards) - DESIGN.md ②
  'notebook-light': {
    bg: '#FBF8F3',
    surface: '#FFFFFF',
    surface2: '#F4EFE7',
    border: '#E6DED2',
    text: '#2B2622',
    textMuted: '#857C72',
    accent: '#FF2442',
    accentText: '#FFFFFF',
    danger: '#D92D20',
    ok: '#12B76A',
    warn: '#F79009',
    highlight: '#FFD60A66',
    radius: '10px',
    radiusLg: '16px',
    font: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", sans-serif',
    fontMono: '"SF Mono", Menlo, monospace',
    shadow: '0 6px 18px rgba(80,60,30,.12)',
  },
};

const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());

export function applyTheme(name: ThemeName, root: HTMLElement = document.documentElement) {
  const t = themes[name] ?? themes['studio-dark'];
  for (const [k, v] of Object.entries(t)) root.style.setProperty(`--${kebab(k)}`, v);
  root.dataset.theme = name;
  root.style.colorScheme = name === 'studio-dark' ? 'dark' : 'light';
}
