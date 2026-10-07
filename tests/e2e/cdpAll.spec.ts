// Assisted fill for every fillable adapter (B站, Instagram, TikTok, 视频号, X, YouTube) against local mocks of
// their upload forms, with the real fuye-style copy (Chinese title, two paragraphs, 7 hashtags): the file (and
// cover) is attached, the text typed per platform rules, the publish button only outlined - never clicked - and
// the choices left to her (B站 分区, 视频号 原创, YouTube 儿童内容) untouched. No CDP click / cookie method is used.
import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { buildSync } from 'esbuild';
import electronPath from 'electron';

test('every adapter fills its mock upload form and never clicks publish', () => {
  const root = path.resolve(import.meta.dirname, '../..');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-cdp-all-'));
  const out = path.join(tmp, 'fixture.cjs');
  buildSync({ entryPoints: [path.join(root, 'tests/e2e/cdpFixtureAll.ts')], outfile: out, bundle: true, platform: 'node', format: 'cjs', external: ['electron'], logLevel: 'silent' });
  const video = path.join(tmp, 'video.mp4');
  const cover = path.join(tmp, 'cover.jpg');
  fs.writeFileSync(video, 'not really a video');
  fs.writeFileSync(cover, 'not really a jpeg');
  const md = path.join(tmp, 'post.md');
  const title = '同一个行业待越久，思路越窄';
  fs.writeFileSync(md, `${title}\n\n我身边的同事几乎都是程序员。\n副业对我最大的价值，是让我链接到主业里遇不到的人。\n\n#副业 #副业思维 #自媒体 #程序员 #职业规划 #个人成长 #认知提升\n`);
  const shots = process.env.PUBTEST_SHOTS || '-';
  const stdout = execFileSync(electronPath as unknown as string, [out, path.join(root, 'tests/e2e/fixture/mocks'), video, cover, md, title, shots], { encoding: 'utf8', timeout: 120000 });
  const line = stdout.split('\n').find((l) => l.startsWith('RESULT '));
  expect(line, stdout).toBeTruthy();
  const r = JSON.parse(line!.slice(7)) as Record<string, { results: { field: string; status: string }[]; page: Record<string, unknown>; methods: string[] }>;
  const ok = (id: string) => r[id].results.map((x) => `${x.field}:${x.status}`);
  for (const id of Object.keys(r)) {
    expect(r[id].page.clicked, `${id} publish clicked`).toBe(false);
    expect(r[id].page.file, `${id} file`).toBe('video.mp4');
    expect(r[id].methods.filter((m) => /Mouse|Cookie|Storage|Network/.test(m)), id).toEqual([]);
  }
  expect(ok('bilibili')).toEqual(['file:ok', 'title:ok', 'description:ok', 'tags:ok', 'cover:ok', 'publish:ok']);
  expect(r.bilibili.page).toMatchObject({ title, cover: 'cover.jpg', zone: '' });
  expect(r.bilibili.page.tags).toEqual(['副业', '副业思维', '自媒体', '程序员', '职业规划', '个人成长', '认知提升']);
  expect(String(r.bilibili.page.desc)).toContain('副业对我最大的价值');
  expect(String(r.bilibili.page.outline)).toContain('solid');

  expect(ok('instagram')).toEqual(['file:ok', 'description:ok']); // no publish button: Share is hers
  const ig = String(r.instagram.page.desc);
  expect(ig.startsWith(title)).toBe(true); // no title field: the title is the first line
  expect(ig.match(/#/g)?.length).toBe(5); // hard max 5

  expect(ok('tiktok')).toEqual(['file:ok', 'description:ok', 'publish:ok']);
  expect(String(r.tiktok.page.desc)).not.toContain('A_换圈子_9x16'); // the file-name prefill is replaced
  expect(String(r.tiktok.page.desc).startsWith(title)).toBe(true); // caption only: the title leads it
  expect(String(r.tiktok.page.desc).match(/#/g)?.length).toBe(5); // the adapter's tag cap

  expect(ok('wechat-channels')).toEqual(['file:ok', 'title:ok', 'description:ok', 'publish:ok']);
  expect(r['wechat-channels'].page).toMatchObject({ title, original: false });

  expect(ok('x-web')).toEqual(['file:ok', 'description:ok', 'publish:ok']);
  const xt = String(r['x-web'].page.desc);
  expect(xt.startsWith(title)).toBe(true);
  expect(xt.match(/#/g)?.length).toBe(2);

  expect(ok('youtube-studio')).toEqual(['file:ok', 'title:ok', 'description:ok', 'cover:ok', 'publish:ok']);
  expect(r['youtube-studio'].page).toMatchObject({ title, cover: 'cover.jpg', kids: false });
});
