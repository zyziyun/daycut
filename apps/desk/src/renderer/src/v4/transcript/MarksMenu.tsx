// The transcript's filter chips (ux/text-edit 02): Fillers n / Pauses n / Typos n. Each opens a menu: fillers grouped
// by word with how many seconds they save and "Remove all 那个 (4)", one button for all of them; pauses tightened to
// 0.25 s (never removed); words the transcription was unsure of. ↑ ↓ step through them in the text.
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Scissors, Wand2 } from 'lucide-react';
import type { OutputDoc, TextMark } from '../../../../shared/v04';
import { fmtClock, t } from '../../i18n';
import { addGaps, addWords, type Drafts } from '../../lib/transcript';

type Kind = 'filler' | 'pause' | 'lowconf';

export function MarksChips({ doc, drafts, setDrafts, onJump }: { doc: OutputDoc; drafts: Drafts; setDrafts: (f: (d: Drafts) => Drafts) => void; onJump: (i: number) => void }) {
  const [open, setOpen] = useState<Kind | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const cutWords = useMemo(() => {
    const s = new Set<number>();
    doc.words.forEach((w, i) => {
      const mid = (w.t + w.te) / 2;
      if (doc.cuts.some((c) => mid >= c.start && mid <= c.end)) s.add(i);
    });
    return s;
  }, [doc.words, doc.cuts]);
  const marks = (doc.marks ?? []).filter((m) => !cutWords.has(m.i0));
  const of = (k: Kind) => marks.filter((m) => m.kind === k && (k !== 'filler' || !(m.i0 in drafts.words)) && (k !== 'pause' || !drafts.gaps.includes(m.i0)));
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(null);
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [open]);
  const chip = (k: Kind, label: string) => {
    const n = of(k).length;
    const all = marks.filter((m) => m.kind === k).length;
    if (!all) return null;
    return (
      <button className={`chip tp-chip ${open === k ? 'on' : ''}`} onClick={() => setOpen(open === k ? null : k)} aria-expanded={open === k} data-testid={`marks-${k}`}>
        {label} <b className="num">{n}</b>
        <ChevronDown className="ico" />
      </button>
    );
  };
  return (
    <div className="tp-chips" ref={box}>
      {chip('filler', t('te.chip.fillers'))}
      {chip('pause', t('te.chip.pauses'))}
      {chip('lowconf', t('te.chip.typos'))}
      {open && <MarksMenu kind={open} marks={of(open)} doc={doc} onClose={() => setOpen(null)} onJump={onJump} setDrafts={setDrafts} />}
    </div>
  );
}

function MarksMenu({ kind, marks, doc, onClose, onJump, setDrafts }: { kind: Kind; marks: TextMark[]; doc: OutputDoc; onClose: () => void; onJump: (i: number) => void; setDrafts: (f: (d: Drafts) => Drafts) => void }) {
  const [k, setK] = useState(-1);
  const groups = useMemo(() => {
    const m = new Map<string, TextMark[]>();
    for (const x of marks) m.set(x.group, [...(m.get(x.group) ?? []), x]);
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [marks]);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        const n = marks.length;
        if (!n) return;
        const next = (k + (e.key === 'ArrowDown' ? 1 : -1) + n) % n;
        setK(next);
        onJump(marks[next].i0);
      } else if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', on, true);
    return () => window.removeEventListener('keydown', on, true);
  }, [k, marks, onJump, onClose]);
  const save = (xs: TextMark[]) => xs.reduce((s, x) => s + x.save_s, 0);
  const removeWords = (xs: TextMark[]) => {
    setDrafts((d) => addWords(d, xs.flatMap((x) => Array.from({ length: x.i1 - x.i0 + 1 }, (_, j) => x.i0 + j)), 'filler'));
    onClose();
  };
  const tighten = (xs: TextMark[]) => {
    setDrafts((d) => addGaps(d, xs.map((x) => x.i0)));
    onClose();
  };
  return (
    <div className="tp-menu" role="menu" data-testid={`marks-menu-${kind}`}>
      <div className="hd muted">{kind === 'filler' ? t('te.menu.fillers') : kind === 'pause' ? t('te.menu.pauses') : t('te.menu.typos')}</div>
      {!marks.length && <div className="muted row1">{t('te.menu.none')}</div>}
      {kind === 'filler' &&
        groups.map(([g, xs]) => (
          <div key={g} className="row1 grp" data-testid="marks-group">
            <b lang="zh-CN">{xs[0].text}</b>
            <span className="muted num">×{xs.length}</span>
            <span className="sp" />
            <span className="muted num">−{save(xs).toFixed(1)} s</span>
            <button className="link" onClick={() => removeWords(xs)} data-testid="marks-remove-group">
              {t('te.menu.removeAll', { w: xs[0].text, n: xs.length })}
            </button>
          </div>
        ))}
      {kind === 'pause' &&
        marks.slice(0, 8).map((x) => (
          <button key={x.i0} className="row1 grp" onClick={() => onJump(x.i0)}>
            <span className="num">{fmtClock(doc.words[x.i0]?.te ?? 0)}</span>
            <span className="muted">{x.text}</span>
            <span className="sp" />
            <span className="muted num">−{x.save_s.toFixed(1)} s</span>
          </button>
        ))}
      {kind === 'lowconf' &&
        marks.slice(0, 12).map((x) => (
          <button key={x.i0} className="row1 grp" onClick={() => onJump(x.i0)}>
            <b lang="zh-CN">{x.text}</b>
            <span className="sp" />
            <span className="muted num">{fmtClock(doc.words[x.i0]?.t ?? 0)}</span>
          </button>
        ))}
      <div className="ft">
        <span className="muted">
          <span className="kbd">↑</span>
          <span className="kbd">↓</span> {t('te.menu.next')}
        </span>
        <span className="sp" />
        {kind === 'filler' && marks.length > 0 && (
          <button className="btn primary sm" onClick={() => removeWords(marks)} data-testid="marks-remove-all">
            <Scissors className="ico" />
            {t('te.menu.removeAllN', { n: marks.length })}
          </button>
        )}
        {kind === 'pause' && marks.length > 0 && (
          <button className="btn primary sm" onClick={() => tighten(marks)} data-testid="marks-tighten-all">
            <Wand2 className="ico" />
            {t('te.menu.tightenAll', { n: marks.length })}
          </button>
        )}
      </div>
    </div>
  );
}
