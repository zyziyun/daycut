// 二次编辑 for every output: player + timeline (thumbnails, waveform, words, effects) + panels 裁剪 / 字幕 / 效果 /
// 标题与封面 / 导出 + 「让 AI 改」. Capability flags decide what is shown: a flattened clip explains in one line why
// its burned captions cannot be restyled and shows no dead controls. One primary: Render.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Check, Contrast, GanttChart, Music, PanelRight, Redo2, Scissors, Sparkle, Sparkles, Square, Trash2, Type, Undo2, ZoomIn } from 'lucide-react';
import type { ClipFile, EditOp, EffectDef, OutputDoc } from '../../../shared/v04';
import { fmtClock, getLang, t, type MessageKey } from '../i18n';
import { useEngine } from '../lib/engine';
import { previewDoc } from '../lib/outputs';
import { snapEdge } from '../lib/timeline';
import { href } from '../lib/router';
import { AIPanel } from './AIPanel';
import { Empty, Sk } from './kit';
import { effectLabel, emsg, errText, setEffectLabels } from './msg';
import { Player, type PlayerApi } from './Player';
import { Timeline } from './Timeline';
import { isTyping, useUi } from './ui';

type Tab = 'trim' | 'captions' | 'effects' | 'cover' | 'export';
const TABS: [Tab, MessageKey][] = [
  ['trim', 'editor.tab.trim'],
  ['captions', 'editor.tab.captions'],
  ['effects', 'editor.tab.effects'],
  ['cover', 'editor.tab.cover'],
  ['export', 'editor.tab.export'],
];
const TARGETS = ['3:4', '9:16', '16:9'] as const;

export function OutputEditor({ id, clip }: { id: string; clip: string }) {
  const { client, subscribe } = useEngine();
  const ui = useUi();
  const [doc, setDoc] = useState<OutputDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('trim');
  const [time, setTime] = useState(0);
  const [sel, setSel] = useState<{ a: number; b: number } | null>(null);
  const [fxSel, setFxSel] = useState<string | null>(null);
  const [preview, setPreview] = useState<EditOp[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [rendered, setRendered] = useState<{ simulated?: boolean } | null>(null);
  const [ai, setAi] = useState(() => window.innerWidth >= 1500 || sessionStorage.getItem('v4.ai') === '1');
  const [effects, setEffects] = useState<EffectDef[]>([]);
  const pl = useRef<PlayerApi | null>(null);
  const [n, setN] = useState(0);
  const reload = useCallback(() => setN((x) => x + 1), []);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .output(id, clip)
      .then((d) => alive && (setDoc(d), setErr(null)))
      .catch((e) => alive && setErr(errText(e)));
    return () => {
      alive = false;
    };
  }, [client, id, clip, n]);
  useEffect(() => {
    if (!client) return;
    void client.effects().then((r) => {
      setEffectLabels(r.effects);
      setEffects(r.effects);
    });
  }, [client]);
  useEffect(() => subscribe((e) => (e.type === 'output-edit' && e.item === id && e.clip === clip ? reload() : undefined)), [subscribe, id, clip, reload]);
  useEffect(() => sessionStorage.setItem('v4.ai', ai ? '1' : '0'), [ai]);

  const edit = useCallback(
    async (ops: EditOp[], undoToast = false) => {
      if (!client) return false;
      setBusy('edit');
      try {
        const r = await client.editOutput(id, clip, ops);
        setRendered(null);
        reload();
        const w = r.warnings?.[0];
        if (w) ui.toast(emsg(w));
        else if (undoToast)
          ui.toast(r.step?.describe?.map(emsg).join(' · ') || t('editor.saved'), {
            undo: async () => {
              await client.undoOutput(id, clip);
              reload();
            },
          });
        return true;
      } catch (e) {
        ui.toast(errText(e), { error: true });
        return false;
      } finally {
        setBusy(null);
      }
    },
    [client, id, clip, reload, ui],
  );
  const undo = useCallback(
    async (steps = 1, redo = false) => {
      if (!client) return;
      try {
        await (redo ? client.redoOutput(id, clip, steps) : client.undoOutput(id, clip, steps));
        setRendered(null);
        reload();
      } catch (e) {
        ui.toast(errText(e), { error: true });
      }
    },
    [client, id, clip, reload, ui],
  );
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (isTyping(e.target) || !(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'z') return;
      e.preventDefault();
      void undo(1, e.shiftKey);
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [undo]);

  const render = async (quality: 'preview' | 'final' = 'preview', targets = 'primary') => {
    if (!client) return;
    setBusy('render');
    try {
      const r = await client.renderOutput(id, clip, { quality, targets });
      setRendered({ simulated: r.simulated });
      reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(null);
    }
  };

  const view = useMemo(() => (doc ? previewDoc(doc, preview) : null), [doc, preview]);
  if (err && !doc)
    return (
      <div className="pg">
        <a className="back" href={href({ name: 'project', id })}>
          <ArrowLeft className="ico" />
          {t('c.back')}
        </a>
        <Empty title={err} />
      </div>
    );
  if (!doc || !view)
    return (
      <div className="ed" aria-busy="true">
        <div className="left">
          <Sk h={24} w={240} />
          <div className="sk" style={{ flex: 1, minHeight: 300 }} />
        </div>
        <div className="panel" />
      </div>
    );

  const fresh = doc.renders.filter((r) => r.fresh && !r.simulated);
  const files: ClipFile[] = [
    ...fresh.map((r) => ({ path: r.file, aspect: r.target === 'primary' ? (doc.files[0]?.aspect ?? '3:4') : r.target, label: t('editor.editedVersion') })),
    ...doc.files.map((f) => (fresh.length ? { ...f, label: t('c.original') } : f)),
  ];
  const dirty = doc.steps.length > 0 && !doc.renders.some((r) => r.fresh);
  const capsNote = doc.caps_notes.find((m) => m.code === 'captions-add-only') ?? doc.caps_notes.find((m) => m.code === 'flattened');
  const words = doc.words;
  const firstWord = words.find((w) => w.w.length >= 2)?.w;

  return (
    <div className={`ed ${ai ? 'ai' : ''}`} data-testid="editor">
      <div className="left">
        <div className="edhead">
          <a className="back" style={{ margin: 0 }} href={href({ name: 'project', id })}>
            <ArrowLeft className="ico" />
          </a>
          <h1 className="clamp1" lang="zh-CN" data-testid="editor-title">
            {doc.title}
          </h1>
          <span className="muted num">{fmtClock(doc.duration)}</span>
          <span className="sp" />
          <button className="btn ghost icon sm" disabled={!doc.undo} onClick={() => void undo()} aria-label={t('c.undo')} data-tip={`${t('c.undo')} · ⌘Z`} data-testid="editor-undo">
            <Undo2 className="ico" />
          </button>
          <button className="btn ghost icon sm" disabled={!doc.redo} onClick={() => void undo(1, true)} aria-label={t('c.redo')} data-tip={`${t('c.redo')} · ⇧⌘Z`} data-testid="editor-redo">
            <Redo2 className="ico" />
          </button>
          <button className={`btn ${ai ? 'toggle on' : ''}`} onClick={() => setAi(!ai)} aria-pressed={ai} data-testid="toggle-ai">
            <Sparkles className="ico" />
            {t('ai.title')}
          </button>
        </div>
        <Player
          ref={pl}
          key={files.map((f) => f.path).join('|')}
          files={files}
          fps={doc.fps}
          duration={doc.duration}
          captions={doc.captions.map((c) => ({ ...c }))}
          captionStyle={doc.caption_style}
          effects={view.effects}
          cuts={fresh.length ? [] : view.cuts}
          trim={fresh.length ? null : view.trim}
          onTime={setTime}
          onSelection={setSel}
          testId="editor-player"
        />
      </div>
      <div className="tl">
        <Timeline
          doc={view}
          time={time}
          selection={sel}
          selectedFx={fxSel}
          onSeek={(x) => pl.current?.seek(x)}
          onSelect={(s) => {
            setSel(s);
            pl.current?.setSelection(s);
          }}
          onSelectFx={(f) => {
            setFxSel(f);
            if (f) setTab('effects');
          }}
          onMoveFx={(fx, start, end) => void edit([{ op: 'effect_update', id: fx.id, start, end }])}
          onTrim={(a, b) => void edit([{ op: 'trim', start: a, end: b }])}
        />
      </div>
      <section className="panel" data-testid="edit-panel">
        <nav className="tabs4" role="tablist">
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)} data-testid={`etab-${k}`}>
              {t(label)}
            </button>
          ))}
        </nav>
        <div className="body">
          {tab === 'trim' && <TrimPanel doc={view} time={time} sel={sel} edit={edit} onClearSel={() => (setSel(null), pl.current?.setSelection(null))} />}
          {tab === 'captions' && <CaptionsPanel doc={doc} note={capsNote ? emsg(capsNote) : null} edit={edit} time={time} sel={sel} />}
          {tab === 'effects' && <EffectsPanel doc={doc} defs={effects} time={time} sel={sel} fxSel={fxSel} setFxSel={setFxSel} edit={edit} firstWord={firstWord} />}
          {tab === 'cover' && <CoverPanel doc={doc} time={time} edit={edit} />}
          {tab === 'export' && <ExportPanel doc={doc} edit={edit} onFinal={() => void render('final', 'all')} busy={busy === 'render'} />}
          <Edits doc={doc} onUndoTo={(k) => void undo(doc.steps.length - k)} />
        </div>
        <div className="foot">
          <span className="muted sp" data-testid="render-state">
            {busy === 'render'
              ? t('editor.rendering')
              : rendered?.simulated
                ? t('editor.simulated')
                : rendered
                  ? t('editor.rendered', { v: doc.steps.length })
                  : dirty
                    ? t('editor.unrendered', { n: doc.steps.length })
                    : t('editor.upToDate')}
          </span>
          <button className="btn primary" disabled={busy === 'render' || !doc.steps.length} onClick={() => void render()} data-testid="render">
            {busy === 'render' ? t('editor.rendering') : t('editor.render')}
          </button>
        </div>
      </section>
      {ai && (
        <AIPanel
          item={id}
          clip={clip}
          clipTitle={doc.title}
          hintWord={firstWord}
          onApplied={() => {
            setPreview(null);
            setRendered(null);
            reload();
          }}
          onCompare={setPreview}
        />
      )}
    </div>
  );
}

type EditFn = (ops: EditOp[], undoToast?: boolean) => Promise<boolean>;

function TrimPanel({ doc, time, sel, edit, onClearSel }: { doc: OutputDoc; time: number; sel: { a: number; b: number } | null; edit: EditFn; onClearSel: () => void }) {
  const a = doc.trim?.start ?? 0;
  const b = doc.trim?.end ?? doc.duration;
  const snap = (x: number) => snapEdge(doc.words, x);
  return (
    <div className="col" style={{ gap: 16 }} data-testid="trim-panel">
      <div className="field4">
        <span className="lbl">{t('editor.tab.trim')}</span>
        <b style={{ fontWeight: 500 }} className="num" data-testid="trim-range">
          {t('editor.keep', { a: fmtClock(a, true), b: fmtClock(b, true) })}
        </b>
        <div className="row">
          <button className="btn" disabled={!doc.caps.trim} onClick={() => void edit([{ op: 'trim', start: snap(time), end: b }])} data-testid="trim-start-here">
            {t('editor.startHere')}
          </button>
          <button className="btn" disabled={!doc.caps.trim} onClick={() => void edit([{ op: 'trim', start: a, end: snap(time) }])} data-testid="trim-end-here">
            {t('editor.endHere')}
          </button>
          {doc.trim && (
            <button className="btn ghost" onClick={() => void edit([{ op: 'trim', start: null, end: null }])}>
              {t('editor.resetTrim')}
            </button>
          )}
        </div>
      </div>
      {doc.caps.cut !== false && (
        <div className="field4">
          <span className="lbl">{t('editor.cuts', { n: doc.cuts.length })}</span>
          <span className="muted">{t('editor.cutHint')}</span>
          <div className="row">
            <span className="muted num sp">{sel ? t('editor.selection', { a: fmtClock(sel.a, true), b: fmtClock(sel.b, true) }) : t('editor.noSelection')}</span>
            <button
              className="btn"
              disabled={!sel}
              onClick={async () => {
                if (sel && (await edit([{ op: 'cut', start: sel.a, end: sel.b }], true))) onClearSel();
              }}
              data-testid="cut-selection"
            >
              <Scissors className="ico" />
              {t('editor.cutSel')}
            </button>
          </div>
          {doc.cuts.map((c) => (
            <div key={c.index} className="row oplist">
              <span className="num sp">
                {fmtClock(c.start, true)} – {fmtClock(c.end, true)}
              </span>
              <button className="btn ghost sm" onClick={() => void edit([{ op: 'cut_remove', index: c.index }], true)} aria-label={t('c.remove')}>
                <Trash2 className="ico" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CaptionsPanel({ doc, note, edit, time, sel }: { doc: OutputDoc; note: string | null; edit: EditFn; time: number; sel: { a: number; b: number } | null }) {
  const ours = !!doc.caps.caption_text;
  const [text, setText] = useState('');
  const added = doc.captions.filter((c) => c.added);
  const style = doc.caption_style ?? {};
  return (
    <div className="col" style={{ gap: 16 }} data-testid="captions-panel">
      {!ours && <div className="note" data-testid="caps-note">{note ?? t('editor.flattened')}</div>}
      {(ours || added.length > 0) && (
        <>
          <div className="field4">
            <span className="lbl">{t('editor.capSize')}</span>
            <input type="range" min={0.6} max={1.8} step={0.05} defaultValue={style.size ?? 1} onChange={(e) => void edit([{ op: 'caption_style', style: { size: Number(e.target.value) } }])} aria-label={t('editor.capSize')} />
          </div>
          <div className="row">
            <label className="field4">
              <span className="lbl">{t('editor.capColor')}</span>
              <input type="color" defaultValue={style.color ?? '#FFFFFF'} onChange={(e) => void edit([{ op: 'caption_style', style: { color: e.target.value.toUpperCase() } }])} />
            </label>
            <label className="field4">
              <span className="lbl">{t('editor.capKeyword')}</span>
              <input type="color" defaultValue={style.highlight ?? '#FFD60A'} onChange={(e) => void edit([{ op: 'caption_style', style: { highlight: e.target.value.toUpperCase() } }])} />
            </label>
          </div>
          <div className="field4">
            <span className="lbl">{t('editor.capPos')}</span>
            <div className="seg">
              {(['bottom', 'middle', 'top'] as const).map((p) => (
                <button key={p} className={(style.position ?? 'bottom') === p ? 'on' : ''} onClick={() => void edit([{ op: 'caption_style', style: { position: p } }])}>
                  {t(`editor.pos.${p}` as MessageKey)}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
      {ours && (
        <div className="field4">
          <span className="lbl">{t('editor.capText')}</span>
          {doc.captions
            .filter((c) => !c.added)
            .map((c) => (
              <input key={c.id} className="inp" defaultValue={c.text} lang="zh-CN" onBlur={(e) => e.target.value.trim() !== c.text && void edit([{ op: 'caption_text', cue: c.id, text: e.target.value.trim() }])} />
            ))}
        </div>
      )}
      {doc.caps.caption_add && (
        <div className="field4">
          <span className="lbl">{t('editor.capAdd')}</span>
          <div className="row">
            <input className="inp sp" value={text} onChange={(e) => setText(e.target.value)} placeholder={t('editor.capAddHint')} data-testid="caption-add-text" />
            <button
              className="btn"
              disabled={!text.trim()}
              onClick={async () => {
                const a = sel?.a ?? time;
                const b = sel?.b ?? Math.min(doc.duration, time + 2.5);
                if (await edit([{ op: 'caption_add', start: a, end: b, text: text.trim() }])) setText('');
              }}
            >
              {t('editor.capAddBtn')}
            </button>
          </div>
          {added.map((c) => (
            <div key={c.id} className="row oplist">
              <span className="num faint">{fmtClock(c.start, true)}</span>
              <span className="sp clamp1" lang="zh-CN">
                {c.text}
              </span>
              <button className="btn ghost sm" onClick={() => void edit([{ op: 'caption_remove', cue: c.id }], true)} aria-label={t('c.remove')}>
                <Trash2 className="ico" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function paramLabel(key: string, sch: { 'x-zh'?: string }): string {
  const k = `fxp.${key}` as MessageKey;
  const own = t(k);
  if (own !== k) return own;
  return getLang() === 'zh-CN' && sch['x-zh'] ? sch['x-zh'].replace(/\s*[(（].*$/, '') : key;
}

function EffectsPanel({
  doc,
  defs,
  time,
  sel,
  fxSel,
  setFxSel,
  edit,
  firstWord,
}: {
  doc: OutputDoc;
  defs: EffectDef[];
  time: number;
  sel: { a: number; b: number } | null;
  fxSel: string | null;
  setFxSel: (id: string | null) => void;
  edit: EditFn;
  firstWord?: string;
}) {
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [pick, setPick] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const cats = [...new Set(defs.map((d) => d.category ?? 'other'))];
  const shown = defs.filter((d) => (!cat || d.category === cat) && (!q || `${d.label.en} ${d.label.zh} ${d.id}`.toLowerCase().includes(q.toLowerCase())));
  const def = defs.find((d) => d.id === pick);
  const inst = doc.effects.find((e) => e.id === fxSel);
  const instDef = inst ? defs.find((d) => d.id === inst.effect) : undefined;
  useEffect(() => {
    if (!def) return;
    const p: Record<string, unknown> = {};
    for (const [k, s] of Object.entries(def.params)) p[k] = s.default ?? (s.type === 'string' ? '' : null);
    if ('text' in def.params && !p.text && firstWord) p.text = firstWord;
    setParams(p);
  }, [def, firstWord]);
  const add = async (where: 'playhead' | 'sel') => {
    if (!def) return;
    const start = where === 'sel' && sel ? sel.a : time;
    const op: EditOp = { op: 'effect_add', effect: def.id, start: Math.round(start * 1000) / 1000, params: Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null)) };
    if (where === 'sel' && sel) op.end = sel.b;
    await edit([op]);
  };
  return (
    <div className="col" style={{ gap: 16 }} data-testid="effects-panel">
      {doc.caps.effects === false ? (
        <div className="note">{t('editor.fxOff')}</div>
      ) : (
        <>
          <input className="inp" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('editor.fxSearch')} aria-label={t('editor.fxSearch')} />
          <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
            <button className={`chip ${!cat ? 'on' : ''}`} onClick={() => setCat('')}>
              {t('editor.fxAll')}
            </button>
            {cats.map((c) => (
              <button key={c} className={`chip ${cat === c ? 'on' : ''}`} onClick={() => setCat(c)}>
                {t(`fx.cat.${c}` as MessageKey) === `fx.cat.${c}` ? c : t(`fx.cat.${c}` as MessageKey)}
              </button>
            ))}
          </div>
          <div className="fxgrid" data-testid="fx-catalogue">
            {shown.map((d) => (
              <button key={d.id} className={`fx ${pick === d.id ? 'on' : ''}`} onClick={() => setPick(pick === d.id ? null : d.id)} title={getLang() === 'zh-CN' ? d.description?.zh : d.description?.en} data-testid="fx-item" data-fx={d.id}>
                <span className={`pv ${previewKind(d)}`}>
                  {d.thumbnail ? <img src={window.desk.mediaUrl(d.thumbnail)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <i>{previewGlyph(d)}</i>}
                </span>
                <span className="clamp1">{effectLabel(d.id, d.label)}</span>
              </button>
            ))}
          </div>
          {def && (
            <div className="card" style={{ padding: 12 }} data-testid="fx-params">
              <b style={{ fontWeight: 500 }}>{effectLabel(def.id, def.label)}</b>
              <div className="muted">{getLang() === 'zh-CN' ? def.description?.zh : def.description?.en}</div>
              <ParamFields schema={def.params} values={params} onChange={setParams} />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn" onClick={() => void add('playhead')} data-testid="fx-add-playhead">
                  {t('editor.fxAddPlayhead')}
                </button>
                <button className="btn" disabled={!sel} onClick={() => void add('sel')}>
                  {t('editor.fxAddSel')}
                </button>
              </div>
            </div>
          )}
          <div className="field4">
            <span className="lbl">{t('editor.fxOnClip')}</span>
            {!doc.effects.length && <span className="muted">{t('editor.fxNone')}</span>}
            <div className="fxlist">
              {doc.effects.map((e) => (
                <div key={e.id} className="li" onClick={() => setFxSel(e.id)} style={{ cursor: 'pointer', fontWeight: e.id === fxSel ? 500 : 400 }} data-testid="fx-instance">
                  <span className="num faint">{fmtClock(e.start, true)}</span>
                  <span className="sp clamp1">
                    {effectLabel(e.effect, e.label)}
                    {typeof e.params?.text === 'string' && e.params.text ? ` · ${e.params.text}` : ''}
                  </span>
                  <button className="btn ghost sm" onClick={(ev) => (ev.stopPropagation(), void edit([{ op: 'effect_remove', id: e.id }], true))} aria-label={t('editor.fxRemove')}>
                    <Trash2 className="ico" />
                  </button>
                </div>
              ))}
            </div>
            {inst && instDef && (
              <div className="card" style={{ padding: 12 }}>
                <ParamFields schema={instDef.params} values={inst.params} onCommit={(k, v) => void edit([{ op: 'effect_update', id: inst.id, params: { [k]: v } }])} />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function previewGlyph(d: EffectDef) {
  const k = previewKind(d);
  const Icon = { pop: Type, zoom: ZoomIn, slide: PanelRight, bar: GanttChart, glow: Square, flash: Sparkle, pulse: Music, fade: Contrast }[k] ?? Sparkle;
  return <Icon className="ico lg" />;
}

function previewKind(d: EffectDef): string {
  if (/pop|stamp|badge|sticker|overlay/.test(d.id)) return 'pop';
  if (/punch|zoom/.test(d.id)) return 'zoom';
  if (/panel|card|callout|bubble/.test(d.id)) return 'slide';
  if (/progress/.test(d.id)) return 'bar';
  if (/box/.test(d.id)) return 'glow';
  if (/xfade|fade|flash/.test(d.id)) return 'flash';
  if (/sfx|music/.test(d.id)) return 'pulse';
  return 'fade';
}

function ParamFields({
  schema,
  values,
  onChange,
  onCommit,
}: {
  schema: EffectDef['params'];
  values: Record<string, unknown>;
  onChange?: (v: Record<string, unknown>) => void;
  onCommit?: (k: string, v: unknown) => void;
}) {
  const set = (k: string, v: unknown, commit = false) => {
    onChange?.({ ...values, [k]: v });
    if (commit) onCommit?.(k, v);
  };
  const keys = Object.keys(schema).filter((k) => !['x', 'y', 'angle', 'in_dur', 'out_dur', 'arrow_x', 'arrow_y', 'w', 'h', 'width'].includes(k));
  return (
    <div className="col" style={{ gap: 8, marginTop: 8 }}>
      {keys.map((k) => {
        const s = schema[k];
        const v = values[k];
        const label = paramLabel(k, s);
        if (s.enum)
          return (
            <label key={k} className="field4">
              <span className="lbl">{label}</span>
              <select className="inp" value={String(v ?? s.default ?? '')} onChange={(e) => set(k, e.target.value, true)}>
                {s.enum.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
          );
        if (s.type === 'number')
          return (
            <label key={k} className="field4">
              <span className="lbl">
                {label} <span className="num">{typeof v === 'number' ? Math.round(v * 100) / 100 : ''}</span>
              </span>
              <input type="range" min={s.minimum ?? 0} max={s.maximum ?? 1} step={((s.maximum ?? 1) - (s.minimum ?? 0)) / 50} value={Number(v ?? s.default ?? 0)} onChange={(e) => set(k, Number(e.target.value))} onMouseUp={(e) => onCommit?.(k, Number((e.target as HTMLInputElement).value))} />
            </label>
          );
        if (s.format === 'color')
          return (
            <label key={k} className="field4">
              <span className="lbl">{label}</span>
              <input type="color" value={typeof v === 'string' && v ? v : '#FFD60A'} onChange={(e) => set(k, e.target.value.toUpperCase(), true)} />
            </label>
          );
        return (
          <label key={k} className="field4">
            <span className="lbl">{label}</span>
            <input className="inp" value={String(v ?? '')} onChange={(e) => set(k, e.target.value)} onBlur={(e) => onCommit?.(k, e.target.value)} lang="zh-CN" data-testid={`fxp-${k}`} />
          </label>
        );
      })}
    </div>
  );
}

function CoverPanel({ doc, time, edit }: { doc: OutputDoc; time: number; edit: EditFn }) {
  const [title, setTitle] = useState(doc.cover_edit?.text ?? doc.post?.title ?? doc.title);
  const [band, setBand] = useState(doc.title_band?.text ?? '');
  const t0 = doc.cover_edit?.t;
  return (
    <div className="col" style={{ gap: 16 }} data-testid="cover-panel">
      {doc.caps.cover !== false && (
        <div className="field4">
          <span className="lbl">{t('editor.coverFrame')}</span>
          {doc.cover && <img src={window.desk.mediaUrl(doc.cover)} alt="" style={{ width: 120, borderRadius: 8 }} />}
          <span className="muted num">{t0 != null ? fmtClock(t0, true) : ''}</span>
          <label className="field4">
            <span className="lbl">{t('editor.coverTitle')}</span>
            <input className="inp" value={title} onChange={(e) => setTitle(e.target.value)} lang="zh-CN" />
          </label>
          <button className="btn" onClick={() => void edit([{ op: 'cover', t: Math.round(time * 100) / 100, text: title, style: 'card' }])} data-testid="cover-use">
            <Check className="ico" />
            {t('editor.coverUse')}
          </button>
        </div>
      )}
      {doc.caps.title_band !== false && (
        <div className="field4">
          <span className="lbl">{t('editor.titleBand')}</span>
          <div className="row">
            <input className="inp sp" value={band} onChange={(e) => setBand(e.target.value)} placeholder={t('editor.titleBandHint')} lang="zh-CN" />
            <button className="btn" onClick={() => void edit([{ op: 'title', text: band.trim() }])}>
              {t('c.save')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ExportPanel({ doc, edit, onFinal, busy }: { doc: OutputDoc; edit: EditFn; onFinal: () => void; busy: boolean }) {
  const have = new Set([...doc.files.map((f) => f.aspect), ...doc.exports.map((e) => e.target)]);
  const flattened = doc.mode === 'flattened';
  return (
    <div className="col" style={{ gap: 16 }} data-testid="export-panel">
      <div className="field4 sizes">
        <span className="lbl">{t('editor.exportSizes')}</span>
        {TARGETS.map((tg) => {
          const orig = doc.files.some((f) => f.aspect === tg);
          const on = have.has(tg);
          return (
            <label key={tg} className="li">
              <input type="checkbox" checked={on} disabled={orig || doc.caps.export === false} onChange={(e) => void edit([e.target.checked ? { op: 'export_add', target: tg, layout: flattened ? 'band' : 'auto' } : { op: 'export_remove', target: tg }])} data-testid={`export-${tg}`} />
              <span>{t(`editor.size.${tg}` as MessageKey)}</span>
            </label>
          );
        })}
        {flattened && <span className="muted">{emsg(doc.caps_notes.find((m) => m.code === 'relayout-crops-burned')) || t('editor.bandHint')}</span>}
      </div>
      <button className="btn" disabled={busy || !doc.steps.length} onClick={onFinal} data-testid="render-final">
        {t('editor.renderFinal')}
      </button>
    </div>
  );
}

function Edits({ doc, onUndoTo }: { doc: OutputDoc; onUndoTo: (k: number) => void }) {
  return (
    <div className="field4" data-testid="edits">
      <span className="lbl">{t('editor.edits')}</span>
      {!doc.steps.length && <span className="muted">{t('editor.noEdits')}</span>}
      <div className="oplist">
        {doc.steps.map((s, k) => (
          <div key={s.id} className="li" data-testid="edit-step">
            <span className="faint num">{k + 1}</span>
            <span className="sp clamp1">{s.describe.map(emsg).join(' · ')}</span>
            {s.by === 'ai' && <Sparkles className="ico faint" />}
            <button className="btn ghost sm" onClick={() => onUndoTo(k)} aria-label={t('c.undo')} data-tip={t('c.undo')}>
              <Undo2 className="ico" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
