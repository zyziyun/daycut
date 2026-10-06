import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { AssetManager } from '../../src/main/assets';
import { findBundledRuntime, prependPath, runtimeEnv } from '../../src/main/runtime';
import { groupsFor, safeRel, type AssetManifest } from '../../src/shared/assets';

const body = crypto.randomBytes(300_000);
const sha = crypto.createHash('sha256').update(body).digest('hex');
let server: http.Server;
let base = '';
let rangeRequests = 0;

beforeAll(async () => {
  server = http.createServer((req, res) => {
    if (req.url === '/missing') return void res.writeHead(404).end();
    const m = /bytes=(\d+)-/.exec(req.headers.range ?? '');
    if (m) {
      rangeRequests++;
      const from = Number(m[1]);
      res.writeHead(206, { 'content-length': body.length - from });
      return void res.end(body.subarray(from));
    }
    res.writeHead(200, { 'content-length': body.length });
    res.end(body);
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
afterAll(() => server.close());

function manifest(over: Partial<AssetManifest['groups'][0]> = {}): AssetManifest {
  return {
    groups: [
      { id: 'core', required: true, root: 'vstudio-cache', licence: 'test', files: [{ url: `${base}/f`, dest: 'models/a.bin', sha256: sha, size: body.length }], ...over },
      { id: 'asr-x', required: true, targets: ['other-arch'], root: 'm', licence: 't', files: [] },
    ],
  };
}

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-assets-'));

describe('AssetManager', () => {
  it('filters groups by target and reports missing required ones', () => {
    expect(groupsFor(manifest(), 'x').map((g) => g.id)).toEqual(['core']);
    const m = new AssetManager({ manifest: manifest(), dir: tmp(), target: 'x' });
    expect(m.missingRequired()).toEqual(['core']);
    expect(m.status().groups[0]).toMatchObject({ id: 'core', installed: false, bytes: body.length });
  });

  it('downloads, verifies and installs; env paths resolve; resume uses Range', async () => {
    const dir = tmp();
    const events: number[] = [];
    const m = new AssetManager({
      manifest: manifest({ env: { SOME_DIR: '', SOME_FILE: 'models/a.bin' } }),
      dir,
      target: 'x',
      onChange: (s) => events.push(s.groups.length),
    });
    // a partial file from an interrupted run
    const staging = path.join(dir, '.downloads', 'core');
    fs.mkdirSync(staging, { recursive: true });
    fs.writeFileSync(path.join(staging, `${sha}.part`), body.subarray(0, 1000));
    const st = await m.install();
    expect(st.groups[0].installed).toBe(true);
    expect(rangeRequests).toBe(1);
    expect(fs.readFileSync(path.join(dir, 'vstudio-cache', 'models', 'a.bin')).equals(body)).toBe(true);
    expect(m.env()).toEqual({ SOME_DIR: path.join(dir, 'vstudio-cache'), SOME_FILE: path.join(dir, 'vstudio-cache', 'models', 'a.bin') });
    expect(st.restartNeeded).toBe(true);
    m.markEngineStarted();
    expect(m.status().restartNeeded).toBe(false);
    expect(events.length).toBeGreaterThan(0);
  });

  it('rejects a checksum mismatch and leaves nothing installed', async () => {
    const dir = tmp();
    const bad = manifest();
    bad.groups[0].files[0].sha256 = '0'.repeat(64);
    const m = new AssetManager({ manifest: bad, dir, target: 'x' });
    const st = await m.install();
    expect(st.groups[0].installed).toBe(false);
    expect(st.groups[0].error).toMatch(/checksum mismatch/);
    expect(fs.existsSync(path.join(dir, 'vstudio-cache'))).toBe(false);
  });

  it('reports HTTP errors per group', async () => {
    const m = new AssetManager({ manifest: manifest({ files: [{ url: `${base}/missing`, dest: 'a', sha256: sha, size: 1 }] }), dir: tmp(), target: 'x' });
    expect((await m.install()).groups[0].error).toMatch(/HTTP 404/);
  });

  it('refuses paths that escape the root', () => {
    expect(() => safeRel('../x')).toThrow();
    expect(() => safeRel('a/../../x')).toThrow();
    expect(() => safeRel('C:\\x')).toThrow();
    expect(safeRel('./a/b')).toBe('a/b');
  });
});

describe('bundled runtime', () => {
  it('is found only when packaged or DESK_RUNTIME_DIR is set, and only if complete', () => {
    const root = tmp();
    expect(findBundledRuntime(root, false, {})).toBeNull();
    fs.mkdirSync(path.join(root, 'runtime', 'python', 'bin'), { recursive: true });
    fs.mkdirSync(path.join(root, 'runtime', 'vstudio', 'lib', 'vstudio'), { recursive: true });
    fs.writeFileSync(path.join(root, 'runtime', 'python', 'bin', 'python3'), '');
    expect(findBundledRuntime(root, true, {})).toBeNull(); // no runtime.json
    fs.writeFileSync(
      path.join(root, 'runtime', 'runtime.json'),
      JSON.stringify({ target: 'darwin-arm64', python: '3.12', vstudioCommit: 'abc', ffmpeg: 'x', h264Encoder: 'h264_videotoolbox', asr: 'mlx', builtAt: '' }),
    );
    const rt = findBundledRuntime(root, true, {})!;
    expect(rt.python).toBe(path.join(root, 'runtime', 'python', 'bin', 'python3'));
    expect(findBundledRuntime('/nowhere', false, { DESK_RUNTIME_DIR: path.join(root, 'runtime') })?.root).toBe(path.join(root, 'runtime'));
    const e = runtimeEnv(rt, {});
    expect(e.env).toMatchObject({
      VSTUDIO_H264_ENCODER: 'h264_videotoolbox',
      VSTUDIO_FFMPEG: path.join(rt.ffmpegBin, 'ffmpeg'),
      VSTUDIO_FFPROBE: path.join(rt.ffmpegBin, 'ffprobe'),
      PYTHONNOUSERSITE: '1',
      PYTHONDONTWRITEBYTECODE: '1',
    });
    expect(e).not.toHaveProperty('pythonPath'); // the engine owns the encoder now: no sitecustomize shim
    expect(runtimeEnv(rt, { DESK_H264_ENCODER: 'libx264' }).env.VSTUDIO_H264_ENCODER).toBe('libx264');
    expect(runtimeEnv(rt, { VSTUDIO_H264_ENCODER: 'h264_mf', DESK_H264_ENCODER: 'libx264' }).env.VSTUDIO_H264_ENCODER).toBe('h264_mf');
    const win = { ...rt, manifest: { ...rt.manifest, target: 'win32-x64' } };
    expect(runtimeEnv(win, {}).env.VSTUDIO_FFMPEG).toBe(path.join(rt.ffmpegBin, 'ffmpeg.exe'));
    expect(e.path).toEqual([rt.ffmpegBin]);
  });

  it('prependPath keeps a single PATH key whatever its case', () => {
    const out = prependPath({ Path: 'b', X: '1' }, ['a']);
    expect(Object.keys(out).filter((k) => k.toUpperCase() === 'PATH')).toEqual(['Path']);
    expect(out.Path).toBe(['a', 'b'].join(path.delimiter));
  });
});
