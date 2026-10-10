// The shot board (C05): every shot's frame, action and line, and what makes it (the popover lists each way with its
// price and why). The routing line sums up the policy; the ask bar changes routes in plain words (preview, then apply).
import { useEffect, useRef, useState } from 'react';
import { Check, SlidersHorizontal, TriangleAlert } from 'lucide-react';
import type { EpisodeView, Shot } from '../../../../shared/create';
import { swatch } from '../../../../shared/create';
import { t } from '../../i18n';
import { Seg } from '../../v4/kit';
import { msgText, useAction, useCreate } from '../api';
import { AskBar, priceText, sourceLabel, SrcChip, Still } from '../bits';
import { svc } from '../series/MakingView';

function policyName(v: string | boolean | undefined): string {
  const s = String(v ?? '');
  if (s === 'cheapest') return t('create.board.cheapest');
  if (s === 'record') return t('create.route.record');
  if (s === 'card') return t('create.route.card');
  if (s.startsWith('local')) return t('create.board.thisComputer');
  const prov = s.replace(/^cloud:|^manual:/, '').split('/')[0];
  if (prov === 'kling-mcp') return `${svc('kling-mcp')} 3.0`;
  if (prov === 'minimax') return `${svc('minimax')} 02`;
  return svc(prov);
}

export function ShotBoard({ ep, onChanged, askRef }: { ep: EpisodeView; onChanged: (v?: EpisodeView) => void; askRef?: React.MutableRefObject<((text: string) => void) | null> }) {
  const c = useCreate();
  const [open, setOpen] = useState<string | null>(null);
  const [mode, setMode] = useState<'grid' | 'list'>('grid');
  const [preview, setPreview] = useState<{ text: string; changes: { no: string; from: string; to: string }[] } | null>(null);
  const act = useAction();
  const ask = useAction();
  const boardRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (open && boardRef.current && !(e.target as HTMLElement).closest('.cr-popover, .cr-src')) setOpen(null);
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [open]);

  const route = (text: string) =>
    ask.run(async () => {
      if (!c) return;
      const r = await c.route(ep.id, text, false);
      setPreview({ text, changes: r.changes });
    });
  if (askRef) askRef.current = (text: string) => void route(text);

  const pol = ep.policy;
  return (
    <div ref={boardRef}>
      <div className="cr-routing" data-testid="create-routing">
        <SlidersHorizontal className="ico" />
        <span>{t('create.board.routing')}</span>
        <b>
          {t('create.board.faces')} → {policyName(pol.faces)}
        </b>
        <span>·</span>
        <b>
          {t('create.board.noFaces')} → {policyName(pol.no_faces)}
        </b>
        <span>·</span>
        <b>
          {t('create.board.drafts')} → {ep.ladder?.drafts === 'skipped' ? t('create.board.skip') : t('create.board.thisComputer')}
        </b>
        <button className="link" onClick={() => document.querySelector<HTMLInputElement>('[data-testid="create-board-ask"]')?.focus()}>
          {t('create.board.change')}
        </button>
        <Seg value={mode} onChange={setMode} options={[{ v: 'grid', label: t('create.board.grid') }, { v: 'list', label: t('create.board.list') }]} />
      </div>
      {ep.warnings.map((w, i) => (
        <div key={i} className="cr-warn" data-testid="create-board-warning">
          <TriangleAlert className="ico" />
          <span>{msgText(w)}</span>
        </div>
      ))}
      {mode === 'grid' ? (
        <div className="cr-grid" data-testid="create-board">
          {ep.shots.map((s) => (
            <ShotCard key={s.no} s={s} open={open === s.no} onOpen={() => setOpen(open === s.no ? null : s.no)} onPick={(src) => pick(s, src)} />
          ))}
        </div>
      ) : (
        <div className="cr-list" data-testid="create-board">
          {ep.shots.map((s) => (
            <div key={s.no} className="row">
              <b className="num">{s.no}</b>
              {s.still ? <Still src={s.still} /> : <span />}
              <div>
                <div>{s.card ?? s.action}</div>
                {s.lines[0] && <div className="muted">{t('create.board.line', { text: s.lines[0].text })}</div>}
              </div>
              <div style={{ position: 'relative' }}>
                <SrcChip r={s.route} onClick={() => setOpen(open === s.no ? null : s.no)} />
                {open === s.no && <SourcePopover s={s} onPick={(src) => pick(s, src)} />}
              </div>
            </div>
          ))}
        </div>
      )}
      {preview && (
        <div className="cr-preview" data-testid="create-route-preview">
          <span>{preview.changes.length ? t('create.board.preview', { n: preview.changes.length, list: preview.changes.map((x) => x.no).join(', ') }) : t('create.board.noChange')}</span>
          <span className="sp" />
          <button className="btn ghost" onClick={() => setPreview(null)}>
            {t('create.board.discard')}
          </button>
          {preview.changes.length > 0 && (
            <button
              className="btn primary"
              onClick={() =>
                void ask.run(async () => {
                  if (!c) return;
                  const r = await c.route(ep.id, preview.text, true);
                  setPreview(null);
                  onChanged(r.view ?? undefined);
                })
              }
              data-testid="create-route-apply"
            >
              {t('create.board.apply')}
            </button>
          )}
        </div>
      )}
      {(act.error || ask.error) && <div className="cr-err" style={{ marginTop: 10 }}>{act.error ?? ask.error}</div>}
      <AskBar testId="create-board-ask" placeholder={t('create.board.ask')} busy={ask.busy} onAsk={(text) => void route(text)} />
    </div>
  );

  function pick(s: Shot, src: string) {
    setOpen(null);
    if (src === s.route.source) return;
    void act.run(async () => {
      if (!c) return;
      const v = await c.setSource(ep.id, s.no, src);
      onChanged(v);
    });
  }
}

function ShotCard({ s, open, onOpen, onPick }: { s: Shot; open: boolean; onOpen: () => void; onPick: (src: string) => void }) {
  return (
    <div className={`cr-shot ${open ? 'sel' : ''}`} data-testid="create-shot" data-shot={s.no}>
      <div className="fr">
        {s.card ? <div className="cardtx">{s.card}</div> : <Still src={s.still} />}
        <span className="no">{s.no}</span>
        <span className="du">{s.dur.toFixed(1)} s</span>
      </div>
      <div className="tx clamp2">
        {s.card ? null : s.action}
        {s.lines[0] && (
          <>
            {' '}
            <q>{s.lines[0].text}</q>
          </>
        )}
      </div>
      <SrcChip r={s.route} onClick={onOpen} testId={`create-src-${s.no}`} />
      {open && <SourcePopover s={s} onPick={onPick} />}
    </div>
  );
}

function SourcePopover({ s, onPick }: { s: Shot; onPick: (src: string) => void }) {
  return (
    <div className="cr-popover" role="menu" data-testid="create-source-popover">
      <div className="hd">{t('create.board.makeWith', { no: s.no })}</div>
      {s.options.map((o) => {
        const on = o.source === s.route.source;
        const free = o.cny === 0 || o.kind === 'record' || o.kind === 'card' || o.kind === 'local';
        return (
          <button key={o.source} className={`cr-opt-row ${on ? 'on' : ''}`} onClick={() => onPick(o.source)} role="menuitem" data-testid="create-source-option" data-source={o.source}>
            <i className={`cr-sw sw-${swatch(o.kind, o.provider)}`} />
            <span style={{ minWidth: 0 }}>
              <div className="l1">{sourceLabel(o)}</div>
              <div className="l2">
                {msgText({ code: o.note, params: {} })}
                {!o.connected && ` · ${t('create.board.notConnected')}`}
              </div>
            </span>
            <span className={`pr ${free ? 'free' : ''}`}>
              {free ? t('create.plan.free') : priceText(o.cny, o.kind)}
              {on && <Check className="ico" />}
            </span>
          </button>
        );
      })}
    </div>
  );
}
