import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseAdapter, type Adapter } from '../../src/shared/publish/adapterSchema';
import { checkFill, resolveInside, type Confirmation } from '../../src/shared/publish/gating';
import type { Manifest, ManifestVerify } from '../../src/shared/types';

const load = (f: string): Adapter => {
  const r = parseAdapter(JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../adapters', f), 'utf8')));
  if (!r.ok) throw new Error(r.error);
  return r.adapter;
};
const adapters = [load('tiktok.json'), load('xiaohongshu.json'), load('kwai.json')];

const manifest: Manifest = {
  batch: 'demo',
  schedule: { per_day: 1, start: '2026-10-06', times: ['12:00'] },
  confirmation_code: 'aaaaaaaaaaaa',
  items: [
    { job: 's001', platform: 'tiktok-vertical', title: 'a', date: '2026-10-06', time: '12:00', files: { video: 'tiktok-vertical/001_s001/video.mp4' }, sha256: 'x', bytes: 1, duration: 1 },
    { job: 's001', platform: 'xiaohongshu-full', title: 'a', date: '2026-10-06', time: '12:00', files: { video: 'xiaohongshu-full/001_s001/video.mp4' }, sha256: 'x', bytes: 1, duration: 1 },
  ],
};
const ok: ManifestVerify = { ok: true, code: 'aaaaaaaaaaaa', stored: 'aaaaaaaaaaaa' };
const conf: Confirmation[] = [{ batchId: 'b00000000001', code: 'aaaaaaaaaaaa', items: 2, confirmedAt: '' }];
const req = { batchId: 'b00000000001', code: 'aaaaaaaaaaaa', job: 's001', platform: 'tiktok-vertical', adapterId: 'tiktok' };

describe('manifest-hash gating', () => {
  it('allows a confirmed item', () => {
    const r = checkFill(req, manifest, ok, conf, adapters);
    expect(r.ok).toBe(true);
  });

  it('refuses without a manifest or when the manifest changed', () => {
    expect(checkFill(req, null, ok, conf, adapters)).toMatchObject({ ok: false, reason: 'no-manifest' });
    expect(checkFill(req, manifest, { ok: false, code: 'bbbbbbbbbbbb', reason: 'changed' }, conf, adapters)).toMatchObject({ ok: false, reason: 'manifest-changed' });
    // verify recomputed a different code than the file claims
    expect(checkFill(req, manifest, { ok: true, code: 'bbbbbbbbbbbb' }, conf, adapters)).toMatchObject({ ok: false, reason: 'manifest-changed' });
  });

  it('refuses an old code (the list was re-packaged)', () => {
    expect(checkFill({ ...req, code: 'cccccccccccc' }, manifest, ok, conf, adapters)).toMatchObject({ ok: false, reason: 'code-mismatch' });
  });

  it('refuses when the creator has not confirmed this code for this batch', () => {
    expect(checkFill(req, manifest, ok, [], adapters)).toMatchObject({ ok: false, reason: 'not-confirmed' });
    expect(checkFill(req, manifest, ok, [{ ...conf[0], batchId: 'b00000000002' }], adapters)).toMatchObject({ ok: false, reason: 'not-confirmed' });
    expect(checkFill(req, manifest, ok, [{ ...conf[0], code: 'dddddddddddd' }], adapters)).toMatchObject({ ok: false, reason: 'not-confirmed' });
  });

  it('refuses items not in the list and adapter mismatches', () => {
    expect(checkFill({ ...req, job: 's999' }, manifest, ok, conf, adapters)).toMatchObject({ ok: false, reason: 'item-not-in-manifest' });
    expect(checkFill({ ...req, platform: 'douyin-vertical' }, manifest, ok, conf, adapters)).toMatchObject({ ok: false, reason: 'item-not-in-manifest' });
    expect(checkFill({ ...req, platform: 'xiaohongshu-full', adapterId: 'tiktok' }, manifest, ok, conf, adapters)).toMatchObject({ ok: false, reason: 'adapter-mismatch' });
  });

  it('refuses TODO adapters', () => {
    expect(checkFill({ ...req, platform: 'kwai-vertical', adapterId: 'kwai' }, { ...manifest, items: [...manifest.items, { ...manifest.items[0], platform: 'kwai-vertical' }] }, ok, conf, adapters)).toMatchObject({ ok: false, reason: 'adapter-todo' });
  });

  it('resolves package files only inside the package folder', () => {
    expect(resolveInside('/p/package', 'tiktok-vertical/001_s001/video.mp4')).toBe('/p/package/tiktok-vertical/001_s001/video.mp4');
    expect(resolveInside('/p/package/', './a/b.mp4')).toBe('/p/package/a/b.mp4');
    expect(resolveInside('/p/package', '../secret.mp4')).toBeNull();
    expect(resolveInside('/p/package', 'a/../../x')).toBeNull();
    expect(resolveInside('/p/package', '/etc/passwd')).toBeNull();
    expect(resolveInside('/p/package', 'C:\\x')).toBeNull();
    expect(resolveInside('/p/package', '')).toBeNull();
  });
});
