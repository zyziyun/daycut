// vsmedia:// answers byte ranges itself (206) so long outputs can be scrubbed before they are buffered.
import { describe, expect, it } from 'vitest';
import { mediaMime, parseRange } from '../../src/main/media';

describe('parseRange', () => {
  it('single ranges, open ends, suffixes', () => {
    expect(parseRange('bytes=0-99', 1000)).toEqual({ start: 0, end: 99 });
    expect(parseRange('bytes=500-', 1000)).toEqual({ start: 500, end: 999 });
    expect(parseRange('bytes=-100', 1000)).toEqual({ start: 900, end: 999 });
    expect(parseRange('bytes=900-5000', 1000)).toEqual({ start: 900, end: 999 });
  });
  it('none / unsupported -> the whole file; unsatisfiable -> invalid', () => {
    expect(parseRange(null, 1000)).toBeNull();
    expect(parseRange('bytes=0-1,5-9', 1000)).toBeNull();
    expect(parseRange('items=0-1', 1000)).toBeNull();
    expect(parseRange('bytes=1000-', 1000)).toBe('invalid');
    expect(parseRange('bytes=9-3', 1000)).toBe('invalid');
    expect(parseRange('bytes=-0', 1000)).toBe('invalid');
  });
  it('content types', () => {
    expect(mediaMime('/a/b.MP4')).toBe('video/mp4');
    expect(mediaMime('/a/sprite.jpg')).toBe('image/jpeg');
  });
});
