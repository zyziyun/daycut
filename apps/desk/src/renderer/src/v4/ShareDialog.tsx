// Share for review: from a project, a clip or the publish package. One dialog, three states - choose (which clips,
// quality, a note, the "Made with Reelfold" footer, privacy warnings that need a tick), making (progress), done
// (folder + zip, Reveal in Finder, how to send it). Import feedback (Inbox) turns the reviewer's code / file back
// into Inbox items. Nothing is uploaded: the page is a folder on disk.
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, Copy, FileUp, FolderOpen, Share2, X } from 'lucide-react';
import type { ShareJob, ShareOptions, ShareQuality } from '../../../shared/share';
import { has, intlLocale, t, tk } from '../i18n';
import { useEngine } from '../lib/engine';
import { useInbox } from '../lib/inbox';
import { media, Seg } from './kit';
import { errText, emsg } from './msg';
import { useUi } from './ui';
import './share.css';

function bytes(n: number | null | undefined): string {
  const v = n ?? 0;
  const u = v >= 1e9 ? ['gigabyte', 1e9] : v >= 1e6 ? ['megabyte', 1e6] : ['kilobyte', 1e3];
  return new Intl.NumberFormat(intlLocale(), { style: 'unit', unit: u[0] as string, maximumFractionDigits: 1 }).format(v / (u[1] as number));
}

export function ShareButton({ item, clips, label = true, testId = 'share-open', className = 'btn' }: { item: string; clips?: string[]; label?: boolean; testId?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className={className} onClick={() => setOpen(true)} data-testid={testId} title={label ? undefined : t('share.button')} aria-label={t('share.button')}>
        <Share2 className="ico" />
        {label && t('share.button')}
      </button>
      {open && <ShareDialog item={item} only={clips} onClose={() => setOpen(false)} />}
    </>
  );
}

export function ShareDialog({ item, only, onClose }: { item: string; only?: string[]; onClose: () => void }) {
  const { client } = useEngine();
  const [opt, setOpt] = useState<ShareOptions | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [quality, setQuality] = useState<ShareQuality>('standard');
  const [footer, setFooter] = useState(true);
  const [title, setTitle] = useState('');
  const [from, setFrom] = useState('');
  const [note, setNote] = useState('');
  const [ack, setAck] = useState(false);
  const [job, setJob] = useState<ShareJob | null>(null);
  const alive = useRef(true);
  useEffect(() => () => void (alive.current = false), []);

  useEffect(() => {
    if (!client) return;
    client
      .shareOptions(item)
      .then((o) => {
        if (!alive.current) return;
        setOpt(o);
        setTitle(o.title);
        const ids = o.clips.map((c) => c.id);
        setPicked(new Set(only?.length ? ids.filter((x) => only.includes(x)) : ids));
      })
      .catch((e: unknown) => alive.current && setErr(errText(e)));
  }, [client, item, only]);

  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === 'Escape' && job?.state !== 'running' && onClose();
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [onClose, job]);

  const make = async () => {
    if (!client || !opt) return;
    setErr(null);
    try {
      const r = await client.share(item, { clips: [...picked], quality, footer, title: title.trim() || opt.title, owner_name: from.trim() || undefined, expiry_note: note.trim() || undefined, ack: opt.privacy.needs_ack ? ack : undefined });
      setJob({ id: r.job, state: 'running', done: 0, total: r.total, result: null, error: null });
      for (;;) {
        await new Promise((res) => setTimeout(res, 400));
        if (!alive.current) return;
        const s = await client.shareJob(r.job);
        setJob(s);
        if (s.state !== 'running') break;
      }
    } catch (e) {
      setErr(errText(e));
      setJob(null);
    }
  };

  const warn = opt?.privacy.warnings ?? [];
  const needAck = !!opt?.privacy.needs_ack;
  const title_ = (c: string) => opt?.clips.find((x) => x.id === c)?.title ?? c;
  const canMake = !!opt && picked.size > 0 && (!needAck || ack);
  const running = job?.state === 'running';
  const res = job?.state === 'done' ? job.result : null;

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && !running && onClose()}>
      <div className="sheet shr" role="dialog" aria-modal="true" aria-label={t('share.title')} data-testid="share-dialog">
        <div className="shr-hd">
          <h2>{res ? t('share.done') : t('share.title')}</h2>
          <span className="sp" />
          {!running && (
            <button className="btn ghost icon" onClick={onClose} aria-label={t('share.close')} data-testid="share-close">
              <X className="ico" />
            </button>
          )}
        </div>
        {res ? (
          <div className="shr-body" data-testid="share-result">
            <p className="muted">{t('share.doneLead', { n: res.clips.length, size: bytes(res.zip_bytes ?? res.bytes) })}</p>
            <PathRow label={t('share.folder')} path={res.dir} testId="share-folder" />
            {res.zip && <PathRow label={t('share.zip')} path={res.zip} testId="share-zip" />}
            <div className="shr-send">
              <b>{t('share.sendTitle')}</b>
              <p className="muted">{t('share.sendZip')}</p>
              <p className="muted">{t('share.sendDrive')}</p>
              <p className="muted">{t('share.howText')}</p>
            </div>
            <div className="shr-ft">
              <span className="sp" />
              <button className="btn" onClick={() => void window.desk.showItem(res.zip ?? res.index)} data-testid="share-reveal">
                <FolderOpen className="ico" />
                {t('share.reveal')}
              </button>
              <button className="btn primary" onClick={onClose} data-testid="share-finish">
                <Check className="ico" />
                {t('share.close')}
              </button>
            </div>
          </div>
        ) : running ? (
          <div className="shr-body" data-testid="share-progress">
            <p>{t('share.making', { done: job.done, total: job.total })}</p>
            <div className="bar">
              <i style={{ width: `${Math.round((job.done / Math.max(1, job.total)) * 100)}%` }} />
            </div>
          </div>
        ) : (
          <div className="shr-body">
            <p className="muted">{t('share.lead')}</p>
            {err && (
              <div className="note err" role="alert" data-testid="share-error">
                {err}
              </div>
            )}
            {job?.state === 'failed' && job.error && (
              <div className="note err" role="alert" data-testid="share-error">
                {t('share.failed', { why: emsg(job.error) })}
              </div>
            )}
            {!opt ? null : !opt.clips.length ? (
              <p>{t('share.noClips')}</p>
            ) : (
              <>
                <div className="shr-sec">
                  <div className="shr-row">
                    <b>{t('share.what')}</b>
                    <span className="sp" />
                    <button className="lnk" onClick={() => setPicked(new Set(opt.clips.map((c) => c.id)))} data-testid="share-all">
                      {t('share.all', { n: opt.clips.length })}
                    </button>
                    <button className="lnk" onClick={() => setPicked(new Set())}>
                      {t('share.none')}
                    </button>
                  </div>
                  <div className="shr-clips" data-testid="share-clips">
                    {opt.clips.map((c) => (
                      <label key={c.id} className={`shr-clip ${picked.has(c.id) ? 'on' : ''}`} data-testid="share-clip" data-clip={c.id}>
                        <input
                          type="checkbox"
                          checked={picked.has(c.id)}
                          onChange={(e) =>
                            setPicked((s) => {
                              const n = new Set(s);
                              if (e.target.checked) n.add(c.id);
                              else n.delete(c.id);
                              return n;
                            })
                          }
                        />
                        {c.cover ? <img src={media(c.cover)} alt="" /> : <span className="ph-thumb" />}
                        <span className="clamp1">{c.title}</span>
                        <span className="muted">{t('share.versions', { n: c.versions.length })}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="shr-sec">
                  <b>{t('share.quality')}</b>
                  <Seg<ShareQuality> value={quality} onChange={setQuality} testId="share-quality" options={(['small', 'standard', 'high'] as const).map((q) => ({ v: q, label: t(`share.q.${q}`) }))} />
                  <span className="muted">{t(`share.qHint.${quality}`)}</span>
                </div>
                <div className="shr-grid">
                  <label>
                    <span>{t('share.pageTitle')}</span>
                    <input value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} data-testid="share-title" />
                  </label>
                  <label>
                    <span>{t('share.from')}</span>
                    <input value={from} maxLength={80} placeholder={t('share.fromPh')} onChange={(e) => setFrom(e.target.value)} />
                  </label>
                  <label className="wide">
                    <span>{t('share.expiry')}</span>
                    <input value={note} maxLength={200} placeholder={t('share.expiryPh')} onChange={(e) => setNote(e.target.value)} data-testid="share-note" />
                    <small className="muted">{t('share.expiryHint')}</small>
                  </label>
                </div>
                <label className="shr-toggle">
                  <input type="checkbox" checked={footer} onChange={(e) => setFooter(e.target.checked)} data-testid="share-footer" />
                  <span>
                    {t('share.footer')}
                    <small className="muted">{t('share.footerHint')}</small>
                  </span>
                </label>
                {warn.length > 0 && (
                  <div className={`shr-privacy ${needAck ? 'warn' : ''}`} data-testid="share-privacy">
                    <b>
                      <AlertTriangle className="ico" />
                      {t('share.privacyTitle')}
                    </b>
                    <ul>
                      {warn.map((w) => (
                        <li key={w.code} data-code={w.code}>
                          {has(`share.privacy.${w.code}`) ? tk(`share.privacy.${w.code}`) : emsg({ code: w.code, message: w.message, message_zh: w.message_zh })}
                          {w.params?.clips?.length ? <span className="muted"> {t('share.privacyClips', { clips: w.params.clips.map(title_).join(', ') })}</span> : null}
                        </li>
                      ))}
                    </ul>
                    {needAck && (
                      <label className="shr-toggle">
                        <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="share-ack" />
                        <span>{t('share.privacyAck')}</span>
                      </label>
                    )}
                  </div>
                )}
                <p className="muted shr-how">
                  <b>{t('share.how')}</b> {t('share.howText')}
                </p>
              </>
            )}
            <div className="shr-ft">
              <span className="sp" />
              <button className="btn ghost" onClick={onClose}>
                {t('share.cancel')}
              </button>
              <button className="btn primary" disabled={!canMake} onClick={() => void make()} data-testid="share-make">
                <Share2 className="ico" />
                {t('share.make')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PathRow({ label, path, testId }: { label: string; path: string; testId: string }) {
  const ui = useUi();
  return (
    <div className="shr-path" data-testid={testId} data-path={path}>
      <span className="muted">{label}</span>
      <code className="clamp1" title={path}>
        {path}
      </code>
      <button
        className="btn ghost icon"
        aria-label={t('share.copyPath')}
        onClick={() => {
          void window.desk.copyText(path);
          ui.toast(t('share.copied'));
        }}
      >
        <Copy className="ico" />
      </button>
    </div>
  );
}

/** Inbox > Import feedback: paste the code / message, or drop the .reelfold.json file. */
export function ImportFeedback({ onClose }: { onClose: () => void }) {
  const { client } = useEngine();
  const { reload } = useInbox();
  const ui = useUi();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [onClose]);
  const go = useCallback(
    async (value: string) => {
      if (!client || !value.trim()) return;
      setBusy(true);
      setErr(null);
      try {
        const r = await client.importFeedback(value);
        reload();
        ui.toast([t('feedback.imported', { n: r.items, who: r.reviewer ? t('feedback.from', { who: r.reviewer }) : '' }), r.duplicates ? t('feedback.dupes', { n: r.duplicates }) : ''].filter(Boolean).join(' · '));
        onClose();
      } catch (e) {
        setErr(errText(e));
      } finally {
        setBusy(false);
      }
    },
    [client, reload, ui, onClose],
  );
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`sheet shr ${over ? 'over' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={t('feedback.title')}
        data-testid="feedback-dialog"
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOver(false);
          const f = e.dataTransfer.files[0];
          if (f) void f.text().then((s) => (setText(s), go(s)));
        }}
      >
        <div className="shr-hd">
          <h2>{t('feedback.title')}</h2>
          <span className="sp" />
          <button className="btn ghost icon" onClick={onClose} aria-label={t('share.close')}>
            <X className="ico" />
          </button>
        </div>
        <div className="shr-body">
          <p className="muted">{t('feedback.lead')}</p>
          <textarea className="shr-code" value={text} onChange={(e) => setText(e.target.value)} placeholder={t('feedback.placeholder')} autoFocus data-testid="feedback-text" />
          <div className="shr-drop muted">
            <FileUp className="ico" />
            {t('feedback.drop')}
          </div>
          {err && (
            <div className="note err" role="alert" data-testid="feedback-error">
              {err}
            </div>
          )}
          <div className="shr-ft">
            <span className="sp" />
            <button className="btn ghost" onClick={onClose}>
              {t('share.cancel')}
            </button>
            <button className="btn primary" disabled={busy || !text.trim()} onClick={() => void go(text)} data-testid="feedback-go">
              {t('feedback.go')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
