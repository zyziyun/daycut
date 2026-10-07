import data from './platforms.json';
export type Platform = (typeof data.platforms)[number];
export const PLATFORMS: Platform[] = data.platforms;
export const CHECKED = data.checked;
/** Up to two distinct aspect ratios, default orientation first ("3:4 · 9:16"). */
export const ratios = (p: Platform) => [...new Set(p.orientations.map((o) => o.aspect))].slice(0, 2).join(' · ');
