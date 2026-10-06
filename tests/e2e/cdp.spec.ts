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

test('assisted fill reaches fields inside a shadow root, makes one tag per Enter, leaves 分区 and submit alone', () => {
  const root = path.resolve(import.meta.dirname, '../..');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-cdp-shadow-'));
  const out = path.join(tmp, 'fixture-shadow.cjs');
  buildSync({ entryPoints: [path.join(root, 'tests/e2e/cdpFixtureShadow.ts')], outfile: out, bundle: true, platform: 'node', format: 'cjs', external: ['electron'], logLevel: 'silent' });
  const video = path.join(tmp, 'video.mp4');
  const cover = path.join(tmp, 'cover.jpg');
  fs.writeFileSync(video, 'not really a video');
  fs.writeFileSync(cover, 'not really a jpeg');
  const stdout = execFileSync(electronPath as unknown as string, [out, path.join(root, 'tests/e2e/fixture'), video, cover], { encoding: 'utf8', timeout: 60000 });
  const line = stdout.split('\n').find((l) => l.startsWith('RESULT '));
  expect(line, stdout).toBeTruthy();
  const r = JSON.parse(line!.slice(7));
  expect(r.results.map((x: { field: string; status: string }) => `${x.field}:${x.status}`)).toEqual(['file:ok', 'title:ok', 'description:ok', 'tags:ok', 'cover:ok', 'publish:ok']);
  expect(r.page.file).toBe('video.mp4');
  expect(r.page.cover).toBe('cover.jpg');
  expect(r.page.title).toBe('第 1 集：批量剪口播');
  expect(r.page.desc).toContain('第一行');
  expect(r.page.tags).toEqual(['口播', '剪辑', 'AI']);
  expect(r.page.zone).toBe('');
  expect(r.page.clicked).toBe(false);
  expect(r.page.outline).toContain('solid');
});
