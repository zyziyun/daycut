// Settings › Watermark: type your handle (or drop a logo, or generate one from the handle), see it on a sample
// 9:16 and 16:9 frame drawn by the engine exactly as an export places it, pick a corner, size and opacity, and
// "Add to every video by default". Every control applies at once (engine: $VSTUDIO_HOME/watermark.json).
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { ImageUp, WandSparkles } from 'lucide-react';
import { EXPORT_PLATFORMS } from '../../../shared/chatEdit';
import { orderPlatforms, platformLabel } from '../../../shared/platforms';
import { WM_MAX_TEXT, WM_OPACITY, WM_POSITIONS, WM_SIZE, WM_STYLES, type WatermarkDoc, type WatermarkKind, type WatermarkSettings } from '../../../shared/watermark';
import { getLang, t, tk } from '../i18n';
import { useEngine } from '../lib/engine';
import { useUi } from '../v4/ui';
import { Group, Page, Row, Segmented, Swatches, Toggle } from './kit';

const COLORS = [
  { v: '#FFFFFF', label: 'wm.color.white' },
  { v: '#111111', label: 'wm.color.black' },
  { v: '#FFD60A', label: 'wm.color.yellow' },
  { v: '#FF2442', label: 'wm.color.red' },
] as const;

/** A slider that shows its value at once and saves when it settles. */
function Slider({ value, min, max, onCommit, label, testId }: { value: number; min: number; max: number; onCommit: (v: number) => void; label: string; testId: string }) {
  const [v, setV] = useState(value);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => setV(value), [value]);
  return (
    <span className="s2-range">
      <input
        type="range"
        min={min}
        max={max}
        step={0.01}
        value={v}
        aria-label={label}
        data-testid={testId}
        onChange={(e) => {
          const n = Number(e.target.value);
          setV(n);
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => onCommit(Math.round(n * 100) / 100), 250);
        }}
      />
      <span className="s2-val">{Math.round(v * 100)}%</span>
    </span>
  );
}

export function WatermarkSection() {
  const { client } = useEngine();
  const ui = useUi();
  const [doc, setDoc] = useState<WatermarkDoc | null>(null);
  const [text, setText] = useState('');
  const [drag, setDrag] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    if (!client) return;
    void client.watermark().then((d) => {
      setDoc(d);
      setText(d.settings.text);
    });
  }, [client]);

  const fail = useCallback((e: unknown) => ui.toast((e as Error).message, { error: true }), [ui]);
  const save = useCallback(
    async (patch: Partial<WatermarkSettings>) => {
      if (!client) return;
      const n = ++seq.current;
      try {
        const d = await client.setWatermark(patch);
        if (n === seq.current) setDoc(d); // the latest change wins
      } catch (e) {
        fail(e);
      }
    },
    [client, fail],
  );
  const commitText = (kind?: WatermarkKind) => {
    if (!doc) return;
    const v = text.trim();
    const patch: Partial<WatermarkSettings> = {};
    if (v !== doc.settings.text) patch.text = v;
    if (kind && kind !== doc.settings.kind) patch.kind = kind;
    // the first time she sets a mark up, "Add to every video" comes on with it (she can turn it off right there)
    if (v && !doc.configured && !doc.settings.default) patch.default = true;
    if (Object.keys(patch).length) void save(patch);
  };
  const applyLogo = async (path: string) => {
    if (!client || !path) return;
    try {
      const d = await client.watermarkLogo(path);
      setDoc(d.configured && !d.settings.default && !doc?.configured ? await client.setWatermark({ default: true }) : d);
    } catch (e) {
      fail(e);
    }
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files[0];
    if (f) void applyLogo(window.desk.pathForFile(f));
  };

  if (!doc) return <Page title={t('wm.nav')} lead={t('wm.lead')} testId="settings-watermark">{null}</Page>;
  const s = doc.settings;
  const lang = getLang();
  const platforms = orderPlatforms(EXPORT_PLATFORMS.map((p) => p.id));
  return (
    <Page title={t('wm.nav')} lead={t('wm.lead')} testId="settings-watermark">
      <Group title={t('wm.mark')} testId="wm-mark">
        <Row label={t('wm.kind')}>
          <Segmented<WatermarkKind>
            value={s.kind}
            onChange={(k) => (k === 'image' ? void save({ kind: k }) : commitText(k))}
            options={[
              { v: 'text', label: t('wm.kind.text'), testId: 'wm-kind-text' },
              { v: 'generate', label: t('wm.kind.generate'), testId: 'wm-kind-generate' },
              { v: 'image', label: t('wm.kind.image'), testId: 'wm-kind-image' },
            ]}
            testId="wm-kind"
          />
        </Row>
        {s.kind !== 'image' && (
          <Row label={t('wm.handle')} hint={t('wm.handleHint')}>
            <input
              className="input s2-key"
              value={text}
              maxLength={WM_MAX_TEXT}
              placeholder={t('wm.handlePh')}
              aria-label={t('wm.handle')}
              onChange={(e) => setText(e.target.value)}
              onBlur={() => commitText()}
              onKeyDown={(e) => e.key === 'Enter' && commitText()}
              data-testid="wm-text"
            />
            {s.kind === 'text' && (
              <button className="btn" disabled={!text.trim()} onClick={() => commitText('generate')} data-testid="wm-generate">
                <WandSparkles className="ico" />
                {t('wm.generate')}
              </button>
            )}
          </Row>
        )}
        {s.kind === 'generate' && (
          <Row label={t('wm.style')}>
            <Segmented value={s.style} onChange={(v) => void save({ style: v })} options={WM_STYLES.map((v) => ({ v, label: tk(`wm.style.${v}`), testId: `wm-style-${v}` }))} testId="wm-style" />
          </Row>
        )}
        {s.kind === 'image' && (
          <div
            className={`s2-row wm-drop ${drag ? 'over' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            data-testid="wm-drop"
          >
            <span className="s2-ricon box">
              <ImageUp className="ico" />
            </span>
            <div className="s2-rtext">
              <div className="s2-rlabel">{doc.logo && doc.configured ? t('wm.logoSet', { name: doc.logo }) : t('wm.logoDrop')}</div>
              <div className="s2-rhint">{t('wm.logoHint')}</div>
            </div>
            <button
              className="btn"
              onClick={async () => {
                const p = await window.desk.openFile('image');
                if (p) void applyLogo(p);
              }}
              data-testid="wm-choose"
            >
              {t('wm.logoChoose')}
            </button>
          </div>
        )}
        {s.kind !== 'image' && (
          <Row label={t('wm.color')}>
            <Swatches value={s.color} onChange={(c) => void save({ color: c })} options={COLORS.map((c) => ({ v: c.v, color: c.v, label: tk(c.label) }))} />
          </Row>
        )}
      </Group>

      <Group title={t('wm.preview')} testId="wm-preview">
        <div className="wm-previews">
          {(['9:16', '16:9'] as const).map((a) => (
            <figure key={a} className={`wm-fig ${a === '9:16' ? 'v' : 'h'}`}>
              <img src={doc.previews?.[a]} alt={a === '9:16' ? t('wm.vertical') : t('wm.horizontal')} data-testid={`wm-preview-${a === '9:16' ? 'v' : 'h'}`} />
              <figcaption>{a === '9:16' ? t('wm.vertical') : t('wm.horizontal')}</figcaption>
            </figure>
          ))}
        </div>
        <p className="s2-rhint wm-phint">{t('wm.previewHint')}</p>
      </Group>

      <Group title={t('wm.placement')} testId="wm-placement">
        <Row label={t('wm.position')}>
          <div className="wm-corners" role="radiogroup" aria-label={t('wm.position')} data-testid="wm-position">
            {WM_POSITIONS.map((p) => (
              <button key={p} role="radio" aria-checked={s.position === p} aria-label={tk(`wm.pos.${p}`)} data-tip={tk(`wm.pos.${p}`)} className={`${p} ${s.position === p ? 'on' : ''}`} onClick={() => p !== s.position && void save({ position: p })} data-testid={`wm-pos-${p}`}>
                <i />
              </button>
            ))}
          </div>
        </Row>
        <Row label={t('wm.size')}>
          <Slider value={s.size} min={WM_SIZE.min} max={WM_SIZE.max} onCommit={(v) => void save({ size: v })} label={t('wm.size')} testId="wm-size" />
        </Row>
        <Row label={t('wm.opacity')}>
          <Slider value={s.opacity} min={WM_OPACITY.min} max={WM_OPACITY.max} onCommit={(v) => void save({ opacity: v })} label={t('wm.opacity')} testId="wm-opacity" />
        </Row>
      </Group>

      <Group title={t('wm.when')} testId="wm-when">
        <Row label={t('wm.default')} hint={doc.configured ? t('wm.defaultHint') : t('wm.defaultNeedsMark')}>
          <Toggle checked={s.default} onChange={(v) => void save({ default: v })} label={t('wm.default')} testId="wm-default" />
        </Row>
        {s.default && (
          <Row label={t('wm.platforms')} hint={t('wm.platformsHint')}>
            <div className="wm-pfs" data-testid="wm-platforms">
              {platforms.map((id) => {
                const on = s.platforms[id] !== false;
                return (
                  <button key={id} className={`wm-pf ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => void save({ platforms: { [id]: !on } })} data-testid={`wm-pf-${id}`}>
                    {platformLabel(id, lang)}
                  </button>
                );
              })}
            </div>
          </Row>
        )}
      </Group>
    </Page>
  );
}
