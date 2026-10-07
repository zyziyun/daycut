import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { guardedSend, runFill, type Send } from '../../src/main/publish/cdpFill';
import { parseAdapter, type Adapter } from '../../src/shared/publish/adapterSchema';
import { planFill } from '../../src/shared/publish/fillPlan';
import { parsePostCopy } from '../../src/shared/publish/postCopy';

const load = (f: string): Adapter => {
  const r = parseAdapter(JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../adapters', f), 'utf8')));
  if (!r.ok) throw new Error(r.error);
  return r.adapter;
};

const copy = parsePostCopy('第 1 集：批量剪口播\n\n第一行\n第二行\n\n#口播 #剪辑\n', '第 1 集：批量剪口播');

/** A fake page: selectors present in `dom` resolve to objectIds; records every CDP call. */
function fakePage(dom: Record<string, { file?: boolean }>, frames = 1) {
  const calls: { method: string; params?: Record<string, unknown> }[] = [];
  const objs = new Map<string, string>();
  const send: Send = async (method, params) => {
    calls.push({ method, params });
    switch (method) {
      case 'Page.getFrameTree': {
        const child = Array.from({ length: frames - 1 }, (_, i) => ({ frame: { id: `f${i + 1}` } }));
        return { frameTree: { frame: { id: 'f0' }, childFrames: child } };
      }
      case 'Page.createIsolatedWorld':
        return { executionContextId: 1 };
      case 'Runtime.evaluate': {
        const sels: string[] = JSON.parse(/for \(const s of (\[.*?\])\)/.exec(String(params!.expression))![1]);
        const hit = sels.find((s) => s in dom);
        if (!hit) return { result: { type: 'object', subtype: 'null' } };
        const id = `obj:${hit}`;
        objs.set(id, hit);
        return { result: { type: 'object', subtype: 'node', objectId: id } };
      }
      case 'Runtime.callFunctionOn': {
        const sel = objs.get(String(params!.objectId))!;
        if (String(params!.functionDeclaration).includes("this.type === 'file'")) return { result: { value: !!dom[sel].file } };
        return { result: { value: true } };
      }
      default:
        return {};
    }
  };
  return { send, calls };
}

describe('assisted fill plan', () => {
  it('parses post.md into title / description / tags', () => {
    expect(copy).toEqual({ title: '第 1 集：批量剪口播', description: '第一行\n第二行', tags: ['口播', '剪辑'] });
    expect(parsePostCopy('标题\n\n正文\n\n标签：a, b', '').tags).toEqual(['a', 'b']);
  });

  it('never contains a click step; publish is only highlighted', () => {
    for (const f of ['tiktok.json', 'youtube-studio.json']) {
      const steps = planFill(load(f), { videoPath: '/p/v.mp4', coverPath: '/p/c.jpg', copy });
      expect(steps.every((s) => ['files', 'text', 'highlight'].includes(s.kind))).toBe(true);
      expect(steps.filter((s) => s.kind === 'highlight').map((s) => s.field)).toEqual(['publish']);
      expect(steps[0]).toMatchObject({ kind: 'files', field: 'file', paths: ['/p/v.mp4'] });
    }
  });

  it('TikTok: caption = description + hashtags, no title, no cover', () => {
    const steps = planFill(load('tiktok.json'), { videoPath: '/p/v.mp4', coverPath: '/p/c.jpg', copy });
    const desc = steps.find((s) => s.field === 'description');
    expect(desc && desc.kind === 'text' && desc.text).toBe('第一行\n第二行\n\n#口播 #剪辑');
    expect(steps.some((s) => s.field === 'title' || s.field === 'cover')).toBe(false);
  });

  it('YouTube: title clipped to 100 chars, cover set when present', () => {
    const long = { ...copy, title: 'x'.repeat(150) };
    const steps = planFill(load('youtube-studio.json'), { videoPath: '/p/v.mp4', coverPath: '/p/c.jpg', copy: long });
    const title = steps.find((s) => s.field === 'title');
    expect(title && title.kind === 'text' && Array.from(title.text).length).toBe(100);
    expect(steps.find((s) => s.field === 'cover')).toMatchObject({ kind: 'files', paths: ['/p/c.jpg'] });
  });
});

describe('CDP executor', () => {
  it('blocks every CDP method assisted fill does not need', async () => {
    const send = guardedSend(async () => ({}));
    await expect(send('Input.dispatchMouseEvent', { type: 'mousePressed' })).rejects.toThrow(/not allowed/);
    await expect(send('Network.getCookies')).rejects.toThrow(/not allowed/);
    await expect(send('Storage.getCookies')).rejects.toThrow(/not allowed/);
    await expect(send('Input.dispatchKeyEvent', { key: 'Tab' })).rejects.toThrow(/Enter/);
    await expect(send('DOM.setFileInputFiles', {})).resolves.toEqual({});
  });

  it('sets the file, types the caption, highlights publish, clicks nothing', async () => {
    const a = load('tiktok.json');
    const page = fakePage({
      'input[type="file"][accept*="video"]': { file: true },
      'div.public-DraftEditor-content[contenteditable="true"]': {},
      'button[data-e2e="post_video_button"]': {},
    });
    const steps = planFill(a, { videoPath: '/p/v.mp4', copy });
    const res = await runFill(page.send, steps, { sleep: async () => undefined });
    expect(res.map((r) => [r.field, r.status])).toEqual([
      ['file', 'ok'],
      ['description', 'ok'],
      ['publish', 'ok'],
    ]);
    const files = page.calls.find((c) => c.method === 'DOM.setFileInputFiles');
    expect(files?.params).toMatchObject({ files: ['/p/v.mp4'] });
    const typed = page.calls.filter((c) => c.method === 'Input.insertText').map((c) => c.params!.text);
    expect(typed).toEqual(['第一行', '第二行', '#口播 #剪辑']);
    expect(page.calls.some((c) => c.method === 'Input.dispatchMouseEvent')).toBe(false);
    expect(page.calls.filter((c) => c.method === 'Runtime.callFunctionOn').some((c) => /\.click\(/.test(String(c.params!.functionDeclaration)))).toBe(false);
  });

  it('stops when the file input is missing (not logged in / page changed)', async () => {
    const page = fakePage({});
    const steps = planFill(load('tiktok.json'), { videoPath: '/p/v.mp4', copy }).map((s) => ({ ...s, timeoutMs: 0 }));
    const res = await runFill(page.send, steps, { sleep: async () => undefined });
    expect(res).toEqual([{ field: 'file', kind: 'files', status: 'not-found', detail: steps[0].selectors[0] }]);
  });

  it('refuses to set files on something that is not a file input', async () => {
    const page = fakePage({ 'input[type="file"][accept*="video"]': { file: false } });
    const steps = planFill(load('tiktok.json'), { videoPath: '/p/v.mp4', copy }).map((s) => ({ ...s, timeoutMs: 0 }));
    const res = await runFill(page.send, steps, { sleep: async () => undefined });
    expect(res[0]).toMatchObject({ status: 'error' });
    expect(page.calls.some((c) => c.method === 'DOM.setFileInputFiles')).toBe(false);
  });

  it('looks in child frames too', async () => {
    const page = fakePage({ 'input[type="file"]': { file: true } }, 3);
    const steps = planFill(load('tiktok.json'), { videoPath: '/p/v.mp4', copy }).slice(0, 1);
    const res = await runFill(page.send, steps, { sleep: async () => undefined });
    expect(res[0].status).toBe('ok');
  });
});
