// Creator rule: platforms are always listed international first, then Chinese, then other languages - in chips and
// their summaries, pickers, stored selections, plan facts. Everything goes through the shared registry order
// (shared/platforms.ts: orderPlatforms / sortPlatforms); no component keeps its own hand-ordered list.
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { basePlatform, orderPlatforms, PLATFORMS, platformRank, sortPlatforms } from '../../src/shared/platforms';

const CHINESE_FIRST = ['douyin', 'xiaohongshu:full', 'bilibili', 'tiktok', 'youtube-shorts', 'wechat-channels', 'instagram'];

describe('registry order', () => {
  it('orders a Chinese-first selection international first', () => {
    expect(orderPlatforms(CHINESE_FIRST)).toEqual(['youtube-shorts', 'tiktok', 'instagram', 'xiaohongshu:full', 'douyin', 'wechat-channels', 'bilibili']);
  });
  it('ranks profiles / targets and engine aliases as their platform', () => {
    expect(basePlatform('douyin:vertical')).toBe('douyin');
    expect(basePlatform('shipinhao')).toBe('wechat-channels');
    expect(platformRank('xiaohongshu:full')).toEqual(platformRank('xiaohongshu'));
    expect(platformRank('shipinhao')[0]).toBe(1);
  });
  it('a connected Chinese account never jumps ahead of an international platform', () => {
    expect(sortPlatforms(['douyin', 'tiktok', 'xiaohongshu'], (x) => x, ['douyin'])).toEqual(['tiktok', 'douyin', 'xiaohongshu']);
  });
  it('drops duplicates and keeps unknown ids last', () => {
    expect(orderPlatforms(['zzz', 'douyin', 'douyin', 'x'])).toEqual(['x', 'douyin', 'zzz']);
  });
});

describe('chips and lists built from Chinese-first input render international first', () => {
  // the helpers the chips use (Home composer chip, plan facts, Settings summary, Focus meta line)
  it('Home composer chip / Settings summary', async () => {
    const ids = orderPlatforms(CHINESE_FIRST.map((p) => p.split(':')[0]));
    expect(ids.slice(0, 2)).toEqual(['youtube-shorts', 'tiktok']);
  });
  it('plan card facts', async () => {
    const { planFacts } = await import('../../src/renderer/src/v4/PlanCard');
    const f = planFacts({ projects: [{ params: { platforms: ['douyin', 'xiaohongshu:vertical', 'tiktok'] } }] } as never);
    expect(f.plats).toEqual(['TikTok', 'Xiaohongshu', 'Douyin']);
  });
});

// ------------------------------------------------ lint: no hand-ordered platform lists in components
const ROOT = path.resolve(import.meta.dirname, '../../src');
const GROUP = new Map(PLATFORMS.map((p) => [p.id, p.group]));
// owned by other branches right now (qa/BUGS.md "platform order", deferred): remove an entry when its branch lands
const DEFERRED = new Set(['renderer/src/create/CreateHome.tsx']);

function files(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => (d.isDirectory() ? files(path.join(dir, d.name)) : /\.(ts|tsx)$/.test(d.name) ? [path.join(dir, d.name)] : []));
}

/** Array literals of quoted platform ids where a Chinese / other-language platform comes before a global one. */
export function misordered(src: string): string[] {
  const out: string[] = [];
  for (const m of src.matchAll(/\[\s*((?:'[a-z0-9:-]+'\s*,\s*)+'[a-z0-9:-]+')\s*,?\s*\]/g)) {
    const ids = [...m[1].matchAll(/'([a-z0-9:-]+)'/g)].map((x) => x[1].split(':')[0]).filter((x) => GROUP.has(x));
    if (ids.length < 2) continue;
    const ranks = ids.map((x) => platformRank(x)[0]);
    if (ranks.some((r, i) => i > 0 && r < ranks[i - 1])) out.push(m[0]);
  }
  return out;
}

describe('lint: no component hardcodes a Chinese-first platform order', () => {
  it('the detector works', () => {
    expect(misordered("const A = ['douyin', 'tiktok'];")).toHaveLength(1);
    expect(misordered("const A = ['tiktok', 'douyin'];")).toHaveLength(0);
  });
  it('src/ has none (outside the deferred list)', () => {
    const bad = files(ROOT)
      .filter((f) => !DEFERRED.has(path.relative(ROOT, f)))
      .flatMap((f) => misordered(fs.readFileSync(f, 'utf8')).map((m) => `${path.relative(ROOT, f)}: ${m}`));
    expect(bad).toEqual([]);
  });
});
