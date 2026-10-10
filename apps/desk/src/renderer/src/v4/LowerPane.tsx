// The editor's lower pane (ux/text-edit): Transcript | Timeline tabs (⌘E; both show the same pending cuts), the
// transcript's filter chips, find (⌘F), and the three layout presets (⌘1 watch · ⌘2 balanced · ⌘3 edit).
import { useEffect, useRef, type ReactNode } from 'react';
import { AlignLeft, PanelBottom, PanelTop, Rows2, Scissors, Search, Table2, X } from 'lucide-react';
import { t } from '../i18n';
import type { LowerTab, Preset } from '../lib/useSplit';
import { keyHint } from '../lib/keys';

export function LowerPane({
  tab,
  onTab,
  preset,
  onPreset,
  chips,
  search,
  children,
  footer,
}: {
  tab: LowerTab;
  onTab: (t: LowerTab) => void;
  preset: Preset | null;
  onPreset: (p: Preset) => void;
  chips?: ReactNode;
  search?: { open: boolean; q: string; n: number; setOpen: (v: boolean) => void; setQ: (q: string) => void; next: () => void; cutAll: () => void } | null;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const inp = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (search?.open) inp.current?.focus();
  }, [search?.open]);
  const P: [Preset, typeof PanelTop, string][] = [
    ['watch', PanelBottom, `${t('te.preset.watch')} · ${keyHint('⌘1')}`],
    ['balanced', Rows2, `${t('te.preset.balanced')} · ${keyHint('⌘2')}`],
    ['edit', PanelTop, `${t('te.preset.edit')} · ${keyHint('⌘3')}`],
  ];
  return (
    <section className="lp" data-testid="lower-pane" data-tab={tab}>
      <div className="lp-bar">
        <div className="seg lp-tabs" role="tablist">
          <button role="tab" aria-selected={tab === 'transcript'} className={tab === 'transcript' ? 'on' : ''} onClick={() => onTab('transcript')} data-tip={`${t('te.tab.transcript')} · ${keyHint('⌘E')}`} data-testid="tab-transcript">
            <AlignLeft className="ico" />
            {t('te.tab.transcript')}
          </button>
          <button role="tab" aria-selected={tab === 'timeline'} className={tab === 'timeline' ? 'on' : ''} onClick={() => onTab('timeline')} data-tip={`${t('te.tab.timeline')} · ${keyHint('⌘E')}`} data-testid="tab-timeline">
            <Table2 className="ico" />
            {t('te.tab.timeline')}
          </button>
        </div>
        {tab === 'transcript' && chips}
        <span className="sp" />
        {tab === 'transcript' && search && (
          <div className={`lp-find ${search.open ? 'open' : ''}`}>
            {search.open ? (
              <>
                <Search className="ico muted" />
                <input
                  ref={inp}
                  value={search.q}
                  placeholder={t('te.find')}
                  onChange={(e) => search.setQ(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') search.next();
                    if (e.key === 'Escape') {
                      e.stopPropagation();
                      search.setOpen(false);
                    }
                  }}
                  data-testid="find-input"
                />
                {search.q && <span className="muted num">{search.n}</span>}
                {search.n > 0 && (
                  <button className="btn ghost sm" onClick={search.cutAll} data-testid="find-cut-all">
                    <Scissors className="ico" />
                    {t('te.findCutAll', { n: search.n })}
                  </button>
                )}
                <button className="btn ghost icon sm" onClick={() => search.setOpen(false)} aria-label={t('c.close')}>
                  <X className="ico" />
                </button>
              </>
            ) : (
              <button className="btn ghost icon sm" onClick={() => search.setOpen(true)} aria-label={t('te.find')} data-tip={`${t('te.find')} · ${keyHint('⌘F')}`} data-testid="find-open">
                <Search className="ico" />
              </button>
            )}
          </div>
        )}
        <span className="lp-div" />
        <div className="lp-presets" role="group" aria-label={t('te.layout')}>
          {P.map(([k, Icon, tip]) => (
            <button key={k} className={`btn ghost icon sm ${preset === k ? 'on' : ''}`} onClick={() => onPreset(k)} aria-pressed={preset === k} aria-label={tip} data-tip={tip} data-testid={`preset-${k}`}>
              <Icon className="ico" />
            </button>
          ))}
        </div>
      </div>
      <div className="lp-body">{children}</div>
      {footer}
    </section>
  );
}
