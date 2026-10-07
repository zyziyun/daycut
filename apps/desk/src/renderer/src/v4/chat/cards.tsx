// The tool cards of the chat editor (§5.4-5.9): effect, captions, trim, cover, export and the AI-unavailable card.
// Every control is an engine op parameter; a card's primary button = one `edit --ops` = one undo step.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, Crop, FolderOpen, Image as ImageIcon, Play, Sparkles, Subtitles, Upload, X } from 'lucide-react';
import type { CardKind, ChatDoc } from '../../../../shared/chatEdit';
import { EXPORT_PLATFORMS } from '../../../../shared/chatEdit';
import type { EditOp, EffectDef, EffectInstance } from '../../../../shared/v04';
import { fmtClock, getLang, has, t, tk, type MessageKey } from '../../i18n';
import { pauses } from '../../lib/chatEdit';
import { snapEdge } from '../../lib/timeline';
import { textLang, wordsText } from '../../lib/transcript';
import { media } from '../kit';
import { effectLabel, humanizeParam } from '../msg';
import { FrameAt } from './Frame';

export interface CardEnv {
  doc: ChatDoc;
  defs: EffectDef[];
  time: number;
  sel: { a: number; b: number } | null;
  seek: (t: number) => void;
  playRange: (a: number, b: number) => void;
  /** is this card's main button THE filled one on screen */
  primary: boolean;
}

export const CARD_ICON: Record<CardKind, typeof Crop> = { trim: Crop, captions: Subtitles, effect: Sparkles, cover: ImageIcon, export: Upload };
const COLOURS = ['#FFD60A', '#E5484D', '#FFFFFF', '#4FBFAE', '#111111'];
const r3 = (x: number) => Math.round(x * 1000) / 1000;

export function Card({ kind, title, meta, pill, tone = 'tool', children, foot, testId }: { kind: CardKind; title: string; meta?: ReactNode; pill?: ReactNode; tone?: 'tool' | 'draft'; children: ReactNode; foot?: ReactNode; testId?: string }) {
  const Icon = CARD_ICON[kind];
  return (
    <div className={`card2 ${tone}`} data-testid={testId ?? `card-${kind}`}>
      <div className="chd">
        <span className="ic">
          <Icon className="ico" />
        </span>
        <b>{title}</b>
        {pill}
        <span className="sp" style={{ flex: 1 }} />
        {meta}
      </div>
      <div className="cbd">{children}</div>
      {foot && <div className="cft">{foot}</div>}
    </div>
  );
}

function Seg2<T extends string>({ value, options, onChange, testId }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void; testId?: string }) {
  return (
    <div className="seg" role="group" data-testid={testId}>
      {options.map((o) => (
        <button key={o.v} className={value === o.v ? 'on' : ''} onClick={() => onChange(o.v)} aria-pressed={value === o.v}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Foot({ primary, label, onOk, onCancel, extra, disabled, testId }: { primary: boolean; label: string; onOk: () => void; onCancel: () => void; extra?: ReactNode; disabled?: boolean; testId?: string }) {
  return (
    <>
      <button className={`btn ${primary ? 'primary' : ''}`} onClick={onOk} disabled={disabled} data-testid={testId ?? 'card-apply'}>
        {label}
      </button>
      {extra}
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onCancel} data-testid="card-cancel">
        {t('ce.cancel')}
      </button>
    </>
  );
}

// ---------------------------------------------------------------- effect card (§5.4)
const SWAPS = ['stacking-stamps', 'punch-in', 'quote-card', 'callout-bubble', 'sfx-placement', 'pop-words', 'badge'];

export function EffectCard({ env, op, onSubmit, onCancel, onRemove, okLabel }: { env: CardEnv; op: EditOp | null; onSubmit: (ops: EditOp[]) => void; onCancel: () => void; onRemove?: () => void; okLabel?: string }) {
  const { doc, defs } = env;
  const inst: EffectInstance | undefined = op?.op === 'effect_update' ? doc.effects.find((e) => e.id === op.id) : undefined;
  const firstWord = doc.words.find((w) => w.w.length >= 2);
  const [eff, setEff] = useState<string>(op?.op === 'effect_add' ? op.effect : (inst?.effect ?? 'pop-words'));
  const [params, setParams] = useState<Record<string, unknown>>(() => ({
    ...(inst?.params ?? {}),
    ...(op?.op === 'effect_add' || op?.op === 'effect_update' ? (op.params ?? {}) : {}),
  }));
  const a0 = op?.op === 'effect_add' ? op.start : op?.op === 'effect_update' ? (op.start ?? inst?.start ?? env.time) : (env.sel?.a ?? firstWord?.t ?? env.time);
  const def = defs.find((d) => d.id === eff);
  const dd = def?.default_dur ?? 1.2;
  const b0 = op?.op === 'effect_add' ? (op.end ?? a0 + dd) : op?.op === 'effect_update' ? (op.end ?? inst?.end ?? a0 + dd) : (env.sel?.b ?? a0 + dd);
  const [rng, setRng] = useState<[number, number]>([r3(a0), r3(Math.min(doc.duration, b0))]);
  useEffect(() => {
    if ('text' in (def?.params ?? {}) && !params.text) {
      const said = wordsText(doc.words.filter((w) => w.t >= rng[0] - 0.01 && w.te <= rng[1] + 0.01)).slice(0, 8);
      setParams((p) => ({ ...p, text: said || firstWord?.w || '' }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eff]);
  const sch = def?.params ?? {};
  const keys = Object.keys(sch).filter((k) => !['x', 'y', 'angle', 'in_dur', 'out_dur', 'arrow_x', 'arrow_y', 'w', 'h', 'width', 'image', 'file', 'chapters', 'bullets'].includes(k));
  const label = (k: string) => {
    const own = `ce.fx.${k === 'color' ? 'colour' : k === 'anim' ? 'motion' : k}`;
    if (has(own)) return tk(own);
    if (has(`fxp.${k}`)) return tk(`fxp.${k}`);
    return getLang() === 'zh-CN' && sch[k]['x-zh'] ? sch[k]['x-zh']!.replace(/\s*[(（].*$/, '') : humanizeParam(k);
  };
  const submit = () => {
    const clean = Object.fromEntries(Object.entries(params).filter(([k, v]) => v !== '' && v !== null && v !== undefined && k in sch));
    if (inst && eff === inst.effect) onSubmit([{ op: 'effect_update', id: inst.id, start: rng[0], end: rng[1], params: clean }]);
    else if (inst) onSubmit([{ op: 'effect_remove', id: inst.id }, { op: 'effect_add', effect: eff, start: rng[0], end: rng[1], params: clean }]);
    else onSubmit([{ op: 'effect_add', effect: eff, start: rng[0], end: rng[1], params: clean }]);
  };
  const swaps = SWAPS.filter((x) => x !== eff && defs.some((d) => d.id === x)).slice(0, 5);
  return (
    <Card
      kind="effect"
      title={effectLabel(eff, def?.label)}
      meta={<span className="mono">{`${fmtClock(rng[0], true)}–${fmtClock(rng[1], true)}`}</span>}
      foot={
        <Foot
          primary={env.primary}
          label={okLabel ?? t('ce.apply')}
          onOk={submit}
          onCancel={onCancel}
          extra={
            <>
              <button className="btn" onClick={() => env.playRange(rng[0], rng[1])} data-testid="fx-play-part">
                <Play className="ico" />
                {t('ce.fx.playPart')}
              </button>
              {onRemove && (
                <button className="btn ghost icon" onClick={onRemove} aria-label={t('ce.fx.remove')} data-tip={t('ce.fx.remove')} data-testid="fx-remove">
                  <X className="ico" />
                </button>
              )}
            </>
          }
        />
      }
      testId="card-effect"
    >
      <div className="fxc">
        <div className="pv">
          <FrameAt file={doc.files[0]?.path ?? null} t={rng[0] + 0.05} w={132} h={176} />
          {typeof params.text === 'string' && params.text && (
            <span style={{ color: String(params.color ?? '#FFD60A'), fontSize: 22 * Math.max(0.6, Math.min(1.8, Number(params.size ?? 0.11) / 0.11)) }}>{params.text}</span>
          )}
        </div>
        <div className="col" style={{ gap: 10, minWidth: 0 }}>
          {keys.map((k) => {
            const s = sch[k];
            const v = params[k];
            if (s.format === 'color' || k === 'color' || k === 'accent')
              return (
                <div key={k} className="fld">
                  <span className="lbl">{label(k)}</span>
                  <div className="sw">
                    {COLOURS.map((c) => (
                      <button key={c} className={String(v ?? '').toUpperCase() === c ? 'on' : ''} style={{ background: c }} onClick={() => setParams({ ...params, [k]: c })} aria-label={c} data-testid={`fx-colour-${c.slice(1)}`} />
                    ))}
                  </div>
                </div>
              );
            if (s.enum)
              return (
                <div key={k} className="fld">
                  <span className="lbl">{label(k)}</span>
                  <Seg2 value={String(v ?? s.default ?? s.enum[0])} options={s.enum.slice(0, 4).map((o) => ({ v: o, label: has(`ce.fx.anim.${o}`) ? tk(`ce.fx.anim.${o}`) : o }))} onChange={(x) => setParams({ ...params, [k]: x })} testId={`fx-${k}`} />
                </div>
              );
            if (s.type === 'number' && (k === 'size' || k === 'scale')) {
              const d = Number(s.default ?? 1);
              const opts: [string, number][] = [
                ['S', r3(Math.max(s.minimum ?? 0, d * 0.75))],
                ['M', d],
                ['L', r3(Math.min(s.maximum ?? d * 2, d * 1.45))],
              ];
              const cur = Number(v ?? d);
              const on = opts.reduce((b, o) => (Math.abs(o[1] - cur) < Math.abs(b[1] - cur) ? o : b))[0];
              return (
                <div key={k} className="fld">
                  <span className="lbl">{label(k)}</span>
                  <Seg2 value={on} options={opts.map(([l]) => ({ v: l, label: l }))} onChange={(x) => setParams({ ...params, [k]: opts.find((o) => o[0] === x)![1] })} testId={`fx-${k}`} />
                </div>
              );
            }
            if (s.type === 'number')
              return (
                <label key={k} className="fld">
                  <span className="lbl">{label(k)}</span>
                  <input type="range" min={s.minimum ?? 0} max={s.maximum ?? 1} step={((s.maximum ?? 1) - (s.minimum ?? 0)) / 50} value={Number(v ?? s.default ?? 0)} onChange={(e) => setParams({ ...params, [k]: Number(e.target.value) })} />
                </label>
              );
            return (
              <label key={k} className="fld">
                <span className="lbl">{label(k)}</span>
                <input className="inp" value={String(v ?? '')} onChange={(e) => setParams({ ...params, [k]: e.target.value })} lang="zh-CN" data-testid={`fx-param-${k}`} />
              </label>
            );
          })}
        </div>
      </div>
      <div className="fld">
        <span className="lbl">{t('ce.fx.when')}</span>
        <WordRange doc={doc} rng={rng} onChange={setRng} />
      </div>
      {swaps.length > 0 && (
        <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
          <span className="lbl" style={{ width: 56, flex: 'none', paddingTop: 5 }}>{t('ce.fx.swap')}</span>
          <div className="chips">
            {swaps.map((x) => (
              <button key={x} className="chip" onClick={() => setEff(x)} data-testid={`fx-swap-${x}`}>
                {effectLabel(x, defs.find((d) => d.id === x)?.label)}
              </button>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

/** A strip of the words around a range; drag the amber edges (snapped to words). */
export function WordRange({ doc, rng, onChange }: { doc: ChatDoc; rng: [number, number]; onChange: (r: [number, number]) => void }) {
  const box = useRef<HTMLDivElement | null>(null);
  const slots = useMemo(() => {
    const ws = doc.words.filter((w) => w.te > rng[0] - 4 && w.t < rng[1] + 4);
    if (ws.length >= 3) {
      const i0 = Math.max(0, ws.findIndex((w) => w.te > rng[0]));
      const inside = ws.filter((w) => w.te > rng[0] && w.t < rng[1]).length;
      const s0 = Math.max(0, Math.min(ws.length - 10, i0 - Math.max(2, Math.floor((10 - inside) / 2))));
      return ws.slice(s0, s0 + 10).map((w) => ({ l: w.w, t: w.t, te: w.te }));
    }
    const a = Math.max(0, rng[0] - 1.5);
    return Array.from({ length: 8 }, (_, i) => ({ l: fmtClock(a + i * 0.5, true), t: a + i * 0.5, te: a + (i + 1) * 0.5 }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.words, Math.round(rng[0]), Math.round(rng[1])]);
  const n = slots.length || 1;
  const t0 = slots[0]?.t ?? 0;
  const t1 = slots[n - 1]?.te ?? 1;
  // index-based layout: every word the same width (readable), the range drawn over the words it covers
  const idx = (x: number, end: boolean) => {
    for (let i = 0; i < n; i++) if (end ? slots[i].te >= x - 0.02 : slots[i].te > x + 0.02) return i;
    return n - 1;
  };
  const li = idx(rng[0], false);
  const ri = idx(rng[1], true);
  const drag = (edge: 'l' | 'r') => (e: React.PointerEvent) => {
    e.preventDefault();
    const r = box.current!.getBoundingClientRect();
    const mv = (ev: PointerEvent) => {
      const i = Math.max(0, Math.min(n - 1, Math.floor(((ev.clientX - r.left) / r.width) * n)));
      if (edge === 'l') onChange([r3(Math.min(slots[i].t, rng[1] - 0.2)), rng[1]]);
      else onChange([rng[0], r3(Math.max(slots[i].te, rng[0] + 0.2))]);
    };
    const up = () => {
      window.removeEventListener('pointermove', mv);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', mv);
    window.addEventListener('pointerup', up);
  };
  return (
    <>
      <div className="wstrip" ref={box} data-testid="fx-words">
        {slots.map((s, i) => (
          <span key={i} lang={textLang(s.l)} style={{ color: i >= li && i <= ri ? 'var(--text)' : undefined }}>
            {s.l}
          </span>
        ))}
        <div className="rng" style={{ left: `${(li / n) * 100}%`, width: `${((ri - li + 1) / n) * 100}%` }} />
        <i className="eg" style={{ left: `${(li / n) * 100}%` }} onPointerDown={drag('l')} data-testid="fx-edge-l" />
        <i className="eg" style={{ left: `${((ri + 1) / n) * 100}%` }} onPointerDown={drag('r')} data-testid="fx-edge-r" />
      </div>
      <div className="wsub">
        <span>{fmtClock(t0, true)}</span>
        <b data-testid="fx-span">{t('ce.fx.span', { a: fmtClock(rng[0], true), b: fmtClock(rng[1], true), d: (Math.round((rng[1] - rng[0]) * 10) / 10).toFixed(1) })}</b>
        <span>{fmtClock(t1, true)}</span>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- captions card (§5.5)
export function CaptionsCard({ env, ops, onSubmit, onCancel, okLabel }: { env: CardEnv; ops: EditOp[]; onSubmit: (ops: EditOp[]) => void; onCancel: () => void; okLabel?: string }) {
  const { doc } = env;
  const ours = !!doc.caps.caption_text;
  const style = doc.caption_style ?? {};
  const a = env.sel?.a ?? Math.max(0, env.time - 3);
  const b = env.sel?.b ?? env.time + 9;
  const rows = doc.captions.filter((c) => !c.removed && !c.added && c.end > a && c.start < b).slice(0, 6);
  const aiText = new Map(ops.filter((o): o is Extract<EditOp, { op: 'caption_text' }> => o.op === 'caption_text').map((o) => [o.cue, o.text]));
  const [text, setText] = useState<Record<string, string>>(() => Object.fromEntries(rows.map((r) => [r.id, aiText.get(r.id) ?? r.text])));
  const st0 = (ops.find((o) => o.op === 'caption_style') as Extract<EditOp, { op: 'caption_style' }> | undefined)?.style;
  const [kw, setKw] = useState<string[]>(st0?.keywords ?? style.keywords ?? []);
  const [hl, setHl] = useState<string>(st0?.highlight ?? style.highlight ?? '#FFD60A');
  const [look, setLook] = useState<'clean' | 'bold' | 'boxed'>('clean');
  const [pos, setPos] = useState<string>(st0?.position ?? style.position ?? 'bottom');
  const [word, setWord] = useState('');
  const [addText, setAddText] = useState(() => (ours ? '' : wordsText(doc.words.filter((w) => w.t >= a - 0.01 && w.te <= (env.sel?.b ?? a + 2.5) + 0.01))));
  const cands = useMemo(() => [...new Set([...kw, ...doc.words.filter((w) => w.w.length >= 2 && w.t >= a && w.t <= b).map((w) => w.w)])].slice(0, 4), [kw, doc.words, a, b]);
  const build = (): EditOp[] => {
    if (!ours)
      return addText.trim()
        ? [{ op: 'caption_add', start: r3(env.sel?.a ?? env.time), end: r3(env.sel?.b ?? Math.min(doc.duration, env.time + 2.5)), text: addText.trim() }]
        : [];
    const out: EditOp[] = rows.filter((r) => (text[r.id] ?? r.text).trim() !== r.text).map((r) => ({ op: 'caption_text', cue: r.id, text: text[r.id].trim() }));
    const sty: Record<string, unknown> = {};
    if (JSON.stringify(kw) !== JSON.stringify(style.keywords ?? [])) sty.keywords = kw;
    if (hl !== (style.highlight ?? '#FFD60A')) sty.highlight = hl;
    if (pos !== (style.position ?? 'bottom')) sty.position = pos;
    if (look !== 'clean') Object.assign(sty, look === 'bold' ? { stroke: 4 } : { box: true });
    if (Object.keys(sty).length) out.push({ op: 'caption_style', style: sty } as EditOp);
    return out;
  };
  const n = build().length;
  return (
    <Card
      kind="captions"
      title={t('ce.cap.title')}
      meta={<span className="mono">{`${fmtClock(a)}–${fmtClock(b)}${ours ? ` · ${t('ce.cap.lines', { n: rows.length })}` : ''}`}</span>}
      foot={
        <>
          <button className={`btn ${env.primary ? 'primary' : ''}`} disabled={!n} onClick={() => onSubmit(build())} data-testid="card-apply">
            {okLabel ?? (ours ? t('ce.cap.applyN', { n }) : t('ce.cap.addHere'))}
          </button>
          {ours && <span className="faint" style={{ fontSize: 12 }}>{t('ce.cap.checked')}</span>}
          <span style={{ flex: 1 }} />
          <button className="btn ghost" onClick={onCancel} data-testid="card-cancel">
            {t('ce.cancel')}
          </button>
        </>
      }
    >
      {!ours && <div className="note" data-testid="caps-burned">{t('ce.cap.burned')}</div>}
      {ours && rows.length > 0 && (
        <div className="caps">
          {rows.map((r) => (
            <div key={r.id} className={`cl ${aiText.has(r.id) ? 'ai' : ''}`}>
              <span className="mono">{fmtClock(r.start, true)}</span>
              <input value={text[r.id] ?? r.text} onChange={(e) => setText({ ...text, [r.id]: e.target.value })} lang="zh-CN" data-testid="cap-line" />
              {aiText.has(r.id) && <span className="pill">{t('ce.cap.aiFix')}</span>}
            </div>
          ))}
        </div>
      )}
      {ours ? (
        <>
          <div className="fld">
            <span className="lbl">{t('ce.cap.keywords')}</span>
            <div className="chips">
              {cands.map((w) => (
                <span key={w} className="kw" lang={textLang(w)}>
                  {w}
                  {['#E5484D', '#FFD60A'].map((c) => (
                    <button
                      key={c}
                      className={kw.includes(w) && hl === c ? 'on' : ''}
                      style={{ background: c }}
                      onClick={() => {
                        if (kw.includes(w) && hl === c) setKw(kw.filter((x) => x !== w));
                        else {
                          setKw([...new Set([...kw, w])]);
                          setHl(c);
                        }
                      }}
                      aria-label={c}
                    />
                  ))}
                </span>
              ))}
              <input className="inp" style={{ width: 96, height: 28 }} value={word} placeholder={t('ce.cap.addWord')} onChange={(e) => setWord(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && word.trim() && (setKw([...new Set([...kw, word.trim()])]), setWord(''))} aria-label={t('ce.cap.addWordHint')} />
            </div>
          </div>
          <div className="row" style={{ gap: 24, flexWrap: 'wrap' }}>
            <div className="fld">
              <span className="lbl">{t('ce.cap.style')}</span>
              <Seg2 value={look} options={(['clean', 'bold', 'boxed'] as const).map((v) => ({ v, label: t(`ce.cap.style.${v}` as MessageKey) }))} onChange={setLook} />
            </div>
            <div className="fld">
              <span className="lbl">{t('ce.cap.position')}</span>
              <Seg2 value={pos} options={(['bottom', 'middle', 'top'] as const).map((v) => ({ v, label: t(`editor.pos.${v}` as MessageKey) }))} onChange={setPos} />
            </div>
          </div>
        </>
      ) : (
        <label className="fld">
          <span className="lbl">{t('ce.cap.addHere')}</span>
          <input className="inp" value={addText} onChange={(e) => setAddText(e.target.value)} placeholder={t('ce.cap.addHint')} lang="zh-CN" data-testid="cap-add-text" />
        </label>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- trim card (§5.6)
export function TrimCard({ env, ops, onSubmit, onCancel, onCompare, comparing, okLabel }: { env: CardEnv; ops: EditOp[]; onSubmit: (ops: EditOp[]) => void; onCancel: () => void; onCompare?: (ops: EditOp[] | null) => void; comparing?: boolean; okLabel?: string }) {
  const { doc } = env;
  const D = doc.duration || 1;
  const words = doc.words;
  const trimOp = ops.find((o) => o.op === 'trim') as Extract<EditOp, { op: 'trim' }> | undefined;
  const firstT = words[0]?.t ?? 0;
  const lastTe = words[words.length - 1]?.te ?? D;
  // start from what is there now (or the AI's proposal); the boxes below say how much silence the edges hold
  const [a, setA] = useState<number>(trimOp?.start ?? doc.trim?.start ?? 0);
  const [b, setB] = useState<number>(trimOp?.end ?? doc.trim?.end ?? D);
  const ps = useMemo(() => pauses(words).filter((p) => !doc.cuts.some((c) => c.start <= p.start + 0.1 && c.end >= p.end - 0.1)), [words, doc.cuts]);
  const proposedCuts = ops.filter((o): o is Extract<EditOp, { op: 'cut' }> => o.op === 'cut');
  const [kept, setKept] = useState<Set<number>>(() => (proposedCuts.length ? new Set(ps.map((p, i) => (proposedCuts.some((c) => c.start < p.end && c.end > p.start) ? -1 : i)).filter((i) => i >= 0)) : new Set()));
  const [snap, setSnap] = useState(true);
  const [cutSel, setCutSel] = useState(!!env.sel);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const W = (c.width = c.clientWidth * 2);
    const H = (c.height = c.clientHeight * 2);
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = getComputedStyle(c).getPropertyValue('--text-faint') || '#888';
    const n = doc.waveform.length || 1;
    doc.waveform.forEach((v, i) => {
      const h = Math.max(2, v * H * 0.85);
      ctx.fillRect((i / n) * W, (H - h) / 2, Math.max(1, W / n - 1), h);
    });
  }, [doc.waveform]);
  const pct = (x: number) => `${(x / D) * 100}%`;
  const drag = (edge: 'a' | 'b') => (e: React.PointerEvent) => {
    e.preventDefault();
    const r = box.current!.getBoundingClientRect();
    const mv = (ev: PointerEvent) => {
      const raw = Math.max(0, Math.min(D, ((ev.clientX - r.left) / r.width) * D));
      const x = snap ? snapEdge(words, raw) : raw;
      if (edge === 'a') setA(r3(Math.min(x, b - 0.5)));
      else setB(r3(Math.max(x, a + 0.5)));
    };
    const up = () => {
      window.removeEventListener('pointermove', mv);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', mv);
    window.addEventListener('pointerup', up);
  };
  const build = (): EditOp[] => {
    const out: EditOp[] = [];
    const ta = doc.trim?.start ?? 0;
    const tb = doc.trim?.end ?? D;
    if (Math.abs(a - ta) > 0.01 || Math.abs(b - tb) > 0.01) out.push({ op: 'trim', start: a, end: b, snap } as EditOp);
    ps.forEach((p, i) => {
      if (!kept.has(i) && p.start >= a && p.end <= b) out.push({ op: 'cut', start: r3(p.start + 0.08), end: r3(p.end - 0.08) });
    });
    if (cutSel && env.sel) out.push({ op: 'cut', start: r3(env.sel.a), end: r3(env.sel.b) });
    return out;
  };
  const built = build();
  const lenAfter = b - a - built.filter((o) => o.op === 'cut').reduce((s, o) => s + ((o as { end: number }).end - (o as { start: number }).start), 0);
  const headW = wordsText(words.filter((w) => w.t >= a).slice(0, 4));
  const tailW = wordsText(words.filter((w) => w.te <= b).slice(-3));
  return (
    <Card
      kind="trim"
      title={t('ce.trim.title')}
      meta={Math.abs(lenAfter - D) > 0.05 ? <span className="mono">{`${fmtClock(D, true)} → ${fmtClock(lenAfter / (doc.speed || 1), true)}`}</span> : undefined}
      foot={
        <Foot
          primary={env.primary}
          label={okLabel ?? t('ce.apply')}
          disabled={!built.length}
          onOk={() => onSubmit(built)}
          onCancel={onCancel}
          extra={
            onCompare && (
              <button className={`btn ${comparing ? 'toggle on' : ''}`} onClick={() => onCompare(comparing ? null : built)} aria-pressed={comparing} data-testid="card-compare">
                {t('ce.compare')}
              </button>
            )
          }
        />
      }
    >
      <div className="row" style={{ justifyContent: 'space-between', fontSize: 12 }}>
        <span className="muted">
          {t('ce.trim.starts')} <span className="mono" style={{ color: 'var(--accent)' }} data-testid="trim-a">{fmtClock(a, true)}</span>
        </span>
        <span className="muted">
          {t('ce.trim.ends')} <span className="mono" style={{ color: 'var(--accent)' }} data-testid="trim-b">{fmtClock(b, true)}</span>
        </span>
      </div>
      <div className="trw" ref={box}>
        <canvas ref={canvas} />
        {ps.map((p, i) => (
          <i key={i} className={`ps ${kept.has(i) ? 'kept' : ''}`} style={{ left: pct(p.start), width: pct(p.end - p.start) }} />
        ))}
        <i className="out" style={{ left: 0, width: pct(a) }} />
        <i className="out" style={{ left: pct(b), right: 0 }} />
        <i className="h" style={{ left: pct(a) }} onPointerDown={drag('a')} data-testid="trim-h-a" />
        <i className="h" style={{ left: pct(b) }} onPointerDown={drag('b')} data-testid="trim-h-b" />
      </div>
      {words.length > 0 && (
        <div className="trends">
          <button onClick={() => env.playRange(a, Math.min(b, a + 3))}>
            <Play className="ico" />
            <span lang={textLang(headW)}>{t('ce.trim.startOn', { w: headW })}</span>
            <small>{t('ce.trim.cutsHead', { s: (Math.round(Math.max(0, firstT - a) * 10) / 10).toFixed(1) })}</small>
          </button>
          <button onClick={() => env.playRange(Math.max(a, b - 3), b)}>
            <Play className="ico" />
            <span lang={textLang(tailW)}>{t('ce.trim.endOn', { w: tailW })}</span>
            <small>{t('ce.trim.cutsTail', { s: (Math.round(Math.max(0, b - lastTe) * 10) / 10).toFixed(1) })}</small>
          </button>
        </div>
      )}
      <div className="fld">
        <span className="lbl">{ps.length ? t('ce.trim.pauses', { n: ps.length - kept.size }) : t('ce.trim.noPauses')}</span>
        {ps.length > 0 && (
          <div className="chips">
            {ps.map((p, i) => (
              <button
                key={i}
                className={`chip mono ${kept.has(i) ? 'kept' : 'on'}`}
                onClick={() => {
                  const k = new Set(kept);
                  if (k.has(i)) k.delete(i);
                  else k.add(i);
                  setKept(k);
                }}
                data-testid="trim-pause"
              >
                {`${fmtClock(p.start, true)} · ${(Math.round((p.end - p.start) * 10) / 10).toFixed(1)} s`}
              </button>
            ))}
          </div>
        )}
      </div>
      {env.sel && (
        <button className={`chip ${cutSel ? 'on' : ''}`} style={{ width: 'fit-content' }} onClick={() => setCutSel(!cutSel)} data-testid="trim-cut-sel">
          {t('ce.trim.cutSel', { a: fmtClock(env.sel.a, true), b: fmtClock(env.sel.b, true) })}
        </button>
      )}
      <span className={`sw2 ${snap ? 'on' : ''}`} role="switch" aria-checked={snap} tabIndex={0} onClick={() => setSnap(!snap)} onKeyDown={(e) => e.key === ' ' && setSnap(!snap)}>
        <i />
        {t('ce.trim.snap')} <span className="faint" style={{ fontSize: 12 }}>{t('ce.trim.snapHint')}</span>
      </span>
    </Card>
  );
}

// ---------------------------------------------------------------- cover card (§5.7)
export function CoverCard({ env, op, onSubmit, onCancel, okLabel }: { env: CardEnv; op: EditOp | null; onSubmit: (ops: EditOp[]) => void; onCancel: () => void; okLabel?: string }) {
  const { doc } = env;
  const a = doc.trim?.start ?? 0;
  const b = doc.trim?.end ?? doc.duration;
  const times = useMemo(() => Array.from({ length: 6 }, (_, i) => r3(a + ((i + 0.5) * (b - a)) / 6)), [a, b]);
  const init = op?.op === 'cover' ? op : null;
  const [pick, setPick] = useState<number>(init?.t ?? times[2]);
  const [title, setTitle] = useState<string>(init?.text ?? doc.cover_edit?.text ?? doc.post?.title ?? doc.title ?? '');
  const [style, setStyle] = useState<'card' | 'plain' | 'band'>((init?.style as 'card') ?? 'card');
  const file = doc.files[0]?.path ?? null;
  return (
    <Card
      kind="cover"
      title={t('ce.cover.title')}
      foot={<Foot primary={env.primary} label={okLabel ?? t('ce.cover.use')} onOk={() => onSubmit([{ op: 'cover', t: pick, text: title.trim(), style }])} onCancel={onCancel} />}
    >
      <div className="cvr">
        <div className="col" style={{ gap: 10, minWidth: 0 }}>
          <div className="frames">
            {times.map((x, i) => (
              <button key={x} className={Math.abs(pick - x) < 0.01 ? 'on' : ''} onClick={() => setPick(x)} title={fmtClock(x, true)} data-testid="cover-frame">
                <FrameAt file={file} t={x} w={72} h={96} />
                {i === 2 && <span className="ai" title={t('ce.cover.why')}>{t('ce.cover.ai')}</span>}
              </button>
            ))}
          </div>
          <label className="fld">
            <span className="lbl">{t('ce.cover.text')}</span>
            <input className="inp" value={title} onChange={(e) => setTitle(e.target.value)} lang="zh-CN" data-testid="cover-title" />
          </label>
          <Seg2 value={style} options={(['card', 'plain', 'band'] as const).map((v) => ({ v, label: t(`ce.cover.style.${v}` as MessageKey) }))} onChange={setStyle} />
        </div>
        <div className="cpv">
          <FrameAt file={file} t={pick} w={108} h={144} />
          <span className={`tt ${style}`} lang="zh-CN">{title.replace(/\|/g, '\n')}</span>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- export card (§5.8)
export interface ExportRun {
  job: string | null;
  targets: string[];
  rows: Record<string, { stage: string; progress: number; done: boolean; file?: string }>;
  state: 'running' | 'done' | 'stopped' | 'failed';
  error?: string;
  simulated?: boolean;
  started: number;
}

export function primaryPlatform(doc: ChatDoc): string {
  const a = doc.files[0]?.aspect;
  return a === '9:16' ? 'douyin:vertical' : a === '16:9' ? 'youtube:horizontal' : 'xiaohongshu:vertical';
}

export function ExportCard({ env, run, onStart, onStop, onCancel }: { env: CardEnv; run: ExportRun | null; onStart: (targets: string[]) => void; onStop: () => void; onCancel: () => void }) {
  const { doc } = env;
  const prim = primaryPlatform(doc);
  const norm = (x: string) => (x === '9:16' ? 'douyin:vertical' : x === '16:9' ? 'youtube:horizontal' : x === '3:4' ? 'xiaohongshu:vertical' : x.includes(':') ? x : `${x}:vertical`);
  const [on, setOn] = useState<Set<string>>(() => new Set([prim, ...doc.exports.map((e) => norm(e.target))]));
  const running = run?.state === 'running';
  const vertical = (doc.h ?? 4) > (doc.w ?? 3) || ['3:4', '9:16'].includes(doc.files[0]?.aspect ?? '');
  const anyH = [...on].some((x) => x.endsWith(':horizontal'));
  const k = run ? Object.values(run.rows).filter((r) => r.done).length : 0;
  const name = (tg: string) => {
    const p = EXPORT_PLATFORMS.find((x) => x.target === tg || (tg === 'primary' && x.target === prim));
    return p ? `${tk(`ce.pf.${p.id}`)} ${p.aspect}` : tg;
  };
  const left = run && running ? Math.max(0, run.targets.length - k) : 0;
  return (
    <Card
      kind="export"
      title={t('ce.exp.title')}
      pill={run ? <span className={`pill ${run.state === 'done' ? 'ok' : 'ok'}`} data-testid="export-count">{t('ce.exp.doneOf', { k, n: run.targets.length })}</span> : undefined}
      meta={<span className="faint" style={{ fontSize: 12 }}>{t('ce.exp.where')}</span>}
      foot={
        running ? (
          <>
            <span className="muted sp" style={{ fontSize: 12, flex: 1 }}>
              {`${t('ce.exp.about', { min: Math.max(1, Math.round(left * 0.7)) })} · ${t('ce.exp.left')}`}
            </span>
            <button className="btn ghost" onClick={onStop} data-testid="export-stop">
              {t('ce.stop')}
            </button>
          </>
        ) : run ? (
          <>
            <span className="muted" style={{ fontSize: 12, flex: 1 }} data-testid="export-state">
              {run.state === 'done' ? (run.simulated ? t('ce.exp.simulated') : t('ce.exp.allDone')) : run.state === 'stopped' ? t('ce.exp.stopped') : t('ce.exp.failed', { why: run.error ?? '' })}
            </span>
            <button className="btn ghost" onClick={onCancel}>
              {t('ce.done')}
            </button>
          </>
        ) : (
          <>
            <button className={`btn ${env.primary ? 'primary' : ''}`} disabled={!on.size} onClick={() => onStart(EXPORT_PLATFORMS.map((p) => p.target).filter((x) => on.has(x)))} data-testid="export-go">
              {t('ce.exp.go', { n: on.size })}
            </button>
            <span className="faint" style={{ fontSize: 12 }}>{t('ce.exp.about', { min: Math.max(1, Math.round(on.size * 0.7)) })}</span>
            <span style={{ flex: 1 }} />
            <button className="btn ghost" onClick={onCancel} data-testid="card-cancel">
              {t('ce.cancel')}
            </button>
          </>
        )
      }
      testId="card-export"
    >
      {!run && <div className="pfg">
        {EXPORT_PLATFORMS.map((p) => (
          <label key={p.id} className={`pf ${on.has(p.target) ? 'on' : ''} ${run ? 'lock' : ''}`} data-testid={`pf-${p.id}`}>
            <input
              type="checkbox"
              checked={on.has(p.target)}
              disabled={!!run || doc.caps.export === false}
              onChange={(e) => {
                const s = new Set(on);
                if (e.target.checked) s.add(p.target);
                else s.delete(p.target);
                setOn(s);
              }}
            />
            <span>{tk(`ce.pf.${p.id}`)}</span>
            <small>{p.aspect}</small>
          </label>
        ))}
      </div>}
      {!run && anyH && vertical && <span className="muted" style={{ fontSize: 12 }}>{t('ce.exp.band')}</span>}
      {run &&
        run.targets.map((tg) => {
          const r = run.rows[tg];
          return (
            <div key={tg} className="erow" data-testid="export-row" data-done={r?.done ? '1' : '0'}>
              <span className="th">{doc.cover && <img src={media(doc.cover)} alt="" />}</span>
              <div style={{ minWidth: 0 }}>
                <b className="clamp1" style={{ fontWeight: 500, display: 'block' }}>{name(tg)}</b>
                {r?.done && <span className="s" style={{ color: 'var(--accent)' }}>{t('ce.exp.done')}</span>}
                {!r?.done && (
                  <>
                    <span className="s">{r ? `${t(`ce.exp.stage.${r.stage}` as MessageKey)} · ${Math.round(r.progress * 100)}%` : t('ce.exp.stage.waiting')}</span>
                    <div className="bar">
                      <i style={{ width: `${Math.round((r?.progress ?? 0) * 100)}%` }} />
                    </div>
                  </>
                )}
              </div>
              {r?.done && r.file ? (
                <div className="row" style={{ gap: 4 }}>
                  <button className="btn sm icon" onClick={() => window.open(media(r.file))} aria-label={t('ce.exp.play')} data-tip={t('ce.exp.play')}>
                    <Play className="ico" />
                  </button>
                  <button className="btn sm icon" onClick={() => void window.desk.showItem(r.file!)} aria-label={t('ce.exp.show')} data-tip={t('ce.exp.show')}>
                    <FolderOpen className="ico" />
                  </button>
                </div>
              ) : (
                <span className="mono">{r ? '' : ''}</span>
              )}
            </div>
          );
        })}
    </Card>
  );
}

// ---------------------------------------------------------------- AI unavailable (§5.9)
export const PHRASES: [MessageKey, MessageKey][] = [
  ['ce.ph.speed', 'ce.ph.speedPrompt'],
  ['ce.ph.head', 'ce.ph.headPrompt'],
  ['ce.ph.douyin', 'ce.ph.douyinPrompt'],
  ['ce.ph.louder', 'ce.ph.louderPrompt'],
  ['ce.ph.progress', 'ce.ph.progressPrompt'],
  ['ce.ph.fade', 'ce.ph.fadePrompt'],
];

export function FallbackCard({ q, failed, primary, onTool, onSay, onConnect, onRetry }: { q: string; failed: boolean; primary: boolean; onTool: (k: CardKind) => void; onSay: (s: string) => void; onConnect: () => void; onRetry: () => void }) {
  return (
    <div className="card2 draft" data-testid="card-offline">
      <div className="chd">
        <span className="ic">
          <AlertTriangle className="ico" />
        </span>
        <b>{failed ? t('ce.off.failed') : t('ce.off.title')}</b>
      </div>
      <div className="cbd">
        <span>{failed ? t('ce.off.leadFailed') : t('ce.off.lead', { q })}</span>
        <div className="fld">
          <span className="lbl">{t('ce.off.tools')}</span>
          <div className="chips">
            {(['trim', 'captions', 'effect', 'cover', 'export'] as CardKind[]).map((k) => {
              const Icon = CARD_ICON[k];
              return (
                <button key={k} className="chip mono" onClick={() => onTool(k)} data-testid={`off-tool-${k}`}>
                  <Icon className="ico" style={{ width: 13, height: 13 }} />/{t(`ce.cmd.${k}` as MessageKey)}
                </button>
              );
            })}
          </div>
        </div>
        <div className="fld">
          <span className="lbl">{t('ce.off.phrases')}</span>
          <div className="chips">
            {PHRASES.map(([k, p]) => (
              <button key={k} className="chip" onClick={() => onSay(t(p))} data-testid="off-phrase">
                {t(k)}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="cft">
        {failed ? (
          <button className={`btn ${primary ? 'primary' : ''}`} onClick={onRetry} data-testid="off-retry">
            {t('ce.off.retry')}
          </button>
        ) : (
          <button className={`btn ${primary ? 'primary' : ''}`} onClick={onConnect} data-testid="off-connect">
            {t('ce.off.connect')}
          </button>
        )}
        <span className="faint" style={{ fontSize: 12 }}>{t('ce.off.connectHint')}</span>
      </div>
    </div>
  );
}
