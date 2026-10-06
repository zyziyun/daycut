// 「让 AI 改」: natural language -> proposed edits shown as cards -> apply / compare before-after / undo. Every
// applied card is undoable (it remembers the first edit number it added).
import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Check, GitCompare, Undo2 } from 'lucide-react';
import type { EditOp, EngineMsg, Proposal } from '../../../shared/v04';
import { t, type MessageKey } from '../i18n';
import { emsg, errText } from './msg';
import { useEngine } from '../lib/engine';
import { useUi } from './ui';

interface Msg {
  id: number;
  me?: boolean;
  text: string;
  proposals?: (Proposal & { applied?: number | null; undone?: boolean })[];
}

let seq = 0;

export function AIPanel({
  item,
  clip,
  clipTitle,
  running,
  liveText,
  hintWord,
  onApplied,
  onCompare,
  testId = 'ai-panel',
}: {
  item: string;
  clip: string | null;
  clipTitle?: string;
  running?: boolean;
  liveText?: string | null;
  hintWord?: string;
  onApplied?: () => void;
  onCompare?: (ops: EditOp[] | null) => void;
  testId?: string;
}) {
  const { client } = useEngine();
  const ui = useUi();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [comparing, setComparing] = useState<string | null>(null);
  const log = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    log.current?.scrollTo({ top: 1e9, behavior: 'smooth' });
  }, [msgs]);
  useEffect(() => {
    setMsgs([]);
    setComparing(null);
  }, [clip]);

  const send = async (prompt: string) => {
    if (!client || !prompt.trim() || busy) return;
    if (!clip) {
      setMsgs((m) => [...m, { id: ++seq, me: true, text: prompt }, { id: ++seq, text: t('ai.pickClip') }]);
      setText('');
      return;
    }
    setMsgs((m) => [...m, { id: ++seq, me: true, text: prompt }]);
    setText('');
    setBusy(true);
    try {
      const r = await client.askOutput(item, clip, prompt);
      const notes = (r.warnings ?? []).map((w: EngineMsg) => emsg(w)).filter(Boolean);
      const text = [r.proposals.length ? t('ai.proposed', { n: r.proposals.length }) : '', r.summary ?? '', ...notes].filter(Boolean).join('\n');
      setMsgs((m) => [...m, { id: ++seq, text: text || t('ai.nothing'), proposals: r.proposals.map((p) => ({ ...p, applied: null })) }]);
    } catch (e) {
      setMsgs((m) => [...m, { id: ++seq, text: errText(e) }]);
    } finally {
      setBusy(false);
    }
  };

  const setProp = (mid: number, pid: string, patch: Partial<Msg['proposals'] extends (infer P)[] | undefined ? P : never>) =>
    setMsgs((m) => m.map((x) => (x.id === mid ? { ...x, proposals: x.proposals?.map((p) => (p.id === pid ? { ...p, ...patch } : p)) } : x)));

  const apply = async (mid: number, p: Proposal) => {
    if (!client || !clip) return;
    try {
      const before = await client.output(item, clip);
      await client.editOutput(item, clip, [p.op]);
      setProp(mid, p.id, { applied: before.steps.length + 1, undone: false });
      onCompare?.(null);
      setComparing(null);
      onApplied?.();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  const undo = async (mid: number, p: Proposal & { applied?: number | null }) => {
    if (!client || !clip || !p.applied) return;
    try {
      const now = await client.output(item, clip);
      await client.undoOutput(item, clip, Math.max(1, now.steps.length - p.applied + 1));
      setProp(mid, p.id, { undone: true, applied: null });
      onApplied?.();
      ui.toast(t('ai.undone'));
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };

  const chips: [MessageKey, string][] = [
    ['ai.chip.tighter', t('ai.chip.tighterPrompt')],
    ['ai.chip.cover', t('ai.chip.coverPrompt')],
    ['ai.chip.douyin', t('ai.chip.douyinPrompt')],
  ];
  if (hintWord) chips.push(['ai.chip.pop', t('ai.chip.popPrompt', { w: hintWord })]);

  return (
    <aside className="agent" data-testid={testId}>
      <div className="hd">
        <b>{t('ai.title')}</b>
        <span className="sp" />
        {running ? (
          <span className="st run">
            <i className="dot run" />
            {t('ai.working')}
          </span>
        ) : clipTitle ? (
          <span className="muted clamp1" style={{ maxWidth: 180 }} title={clipTitle}>
            {t('ai.forClip', { title: clipTitle })}
          </span>
        ) : null}
      </div>
      <div className="alog" ref={log} data-testid="ai-log">
        {liveText && <div className="msg" lang="zh-CN">{liveText}</div>}
        {!msgs.length && !liveText && <div className="muted">{clip ? t('ai.empty') : t('ai.pickClip')}</div>}
        {msgs.map((m) => (
          <div key={m.id} className="col" style={{ gap: 8 }}>
            <div className={`msg ${m.me ? 'me' : ''}`}>{m.text}</div>
            {m.proposals?.map((p) => (
              <div key={p.id} className="change" data-testid="ai-proposal">
                <div className="row">
                  <b className="sp clamp2">{emsg(p.describe) || p.op.op}</b>
                  {p.applied ? (
                    <span className="st done">
                      <Check className="ico" style={{ width: 12, height: 12 }} />
                      {t('ai.applied')}
                    </span>
                  ) : null}
                </div>
                {p.why && <span className="muted">{emsg(p.why)}</span>}
                <div className="row">
                  {!p.applied ? (
                    <button className="btn sm primary" onClick={() => void apply(m.id, p)} data-testid="ai-apply">
                      {t('ai.apply')}
                    </button>
                  ) : (
                    <button className="btn sm" onClick={() => void undo(m.id, p)} data-testid="ai-undo">
                      <Undo2 className="ico" />
                      {t('ai.undo')}
                    </button>
                  )}
                  {onCompare && !p.applied && (
                    <button
                      className={`btn sm ${comparing === p.id ? 'toggle on' : 'ghost'}`}
                      onClick={() => {
                        const on = comparing !== p.id;
                        setComparing(on ? p.id : null);
                        onCompare(on ? [p.op] : null);
                      }}
                      aria-pressed={comparing === p.id}
                      data-testid="ai-compare"
                    >
                      <GitCompare className="ico" />
                      {t('ai.compare')}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))}
        {busy && <div className="msg muted">{t('ai.thinking')}</div>}
      </div>
      <div className="in">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={running ? t('ai.placeholderRun') : t('ai.placeholder')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send(text);
            }
          }}
          data-testid="ai-input"
        />
        <div className="row">
          {chips.map(([k, prompt]) => (
            <button key={k} className="chip" onClick={() => void send(prompt)} disabled={busy}>
              {t(k)}
            </button>
          ))}
          <span className="sp" />
          <button className="btn icon sm" onClick={() => void send(text)} disabled={!text.trim() || busy} aria-label={t('ai.send')} data-testid="ai-send">
            <ArrowUp className="ico" />
          </button>
        </div>
      </div>
    </aside>
  );
}
