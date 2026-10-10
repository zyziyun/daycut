// 「和 AI 一起改」: the clip's conversation (persisted with the clip's edit doc). What she asks for in plain words is
// applied at once (ux/fewer-steps: act, then make it undoable) - the card says what changed, with Undo and Before/after;
// only what removes a lot or cannot be taken back cheaply waits for Apply, and Settings › "Ask before applying AI
// edits" makes every change wait. Older cards collapse to one line and undo ON THEIR OWN (an older card is reverted
// alone, the later ones stay). Slash commands open the tool cards without the model.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { ArrowUp, Check, Crop, Image as ImageIcon, MessageSquare, PanelRightClose, PanelRightOpen, Scissors, Sparkles, Square, Undo2, Upload, Wand2, X } from 'lucide-react';
import type { AskContext, CardKind, ChatDoc, ChatTurn } from '../../../../shared/chatEdit';
import { providerName } from '../../../../shared/aiRoutes';
import { EngineError } from '../../../../shared/engineClient';
import type { EditOp, EffectDef } from '../../../../shared/v04';
import { fmtClock, getLang, intlLocale, t, type MessageKey } from '../../i18n';
import { askFirstReason, needsRenderedCompare, cardFor, cardState, contextOf, costLine, lengthChange, offlineFrom, slashCommand, slashMatches, suggestions, undoPlan, undoToCount, SLASH, type Primary, type Suggestion } from '../../lib/chatEdit';
import { useAskAiEdits } from '../../lib/prefs';
import { useEngine } from '../../lib/engine';
import { go } from '../../lib/router';
import { textLang } from '../../lib/transcript';
import { ProviderChip } from '../AiChip';
import { Sk } from '../kit';
import { effectLabel, emsg, errText } from '../msg';
import { useUi } from '../ui';
import { CaptionsCard, CARD_ICON, CoverCard, EffectCard, ExportCard, FallbackCard, primaryPlatform, TrimCard, type CardEnv, type ExportRun } from './cards';
import { CutCard } from './CutCard';
import './chat.css';
import { trackUsage } from '../../lib/usage';
import { keyHint } from '../../lib/keys';

export interface ChatApi {
  focus(text?: string): void;
  applyLatest(): void;
  openCard(kind: CardKind): void;
  focusTurn(id: string): void;
  escape(): boolean;
}

interface Props {
  item: string;
  clip: string;
  doc: ChatDoc;
  defs: EffectDef[];
  time: number;
  sel: { a: number; b: number } | null;
  fxSel: string | null;
  onClearSel: () => void;
  onClearFx: () => void;
  seek: (t: number) => void;
  playRange: (a: number, b: number) => void;
  reload: () => void;
  /** amber markers + the player's "after": the draft ops; compare = the split wipe is on */
  onDrafts: (d: { turn: string; ops: EditOp[] }[]) => void;
  onPreview: (p: { ops: EditOp[] | null; compare: boolean; before?: ChatDoc | null; rendered?: boolean }) => void;
  onPrimary: (p: Primary) => void;
  /** an inbox question pinned on top of the conversation (triage / arrived from the Inbox) */
  pinned?: React.ReactNode;
  /** shown in the same place when nothing is pinned: what the AI already decided on this clip */
  top?: React.ReactNode;
  /** the column folded to a 48 px rail (⌘\) */
  collapsed?: boolean;
  onToggle?: () => void;
  /** a transcript cut card's "Show in transcript" */
  onShowInTranscript?: (t: number) => void;
  /** save what the transcript has not saved yet (Export renders the cuts made a moment ago); false = it could not */
  flush?: () => Promise<boolean>;
  /** suggestions that act in the transcript without the model (fillers -> pending cuts), shown first */
  textSuggestions?: { id: string; icon: typeof Scissors; title: string; sub: string; run: () => void }[];
  /** the empty state's first line (the transcript is open: "select words and press Delete") */
  lead?: string | null;
}

interface Local {
  ops: EditOp[];
  checked: boolean[];
}

const r1 = (x: number) => fmtClock(x, true);
/** how long the panel waits for an answered /ask turn to appear in the conversation before showing an error */
const LOST_TURN_MS = 12_000;
const SUG_ICON = { pauses: Scissors, pop: Sparkles, platform: Upload, cover: ImageIcon };

export const ChatPanel = forwardRef<ChatApi, Props>(function ChatPanel(p, ref) {
  const { client, subscribe } = useEngine();
  const ui = useUi();
  const { doc, item, clip } = p;
  const turns = useMemo(() => doc.chat ?? [], [doc.chat]);
  const [local, setLocal] = useState<Record<string, Local>>({});
  const [adjust, setAdjust] = useState<{ turn: string; i: number } | null>(null);
  const [pending, setPending] = useState<{ text: string; ctx: AskContext | null; token: number; turn?: string } | null>(null);
  // /ask answered but its turn never showed up in the clip's conversation: stop the spinner and say so
  const [lost, setLost] = useState<{ text: string; ctx: AskContext | null } | null>(null);
  // Before / after: a draft's ops over the clip, or an applied change against the clip as it was before it
  const [cmp, setCmp] = useState<{ turn: string; ops: EditOp[]; before?: ChatDoc; rendered?: boolean } | null>(null);
  // the clip as it was before each change applied in this session (its Before / after)
  const [befores, setBefores] = useState<Record<string, ChatDoc>>({});
  const askAi = useAskAiEdits();
  const [conflict, setConflict] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [runs, setRuns] = useState<Record<string, ExportRun>>({});
  const [text, setText] = useState('');
  const [mi, setMi] = useState(0);
  const [hot, setHot] = useState<string | null>(null);
  const log = useRef<HTMLDivElement | null>(null);
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const tok = useRef(0);

  // a different clip: its own conversation, nothing carried over
  useEffect(() => {
    setLocal({});
    setAdjust(null);
    setPending(null);
    setCmp(null);
    setConflict({});
    setErrs({});
    setLost(null);
    setBefores({});
  }, [clip]);
  useEffect(() => {
    if (pending?.turn && turns.some((x) => x.id === pending.turn)) setPending(null);
  }, [turns, pending]);
  const reloadRef = useRef(p.reload);
  reloadRef.current = p.reload;
  useEffect(() => {
    if (!pending?.turn) return;
    const again = window.setTimeout(() => reloadRef.current(), LOST_TURN_MS / 3);
    const give = window.setTimeout(() => {
      setPending((x) => (x && x.token === pending.token ? null : x));
      setLost({ text: pending.text, ctx: pending.ctx });
    }, LOST_TURN_MS);
    return () => {
      window.clearTimeout(again);
      window.clearTimeout(give);
    };
  }, [pending]);
  const count = turns.length + (pending ? 1 : 0);
  useEffect(() => {
    log.current?.scrollTo({ top: 1e9 });
  }, [count]);
  useEffect(() => {
    if (!adjust) return;
    const el = log.current?.querySelector(`[data-turn="${adjust.turn}"]`);
    window.requestAnimationFrame(() => el?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
  }, [adjust]);

  const opsOf = useCallback((x: ChatTurn): Local => local[x.id] ?? { ops: x.proposals.map((q) => q.op), checked: x.proposals.map(() => true) }, [local]);
  const checkedOps = useCallback((x: ChatTurn) => {
    const l = opsOf(x);
    return l.ops.filter((_, i) => l.checked[i]);
  }, [opsOf]);
  const states = useMemo(() => Object.fromEntries(turns.map((x) => [x.id, cardState(x, doc)])), [turns, doc]);
  useEffect(() => {
    if (cmp?.before && states[cmp.turn] !== 'applied') setCmp(null);
  }, [cmp, states]);
  const isOpenCard = (x: ChatTurn) => !!x.card && x.card !== 'transcript' && states[x.id] === 'note' && !runs[x.id];
  const lastAi = [...turns].reverse().find((x) => x.role === 'ai');
  const offline = lastAi ? offlineFrom({ warnings: lastAi.warnings ?? [] }) : null;
  const primaryTurn = useMemo(() => {
    if (adjust) return adjust.turn;
    for (let i = turns.length - 1; i >= 0; i--) {
      const x = turns[i];
      if ((states[x.id] === 'draft' && x.proposals.length) || isOpenCard(x)) return x.id;
    }
    return null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns, states, adjust, runs]);
  const exporting = Object.values(runs).some((r) => r.state === 'running');
  const newestChange = [...turns].reverse().find((x) => x.role === 'ai' && x.proposals.length)?.id ?? null;
  const offlineCard = !!lastAi && !!offline && !lastAi.proposals.length && turns[turns.length - 1]?.id === lastAi.id;
  const primary: Primary = primaryTurn ? 'apply' : exporting ? 'none' : offlineCard ? 'connect' : 'export';
  const { onPrimary, onDrafts, onPreview } = p;
  useEffect(() => onPrimary(primary), [primary, onPrimary]);
  const drafts = useMemo(() => turns.filter((x) => states[x.id] === 'draft').map((x) => ({ turn: x.id, ops: checkedOps(x) })), [turns, states, checkedOps]);
  const dkey = JSON.stringify(drafts);
  useEffect(() => onDrafts(drafts), [dkey]); // eslint-disable-line react-hooks/exhaustive-deps
  const latestDraftOps = drafts.length ? drafts[drafts.length - 1].ops : null;
  const pkey = JSON.stringify([cmp, latestDraftOps]);
  useEffect(() => onPreview(cmp ? (cmp.before ? { ops: null, compare: true, before: cmp.before, rendered: cmp.rendered } : { ops: cmp.ops, compare: true }) : { ops: latestDraftOps, compare: false }), [pkey, cmp?.before, cmp?.rendered]); // eslint-disable-line react-hooks/exhaustive-deps

  // export progress (output-render events of this job)
  useEffect(
    () =>
      subscribe((e) => {
        if (e.type !== 'output-render' || e.item !== item || e.clip !== clip) return;
        setRuns((rs) => {
          const id = Object.keys(rs).find((k) => rs[k].job === e.job);
          if (!id) return rs;
          const r = { ...rs[id], rows: { ...rs[id].rows } };
          const order = ['canvas', 'timeline', 'audio', 'final'];
          if (e.event === 'target-start' && e.target) r.rows[e.target] = { stage: 'canvas', progress: 0.03, done: false };
          else if (e.event === 'stage-done' && e.target) {
            const nx = order[order.indexOf(e.stage ?? '') + 1] ?? 'final';
            r.rows[e.target] = { ...(r.rows[e.target] ?? { done: false }), stage: nx, progress: e.progress ?? 0.5, done: false };
          } else if (e.event === 'target-done' && e.target) r.rows[e.target] = { stage: 'final', progress: 1, done: true, file: e.file };
          else if (e.event === 'render-done') Object.assign(r, { state: 'done', simulated: e.simulated });
          else if (e.event === 'stopped') r.state = 'stopped';
          else if (e.event === 'failed') Object.assign(r, { state: 'failed', error: e.error });
          return { ...rs, [id]: r };
        });
      }),
    [subscribe, item, clip],
  );

  // ------------------------------------------------------------ actions
  const send = async (prompt: string) => {
    const q = prompt.trim();
    if (!q || !client) return;
    const kind = slashCommand(q);
    if (kind) return openCard(kind);
    const ctx = contextOf(p.sel, p.fxSel, doc);
    const token = ++tok.current;
    setLost(null);
    setPending({ text: q, ctx, token });
    setText('');
    try {
      const r = await client.askOutput(item, clip, q, ctx);
      if (tok.current !== token) return;
      // act at once, make it undoable: the change goes on the clip now (Undo / Before / after on its card); what
      // removes most of the clip or cannot be taken back cheaply - or everything, when she asked for that - waits
      const ops = (r.proposals ?? []).map((x) => x.op);
      if (r.turn && ops.length && !askAi && !askFirstReason(ops, doc)) {
        const turn = r.turn;
        setBefores((m) => ({ ...m, [turn]: doc }));
        try {
          await client.editOutput(item, clip, ops, turn);
        } catch (e) {
          setErrs((m) => ({ ...m, [turn]: errText(e) }));
        }
      }
      setPending((x) => (x && x.token === token ? { ...x, turn: r.turn ?? undefined } : x));
      p.reload();
      if (!r.turn) setPending(null);
    } catch (e) {
      if (tok.current === token) setPending(null);
      ui.toast(errText(e), { error: true });
    }
  };
  const stop = () => {
    tok.current++;
    setPending(null);
  };
  const openCard = async (kind: CardKind) => {
    if (!client) return;
    setText('');
    try {
      await client.addChatTurn(item, clip, { role: 'user', text: `/${t(`ce.cmd.${kind}` as MessageKey)}`, card: kind, status: 'note', context: contextOf(p.sel, p.fxSel, doc) });
      p.reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  const apply = async (x: ChatTurn, ops: EditOp[]) => {
    if (!client || !ops.length) return;
    setBusy(x.id);
    setErrs((m) => ({ ...m, [x.id]: '' }));
    setBefores((m) => ({ ...m, [x.id]: doc }));
    try {
      await client.editOutput(item, clip, ops, x.id);
      if (cmp?.turn === x.id) setCmp(null);
      setAdjust(null);
      p.reload();
    } catch (e) {
      setErrs((m) => ({ ...m, [x.id]: errText(e) }));
    } finally {
      setBusy(null);
    }
  };
  const setStatus = async (x: ChatTurn, status: ChatTurn['status']) => {
    if (!client) return;
    try {
      await client.updateChatTurn(item, clip, x.id, { status });
      if (cmp?.turn === x.id) setCmp(null);
      if (adjust?.turn === x.id) setAdjust(null);
      p.reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  const undo = async (x: ChatTurn) => {
    if (!client) return;
    const plan = undoPlan(x, doc);
    try {
      if (plan.kind === 'undo') await client.undoOutput(item, clip, 1);
      else if (plan.kind === 'revert') await client.revertOutput(item, clip, plan.step);
      p.reload();
    } catch (e) {
      if (e instanceof EngineError && (e.code === 'revert-conflict' || e.code === 'revert-unsupported') && x.applied_step) setConflict((m) => ({ ...m, [x.id]: undoToCount(doc, x.applied_step!) - 1 }));
      else ui.toast(errText(e), { error: true });
    }
  };
  const undoBack = async (x: ChatTurn) => {
    if (!client || !x.applied_step) return;
    try {
      await client.undoOutput(item, clip, undoToCount(doc, x.applied_step));
      setConflict((m) => ({ ...m, [x.id]: 0 }));
      p.reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  const restore = async (x: ChatTurn) => {
    if (!client || !x.reverted_by) return;
    try {
      await client.revertOutput(item, clip, x.reverted_by);
      p.reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  const startExport = async (x: ChatTurn, targets: string[], watermark?: boolean) => {
    if (!client) return;
    const prim = primaryPlatform(doc);
    const norm = (s: string) => (s === '9:16' ? 'douyin:vertical' : s === '16:9' ? 'youtube:horizontal' : s === '3:4' ? 'xiaohongshu:vertical' : s);
    const add = targets.filter((tg) => tg !== prim && !doc.exports.some((e) => norm(e.target) === tg));
    const rt = targets.map((tg) => (tg === prim ? 'primary' : tg));
    setRuns((rs) => ({ ...rs, [x.id]: { job: null, targets: rt, rows: {}, state: 'running', started: Date.now() } }));
    window.setTimeout(() => log.current?.scrollTo({ top: 1e9, behavior: 'smooth' }), 60);
    try {
      // the transcript's last deletes go into this export (saved now if the timer has not done it yet)
      if (p.flush && !(await p.flush())) throw new Error(t('fs.cut.notSaved'));
      if (add.length) await client.editOutput(item, clip, add.map((tg) => ({ op: 'export_add', target: tg, layout: doc.mode === 'flattened' && tg.endsWith(':horizontal') ? 'band' : 'auto' })), x.id);
      else await client.updateChatTurn(item, clip, x.id, { status: 'applied' });
      const j = await client.exportOutput(item, clip, rt, watermark);
      trackUsage('export_done', { count: rt.length });
      setRuns((rs) => ({ ...rs, [x.id]: { ...rs[x.id], job: j.job } }));
      p.reload();
    } catch (e) {
      setRuns((rs) => ({ ...rs, [x.id]: { ...rs[x.id], state: 'failed', error: errText(e) } }));
    }
  };
  const replaceOps = (x: ChatTurn, idx: number[], next: EditOp[]) => {
    const l = opsOf(x);
    const ops: EditOp[] = [];
    const checked: boolean[] = [];
    let placed = false;
    l.ops.forEach((o, i) => {
      if (idx.includes(i)) {
        if (!placed) next.forEach((n) => (ops.push(n), checked.push(true)));
        placed = true;
      } else {
        ops.push(o);
        checked.push(l.checked[i]);
      }
    });
    setLocal((m) => ({ ...m, [x.id]: { ops, checked } }));
    setAdjust(null);
  };

  const matches = slashMatches(text);
  const slashOpen = matches.length > 0 && text.startsWith('/');
  useImperativeHandle(ref, () => ({
    focus(s?: string) {
      if (s != null) setText(s);
      ta.current?.focus();
    },
    applyLatest() {
      const x = turns.find((y) => y.id === primaryTurn);
      if (x && states[x.id] === 'draft' && !adjust) void apply(x, checkedOps(x));
    },
    openCard: (k) => void openCard(k),
    focusTurn(id: string) {
      const el = log.current?.querySelector(`[data-turn="${id}"]`);
      el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      setHot(id);
      window.setTimeout(() => setHot((h) => (h === id ? null : h)), 1400);
    },
    escape: () => escapeOne(),
  }));
  function escapeOne(): boolean {
    {
      if (slashOpen) {
        setText('');
        return true;
      }
      if (adjust) {
        setAdjust(null);
        return true;
      }
      if (cmp) {
        setCmp(null);
        return true;
      }
      const open = [...turns].reverse().find((x) => isOpenCard(x));
      if (open) {
        void setStatus(open, 'discarded');
        return true;
      }
      return false;
    }
  }

  // ------------------------------------------------------------ rendering helpers
  const env = (x: ChatTurn | null): CardEnv => ({ doc, defs: p.defs, time: p.time, sel: p.sel, seek: p.seek, playRange: p.playRange, primary: !!x && x.id === primaryTurn });
  const lenTxt = (ops: EditOp[]) => {
    const l = lengthChange(doc, ops);
    return Math.abs(l.before - l.after) > 0.05 ? `${r1(l.before)} → ${r1(l.after)}` : '';
  };
  const subOf = (op: EditOp, why: string) => {
    const parts: string[] = [];
    if (op.op === 'cut') parts.push(`${r1(op.start)}–${r1(op.end)} · −${(op.end - op.start).toFixed(1)} s`);
    else if (op.op === 'effect_add') parts.push((op.end ?? op.start + 1.2) - op.start > doc.duration * 0.6 ? t('ce.wholeClip') : `${r1(op.start)}–${r1(op.end ?? op.start + 1.2)}`);
    else if (op.op === 'trim') parts.push(`${r1(op.start ?? 0)}–${r1(op.end ?? doc.duration)}`);
    else if (op.op === 'speed' || op.op === 'export_add' || op.op === 'caption_style') parts.push(t('ce.wholeClip'));
    if (why) parts.push(why);
    return parts.join(' · ');
  };
  const rowIcon = (op: EditOp) => {
    const k = cardFor(op);
    if (op.op === 'cut') return Scissors;
    return k ? CARD_ICON[k] : Wand2;
  };

  const changeCard = (x: ChatTurn) => {
    const l = opsOf(x);
    const on = l.ops.filter((_, i) => l.checked[i]);
    const isP = x.id === primaryTurn;
    const lt = lenTxt(on);
    const waits = askFirstReason(on, doc);
    return (
      <div className="card2 draft" data-testid="change-card">
        <div className="chd">
          <span className="ic">
            <Wand2 className="ico" />
          </span>
          <b>{t('ce.changes', { n: l.ops.length })}</b>
          <span className="pill">{t('ce.draft')}</span>
          <span style={{ flex: 1 }} />
          {lt && <span className="mono" data-testid="change-length">{lt}</span>}
        </div>
        <div className="cbd" style={{ gap: 6 }}>
          {groups(l.ops).map((g) => {
            const i = g[0];
            const op = l.ops[i];
            const pr = x.proposals[i];
            const many = g.length > 1;
            const Icon = rowIcon(op);
            const title = many ? t('ce.row.cuts', { n: g.length }) : op.op === 'effect_add' || !pr || JSON.stringify(pr.op) !== JSON.stringify(op) ? describeOp(op) : emsg(pr.describe) || op.op;
            const secs = g.reduce((s2, j) => s2 + (l.ops[j].op === 'cut' ? (l.ops[j] as { end: number }).end - (l.ops[j] as { start: number }).start : 0), 0);
            const sub = many ? t('ce.row.cutsSub', { s: secs.toFixed(1) }) : subOf(op, pr ? emsg(pr.why) : '');
            const adj = cardFor(op);
            const on1 = g.every((j) => l.checked[j]);
            return (
              <div key={i} className={`crow ${on1 ? '' : 'off'}`} data-testid="change-row">
                <input
                  type="checkbox"
                  checked={on1}
                  onChange={(e) => setLocal((m) => ({ ...m, [x.id]: { ops: l.ops, checked: l.checked.map((c, j) => (g.includes(j) ? e.target.checked : c)) } }))}
                  aria-label={title}
                  data-testid="change-check"
                />
                <span className="ic">
                  <Icon className="ico" style={{ width: 14, height: 14 }} />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="t clamp1" lang="zh-CN">{title}</div>
                  <div className="s clamp1">{sub}</div>
                </div>
                {adj && adj !== 'export' ? (
                  <button className="btn ghost sm" onClick={() => setAdjust({ turn: x.id, i })} data-testid="change-adjust">
                    {t('ce.adjust')}
                  </button>
                ) : (
                  <span />
                )}
              </div>
            );
          })}
          {errs[x.id] && <span className="drop1" data-testid="change-error">{t('ce.partial', { why: errs[x.id] })}</span>}
          {!askAi && !errs[x.id] && waits && <span className="muted" data-testid="change-waits">{t(`fs.ai.waits.${waits}` as MessageKey)}</span>}
        </div>
        <div className="cft">
          <button className={`btn ${isP ? 'primary' : ''}`} disabled={!on.length || busy === x.id} onClick={() => void apply(x, on)} data-testid="change-apply">
            {busy === x.id ? t('ce.applying') : t('ce.applyN', { n: on.length })}
          </button>
          <button
            className={`btn ${cmp?.turn === x.id ? 'toggle on' : ''}`}
            onClick={() => setCmp(cmp?.turn === x.id ? null : { turn: x.id, ops: on })}
            aria-pressed={cmp?.turn === x.id}
            disabled={!on.length}
            data-testid="change-compare"
          >
            {t('ce.compare')}
          </button>
          <span style={{ flex: 1 }} />
          <button className="btn ghost" onClick={() => void setStatus(x, 'discarded')} data-testid="change-discard">
            {t('ce.discard')}
          </button>
        </div>
      </div>
    );
  };

  /** The newest applied AI change, open: what changed, Undo, Before / after (against the clip as it was). */
  const appliedCard = (x: ChatTurn) => {
    const ops = x.proposals.map((q) => q.op);
    const before = befores[x.id];
    const l = before ? lengthChange(before as never, ops) : null;
    const lt = l && Math.abs(l.before - l.after) > 0.05 ? `${r1(l.before)} → ${r1(l.after)}` : '';
    const on = cmp?.turn === x.id;
    return (
      <div className="card2 done" data-testid="applied-card">
        <div className="chd" data-testid="applied-line">
          <span className="ic ok">
            <Check className="ico" />
          </span>
          <b>{t('fs.ai.applied', { n: x.applied_ops ?? ops.length })}</b>
          <span style={{ flex: 1 }} />
          {lt && <span className="mono">{lt}</span>}
        </div>
        <div className="cbd" style={{ gap: 6 }}>
          {groups(ops).map((g) => {
            const i = g[0];
            const op = ops[i];
            const pr = x.proposals[i];
            const Icon = rowIcon(op);
            const many = g.length > 1;
            const title = many ? t('ce.row.cuts', { n: g.length }) : op.op === 'effect_add' || !pr ? describeOp(op) : emsg(pr.describe) || describeOp(op);
            const secs = g.reduce((s2, j) => s2 + (ops[j].op === 'cut' ? (ops[j] as { end: number }).end - (ops[j] as { start: number }).start : 0), 0);
            const sub = many ? t('ce.row.cutsSub', { s: secs.toFixed(1) }) : subOf(op, pr ? emsg(pr.why) : '');
            return (
              <div key={i} className="crow done" data-testid="applied-row">
                <span className="ic">
                  <Icon className="ico" style={{ width: 14, height: 14 }} />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="t clamp1" lang="zh-CN">{title}</div>
                  <div className="s clamp1">{sub}</div>
                </div>
              </div>
            );
          })}
        </div>
        <div className="cft">
          <button className="btn" onClick={() => void undo(x)} data-tip={t('ce.undoTip')} data-testid="applied-undo">
            <Undo2 className="ico" />
            {t('ce.undo')}
          </button>
          {before && (
            <button className={`btn ${on ? 'toggle on' : ''}`} onClick={() => setCmp(on ? null : { turn: x.id, ops, before, rendered: needsRenderedCompare(ops) })} aria-pressed={on} data-tip={needsRenderedCompare(ops) ? t('fs.ai.renderedTip') : undefined} data-testid="applied-compare">
              {t('ce.compare')}
            </button>
          )}
        </div>
      </div>
    );
  };

  const doneLine = (x: ChatTurn) => {
    const st = states[x.id];
    const n = x.applied_ops ?? (x.proposals.length || 1);
    const step = doc.steps.find((s) => s.id === x.applied_step);
    const what = n === 1 && step?.describe?.length ? step.describe.map(emsg).join(' · ') : null;
    if (conflict[x.id])
      return (
        <div className="conf" data-testid="revert-conflict">
          <span>{t('ce.conflict', { n: conflict[x.id] })}</span>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn sm" onClick={() => void undoBack(x)} data-testid="undo-back">
              {t('ce.undoBack')}
            </button>
            <button className="btn ghost sm" onClick={() => setConflict((m) => ({ ...m, [x.id]: 0 }))}>
              {t('ce.keep')}
            </button>
          </div>
        </div>
      );
    if (st === 'applied')
      return (
        <div className="line1" data-testid="applied-line">
          <Check className="ico ok" />
          <b className="clamp1" lang="zh-CN">{what ?? t('ce.applied', { n })}</b>
          {x.card === 'export' ? null : (
            <button className="btn ghost sm" onClick={() => void undo(x)} data-tip={t('ce.undoTip')} data-testid="applied-undo">
              <Undo2 className="ico" />
              {t('ce.undo')}
            </button>
          )}
        </div>
      );
    if (st === 'reverted')
      return (
        <div className="line1 muted2" data-testid="reverted-line">
          <Undo2 className="ico" />
          <span>{t('ce.reverted', { n })}</span>
          {x.reverted_by && doc.steps.some((s) => s.id === x.reverted_by && !s.reverted) && (
            <button className="btn ghost sm" onClick={() => void restore(x)} data-testid="reverted-restore">
              {t('ce.restore')}
            </button>
          )}
        </div>
      );
    if (st === 'undone')
      return (
        <div className="line1 muted2" data-testid="undone-line">
          <Undo2 className="ico" />
          <span>{t('ce.undone')}</span>
        </div>
      );
    if (st === 'discarded')
      return (
        <div className="line1 muted2" data-testid="discarded-line">
          <X className="ico" />
          <span>{t('ce.notApplied')}</span>
          {(x.proposals.length > 0 || x.card) && (
            <button className="btn ghost sm" onClick={() => void setStatus(x, x.card ? 'note' : 'draft')} data-testid="restore-draft">
              {t('ce.restoreDraft')}
            </button>
          )}
        </div>
      );
    return null;
  };

  const toolCard = (x: ChatTurn, kind: CardKind, ops: EditOp[], onSubmit: (o: EditOp[]) => void, onCancel: () => void, ok?: string) => {
    const e = env(x);
    if (kind === 'effect') {
      const inst = !ops.length && p.fxSel ? doc.effects.find((f) => f.id === p.fxSel) : undefined;
      const op = ops[0] ?? (inst ? ({ op: 'effect_update', id: inst.id } as EditOp) : null);
      return <EffectCard env={e} op={op} onSubmit={onSubmit} onCancel={onCancel} okLabel={ok} onRemove={inst ? () => onSubmit([{ op: 'effect_remove', id: inst.id }]) : undefined} />;
    }
    if (kind === 'captions') return <CaptionsCard env={e} ops={ops} onSubmit={onSubmit} onCancel={onCancel} okLabel={ok} />;
    if (kind === 'trim') return <TrimCard env={e} ops={ops} onSubmit={onSubmit} onCancel={onCancel} okLabel={ok} comparing={cmp?.turn === x.id} onCompare={(o) => setCmp(o ? { turn: x.id, ops: o } : null)} />;
    if (kind === 'cover') return <CoverCard env={e} op={ops[0] ?? null} onSubmit={onSubmit} onCancel={onCancel} okLabel={ok} />;
    return <ExportCard env={e} run={runs[x.id] ?? null} onStart={(tg, wmk) => void startExport(x, tg, wmk)} onStop={() => runs[x.id]?.job && void client?.stopExport(item, clip, runs[x.id].job!)} onCancel={onCancel} />;
  };

  const meBubble = (txt: string | null | undefined, ctx?: AskContext | null) =>
    txt ? (
      <div className="cc-me" lang={textLang(txt)} data-testid="chat-me">
        {ctx?.range && <span className="cctx"><span className="mono">{`${r1(ctx.range[0])}–${r1(ctx.range[1])}`}</span></span>}
        {txt}
      </div>
    ) : null;

  const aiTurn = (x: ChatTurn) => {
    const st = states[x.id];
    const off = offlineFrom({ warnings: x.warnings ?? [] });
    const notes = (x.warnings ?? []).filter((w) => !['no-model', 'llm-failed', 'llm-bad-json'].includes(w.code)).map((w) => emsg(w)).filter(Boolean);
    const adj = adjust?.turn === x.id ? adjust : null;
    const l = opsOf(x);
    let say: string;
    if (adj) say = t('ce.reply.adjust', { i: adj.i + 1, n: l.ops.length });
    else if (x.proposals.length) say = x.summary || (st === 'draft' ? t('ce.reply.draft') : '');
    else if (off) say = '';
    else say = notes.join('\n') || t('ce.reply.nothing');
    const cost = costLine(x, (pv) => (pv === 'rules' || pv === 'none' ? t('aiacc.name.rules') : providerName(pv)));
    let body: React.ReactNode = null;
    if (adj) {
      const op = l.ops[adj.i];
      const kind = cardFor(op);
      const idx = kind === 'trim' ? l.ops.map((o, i) => (cardFor(o) === 'trim' ? i : -1)).filter((i) => i >= 0) : kind === 'captions' ? l.ops.map((o, i) => (cardFor(o) === 'captions' ? i : -1)).filter((i) => i >= 0) : [adj.i];
      body = kind ? toolCard(x, kind, idx.map((i) => l.ops[i]), (next) => replaceOps(x, idx, next), () => setAdjust(null), t('ce.done')) : null;
    } else if (st === 'draft' && x.proposals.length) body = changeCard(x);
    else if (x.proposals.length) body = st === 'applied' && x.id === newestChange && !conflict[x.id] ? appliedCard(x) : doneLine(x);
    else if (off && x.id === lastAi?.id)
      body = <FallbackCard q={x.text ?? ''} failed={off === 'llm-failed'} primary={primary === 'connect'} onTool={(k) => void openCard(k)} onSay={(s) => void send(s)} onConnect={() => go({ name: 'aiAccounts' })} onRetry={() => void send(x.text ?? '')} />;
    return (
      <div className={`cc-ai ${hot === x.id ? 'hot' : ''}`} data-turn={x.id} data-testid="chat-ai">
        <span className="av">
          <Sparkles className="ico" />
        </span>
        <div className="body">
          {say && <div className="say" data-testid="chat-say">{say}</div>}
          {(x.dropped ?? []).length > 0 && !adj && (
            <div className="drop1">
              {t('ce.reply.dropped', { n: x.dropped!.length })} {x.dropped!.map((d) => emsg(d.error as never)).filter(Boolean).join(' · ')}
            </div>
          )}
          {body}
          {cost && <span className="cost" data-testid="chat-cost">{cost}</span>}
        </div>
      </div>
    );
  };

  const cardTurn = (x: ChatTurn) => {
    if (x.card === 'transcript')
      return (
        <div className={`cc-ai ${hot === x.id ? 'hot' : ''}`} data-turn={x.id} data-testid="chat-cut-turn">
          <span className="av me">
            <Scissors className="ico" />
          </span>
          <div className="body">
            <div className="cc-from muted">{t('te.card.from')}</div>
            <CutCard turn={x} doc={doc} state={states[x.id]} onUndo={() => void undo(x)} onRestore={x.reverted_by ? () => void restore(x) : undefined} onShow={(tt) => p.onShowInTranscript?.(tt)} />
          </div>
        </div>
      );
    const kind = x.card as CardKind;
    const st = states[x.id];
    let body: React.ReactNode;
    if (runs[x.id] || st === 'note') body = toolCard(x, kind, [], (ops) => void apply(x, ops), () => void setStatus(x, 'discarded'));
    else body = doneLine(x);
    return (
      <div className={`cc-ai ${hot === x.id ? 'hot' : ''}`} data-turn={x.id} data-testid="chat-card-turn">
        <span className="av">
          <Sparkles className="ico" />
        </span>
        <div className="body">
          {st === 'note' && !runs[x.id] && <div className="say">{t(`ce.reply.card.${kind}` as MessageKey)}</div>}
          {body}
        </div>
      </div>
    );
  };

  // ------------------------------------------------------------ composer
  const capOk = (k: CardKind) => (k === 'trim' ? doc.caps.trim !== false : k === 'captions' ? !!(doc.caps.caption_add || doc.caps.caption_text) : k === 'effect' ? doc.caps.effects !== false : k === 'cover' ? doc.caps.cover !== false : doc.caps.export !== false);
  const fx = p.fxSel ? doc.effects.find((f) => f.id === p.fxSel) : undefined;
  const sugs = useMemo(() => suggestions(doc as never), [doc]);
  const popWord = sugs.find((s): s is Extract<Suggestion, { kind: 'pop' }> => s.kind === 'pop')?.words[0]?.w;
  const quick: { label: string; run: () => void; id: string }[] = p.sel
    ? [
        { id: 'cut', label: t('ce.chip.cutSel'), run: () => void send(t('ce.chip.cutSelPrompt')) },
        { id: 'pop', label: t('ce.chip.popSel'), run: () => void send(t('ce.chip.popSelPrompt')) },
        { id: 'zoom', label: t('ce.chip.zoomSel'), run: () => void send(t('ce.chip.zoomSelPrompt')) },
      ]
    : fx
      ? [
          { id: 'bigger', label: t('ce.chip.bigger'), run: () => void send(t('ce.chip.biggerPrompt')) },
          { id: 'later', label: t('ce.chip.later'), run: () => void send(t('ce.chip.laterPrompt')) },
        ]
      : offline
        ? (['trim', 'captions'] as CardKind[]).map((k) => ({ id: k, label: `/${t(`ce.cmd.${k}` as MessageKey)}`, run: () => void openCard(k) }))
        : [
            ...(sugs.some((s) => s.kind === 'pauses') ? [{ id: 'tighter', label: t('ce.chip.tighter'), run: () => void send(t('ce.sug.pausesPrompt')) }] : []),
            ...(popWord ? [{ id: 'pop', label: t('ce.chip.pop'), run: () => void send(t('ce.sug.popPrompt', { w: popWord })) }] : []),
            { id: 'captions', label: t('ce.chip.captions'), run: () => void openCard('captions') },
          ];
  const placeholder = offline ? t('ce.placeholderOffline') : fx ? t('ce.placeholderFx') : t('ce.placeholder');
  const day = turns[0]?.at ? dayLabel(turns[0].at) : null;

  if (p.collapsed)
    return (
      <aside className="cc cc-rail" data-testid="chat-panel" data-collapsed="1">
        <button className="btn ghost icon" onClick={p.onToggle} aria-label={t('te.chatOpen')} data-tip={`${t('te.chatOpen')} · ${keyHint('⌘\\')}`} data-testid="chat-expand">
          <PanelRightOpen className="ico" />
        </button>
        <button className="btn ghost icon" onClick={p.onToggle} aria-label={t('ce.chatTitle')}>
          <MessageSquare className="ico" />
          {(drafts.length > 0 || !!p.pinned) && <i className="cc-dot" data-testid="chat-rail-dot" />}
        </button>
      </aside>
    );
  return (
    <aside className="cc" data-testid="chat-panel">
      <div className="cc-hd">
        <MessageSquare className="ico" />
        <b>{t('ce.chatTitle')}</b>
        <span style={{ flex: 1 }} />
        {p.onToggle && (
          <button className="btn ghost icon sm" onClick={p.onToggle} aria-label={t('te.chatClose')} data-tip={`${t('te.chatClose')} · ${keyHint('⌘\\')}`} data-testid="chat-collapse">
            <PanelRightClose className="ico" />
          </button>
        )}
      </div>
      {(p.pinned || p.top) && <div className="cc-pinned">{p.pinned || p.top}</div>}
      <div className="cc-log" ref={log} data-testid="chat-log">
        {day && <div className="cc-day">{day}</div>}
        {!turns.length && !pending && (
          <div className="cc-ai" data-testid="chat-empty">
            <span className="av">
              <Sparkles className="ico" />
            </span>
            <div className="body">
              <div className="say">{p.lead ?? (sugs.length ? t('ce.empty.lead') : t('ce.empty.leadNoIdeas'))}</div>
              {sugs.length + (p.textSuggestions?.length ?? 0) > 0 && (
                <div className="sug">
                  {(p.textSuggestions ?? []).map((x) => (
                    <button key={x.id} onClick={x.run} data-testid={`sug-${x.id}`}>
                      <x.icon className="ico" />
                      <span>{x.title}</span>
                      <small lang="zh-CN">{x.sub}</small>
                    </button>
                  ))}
                  {sugs.map((s) => {
                    const Icon = SUG_ICON[s.kind];
                    const [title, sub, prompt] =
                      s.kind === 'pauses'
                        ? [t('ce.sug.pauses', { n: s.n }), t('ce.sug.pausesSub', { secs: s.secs.toFixed(1) }), t('ce.sug.pausesPrompt')]
                        : s.kind === 'pop'
                          ? [t('ce.sug.pop', { n: s.words.length }), s.words.map((w) => `${w.w} ${fmtClock(w.t)}`).join(' · '), t('ce.sug.popPrompt', { w: s.words[0].w })]
                          : s.kind === 'platform'
                            ? [t('ce.sug.platform'), t('ce.sug.platformSub'), t('ce.sug.platformPrompt')]
                            : [t('ce.sug.cover'), t('ce.sug.coverSub'), t('ce.sug.coverPrompt')];
                    return (
                      <button key={s.kind} onClick={() => void send(prompt)} data-testid={`sug-${s.kind}`}>
                        <Icon className="ico" />
                        <span>{title}</span>
                        <small lang="zh-CN">{sub}</small>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
        {turns.map((x) => (
          <div key={x.id} className="col" style={{ gap: 10 }}>
            {x.role === 'ai' ? meBubble(x.text, x.context) : x.card && x.card !== 'transcript' ? meBubble(x.text) : null}
            {x.role === 'ai' ? aiTurn(x) : x.card ? cardTurn(x) : meBubble(x.text)}
          </div>
        ))}
        {p.sel && !pending && turns.length > 0 && (
          <div className="cc-ai" data-testid="chat-sel-hint">
            <span className="av">
              <Sparkles className="ico" />
            </span>
            <div className="body">
              <div className="say">{t('ce.selHint', { a: r1(p.sel.a), b: r1(p.sel.b) })}</div>
            </div>
          </div>
        )}
        {lost && !pending && (
          <div className="col" style={{ gap: 10 }}>
            {meBubble(lost.text, lost.ctx)}
            <div className="cc-ai" data-testid="chat-lost">
              <span className="av">
                <Sparkles className="ico" />
              </span>
              <div className="body">
                <div className="say drop1">{t('ce.lost')}</div>
                <div className="row" style={{ gap: 8 }}>
                  <button className="btn" onClick={() => void send(lost.text)} data-testid="chat-lost-retry">
                    {t('ce.off.retry')}
                  </button>
                  <button className="btn ghost" onClick={() => setLost(null)}>
                    {t('ce.lostDismiss')}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
        {pending && (
          <div className="col" style={{ gap: 10 }}>
            {meBubble(pending.text, pending.ctx)}
            <div className="cc-ai" data-testid="chat-thinking">
              <span className="av">
                <Sparkles className="ico" />
              </span>
              <div className="body skl">
                <span className="muted">{pending.ctx?.range ? t('ce.thinkingRange', { a: r1(pending.ctx.range[0]), b: r1(pending.ctx.range[1]) }) : t('ce.thinking')}</span>
                <Sk w="78%" h={10} />
                <Sk w="52%" h={10} />
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="cc-in">
        {slashOpen && (
          <div className="slash" role="listbox" data-testid="slash-menu">
            <div className="t">{p.sel ? t('ce.slash.titleSel') : t('ce.slash.title')}</div>
            {matches.map((k, i) => {
              const Icon = CARD_ICON[k];
              const ok = capOk(k);
              return (
                <button key={k} className={i === Math.min(mi, matches.length - 1) ? 'on' : ''} disabled={!ok} title={ok ? undefined : t('ce.slash.off')} onMouseEnter={() => setMi(i)} onClick={() => void openCard(k)} role="option" aria-selected={i === mi} data-testid={`slash-${k}`}>
                  <Icon className="ico" />
                  <span className="mono">/{getLang() === 'zh-CN' ? SLASH.find((s) => s.kind === k)!.zh : SLASH.find((s) => s.kind === k)!.en}</span>
                  <small>{t(`ce.slash.${k}` as MessageKey)}</small>
                </button>
              );
            })}
          </div>
        )}
        <div className="cmp">
          {(p.sel || fx) && (
            <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
              {p.sel && (
                <span className="cctx" data-testid="ctx-sel">
                  <Crop className="ico" style={{ width: 13, height: 13 }} />
                  <span className="mono">{`${r1(p.sel.a)}–${r1(p.sel.b)}`}</span>
                  {t('ce.selected')}
                  <button onClick={p.onClearSel} aria-label={t('ce.ctx.remove')} data-testid="ctx-sel-x">
                    <X className="ico" style={{ width: 13, height: 13 }} />
                  </button>
                </span>
              )}
              {fx && (
                <span className="cctx" data-testid="ctx-fx">
                  <Sparkles className="ico" style={{ width: 13, height: 13 }} />
                  {effectLabel(fx.effect, fx.label)} ·<span className="mono">{r1(fx.start)}</span>
                  <button onClick={p.onClearFx} aria-label={t('ce.ctx.remove')}>
                    <X className="ico" style={{ width: 13, height: 13 }} />
                  </button>
                </span>
              )}
            </div>
          )}
          <textarea
            ref={ta}
            rows={1}
            value={text}
            placeholder={placeholder}
            onChange={(e) => {
              setText(e.target.value);
              setMi(0);
              e.target.style.height = 'auto';
              e.target.style.height = `${Math.min(140, e.target.scrollHeight)}px`;
            }}
            onKeyDown={(e) => {
              if (slashOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
                e.preventDefault();
                setMi((i) => (i + (e.key === 'ArrowDown' ? 1 : matches.length - 1)) % matches.length);
                return;
              }
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !e.metaKey && !e.ctrlKey) {
                e.preventDefault();
                if (slashOpen && !slashCommand(text)) {
                  const k = matches[Math.min(mi, matches.length - 1)];
                  if (capOk(k)) void openCard(k);
                } else void send(text);
              }
              if (e.key === 'Escape') {
                e.preventDefault();
                if (text) setText('');
                else if (!escapeOne()) (e.target as HTMLTextAreaElement).blur();
              }
            }}
            aria-label={placeholder}
            data-testid="chat-input"
          />
          <div className="bot">
            <div className="chips">
              {quick.map((c) => (
                <button key={c.id} className="chip" onClick={c.run} disabled={!!pending} data-testid={`quick-${c.id}`}>
                  {c.label}
                </button>
              ))}
            </div>
            {offline ? (
              <button className="chip nomodel" onClick={() => go({ name: 'aiAccounts' })} data-testid="model-chip-off">
                <i className="dot" style={{ background: 'var(--danger)' }} />
                {t('ce.off.noModel')}
              </button>
            ) : (
              <ProviderChip task="edit" testId="ce-provider-chip" />
            )}
            {pending ? (
              <button className="send on" onClick={stop} aria-label={t('ce.stop')} data-tip={t('ce.stop')} data-testid="chat-stop">
                <Square className="ico" style={{ width: 12, height: 12 }} />
              </button>
            ) : (
              <button className={`send ${text.trim() ? 'on' : ''}`} onClick={() => void send(text)} disabled={!text.trim()} aria-label={t('ce.send')} data-testid="chat-send">
                <ArrowUp className="ico" />
              </button>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
});

/** Rows of a change set: all cuts of one set are ONE row ("Remove 6 pauses"); everything else one row each. */
function groups(ops: EditOp[]): number[][] {
  const cuts = ops.map((o, i) => (o.op === 'cut' ? i : -1)).filter((i) => i >= 0);
  const out: number[][] = [];
  ops.forEach((o, i) => {
    if (o.op !== 'cut') out.push([i]);
    else if (i === cuts[0]) out.push(cuts.length > 1 ? cuts : [i]);
  });
  return out;
}

function describeOp(op: EditOp): string {
  switch (op.op) {
    case 'cut':
      return `${t('editor.cutSel')} ${fmtClock(op.start, true)}–${fmtClock(op.end, true)}`;
    case 'effect_add':
    case 'effect_update':
      return op.op === 'effect_add' ? `${effectLabel(op.effect)}${typeof op.params?.text === 'string' ? ` “${op.params.text}”` : ''}` : t('ce.adjust');
    case 'trim':
      return `${t('editor.tab.trim')} ${fmtClock(op.start ?? 0, true)}–${op.end != null ? fmtClock(op.end, true) : ''}`;
    case 'caption_text':
      return `${t('ce.cap.title')} · ${op.text}`;
    case 'caption_style':
      return t('ce.cap.style');
    case 'cover':
      return t('ce.cover.title');
    default:
      return op.op;
  }
}

function dayLabel(at: string): string {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const time = d.toLocaleTimeString(intlLocale(), { hour: '2-digit', minute: '2-digit', hour12: false });
  if (d.toDateString() === now.toDateString()) return t('ce.today', { time });
  return d.toLocaleString(intlLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}
