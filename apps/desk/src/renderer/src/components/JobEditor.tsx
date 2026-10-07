// In-review edits (P0-3): caption text (only edits consistent with the audio are accepted - the engine re-hears
// the cue window, refusals say why and what it heard), hook swap, trim (word-snapped), inner cut (word-snapped),
// 记笔记 notes panel (overlay re-render only), cover frame + text, title / body / tags. Every edit is recorded and undoable (⌘Z); the bar
// shows which stages will re-run and "re-render affected" runs only those.
import { useEffect, useRef, useState } from 'react';
import type { EditBody, EditResult, JobEditInfo } from '../../../shared/v02';
import { t, tk } from '../i18n';
import { useEngine } from '../lib/engine';
import { hms } from '../lib/format';
import { wordsText } from '../lib/transcript';
import { EdgeEditor } from './SegmentReview';
import { ErrorBox, Media } from './ui';

type Tab = 'captions' | 'hook' | 'trim' | 'cut' | 'notes' | 'cover' | 'copy';
const TABS: Tab[] = ['captions', 'hook', 'trim', 'cut', 'notes', 'cover', 'copy'];

/** A refusal in words: the engine's code (translated when known) or its own sentence, plus what was re-heard. */
export function refusalText(r: Pick<EditResult, 'reason' | 'reason_code' | 'heard'>): string {
  const code = r.reason_code ?? r.reason ?? 'rejected';
  const key = `edit.reason.${code}`;
  const base = tk(key) !== key ? tk(key) : (r.reason ?? t('edit.reason.rejected'));
  const extra = r.reason && tk(key) !== key && r.reason !== code ? ` (${r.reason})` : '';
  return base + extra + (r.heard ? ` · ${t('edit.heardAudio')}: 「${r.heard}」` : '');
}

export function JobEditor({ batch, job, info, getTime, onChanged }: { batch: string; job: string; info: JobEditInfo; getTime: () => number; onChanged: () => void }) {
  const { client } = useEngine();
  const [tab, setTab] = useState<Tab>('captions');
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function edit(body: EditBody): Promise<EditResult | null> {
    if (!client) return null;
    setBusy(true);
    setMsg(null);
    try {
      const r = await client.editJob(batch, job, body);
      if (!r.ok) setMsg({ ok: false, text: refusalText(r) });
      else {
        setMsg({ ok: true, text: r.glossary_added ? t('edit.glossaryAdded', { w: r.glossary_added.wrong, r: r.glossary_added.right }) : r.rerun.length ? t('edit.savedRerun', { s: r.rerun.join(', ') }) : t('edit.savedInstant') });
        onChanged();
      }
      return r;
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (!client || !info.history.length) return;
    try {
      const r = await client.undoJob(batch, job);
      setMsg({ ok: true, text: t('edit.undone', { op: t(`edit.tab.${opTab(r.undone?.op)}`) }) });
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }

  async function rerun() {
    if (!client) return;
    try {
      const r = await client.rerunJob(batch, job);
      setMsg({ ok: true, text: t('edit.rerunStarted', { s: r.stages.join(', ') }) });
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return;
      if ((e.metaKey || e.ctrlKey) && e.key === 'z') {
        e.preventDefault();
        void undo();
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  });

  if (!info.can_edit) return <div className="notice">{t('edit.unsupported')}</div>;
  return (
    <div className="card col" data-testid="job-editor">
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <b>{t('edit.title')}</b>
        <div className="tabs" role="tablist">
          {TABS.map((x) => (
            <button key={x} role="tab" aria-selected={tab === x} className={`tab ${tab === x ? 'on' : ''}`} onClick={() => setTab(x)} data-testid={`edit-tab-${x}`}>
              {t(`edit.tab.${x}`)}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button className="btn sm" disabled={!info.history.length} onClick={undo} title="⌘Z" data-testid="edit-undo">
          ↶ {t('edit.undo')} <kbd>⌘Z</kbd>
        </button>
      </div>
      <div className={`rerunbar ${info.pending.length ? 'on' : ''}`} data-testid="rerun-bar">
        {info.pending.length ? (
          <>
            <span>{t('edit.pending')}</span>
            {info.pending.map((s) => (
              <span key={s} className="badge accent">
                {s}
              </span>
            ))}
            <div style={{ flex: 1 }} />
            <button className="btn primary sm" disabled={!info.can_rerun} onClick={rerun} data-testid="rerun-affected">
              {t('edit.rerun')}
            </button>
          </>
        ) : (
          <span className="muted small">{info.history.length ? t('edit.upToDate') : t('edit.noEdits')}</span>
        )}
      </div>
      {msg && <div className={`small ${msg.ok ? 'okc' : 'err'}`} data-testid="edit-msg">{msg.text}</div>}
      {tab === 'captions' && <Captions info={info} busy={busy} onEdit={edit} />}
      {tab === 'hook' && <Hooks info={info} onEdit={edit} />}
      {tab === 'trim' && <Trim info={info} onEdit={edit} />}
      {tab === 'cut' && <InnerCut info={info} getTime={getTime} onEdit={edit} />}
      {tab === 'notes' && <Notes info={info} onEdit={edit} />}
      {tab === 'cover' && <Cover info={info} getTime={getTime} onEdit={edit} />}
      {tab === 'copy' && <Copy info={info} onEdit={edit} />}
      {info.history.length > 0 && (
        <details>
          <summary className="small muted">{t('edit.history', { n: info.history.length })}</summary>
          <ol className="small" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {info.history.map((h) => (
              <li key={h.n}>
                {t(`edit.tab.${opTab(h.op)}`)} · <span className="mono muted">{summarize(h.args)}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

function opTab(op?: string): Tab {
  return op === 'caption' ? 'captions' : ((op ?? 'copy') as Tab);
}

function summarize(a: Record<string, unknown>): string {
  return Object.entries(a)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(',') : typeof v === 'number' ? Number(v).toFixed(2).replace(/\.00$/, '') : String(v ?? '')}`)
    .join(' ')
    .slice(0, 120);
}

function Captions({ info, busy, onEdit }: { info: JobEditInfo; busy: boolean; onEdit: (b: EditBody) => Promise<EditResult | null> }) {
  const [draft, setDraft] = useState<Record<number, string>>({});
  const [result, setResult] = useState<Record<number, EditResult>>({});
  const inflight = useRef(new Set<number>());
  if (!info.cues.length) return <div className="muted small">{t('edit.noCues')}</div>;
  const commit = async (i: number) => {
    const c = info.cues.find((x) => x.i === i);
    const v = draft[i];
    if (!c || v === undefined || v.trim() === c.text || !v.trim() || inflight.current.has(i)) return;
    inflight.current.add(i);
    const r = await onEdit({ op: 'caption', cue: i, text: v.trim() }).finally(() => inflight.current.delete(i));
    if (r) {
      setResult((m) => ({ ...m, [i]: r }));
      if (r.ok)
        setDraft((d) => {
          const n = { ...d };
          delete n[i];
          return n;
        });
    }
  };
  const reHear = async (i: number) => {
    const v = (draft[i] ?? '').trim();
    if (!v || inflight.current.has(i)) return;
    inflight.current.add(i);
    const r = await onEdit({ op: 'caption', cue: i, text: v, reasr: true }).finally(() => inflight.current.delete(i));
    if (r) {
      setResult((m) => ({ ...m, [i]: r }));
      if (r.ok)
        setDraft((d) => {
          const n = { ...d };
          delete n[i];
          return n;
        });
    }
  };
  return (
    <div className="col cues" style={{ gap: 4, maxHeight: 360, overflow: 'auto' }}>
      <span className="muted small">{t('edit.captionHint')}</span>
      {info.cues.map((c) => {
        const r = result[c.i];
        const changed = c.text !== c.heard;
        return (
          <div key={c.i} className="cue row" style={{ flexWrap: 'wrap' }}>
            <span className="mono small muted" style={{ width: 70 }}>
              {hms(c.start)}
            </span>
            <input
              className={`input ${r && !r.ok ? 'bad' : ''}`}
              style={{ flex: 1 }}
              aria-label={`${t('edit.cue')} ${c.i + 1}`}
              value={draft[c.i] ?? c.text}
              maxLength={200}
              disabled={busy}
              onChange={(e) => setDraft((d) => ({ ...d, [c.i]: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void commit(c.i);
                if (e.key === 'Escape')
                  setDraft((d) => {
                    const n = { ...d };
                    delete n[c.i];
                    return n;
                  });
              }}
              onBlur={() => void commit(c.i)}
              data-testid={`cue-${c.i}`}
            />
            <span className="small" style={{ width: 22 }} title={r && !r.ok ? refusalText(r) : changed ? `${t('edit.heard')}: ${c.heard}` : ''}>
              {r && !r.ok ? <span className="err">✕</span> : changed ? <span className="okc">✓</span> : ''}
            </span>
            {r && !r.ok && (
              <div className="small err" style={{ flexBasis: '100%', paddingLeft: 78 }} data-testid={`cue-refusal-${c.i}`}>
                {refusalText(r)}{' '}
                {r.reason_code !== 'rehear-unavailable' && (
                  <button className="btn sm" disabled={busy} onClick={() => void reHear(c.i)} data-testid={`cue-reasr-${c.i}`}>
                    {t('edit.reHear')}
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Hooks({ info, onEdit }: { info: JobEditInfo; onEdit: (b: EditBody) => Promise<EditResult | null> }) {
  const [optimistic, setOptimistic] = useState<number | null>(null);
  useEffect(() => setOptimistic(null), [info.hook_pick]);
  if (!info.hooks.length) return <div className="muted small">{t('edit.noHooks')}</div>;
  const cur = optimistic ?? info.hook_pick ?? 0;
  return (
    <div className="col" role="radiogroup" style={{ gap: 6 }}>
      {info.hooks.map((h, i) => (
        <label key={i} className={`item ${cur === i ? 'on' : ''}`} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <input
            type="radio"
            name="hook"
            checked={cur === i}
            onChange={() => {
              setOptimistic(i);
              void onEdit({ op: 'hook', pick: i }).then((r) => !r?.ok && setOptimistic(null));
            }}
            data-testid={`hook-${i}`}
          />
          <span className="mono small muted">{h.start != null ? `${hms(h.start)}–${hms(h.end)}` : ''}</span>
          <span>{h.text}</span>
        </label>
      ))}
    </div>
  );
}

function Trim({ info, onEdit }: { info: JobEditInfo; onEdit: (b: EditBody) => Promise<EditResult | null> }) {
  const base = info.range ? { start: info.range[0], end: info.range[1] } : null;
  const [r, setR] = useState(base);
  useEffect(() => setR(base), [info.range?.[0], info.range?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r || !base) return <div className="muted small">{t('edit.noRange')}</div>;
  const dirty = Math.abs(r.start - base.start) > 1e-3 || Math.abs(r.end - base.end) > 1e-3;
  const duration = info.words.at(-1)?.te ?? r.end + 20;
  return (
    <div className="col" style={{ gap: 6 }}>
      <span className="muted small">{t('edit.trimHint')}</span>
      <EdgeEditor seg={r} words={info.words} duration={duration} onChange={(s) => setR({ start: s.start, end: s.end })} />
      <div className="row">
        <span className="mono small">
          {hms(r.start)}–{hms(r.end)} ({(r.end - r.start).toFixed(1)}s)
          {dirty && <span className="muted"> · {t('edit.was', { a: hms(base.start), b: hms(base.end) })}</span>}
        </span>
        <div style={{ flex: 1 }} />
        <button className="btn sm" disabled={!dirty} onClick={() => setR(base)}>
          {t('edit.reset')}
        </button>
        <button className="btn primary sm" disabled={!dirty} onClick={() => void onEdit({ op: 'trim', start: r.start, end: r.end })} data-testid="trim-apply">
          {t('edit.applyTrim')}
        </button>
      </div>
    </div>
  );
}

function InnerCut({ info, getTime, onEdit }: { info: JobEditInfo; getTime: () => number; onEdit: (b: EditBody) => Promise<EditResult | null> }) {
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const [why, setWhy] = useState('');
  if (!info.range) return <div className="muted small">{t('edit.noRange')}</div>;
  // the player plays the clip from the start of its source range (output ≈ source - range start before cuts)
  const fromPlayer = () => Math.round((info.range![0] + getTime()) * 100) / 100;
  const words = a != null && b != null && b > a ? wordsText(info.words.filter((w) => w.t >= a - 0.05 && w.te <= b + 0.05).map((w) => ({ w: w.w, t: w.t, te: w.te }))) : '';
  const ok = a != null && b != null && b > a && a >= info.range[0] && b <= info.range[1];
  return (
    <div className="col" style={{ gap: 6 }} data-testid="cut-editor">
      <span className="muted small">{t('edit.cutHint')}</span>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        <label className="small">
          {t('edit.cutStart')}{' '}
          <input className="input mono" type="number" step={0.01} style={{ width: 100 }} value={a ?? ''} onChange={(e) => setA(e.target.value === '' ? null : Number(e.target.value))} data-testid="cut-start" />
        </label>
        <button className="btn sm" onClick={() => setA(fromPlayer())}>
          {t('edit.atPlayhead')}
        </button>
        <label className="small">
          {t('edit.cutEnd')}{' '}
          <input className="input mono" type="number" step={0.01} style={{ width: 100 }} value={b ?? ''} onChange={(e) => setB(e.target.value === '' ? null : Number(e.target.value))} data-testid="cut-end" />
        </label>
        <button className="btn sm" onClick={() => setB(fromPlayer())}>
          {t('edit.atPlayhead')}
        </button>
        <input className="input" placeholder={t('edit.cutWhy')} aria-label={t('edit.cutWhy')} value={why} maxLength={200} onChange={(e) => setWhy(e.target.value)} style={{ flex: 1, minWidth: 120 }} />
      </div>
      {words && <div className="small mono muted">{t('edit.cutWords')}: 「{words}」</div>}
      <div className="row">
        <span className="small muted">{t('edit.rangeIs', { a: hms(info.range[0]), b: hms(info.range[1]) })}</span>
        <div style={{ flex: 1 }} />
        <button className="btn primary sm" disabled={!ok} onClick={() => void onEdit({ op: 'cut', start: a!, end: b!, why: why.trim() || undefined }).then((r) => r?.ok && (setA(null), setB(null), setWhy('')))} data-testid="cut-apply">
          {t('edit.applyCut')}
        </button>
      </div>
      {(info.cuts ?? []).length > 0 && (
        <ul className="small" style={{ margin: 0, paddingLeft: 18 }} data-testid="cut-list">
          {(info.cuts ?? []).map((c, k) => (
            <li key={k} className="mono">
              {hms(c.start)}–{hms(c.end)} {c.why && <span className="muted">· {c.why}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Notes({ info, onEdit }: { info: JobEditInfo; onEdit: (b: EditBody) => Promise<EditResult | null> }) {
  const cur = (info.notes ?? []).join('\n');
  const [text, setText] = useState(cur);
  useEffect(() => setText(cur), [cur]);
  const lines = text
    .split('\n')
    .map((x) => x.replace(/\|/g, '／').trim())
    .filter(Boolean)
    .slice(0, 12);
  const dirty = lines.join('\n') !== cur;
  return (
    <div className="col" style={{ gap: 6 }} data-testid="notes-editor">
      <span className="muted small">{t('edit.notesHint')}</span>
      <textarea className="input" rows={5} aria-label={t('edit.tab.notes')} value={text} onChange={(e) => setText(e.target.value)} data-testid="notes-text" />
      <div className="row">
        <span className="small muted">{t('edit.notesCount', { n: lines.length })}</span>
        <div style={{ flex: 1 }} />
        <button className="btn primary sm" disabled={!dirty} onClick={() => void onEdit({ op: 'notes', lines: lines.map((x) => x.slice(0, 80)) })} data-testid="notes-save">
          {t('edit.saveNotes')}
        </button>
      </div>
    </div>
  );
}

function Cover({ info, getTime, onEdit }: { info: JobEditInfo; getTime: () => number; onEdit: (b: EditBody) => Promise<EditResult | null> }) {
  const [tt, setTt] = useState<number | null>(info.cover.t);
  const [text, setText] = useState(info.cover.text);
  useEffect(() => {
    setTt(info.cover.t);
    setText(info.cover.text);
  }, [info.cover.t, info.cover.text]);
  const dirty = tt !== info.cover.t || text !== info.cover.text;
  return (
    <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
      <div style={{ width: 140 }}>
        <Media path={info.cover.file} kind="img" />
      </div>
      <div className="col" style={{ flex: 1 }}>
        <div className="row">
          <button className="btn sm" onClick={() => setTt(Math.round(getTime() * 100) / 100)} data-testid="cover-frame">
            {t('edit.useFrame')}
          </button>
          <span className="mono small">{tt == null ? t('edit.autoFrame') : `${tt.toFixed(2)}s`}</span>
        </div>
        <input className="input" placeholder={t('edit.coverText')} aria-label={t('edit.coverText')} value={text} maxLength={60} onChange={(e) => setText(e.target.value)} data-testid="cover-text" />
        <div className="row">
          <button className="btn primary sm" disabled={!dirty} onClick={() => void onEdit({ op: 'cover', t: tt, text })} data-testid="cover-save">
            {t('edit.saveCover')}
          </button>
        </div>
      </div>
    </div>
  );
}

function Copy({ info, onEdit }: { info: JobEditInfo; onEdit: (b: EditBody) => Promise<EditResult | null> }) {
  const [title, setTitle] = useState(info.copy.title);
  const [body, setBody] = useState(info.copy.body);
  const [tags, setTags] = useState(info.copy.tags.join(' '));
  useEffect(() => {
    setTitle(info.copy.title);
    setBody(info.copy.body);
    setTags(info.copy.tags.join(' '));
  }, [info.copy.title, info.copy.body, info.copy.tags]);
  const tagList = tags
    .split(/[\s,，、]+/)
    .map((x) => x.replace(/^#/, ''))
    .filter(Boolean);
  const dirty = title !== info.copy.title || body !== info.copy.body || tagList.join(',') !== info.copy.tags.join(',');
  return (
    <div className="col" style={{ gap: 6 }}>
      <input className="input" aria-label={t('edit.postTitle')} value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} data-testid="copy-title" />
      <span className="muted small">{t('edit.titleLen', { n: [...title].length })}</span>
      <textarea className="input" aria-label={t('edit.postBody')} rows={4} value={body} maxLength={2000} onChange={(e) => setBody(e.target.value)} />
      <input className="input" aria-label={t('edit.postTags')} placeholder="#标签 #tag" value={tags} onChange={(e) => setTags(e.target.value)} />
      <ErrorBox error={title.trim() ? null : t('edit.titleRequired')} />
      <div className="row">
        <button className="btn primary sm" disabled={!dirty || !title.trim()} onClick={() => void onEdit({ op: 'copy', title: title.trim(), body, tags: tagList.slice(0, 30) })} data-testid="copy-save">
          {t('edit.saveCopy')}
        </button>
      </div>
    </div>
  );
}
