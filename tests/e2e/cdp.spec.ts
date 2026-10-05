// The assisted-fill CDP path against a local fixture page (file input inside an iframe, caption editor that
// appears after upload, a post button that records clicks).
import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { buildSync } from 'esbuild';
import electronPath from 'electron';

test('assisted fill sets the file, types the caption and never clicks post', () => {
  const root = path.resolve(import.meta.dirname, '../..');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-cdp-'));
  const out = path.join(tmp, 'fixture.cjs');
  buildSync({ entryPoints: [path.join(root, 'tests/e2e/cdpFixture.ts')], outfile: out, bundle: true, platform: 'node', format: 'cjs', external: ['electron'], logLevel: 'silent' });
  const video = path.join(tmp, 'video.mp4');
  fs.writeFileSync(video, 'not really a video');
  const stdout = execFileSync(electronPath as unknown as string, [out, path.join(root, 'tests/e2e/fixture'), video], { encoding: 'utf8', timeout: 60000 });
  const line = stdout.split('\n').find((l) => l.startsWith('RESULT '));
  expect(line, stdout).toBeTruthy();
  const r = JSON.parse(line!.slice(7));
  expect(r.results.map((x: { field: string; status: string }) => `${x.field}:${x.status}`)).toEqual(['file:ok', 'description:ok', 'publish:ok']);
  expect(r.page.file).toBe('video.mp4');
  expect(r.page.caption).toContain('第一行');
  expect(r.page.caption).toContain('第二行');
  expect(r.page.caption).toContain('#口播 #剪辑');
  expect(r.page.caption).not.toContain('fixture-file-name');
  expect(r.page.clicked).toBe(false);
  expect(r.page.outline).toContain('solid');
});
