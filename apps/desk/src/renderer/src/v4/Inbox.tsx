// Inbox (ux/home-redesign I1 / I2): every decision waiting for the creator, one list, quickest first. Left: the list
// (↑ ↓ move, ↵ accept, E open in editor). Right: the selected item - where it lives (project › clip, every mention a
// link), a before / after preview that plays 3 s around each cut, plain-language options with the recommended choice
// first (never file paths or raw numbers: the engine gives labels + choices), and ONE primary button. Resolving an
// item moves on to the next one with an Undo toast; "Review all in a row" opens the triage queue in the editor.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowRight, Check, ChevronDown, ChevronRight, FileDown, FileText, Film, Inbox as InboxIcon, Pause, Play, Sparkles } from 'lucide-react';
import type { InboxItem, InboxOption } from '../../../shared/v04';
import { fmtClock, has, intlLocale, t } from '../i18n';
import { answerOf, authorHelp, clipName, inboxClip, inboxSub, inboxTitle, issueText, keptChanged, keptOf, keptSpans, money, optionLabel, secsLabel } from '../lib/inboxView';
import { DraftPane, useDraftIt, type KeepEdits } from './DraftReview';
import { useEngine } from '../lib/engine';
import { useInbox } from '../lib/inbox';
import { clipHref, itemTarget, projectHref, startTriage, triageStep, useTriageState } from '../lib/nav';
import { go, useRouteQuery } from '../lib/router';
import { Empty, media, Sk, Thumb } from './kit';
import { FeedbackLink } from '../support/Support';
import { FailureActions, failureReason } from './Failure';
import { emsg, errText } from './msg';
import { TriageBar } from './TriageBar';
import { ImportFeedback } from './ShareDialog';
import { isTyping, useUi } from './ui';
import '../theme/uxcore.css';

export { answerOf, clipName, inboxClip, inboxSub, inboxTitle, issueText, money, optionLabel, secsLabel };

/** Resolve an item: answer, move on, Undo in the toast. Shared by the Inbox, Home rows and the editor triage card. */
export function useResolve() {
  const { client } = useEngine();
  const { reload } = useInbox();
  const ui = useUi();
  return useCallback(
    async (x: InboxItem, answer?: Record<string, unknown>) => {
      if (!client) return false;
      try {
        await client.answerInbox([x.key], answer);
        reload();
        ui.toast(t('inbox.resolved', { what: inboxTitle(x) }), {
          undo: async () => {
            await client.undoInbox([x.key]);
            reload();
          },
        });
        return true;
      } catch (e) {
        ui.toast(errText(e), { error: true });
        return false;
      }
    },
    [client, reload, ui],
  );
}

export function InboxScreen() {
  const { items, loading, doneToday, reload } = useInbox();
  // while she looks at the Inbox: a missed event (a stream reconnect, an answer that raced a run) never leaves a
  // stale list for long
  useEffect(() => {
    const id = setInterval(reload, 20000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const q = useRouteQuery();
  // the "review all in a row" queue only while the route says so (?triage=1, like the editor): a queue left through
  // the sidebar stays in sessionStorage and would otherwise put a stale "2 of 2" bar over the plain Inbox
  const queue = useTriageState();
  const triage = q.triage === '1' ? queue : null;
  const [proj, setProj] = useState<string>('');
  const [skipped, setSkipped] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);
  const [sel, setSel] = useState<string | null>(q.item ?? null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const resolve = useResolve();
  const projects = useMemo(() => [...new Map(items.filter((x) => x.project.id).map((x) => [x.project.id!, x.project.name ?? ''])).entries()], [items]);
  const shown = useMemo(() => {
    const xs = items.filter((x) => !proj || x.project.id === proj);
    return [...xs.filter((x) => !skipped.includes(x.key)), ...skipped.map((k) => xs.find((x) => x.key === k)).filter((x): x is InboxItem => !!x)];
  }, [items, proj, skipped]);
  useEffect(() => {
    if (q.item) setSel(q.item);
  }, [q.item]);
  // the selection follows the list: a resolved item hands over to the one that took its place
  const prevShown = useRef<InboxItem[]>([]);
  useEffect(() => {
    if (sel && shown.some((x) => x.key === sel)) {
      prevShown.current = shown;
      return;
    }
    const before = prevShown.current.findIndex((x) => x.key === sel);
    const next = shown[Math.max(0, Math.min(shown.length - 1, before < 0 ? 0 : before))];
    setSel(next?.key ?? null);
    prevShown.current = shown;
  }, [shown, sel]);
  const cur = shown.find((x) => x.key === sel) ?? null;
  const minutes = shown.reduce((s, x) => s + (x.minutes ?? 1), 0);
  const move = useCallback(
    (d: 1 | -1) => {
      const i = shown.findIndex((x) => x.key === sel);
      const n = shown[Math.max(0, Math.min(shown.length - 1, i + d))];
      if (n) {
        setSel(n.key);
        listRef.current?.querySelector(`[data-key="${n.key}"]`)?.scrollIntoView({ block: 'nearest' });
      }
    },
    [shown, sel],
  );
  const skip = useCallback(
    (x: InboxItem) => {
      if (triage) return triageStep(items, 1);
      const i = shown.findIndex((y) => y.key === x.key);
      const next = shown[i + 1] ?? shown[0];
      setSkipped((s) => [...s.filter((k) => k !== x.key), x.key]);
      if (next && next.key !== x.key) setSel(next.key);
    },
    [shown, triage, items],
  );
  const done = useCallback(
    async (x: InboxItem, answer?: Record<string, unknown>) => {
      if (await resolve(x, answer)) {
        setSkipped((s) => s.filter((k) => k !== x.key));
        if (triage) triageStep(items, 1, x.key);
      }
    },
    [resolve, triage, items],
  );

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector('.scrim, .ctx')) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        move(e.key === 'ArrowDown' ? 1 : -1);
      } else if ((e.key === 'e' || e.key === 'E') && cur) {
        e.preventDefault();
        location.hash = itemTarget(cur, !!triage);
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [move, cur, triage]);

  return (
    <div className="ux-inbox" data-testid="inbox">
      {triage && cur && <TriageBar item={cur} items={items} onSkip={() => skip(cur)} />}
      <div className="ux-ih">
        <div>
          <h1>{t('inbox.title')}</h1>
          <p className="muted" data-testid="inbox-summary">
            {shown.length ? t('inbox.summaryLine', { n: shown.length, m: minutes }) : t('inbox.empty')}
          </p>
        </div>
        <span className="sp" />
        <button className="btn lg" onClick={() => setImporting(true)} data-testid="feedback-import">
          <FileDown className="ico" />
          {t('feedback.import')}
        </button>
        {importing && <ImportFeedback onClose={() => setImporting(false)} />}
        {projects.length > 1 && (
          <label className="ux-select">
            <select value={proj} onChange={(e) => setProj(e.target.value)} aria-label={t('inbox.allProjects')} data-testid="inbox-project">
              <option value="">{t('inbox.allProjects')}</option>
              {projects.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
            <ChevronDown className="ico" />
          </label>
        )}
        {shown.length > 1 && !triage && (
          <button className="btn lg" onClick={() => startTriage(shown, Math.max(0, shown.findIndex((x) => x.key === sel)))} data-testid="inbox-triage">
            <Play className="ico" />
            {t('inbox.reviewAll')}
          </button>
        )}
      </div>
      {loading ? (
        <div className="ux-isplit">
          <div className="card ux-ilist">
            {[0, 1, 2].map((i) => (
              <Sk key={i} h={64} r={10} />
            ))}
          </div>
          <div className="card ux-ipv">
            <Sk h={300} r={12} />
          </div>
        </div>
      ) : !shown.length ? (
        <div style={{ maxWidth: 720 }}>
          <Empty title={t('inbox.empty')} hint={t('inbox.emptyHint')} action={<FeedbackLink />} />
        </div>
      ) : (
        <div className="ux-isplit">
          <div className="card ux-ilist" data-testid="inbox-list">
            <div className="ux-ilh muted">{t('inbox.quickestFirst')}</div>
            <div className="ux-irows" ref={listRef} role="listbox" aria-label={t('inbox.title')}>
              {shown.map((x) => (
                <InboxRow key={x.key} x={x} on={x.key === sel} skipped={skipped.includes(x.key)} onClick={() => setSel(x.key)} />
              ))}
            </div>
            {(doneToday ?? 0) > 0 && (
              <div className="ux-idone muted" data-testid="inbox-done-today">
                <Check className="ico" />
                <span>{t('inbox.doneToday', { n: doneToday ?? 0 })}</span>
                <span className="sp" />
                <ChevronRight className="ico" />
              </div>
            )}
            <div className="ux-ikeys muted">
              <span className="kbd">↑</span>
              <span className="kbd">↓</span> {t('inbox.key.move')}
              <span className="kbd">↵</span> {t('inbox.key.accept')}
              <span className="kbd">E</span> {t('inbox.key.open')}
            </div>
          </div>
          {cur && <ItemPane key={cur.key} x={cur} onDone={(a) => void done(cur, a)} onSkip={() => skip(cur)} />}
        </div>
      )}
    </div>
  );
}

function InboxRow({ x, on, skipped, onClick }: { x: InboxItem; on: boolean; skipped: boolean; onClick: () => void }) {
  const o = (x.options ?? []).find((y) => y.cover);
  const th = o?.cover ?? x.project.thumb;
  return (
    <div className={`ux-irow ${on ? 'on' : ''} ${skipped ? 'skipped' : ''}`} role="option" aria-selected={on} onClick={onClick} data-key={x.key} data-kind={x.kind} data-testid="inbox-item">
      <InboxThumb x={x} src={th} />
      <div className="tx">
        <div className="row1">
          <b className="clamp1">{inboxTitle(x)}</b>
          <span className="sp" />
          <span className="muted num mins">{t('inbox.minutes', { n: x.minutes ?? 1 })}</span>
        </div>
        <div className="muted clamp1" data-testid={x.failure ? 'inbox-failed-reason' : undefined}>
          {[x.project.name, inboxSub(x)].filter(Boolean).join(' · ')}
        </div>
      </div>
    </div>
  );
}

/** The row's picture: the clip / project cover, else a frame of the item's own recording, else an icon for what
 * the item is (never a letter of the project's name: "01-AIGC" read as a "0"). */
export function InboxThumb({ x, src }: { x: InboxItem; src?: string | null }) {
  const video = src ? null : (x.project.video ?? null);
  if (src || video) return <Thumb src={src} video={video} className="ux-ith" />;
  const Icon = x.failure || x.kind === 'failed' ? AlertTriangle : x.author ? FileText : x.kind === 'plan' || x.kind === 'needs' ? Sparkles : x.kind === 'review' || x.kind === 'publish' ? Film : InboxIcon;
  return (
    <div className={`th ux-ith ph-thumb ${x.failure || x.kind === 'failed' ? 'err' : ''}`} data-testid="inbox-thumb-icon">
      <Icon className="ico" />
    </div>
  );
}

// ---------------------------------------------------------------- the selected item
function ItemPane({ x, onDone, onSkip }: { x: InboxItem; onDone: (answer?: Record<string, unknown>) => void; onSkip: () => void }) {
  const opts = x.options ?? [];
  const [picked, setPicked] = useState<Set<string>>(() => new Set(opts.filter((o) => o.checked !== false).map((o) => o.id)));
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [act, setAct] = useState<string | null>(opts.find((o) => o.file)?.id ?? null);
  const [play, setPlay] = useState(0);
  const cur = opts.find((o) => o.id === act) ?? null;
  const confirmable = x.kind === 'confirm' || opts.length > 0 || x.code === 'inbox.spend';
  const author = x.author ?? null;
  const [edits, setEdits] = useState<KeepEdits | null>(null);
  const draftIt = useDraftIt(x.key);
  const segs = author?.review?.kind === 'keep-spans' ? (author.review.segments ?? []) : [];
  const mine = keptChanged(segs, edits);
  const primary = (): void => {
    if (x.failure) return;
    if (x.href) return void (location.hash = x.href);
    if (x.kind === 'review' && x.project.id) return go({ name: 'focus', id: x.project.id });
    if (author) {
      if (author.drafting) return;
      if (!author.review) return author.can_draft ? void draftIt() : undefined;
      // the draft as it is = the step's own default; her clicks = exactly what she keeps
      return onDone(mine ? { done: true, spans: keptSpans(segs, keptOf(segs, edits)) } : undefined);
    }
    onDone(confirmable ? answerOf(x, picked, choices) : undefined);
  };
  const primaryRef = useRef(primary);
  primaryRef.current = primary;
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey || e.key !== 'Enter') return;
      if (document.querySelector('.scrim, .ctx')) return;
      if ((e.target as HTMLElement | null)?.closest?.('button, a')) return;
      e.preventDefault();
      primaryRef.current();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);
  const where = cur ?? opts[0];
  const kept = opts.filter((o) => !o.choices?.length && picked.has(o.id)).length;
  const chosen = opts.filter((o) => o.choices?.length).map((o) => o.choices!.find((c) => c.id === (choices[o.id] ?? o.choice))?.label).filter(Boolean);
  return (
    <div className="card ux-ipv" data-testid="inbox-preview" data-kind={x.kind}>
      <div className="ux-ipv-hd">
        <nav className="ux-crumbs" aria-label={t('nav.where')}>
          {x.project.id ? (
            <a className="crumb" href={projectHref(x.project.id)} data-testid="crumb-project">
              {x.project.name}
            </a>
          ) : (
            <span className="crumb">{x.project.name}</span>
          )}
          {where?.clip_id && x.project.id && (
            <>
              <ChevronRight className="ico sep" />
              <a className="crumb" href={clipHref(x.project.id, where.clip_id, { t: where.at })} data-testid="crumb-clip">
                {where.cover && <img src={media(where.cover)} alt="" />}
                <span className="clamp1">{clipName(where) || inboxClip(x)}</span>
              </a>
            </>
          )}
        </nav>
        <span className="sp" />
        {where?.clip_id && (
          <a className="btn" href={itemTarget(x)} data-testid="inbox-open-editor">
            <ArrowRight className="ico" />
            {t('inbox.openEditor')}
            <span className="kbd">E</span>
          </a>
        )}
      </div>
      <div className="ux-ipv-title">
        <h2>{inboxTitle(x)}</h2>
        <p className="muted">{leadOf(x)}</p>
      </div>
      <div className="ux-ipv-body">
        {opts.some((o) => o.file) && (
          <div className="ux-pvcol">
            <CutPreview opts={opts} cur={cur} onPick={setAct} play={play} />
            <div className="muted ux-pvhint">{t('inbox.previewHint')}</div>
          </div>
        )}
        <div className="ux-opts" data-testid="inbox-options">
          {x.failure ? (
            <div className="ux-opt">
              <div className="ux-optt">{failureReason(x.failure)}</div>
            </div>
          ) : author ? (
            <DraftPane itemKey={x.key} a={author} edits={edits} onEdits={setEdits} />
          ) : x.kind === 'review' ? (
            <div className="col" style={{ gap: 10 }}>
              {(x.reasons ?? []).map((r) => (
                <div key={r.code} className="ux-opt" data-testid="inbox-reason">
                  <div className="ux-optt">{issueText(r.code)}</div>
                  <div className="muted">{t('inbox.inNClips', { n: r.n })}</div>
                </div>
              ))}
            </div>
          ) : (
            opts.map((o, i) => (
              <OptionCard
                key={o.id}
                o={o}
                n={i + 1}
                on={picked.has(o.id)}
                act={act === o.id}
                choice={choices[o.id] ?? o.choice ?? null}
                onToggle={(v) => setPicked((s) => {
                  const n = new Set(s);
                  if (v) n.add(o.id);
                  else n.delete(o.id);
                  return n;
                })}
                onChoice={(c) => setChoices((m) => ({ ...m, [o.id]: c }))}
                onPlay={(andPlay) => {
                  setAct(o.id);
                  if (andPlay) setPlay((n) => n + 1);
                }}
              />
            ))
          )}
        </div>
      </div>
      <div className="ux-ipv-ft">
        <button className="btn ghost lg" onClick={onSkip} data-testid="inbox-skip">
          {t('inbox.skip')}
        </button>
        <span className="sp" />
        {x.kind === 'confirm' && (
          <span className="muted" data-testid="inbox-confirm-summary">
            {[t('inbox.keptN', { n: kept }), ...chosen.map((c) => emsg(c!).toLocaleLowerCase(intlLocale()))].join(' · ')}
          </span>
        )}
        {x.failure && x.project.id ? (
          <FailureActions item={x.project.id} failure={x.failure} primary />
        ) : x.href ? (
          <a className="btn primary lg" href={x.href} data-testid="inbox-open">
            {t('inbox.openCreate')}
          </a>
        ) : author ? (
          <button className="btn primary lg" onClick={primary} disabled={!!author.drafting || (!author.review && !author.can_draft)} data-testid="inbox-confirm">
            {author.review ? <Check className="ico" /> : <Sparkles className="ico" />}
            {author.drafting ? t('draft.drafting') : !author.review ? t('draft.draftIt') : mine ? t('draft.acceptMine') : t('draft.accept')}
            <span className="kbd on">↵</span>
          </button>
        ) : (
          <button className="btn primary lg" onClick={primary} data-testid="inbox-confirm">
            <Check className="ico" />
            {x.kind === 'confirm'
              ? t('inbox.confirmEdits', { n: opts.length })
              : x.kind === 'review'
                ? t('inbox.startReview', { m: t('inbox.minutes', { n: x.minutes ?? 1 }) })
                : x.kind === 'feedback-approve'
                  ? t('inbox.markReady')
                  : x.kind === 'feedback-change'
                    ? t('inbox.feedbackDone')
                : x.code === 'inbox.spend'
                  ? t('inbox.approveSpend', { amount: money(Number(x.params.amount), String(x.params.currency ?? 'USD')) })
                  : t('inbox.continue')}
            <span className="kbd on">↵</span>
          </button>
        )}
      </div>
    </div>
  );
}

function leadOf(x: InboxItem): string {
  if (x.author) return authorHelp(x);
  if (x.kind === 'needs' && x.need) return emsg(x.need);
  if (x.kind === 'confirm') return t('inbox.confirmLead');
  if (x.kind === 'review') return x.params.total ? t('inbox.passed', { passed: x.params.passed, total: x.params.total }) : '';
  if (x.code === 'inbox.spend') return t('inbox.spendLead');
  if (x.failure) return t('inbox.failedLead');
  if (x.source === 'feedback') return t('inbox.feedbackLead');
  // an engine question the desk has words for: the title says it; the lead says which clip (never the recipe's
  // own 「确认去 filler」 label again)
  if (x.source === 'engine' && x.kind && has(`checkpoint.${x.kind}`)) return inboxClip(x);
  return x.label ? emsg(x.label) : (x.text ?? '');
}

export function OptionCard({
  o,
  n,
  on,
  act,
  choice,
  onToggle,
  onChoice,
  onPlay,
  compact,
}: {
  o: InboxOption;
  n: number;
  on: boolean;
  act: boolean;
  choice: string | null;
  onToggle: (v: boolean) => void;
  onChoice: (c: string) => void;
  /** select the option (and play its cut when the ▶ chip was pressed) */
  onPlay: (andPlay?: boolean) => void;
  compact?: boolean;
}) {
  return (
    <div className={`ux-opt ${act ? 'act' : ''} ${on ? '' : 'off'}`} onClick={() => onPlay()} data-testid="inbox-option" data-kind={o.kind}>
      <div className="ux-opth">
        <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} onClick={(e) => e.stopPropagation()} aria-label={optionLabel(o)} data-testid="inbox-option-check" />
        <span className="ux-n">{n}</span>
        <div className="ux-optx">
          <div className="ux-optt">
            {optionLabel(o)}
            {o.at != null && !compact && o.choices?.length ? <span className="muted num"> · {fmtClock(o.at)}</span> : null}
          </div>
          {!compact && o.detail && <div className="muted">{emsg(o.detail)}</div>}
          {!compact && o.quote && !o.choices?.length && (
            <div className="ux-quote clamp1" lang="zh-CN">
              「{o.quote}」
            </div>
          )}
        </div>
        {!o.choices?.length && o.secs != null && (
          <button
            className="ux-secs"
            onClick={(e) => {
              e.stopPropagation();
              onPlay(true);
            }}
            disabled={!o.file}
            aria-label={t('inbox.playCut')}
            title={o.approx ? t('inbox.aboutSecs', { s: Math.round(Math.abs(o.secs)) }) : undefined}
            data-testid="inbox-option-play"
          >
            {o.file ? <Play className="ico" /> : null}
            {secsLabel(o)}
          </button>
        )}
        {compact && act && <span className="muted">{t('inbox.playing')}</span>}
      </div>
      {o.choices?.length ? (
        <div className="ux-choices" role="radiogroup" onClick={(e) => e.stopPropagation()}>
          {o.choices.map((c) => (
            <label key={c.id} className={`ux-choice ${choice === c.id ? 'on' : ''}`} data-testid="inbox-choice">
              <input type="radio" name={`ch-${o.id}`} checked={choice === c.id} onChange={() => onChoice(c.id)} />
              <span>{emsg(c.label)}</span>
              {c.secs != null && <span className="muted num">{Math.round(c.secs)} s</span>}
              <span className="sp" />
              {c.recommended && !compact && <span className="ux-rec">{t('inbox.recommended')}</span>}
            </label>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- before / after, 3 s each side of the cut
export function CutPreview({ opts, cur, onPick, play = 0 }: { opts: InboxOption[]; cur: InboxOption | null; onPick: (id: string) => void; play?: number }) {
  const v = useRef<HTMLVideoElement | null>(null);
  const autoplay = useRef(false);
  const [side, setSide] = useState<'before' | 'after'>('after');
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  // free = she dragged or clicked the bar: play from there and stop looping the 6 s window until the next cut is picked
  const [free, setFree] = useState(false);
  const bar = useRef<HTMLDivElement | null>(null);
  const o = cur ?? opts.find((x) => x.file) ?? null;
  const canBefore = !!o?.before?.file;
  const showSide = side === 'before' && canBefore ? 'before' : 'after';
  const src = showSide === 'before' ? o?.before?.file : o?.file;
  const at = (showSide === 'before' ? o?.before?.at : o?.at) ?? 0;
  const a = Math.max(0, at - 3);
  const b = o?.at == null && o?.before?.at == null ? Number.POSITIVE_INFINITY : at + 3; // a whole video (e.g. before publishing) plays through
  const idx = o ? opts.indexOf(o) + 1 : 0;
  const sameClip = opts.filter((x) => x.file && x.file === o?.file && x.at != null);
  useEffect(() => {
    if (play) autoplay.current = true;
  }, [play]);
  useEffect(() => setFree(false), [src, a]);
  const seekTo = (clientX: number) => {
    const el = v.current;
    const r = bar.current?.getBoundingClientRect();
    if (!el || !r || !dur) return;
    const tt = Math.min(Math.max((clientX - r.left) / r.width, 0), 1) * dur;
    el.currentTime = tt;
    setTime(tt);
    setFree(true);
  };
  useEffect(() => {
    const el = v.current;
    if (!el) return;
    // the window around the cut is ready; it plays when she asks (▶ here or on an option), never by itself
    const go = () => {
      el.currentTime = a;
      if (autoplay.current) void el.play().catch(() => undefined);
      autoplay.current = false;
    };
    if (el.readyState >= 1) go();
    else el.addEventListener('loadedmetadata', go, { once: true });
    return () => el.removeEventListener('loadedmetadata', go);
  }, [src, a, play]);
  return (
    <div className="ux-cutpv" data-testid="cut-preview" data-side={showSide}>
      <div className="ux-cutpv-stage">
        {src ? (
          <video
            ref={v}
            src={media(src)}
            muted={false}
            playsInline
            preload="auto"
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onLoadedMetadata={(e) => setDur((e.target as HTMLVideoElement).duration || 0)}
            onTimeUpdate={(e) => {
              const el = e.target as HTMLVideoElement;
              setTime(el.currentTime);
              if (!free && (el.currentTime >= b || (dur && el.currentTime >= dur - 0.05))) el.currentTime = a; // loop the 6 s window
            }}
            onClick={() => (v.current?.paused ? void v.current.play().catch(() => undefined) : v.current?.pause())}
            data-testid="cut-preview-video"
          />
        ) : (
          <div className="ph-thumb" style={{ width: '100%', height: '100%' }} />
        )}
        <div className="ux-ba" role="tablist">
          <button role="tab" aria-selected={showSide === 'before'} className={showSide === 'before' ? 'on' : ''} disabled={!canBefore} title={canBefore ? undefined : t('inbox.noBefore')} onClick={() => setSide('before')} data-testid="cut-before">
            {t('inbox.before')}
          </button>
          <button role="tab" aria-selected={showSide === 'after'} className={showSide === 'after' ? 'on' : ''} onClick={() => setSide('after')} data-testid="cut-after">
            {t('inbox.after')}
          </button>
        </div>
        {idx > 0 && <span className="ux-editn">{t('inbox.editN', { n: idx })}</span>}
        <div className="ux-pvctl">
          <button className="ux-pvplay" onClick={() => (v.current?.paused ? void v.current.play().catch(() => undefined) : v.current?.pause())} aria-label={playing ? t('player.pause') : t('player.play')}>
            {playing ? <Pause className="ico" /> : <Play className="ico" />}
          </button>
          <span className="num">{fmtClock(time)}</span>
          <div
            className="ux-pvbar"
            ref={bar}
            role="slider"
            aria-label={t('player.seek')}
            aria-valuemin={0}
            aria-valuemax={Math.round(dur)}
            aria-valuenow={Math.round(time)}
            tabIndex={0}
            data-testid="cut-preview-bar"
            onPointerDown={(e) => {
              if ((e.target as HTMLElement).closest('.dia')) return; // the diamonds pick a cut
              e.currentTarget.setPointerCapture(e.pointerId);
              seekTo(e.clientX);
            }}
            onPointerMove={(e) => {
              if (e.currentTarget.hasPointerCapture(e.pointerId)) seekTo(e.clientX);
            }}
            onKeyDown={(e) => {
              const el = v.current;
              if (!el || !dur) return;
              const step = e.shiftKey ? 5 : 1;
              if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                el.currentTime = Math.min(Math.max(el.currentTime + (e.key === 'ArrowRight' ? step : -step), 0), dur);
                setTime(el.currentTime);
                setFree(true);
              }
            }}
          >
            {dur > 0 && <i className="win" style={{ left: `${(a / dur) * 100}%`, width: `${((Math.min(b, dur) - a) / dur) * 100}%` }} />}
            {dur > 0 && <i className="head" style={{ left: `${(time / dur) * 100}%` }} />}
            {showSide === 'after' &&
              dur > 0 &&
              sameClip.map((x) => (
                <button key={x.id} className={`dia ${x.id === o?.id ? 'on' : ''}`} style={{ left: `${((x.at ?? 0) / dur) * 100}%` }} onClick={() => onPick(x.id)} aria-label={t('inbox.editN', { n: opts.indexOf(x) + 1 })} />
              ))}
          </div>
          <span className="num">{fmtClock(dur)}</span>
        </div>
      </div>
    </div>
  );
}

/** Minutes left in the queue, rounded the way the header says it ("about 12 min"). */
export function queueMinutes(items: InboxItem[]): number {
  return items.reduce((s, x) => s + (x.minutes ?? 1), 0);
}

