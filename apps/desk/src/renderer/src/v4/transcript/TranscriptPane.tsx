// The transcript as the place to edit (ux/text-edit §2.2, Descript mode): paragraphs with their start time, the word
// being said highlighted (the pane follows while playing; a manual scroll pauses that for 5 s), click a word to seek,
// drag / Shift-click to select whole words, Delete marks them as a pending cut (struck through, still there, skipped
// while previewing), Restore on hover, fillers as grey chips and pauses as dashed chips, low-confidence words with a
// dotted underline, caption-only fixes with a teal underline (E / double-click), applied cuts collapsed to a small
// "✂ cut 2.7 s" marker. Words are spans with data-i; the selection is word indices, never the browser's.
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AudioLines, Pencil, Play, RotateCcw, Scissors, Trash2 } from 'lucide-react';
import type { OutputDoc, TextMark, Word } from '../../../../shared/v04';
import type { TranscribeState } from '../../../../shared/timeline';
import { fmtClock, t } from '../../i18n';
import { appliedRuns, draftSpans, joinWords, paragraphs, selectionInfo, spaceBefore, toggleGap, toggleRange, wordIndexAt, type Drafts } from '../../lib/transcript';
import { listenEstimate } from '../../lib/timeline';
import { FixWordPopover } from './FixWordPopover';
import { TranscriptMinimap } from './TranscriptMinimap';
import './transcript.css';

export interface TranscriptApi {
  /** scroll a word into view (and select it when `select`) */
  reveal(i: number, select?: boolean): void;
  hasSelection(): boolean;
}

interface Props {
  doc: OutputDoc;
  time: number;
  playing: boolean;
  drafts: Drafts;
  setDrafts: (f: (d: Drafts) => Drafts) => void;
  seek: (t: number) => void;
  playFrom: (t: number) => void;
  fixed: Record<number, string>;
  canFix: boolean;
  fixWhyNot?: string;
  onFix: (i: number, text: string) => Promise<boolean>;
  onRestoreCut: (index: number) => void;
  transcribe?: { state: TranscribeState; start: () => void } | null;
  /** search hits (word indices) from the ⌘F box */
  hits?: Set<number>;
  apiRef?: React.MutableRefObject<TranscriptApi | null>;
  onSelection?: (has: boolean) => void;
  onDiscardAll?: () => void;
}

type Sel = { a: number; b: number } | null;

export function TranscriptPane(p: Props) {
  const { doc, drafts, setDrafts } = p;
  const words = doc.words;
  const body = useRef<HTMLDivElement | null>(null);
  const [sel, setSelS] = useState<Sel>(null);
  const [fix, setFix] = useState<number | null>(null);
  const [view, setView] = useState<[number, number]>([0, 0]);
  const anchor = useRef<number | null>(null);
  const dragging = useRef(false);
  const moved = useRef(false);
  const manualScroll = useRef(0);
  const escOnce = useRef(0);
  const paras = useMemo(() => paragraphs(words), [words]);
  const marks = useMemo(() => doc.marks ?? [], [doc.marks]);
  const fillers = useMemo(() => new Set(marks.filter((m) => m.kind === 'filler').flatMap((m) => range(m.i0, m.i1))), [marks]);
  const lowconf = useMemo(() => new Set([...marks.filter((m) => m.kind === 'lowconf').flatMap((m) => range(m.i0, m.i1)), ...words.flatMap((w, i) => (w.p != null && w.p < 0.5 ? [i] : []))]), [marks, words]);
  const pauses = useMemo(() => new Map(marks.filter((m) => m.kind === 'pause').map((m) => [m.i0, m] as [number, TextMark])), [marks]);
  const applied = useMemo(() => appliedRuns(words, doc.cuts), [words, doc.cuts]);
  const hidden = useMemo(() => {
    const s = new Set<number>();
    for (const r of applied.values()) for (let i = r.i0; i <= r.i1; i++) s.add(i);
    return s;
  }, [applied]);
  const setSel = useCallback(
    (s: Sel) => {
      setSelS(s);
      p.onSelection?.(!!s);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [p.onSelection],
  );
  const lo = sel ? Math.min(sel.a, sel.b) : -1;
  const hi = sel ? Math.max(sel.a, sel.b) : -1;

  // ---------------------------------------------------------------- the word being said (imperative: no re-render)
  const curRef = useRef(-1);
  useEffect(() => {
    const el = body.current;
    if (!el) return;
    const i = wordIndexAt(words, p.time);
    const inWord = i >= 0 && p.time <= words[i].te + 0.15;
    const next = inWord ? i : -1;
    if (next === curRef.current) return;
    el.querySelector('.w.cur')?.classList.remove('cur');
    el.querySelector('.para.on')?.classList.remove('on');
    curRef.current = next;
    if (next < 0) return;
    const w = el.querySelector(`.w[data-i="${next}"]`);
    w?.classList.add('cur');
    w?.closest('.para')?.classList.add('on');
    if (p.playing && w && Date.now() - manualScroll.current > 5000) {
      const r = w.getBoundingClientRect();
      const b = el.getBoundingClientRect();
      if (r.top < b.top + 40 || r.bottom > b.bottom - 80) (w as HTMLElement).scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [p.time, p.playing, words]);

  // ---------------------------------------------------------------- the visible stretch (for the minimap)
  const measure = useCallback(() => {
    const el = body.current;
    if (!el || !paras.length) return;
    const top = el.scrollTop;
    const bottom = top + el.clientHeight;
    const nodes = el.querySelectorAll<HTMLElement>('.para');
    let a = paras[0].t;
    let b = doc.duration;
    let first = true;
    nodes.forEach((n, k) => {
      const y0 = n.offsetTop;
      const y1 = y0 + n.offsetHeight;
      if (y1 >= top && first) {
        a = paras[k]?.t ?? a;
        first = false;
      }
      if (y0 <= bottom) b = words[paras[k]?.i1 ?? 0]?.te ?? b;
    });
    setView([a, Math.max(a, b)]);
  }, [paras, words, doc.duration]);
  useLayoutEffect(() => {
    measure();
  }, [measure]);

  const reveal = useCallback(
    (i: number, select = false) => {
      const w = body.current?.querySelector(`.w[data-i="${i}"]`) as HTMLElement | null;
      w?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      manualScroll.current = Date.now();
      if (select) setSel({ a: i, b: i });
    },
    [setSel],
  );
  useEffect(() => {
    if (p.apiRef) p.apiRef.current = { reveal, hasSelection: () => !!sel };
  });

  // ---------------------------------------------------------------- pointer selection (whole words)
  const wordOf = (e: { target: EventTarget | null }): number | null => {
    const el = (e.target as HTMLElement | null)?.closest?.('.w') as HTMLElement | null;
    return el && el.dataset.i != null ? Number(el.dataset.i) : null;
  };
  const onDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const i = wordOf(e);
    if (i == null) return;
    e.preventDefault();
    body.current?.focus({ preventScroll: true });
    if (e.shiftKey && sel) {
      setSel({ a: sel.a, b: i });
      return;
    }
    anchor.current = i;
    dragging.current = true;
    moved.current = false;
    setSel(null);
  };
  const onMove = (e: React.PointerEvent) => {
    if (!dragging.current || anchor.current == null) return;
    const i = wordOf(e);
    if (i == null) return;
    if (i !== anchor.current || moved.current) {
      moved.current = true;
      setSel({ a: anchor.current, b: i });
    }
  };
  useEffect(() => {
    const up = () => {
      if (!dragging.current) return;
      dragging.current = false;
      if (!moved.current && anchor.current != null) {
        const i = anchor.current;
        p.seek(words[i].t); // a click = go to that word
        setSel({ a: i, b: i });
      }
      anchor.current = null;
    };
    window.addEventListener('pointerup', up);
    return () => window.removeEventListener('pointerup', up);
  });

  const cut = useCallback(() => {
    if (!sel) return;
    setDrafts((d) => toggleRange(d, sel.a, sel.b, 'transcript'));
    setSel(null);
  }, [sel, setDrafts, setSel]);

  const onKey = (e: React.KeyboardEvent) => {
    if (fix != null) return;
    const mod = e.metaKey || e.ctrlKey;
    if ((e.key === 'Delete' || e.key === 'Backspace') && !mod) {
      if (sel) {
        e.preventDefault();
        cut();
      }
    } else if ((e.key === 'e' || e.key === 'E') && !mod && !e.altKey && sel) {
      e.preventDefault();
      e.stopPropagation();
      setFix(Math.min(sel.a, sel.b));
    } else if (e.key === 'Escape') {
      if (sel) {
        e.stopPropagation();
        setSel(null);
        escOnce.current = Date.now();
      } else if (Date.now() - escOnce.current < 1500 && p.onDiscardAll) {
        e.stopPropagation();
        p.onDiscardAll();
      } else escOnce.current = Date.now();
    } else if (e.key === ' ' && sel && !mod) {
      p.seek(words[Math.min(sel.a, sel.b)].t); // Space with words selected plays from them (the player toggles)
    } else if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault();
      const d = e.key === 'ArrowRight' ? 1 : -1;
      const base = sel ? sel.b : Math.max(0, wordIndexAt(words, p.time));
      const n = Math.max(0, Math.min(words.length - 1, base + d));
      setSel(e.shiftKey && sel ? { a: sel.a, b: n } : { a: n, b: n });
      if (!e.shiftKey) p.seek(words[n].t);
      reveal(n);
    }
  };

  // floating selection bar, above the first selected word
  const [barPos, setBarPos] = useState<{ x: number; y: number } | null>(null);
  useLayoutEffect(() => {
    if (!sel || !body.current) return setBarPos(null);
    const w = body.current.querySelector(`.w[data-i="${lo}"]`) as HTMLElement | null;
    if (!w) return setBarPos(null);
    setBarPos({ x: Math.max(8, w.offsetLeft - 8), y: w.offsetTop - 46 });
  }, [sel, lo]);
  const info = sel ? selectionInfo(words, lo, hi) : null;
  const allPending = sel ? range(lo, hi).every((i) => i in drafts.words) : false;
  const spans = useMemo(() => draftSpans(words, drafts), [words, drafts]);

  if (!words.length) {
    const st = p.transcribe?.state;
    return (
      <div className="tp tp-empty" data-testid="transcript">
        <div className="col" style={{ alignItems: 'center', gap: 10 }}>
          <AudioLines className="ico lg muted" />
          <span className="muted">{t('te.noWords')}</span>
          {p.transcribe && (
            <button className="btn" disabled={st?.state === 'running'} onClick={p.transcribe.start} data-testid="transcript-listen">
              {st?.state === 'running' ? t('tl.listening', { s: listenEstimate(doc.duration) }) : t('tl.listen', { s: listenEstimate(doc.duration) })}
            </button>
          )}
          {st?.state === 'failed' && <span className="drop1">{t('tl.listenFailed', { e: st.error ?? '' })}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="tp" data-testid="transcript">
      <TranscriptMinimap duration={doc.duration} time={p.time} view={view} pending={spans} applied={doc.cuts} onJump={(x) => {
        p.seek(x);
        const i = Math.max(0, wordIndexAt(words, x));
        reveal(i);
      }} />
      <div
        className="tp-body"
        ref={body}
        tabIndex={0}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onKeyDown={onKey}
        onDoubleClick={(e) => {
          const i = wordOf(e);
          if (i != null) {
            setSel({ a: i, b: i });
            setFix(i);
          }
        }}
        onScroll={() => {
          if (!dragging.current) manualScroll.current = Date.now();
          measure();
        }}
        onWheel={() => (manualScroll.current = Date.now())}
        role="textbox"
        aria-readonly
        aria-label={t('te.transcript')}
        data-testid="transcript-body"
      >
        {paras.map((pa) => (
          <Para
            key={pa.i0}
            i0={pa.i0}
            i1={pa.i1}
            t0={pa.t}
            words={words}
            sel={lo <= pa.i1 && hi >= pa.i0 ? [Math.max(lo, pa.i0), Math.min(hi, pa.i1)] : null}
            dkey={draftKeyOf(drafts, pa.i0, pa.i1)}
            drafts={drafts}
            fillers={fillers}
            lowconf={lowconf}
            pauses={pauses}
            applied={applied}
            hidden={hidden}
            fixed={p.fixed}
            hits={p.hits}
            hkey={p.hits ? hitKey(p.hits, pa.i0, pa.i1) : ''}
            onGap={(i) => setDrafts((d) => toggleGap(d, i))}
            onRestoreWords={(a, b) => setDrafts((d) => toggleRange(d, a, b))}
            onRestoreCut={p.onRestoreCut}
            onSeek={p.seek}
          />
        ))}
        {sel && barPos && info && fix == null && (
          <div className="tp-selbar" style={{ left: barPos.x, top: Math.max(0, barPos.y) }} onPointerDown={(e) => e.stopPropagation()} data-testid="selection-bar">
            <button className="danger" onClick={cut} data-testid="sel-delete">
              {allPending ? <RotateCcw className="ico" /> : <Trash2 className="ico" />}
              {allPending ? t('te.restore') : t('te.delete')}
              <span className="kbd">Del</span>
            </button>
            <button onClick={() => setFix(lo)} disabled={!p.canFix} title={p.canFix ? undefined : p.fixWhyNot} data-testid="sel-fix">
              <Pencil className="ico" />
              {t('te.fixText')}
              <span className="kbd">E</span>
            </button>
            <button onClick={() => p.playFrom(words[lo].t)} data-testid="sel-play">
              <Play className="ico" />
              {t('te.playFrom')}
              <span className="kbd">Space</span>
            </button>
            <span className="sep" />
            <span className="muted num">{t('te.selInfo', { n: info.n, s: info.secs.toFixed(1) })}</span>
          </div>
        )}
        {fix != null && words[fix] && (
          <FixWordPopover
            anchor={body.current?.querySelector(`.w[data-i="${fix}"]`) as HTMLElement | null}
            word={p.fixed[fix] ?? words[fix].w}
            original={words[fix].w}
            canFix={p.canFix}
            whyNot={p.fixWhyNot}
            onCancel={() => {
              setFix(null);
              body.current?.focus({ preventScroll: true });
            }}
            onSave={async (txt) => {
              if (await p.onFix(fix, txt)) {
                setFix(null);
                setSel(null);
                body.current?.focus({ preventScroll: true });
              }
            }}
          />
        )}
      </div>
    </div>
  );
}

const range = (a: number, b: number) => Array.from({ length: Math.max(0, b - a + 1) }, (_, k) => a + k);

function draftKeyOf(d: Drafts, a: number, b: number): string {
  let s = '';
  for (const k of Object.keys(d.words)) {
    const i = Number(k);
    if (i >= a && i <= b) s += `${i}${d.words[i][0]},`;
  }
  for (const g of d.gaps) if (g >= a && g <= b) s += `g${g},`;
  return s;
}

function hitKey(h: Set<number>, a: number, b: number): string {
  let s = '';
  for (const i of h) if (i >= a && i <= b) s += `${i},`;
  return s;
}

interface ParaProps {
  i0: number;
  i1: number;
  t0: number;
  words: Word[];
  sel: [number, number] | null;
  dkey: string;
  drafts: Drafts;
  fillers: Set<number>;
  lowconf: Set<number>;
  pauses: Map<number, TextMark>;
  applied: ReturnType<typeof appliedRuns>;
  hidden: Set<number>;
  fixed: Record<number, string>;
  hits?: Set<number>;
  hkey: string;
  onGap: (i: number) => void;
  onRestoreWords: (a: number, b: number) => void;
  onRestoreCut: (index: number) => void;
  onSeek: (t: number) => void;
}

const Para = memo(
  function Para(p: ParaProps) {
    const out: ReactNode[] = [];
    let i = p.i0;
    while (i <= p.i1) {
      const run = p.applied.get(i);
      if (run) {
        const secs = run.cut.end - run.cut.start;
        out.push(
          <span key={`c${i}`} className="cutmark" data-cut={run.cut.index} data-testid="cut-marker">
            <Scissors className="ico" />
            {t('te.cutMark', { s: secs.toFixed(1) })}
            <span className="cm-pop" onPointerDown={(e) => e.stopPropagation()}>
              <s lang="zh-CN">{joinWords(p.words, run.i0, run.i1)}</s>
              <button onClick={() => p.onRestoreCut(run.cut.index)} data-testid="cut-marker-restore">
                <RotateCcw className="ico" />
                {t('te.restore')}
              </button>
            </span>
          </span>,
        );
        i = run.i1 + 1;
        continue;
      }
      if (p.hidden.has(i)) {
        i++;
        continue;
      }
      const w = p.words[i];
      const pend = p.drafts.words[i];
      const cls = ['w'];
      if (p.fillers.has(i)) cls.push('f');
      if (pend) cls.push('p');
      if (p.lowconf.has(i)) cls.push('lc');
      if (p.fixed[i] != null) cls.push('fx');
      if (p.sel && i >= p.sel[0] && i <= p.sel[1]) cls.push('sel');
      if (p.hits?.has(i)) cls.push('hit');
      const sp = spaceBefore(p.words[i - 1], w) && i > p.i0 ? ' ' : '';
      // the first pending word of a run carries the hover Restore
      const first = pend && !p.drafts.words[i - 1];
      let end = i;
      if (first) while (p.drafts.words[end + 1] && end + 1 <= p.i1) end++;
      out.push(
        <span key={i} className={cls.join(' ')} data-i={i} lang="zh-CN">
          {sp}
          {p.fixed[i] ?? w.w}
          {first && (
            <button className="restore" onPointerDown={(e) => e.stopPropagation()} onClick={() => p.onRestoreWords(i, end)} data-testid="pending-restore">
              <RotateCcw className="ico" />
              {t('te.restore')}
            </button>
          )}
        </span>,
      );
      const gap = p.pauses.get(i);
      if (gap && i < p.i1) {
        const on = p.drafts.gaps.includes(i);
        out.push(
          <button key={`g${i}`} className={`gap ${on ? 'p' : ''}`} onPointerDown={(e) => e.stopPropagation()} onClick={() => p.onGap(i)} title={on ? t('te.pauseRestore') : t('te.pauseTighten')} data-testid="pause-chip">
            {gap.text}
          </button>,
        );
      }
      i++;
    }
    return (
      <div className="para" data-i0={p.i0}>
        <button className="pt num" onPointerDown={(e) => e.stopPropagation()} onClick={() => p.onSeek(p.t0)} tabIndex={-1}>
          {fmtClock(p.t0)}
        </button>
        <p>{out}</p>
      </div>
    );
  },
  (a, b) => a.sel?.[0] === b.sel?.[0] && a.sel?.[1] === b.sel?.[1] && a.dkey === b.dkey && a.hkey === b.hkey && a.words === b.words && a.applied === b.applied && a.fixed === b.fixed && a.fillers === b.fillers && a.lowconf === b.lowconf && a.pauses === b.pauses && a.onRestoreCut === b.onRestoreCut,
);
