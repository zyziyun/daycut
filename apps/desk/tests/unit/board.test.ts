// The legacy board: every job state a batch or a project run writes (vstudio.batch run, vstudio.project core)
// lands in a lane, so a real project's board never shows empty lanes while it has jobs.
import { describe, expect, it } from 'vitest';
import { setLang, tk } from '../../src/renderer/src/i18n';
import { LANES } from '../../src/renderer/src/screens/Board';

describe('board lanes', () => {
  it('show every job state the engine writes, dropped jobs aside', () => {
    const shown = LANES.flatMap((l) => l.states);
    for (const s of ['planned', 'running', 'waiting', 'interrupted', 'failed', 'done', 'needs-replan', 'approved', 'packaged']) {
      expect(shown, s).toContain(s);
    }
    expect(shown).not.toContain('dropped');
    expect(new Set(shown).size).toBe(shown.length);
  });
  it('name every lane in each language', () => {
    for (const lang of ['en', 'zh-CN', 'fr'] as const) {
      setLang(lang);
      for (const l of LANES) expect(tk(`lane.${l.key}`), `${lang} lane.${l.key}`).not.toBe(`lane.${l.key}`);
    }
    setLang('en');
  });
});
