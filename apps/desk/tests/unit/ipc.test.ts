import { describe, expect, it } from 'vitest';
import { IPC_CHANNELS, IpcValidationError, partitionFor, validateIpc } from '../../src/shared/ipc';

const fill = { batchId: 'a1b2c3d4e5f6', code: '0123456789ab', job: 's001', platform: 'tiktok-vertical', adapterId: 'tiktok', account: 'main' };

describe('IPC validation', () => {
  it('accepts well-formed payloads', () => {
    expect(validateIpc('publish:fill', fill)).toEqual(fill);
    expect(validateIpc('dialog:openFile', { kind: 'video' })).toEqual({ kind: 'video' });
    expect(validateIpc('engine:info', undefined)).toBeUndefined();
    expect(validateIpc('publish:setBounds', { x: 0, y: 40, width: 800, height: 600 })).toBeTruthy();
  });

  it('rejects unknown channels and extra keys', () => {
    expect(() => validateIpc('fs:readFile' as never, { path: '/etc/passwd' })).toThrow(IpcValidationError);
    expect(() => validateIpc('publish:fill', { ...fill, click: true })).toThrow(/unrecognized|click/i);
  });

  it('rejects path traversal / injection in ids', () => {
    expect(() => validateIpc('publish:fill', { ...fill, batchId: '../../etc' })).toThrow();
    expect(() => validateIpc('publish:fill', { ...fill, job: '../x' })).toThrow();
    expect(() => validateIpc('publish:fill', { ...fill, account: 'Main Account' })).toThrow();
    expect(() => validateIpc('publish:fill', { ...fill, account: 'a:b' })).toThrow();
    expect(() => validateIpc('publish:fill', { ...fill, code: 'zzzz' })).toThrow();
  });

  it('only allows https URLs for external links and post URLs', () => {
    expect(() => validateIpc('shell:openExternal', { url: 'file:///etc/passwd' })).toThrow();
    expect(() => validateIpc('shell:openExternal', { url: 'javascript:alert(1)' })).toThrow();
    expect(() => validateIpc('publish:markPosted', { ...fill, url: 'http://tiktok.com/x' })).toThrow();
    expect(validateIpc('publish:markPosted', { ...fill, url: 'https://www.tiktok.com/@me/video/1' }).url).toContain('https://');
  });

  it('requires absolute paths', () => {
    expect(() => validateIpc('shell:showItem', { path: 'relative/file.mp4' })).toThrow();
    expect(() => validateIpc('settings:set', { python: 'python3' })).toThrow();
    expect(validateIpc('settings:set', { lang: 'en' })).toEqual({ lang: 'en' });
  });

  it('bounds numbers', () => {
    expect(() => validateIpc('publish:setBounds', { x: -1, y: 0, width: 1, height: 1 })).toThrow();
    expect(() => validateIpc('publish:setBounds', { x: 1.5, y: 0, width: 1, height: 1 })).toThrow();
  });

  it('has a schema for every channel and builds partitions safely', () => {
    expect(IPC_CHANNELS.length).toBeGreaterThan(15);
    expect(partitionFor('tiktok', 'main')).toBe('persist:tiktok-main');
    expect(() => partitionFor('tiktok', '../x')).toThrow();
  });
});
