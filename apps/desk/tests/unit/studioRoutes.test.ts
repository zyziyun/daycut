import { afterEach, describe, expect, it } from 'vitest';
import { href, parseRoute } from '../../src/renderer/src/lib/router';
import { setStudioPrefs } from '../../src/renderer/src/lib/studioFlag';

const P = 'abcdef012345';

describe('the Studio routes', () => {
  afterEach(() => setStudioPrefs({ studio: false }));

  it('off: the pages as before; #/studio lands on Home', () => {
    expect(parseRoute('#/')).toEqual({ name: 'home' });
    expect(parseRoute(`#/p/${P}/clip/talk`)).toEqual({ name: 'clip', id: P, clip: 'talk' });
    expect(parseRoute('#/studio')).toEqual({ name: 'home' });
    expect(href({ name: 'clip', id: P, clip: 'talk' })).toBe(`#/p/${P}/clip/talk`);
  });

  it('on: Home, the Inbox, All projects, a project and the editor open in the Studio', () => {
    setStudioPrefs({ studio: true });
    expect(parseRoute('#/')).toEqual({ name: 'studio' });
    expect(parseRoute('#/inbox')).toEqual({ name: 'studio' });
    expect(parseRoute('#/projects?sel=x')).toEqual({ name: 'studio' });
    expect(parseRoute(`#/p/${P}`)).toEqual({ name: 'studio', id: P });
    expect(parseRoute(`#/p/${P}/history`)).toEqual({ name: 'project', id: P, tab: 'history' }); // a project's details stay
    expect(parseRoute(`#/p/${P}/clip/A_换圈子?t=2`)).toEqual({ name: 'studio', id: P, clip: 'A_换圈子' });
    expect(parseRoute(`#/studio/${P}/talk`)).toEqual({ name: 'studio', id: P, clip: 'talk' });
    expect(parseRoute(`#/p/${P}/focus`)).toEqual({ name: 'focus', id: P }); // Review all in a row stays
    expect(parseRoute('#/publish')).toEqual({ name: 'calendar' });
  });

  it('on: links point at the Studio (the Inbox = its Needs you filter)', () => {
    setStudioPrefs({ studio: true });
    expect(href({ name: 'clip', id: P, clip: 'A_换圈子' })).toBe(`#/studio/${P}/A_%E6%8D%A2%E5%9C%88%E5%AD%90`);
    expect(href({ name: 'project', id: P })).toBe(`#/studio/${P}`);
    expect(href({ name: 'inbox' })).toBe('#/studio?f=you');
    expect(href({ name: 'home' })).toBe('#/studio');
    expect(href({ name: 'project', id: P, tab: 'files' })).toBe(`#/p/${P}/files`);
  });
});
