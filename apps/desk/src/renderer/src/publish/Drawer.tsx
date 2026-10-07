// The second (and last) layer: a right drawer for one card. When (date / time, or typed "next Friday evening"),
// Where (one switch per connected platform with its account + own time + problem), Caption (a tab per platform with
// the counter, the overflow marked, "Shorten for X"), Back to queue (unschedule, undo; files never touched),
// Duplicate…, Done.
import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CalendarDays, Clock, Copy, CornerUpLeft, ExternalLink, Sparkles, X } from 'lucide-react';
import type { CalendarPost } from '../../../shared/v04';
import { xWeightedLength } from '../../../shared/publish/postCopy';
import { fmtClock, fmtDate, t } from '../i18n';
import { go } from '../lib/router';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { Thumb } from '../v4/kit';
import { useUi } from '../v4/ui';
import { StatusMark } from './Board';
import { addDays, base, dayOf, iso, overflowAt, parseWhen, type PostGroup } from './model';
import type { Accounts, usePublishData } from './usePublish';

type Actions = ReturnType<typeof usePublishData>['actions'];

export function PostDrawer({
  g,
  accounts,
  actions,
  onClose,
  onMoved,
  shorten,
}: {
  g: PostGroup;
  accounts: Accounts;
  actions: Actions;
  onClose: () => void;
  /** the card's day changed (its key too): keep the drawer on it */
  onMoved: (day: string) => void;
  shorten: (text: string, platform: string) => Promise<{ text: string; provider: string } | undefined>;
}) {
  const ui = useUi();
  const [typed, setTyped] = useState('');
  const [typedErr, setTypedErr] = useState(false);
  const rows = useMemo(() => {
    const pfs = [...new Set([...accounts.connected, ...g.posts.map((p) => base(p.platform))])];
    return pfs.map((pf) => ({ pf, post: g.posts.find((p) => base(p.platform) === pf) ?? null }));
  }, [accounts.connected, g.posts]);
  const onRows = rows.filter((r) => r.post && r.post.enabled !== false) as { pf: string; post: CalendarPost }[];
  const [tab, setTab] = useState<string>(() => onRows.find((r) => r.post.warnings?.some((w) => w.kind === 'caption_too_long'))?.pf ?? onRows[0]?.pf ?? '');
  const cur = onRows.find((r) => r.pf === tab) ?? onRows[0];
  const fixes = new Set(g.warnings.filter((w) => w.kind !== 'slot_clash').map((w) => w.platform)).size;

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !(e.target as HTMLElement)?.closest?.('input, textarea')) onClose();
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  const applyTyped = () => {
    const w = parseWhen(typed, new Date());
    if (!w) return setTypedErr(true);
    setTypedErr(false);
    setTyped('');
    void actions.retime(g, w.day ?? g.day, w.time).then(() => onMoved(w.day ?? g.day));
  };
  const dup = (e: React.MouseEvent) =>
    ui.menu(e, [
      { label: t('pb.d.dupTomorrow'), run: () => actions.add(g.on.map((p) => ({ item: g.item, clip: g.clip, platform: p.platform, at: `${iso(addDays(dayOf(p.at), 1))}${p.at.slice(10)}` })), t('pb.t.duplicated', { date: fmtDate(addDays(dayOf(g.day), 1)) })), testId: 'pb-dup-tomorrow' },
      { label: t('pb.d.dupNextWeek'), run: () => actions.add(g.on.map((p) => ({ item: g.item, clip: g.clip, platform: p.platform, at: `${iso(addDays(dayOf(p.at), 7))}${p.at.slice(10)}` })), t('pb.t.duplicated', { date: fmtDate(addDays(dayOf(g.day), 7)) })), testId: 'pb-dup-week' },
      ...accounts.connected
        .filter((pf) => !g.platforms.includes(pf))
        .map((pf) => ({ label: t('pb.d.dupOn', { pf: platformName(pf) }), icon: <PlatformIcon id={pf} size={14} />, run: () => actions.togglePlatform(g, pf, true, `${g.day}T${accounts.timeOf(pf)}`, platformName(pf)) })),
    ]);

  return (
    <aside className="pb-drawer" role="dialog" aria-label={g.title} data-testid="pb-drawer">
      <header className="pb-dhead">
        <span className="muted">
          {fmtDate(`${g.day}T12:00`, { weekday: 'short', month: 'short', day: 'numeric' })}
          {g.project ? ` · ${g.project}` : ''}
        </span>
        <span className="sp" />
        <button className="btn ghost icon" onClick={() => go({ name: 'clip', id: g.item, clip: g.clip })} aria-label={t('pb.d.editor')} data-tip={t('pb.d.editor')}>
          <ExternalLink className="ico" />
        </button>
        <button className="btn ghost icon" onClick={onClose} aria-label={t('pb.d.close')} data-tip={t('pb.d.close')} data-testid="pb-drawer-close">
          <X className="ico" />
        </button>
      </header>
      <div className="pb-dscroll">
        <div className="pb-dclip">
          <Thumb src={g.cover} ratio="3/4" />
          <div className="col" style={{ gap: 6, minWidth: 0 }}>
            <h3 lang="zh-CN">{g.title}</h3>
            <span className="muted num">{[g.project, g.duration ? fmtClock(g.duration) : null].filter(Boolean).join(' · ')}</span>
            <span className="row" style={{ gap: 6 }}>
              <StatusMark s={g.status} views={g.views} />
              {fixes > 0 && <span className="pb-amber">— {t('pb.d.fixes', { n: fixes })}</span>}
            </span>
          </div>
        </div>

        <h4>{t('pb.d.when')}</h4>
        <div className="pb-when">
          <label className="pb-field" onClick={(e) => (e.currentTarget.querySelector('input') as HTMLInputElement | null)?.showPicker?.()}>
            <CalendarDays className="ico" />
            <span className="lbl">{fmtDate(`${g.day}T12:00`, { weekday: 'short', month: 'short', day: 'numeric' })}</span>
            <input
              className="over"
              type="date"
              aria-label={t('pb.d.date')}
              value={g.day}
              onChange={(e) => {
                const d = e.target.value;
                if (d) void actions.retime(g, d).then(() => onMoved(d));
              }}
              data-testid="pb-date"
            />
          </label>
          <label className="pb-field narrow">
            <Clock className="ico" />
            <input type="time" aria-label={t('pb.d.time')} value={g.time} onChange={(e) => /^\d{2}:\d{2}$/.test(e.target.value) && void actions.retime(g, g.day, e.target.value)} data-testid="pb-time" />
          </label>
        </div>
        <input
          className={`input pb-typed ${typedErr ? 'bad' : ''}`}
          placeholder={t('pb.d.typePh')}
          value={typed}
          onChange={(e) => (setTyped(e.target.value), setTypedErr(false))}
          onKeyDown={(e) => e.key === 'Enter' && typed.trim() && applyTyped()}
          aria-label={t('pb.d.typePh')}
          data-testid="pb-typed"
        />
        <p className="pb-hint">{typedErr ? <span className="pb-amber">{t('pb.d.notUnderstood')}</span> : t('pb.d.typeIt')}</p>

        <h4>{t('pb.d.where')}</h4>
        <div className="pb-where">
          {rows.map(({ pf, post }) => {
            const on = !!post && post.enabled !== false;
            const acct = accounts.accountOf(pf);
            const w = post?.warnings?.find((x) => x.kind !== 'slot_clash');
            const clash = post?.warnings?.some((x) => x.kind === 'slot_clash');
            return (
              <div key={pf} className={`pb-wrow ${on ? '' : 'off'}`} data-testid="pb-where" data-pf={pf}>
                <PlatformIcon id={pf} size={22} />
                <b>{platformName(pf)}</b>
                <span className="sp" />
                {on && w ? (
                  <button className="pb-amber pb-link" onClick={() => setTab(pf)}>
                    {w.kind === 'caption_too_long' ? t('pb.d.tooLong') : t('pb.d.noCaption')}
                  </button>
                ) : on ? (
                  <span className="muted row" style={{ gap: 6 }}>
                    {acct ? acct.name : t('pb.d.noAccount')} ·
                    <input
                      type="time"
                      className={`pb-tinput num ${clash ? 'clash' : ''}`}
                      value={post!.at.slice(11, 16)}
                      onChange={(e) => /^\d{2}:\d{2}$/.test(e.target.value) && void actions.setPostTime(post!, e.target.value)}
                      aria-label={`${platformName(pf)} ${t('pb.d.time')}`}
                      title={clash ? t('pb.d.clash') : undefined}
                      data-testid="pb-where-time"
                    />
                  </span>
                ) : (
                  <span className="muted">{t('pb.off')}</span>
                )}
                <button
                  role="switch"
                  aria-checked={on}
                  aria-label={platformName(pf)}
                  className={`tgl ${on ? 'on' : ''}`}
                  disabled={post?.state === 'posted'}
                  onClick={() => void actions.togglePlatform(g, pf, !on, `${g.day}T${accounts.timeOf(pf)}`, platformName(pf))}
                  data-testid="pb-where-toggle"
                >
                  <i />
                </button>
              </div>
            );
          })}
        </div>

        {cur && (
          <>
            <h4>{t('pb.d.caption')}</h4>
            <div className="pb-ctabs" role="tablist">
              {onRows.map(({ pf, post }) => (
                <button key={pf} role="tab" aria-selected={pf === cur.pf} className={pf === cur.pf ? 'on' : ''} onClick={() => setTab(pf)} data-testid="pb-ctab" data-pf={pf}>
                  <PlatformIcon id={pf} size={16} />
                  {platformName(pf)}
                  {post.warnings?.some((w) => w.kind !== 'slot_clash') && <i className="wdot" />}
                </button>
              ))}
            </div>
            <CaptionEditor key={cur.post.id} post={cur.post} actions={actions} shorten={shorten} />
          </>
        )}
        {g.on.some((p) => p.state !== 'posted') && (
          <p className="pb-hint" style={{ marginTop: 16 }}>
            <button className="pb-link" onClick={() => go({ name: 'publish', batch: g.item })}>
              {t('pb.d.fill')}
            </button>
            {' · '}
            <button className="pb-link" onClick={() => g.on.forEach((p) => void actions.setState(p, 'posted'))} data-testid="pb-mark-posted">
              {t('pb.d.markPosted')}
            </button>
          </p>
        )}
      </div>
      <footer className="pb-dfoot">
        <button className="btn ghost" onClick={() => (onClose(), void actions.unschedule(g))} title={t('pb.d.backHint')} data-testid="pb-back">
          <CornerUpLeft className="ico" />
          {t('pb.d.back')}
        </button>
        <button className="btn ghost" onClick={dup} data-testid="pb-dup">
          <Copy className="ico" />
          {t('pb.d.duplicate')}
        </button>
        <span className="sp" />
        <button className="btn primary" onClick={onClose} data-testid="pb-done">
          {t('pb.d.done')}
        </button>
      </footer>
    </aside>
  );
}

function CaptionEditor({ post, actions, shorten }: { post: CalendarPost; actions: Actions; shorten: (text: string, platform: string) => Promise<{ text: string; provider: string } | undefined> }) {
  const ui = useUi();
  const [text, setText] = useState(post.caption ?? '');
  const [busy, setBusy] = useState(false);
  const saved = useRef(post.caption ?? '');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const back = useRef<HTMLDivElement>(null);
  const pf = base(post.platform);
  const limit = post.limit ?? null;
  const cut = overflowAt(text, pf, limit);
  const length = pf === 'x' ? xWeightedLength(text) : [...text].length;
  const save = (v: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (v !== saved.current) {
        saved.current = v;
        void actions.caption(post, v);
      }
    }, 500);
  };
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const over = cut >= 0;
  return (
    <div className="pb-caption">
      <div className="pb-cbox">
        <div ref={back} className="pb-cback" aria-hidden>
          {over ? (
            <>
              {text.slice(0, cut)}
              <mark>{text.slice(cut)}</mark>
            </>
          ) : (
            text
          )}
          {'\n'}
        </div>
        <textarea
          value={text}
          onChange={(e) => (setText(e.target.value), save(e.target.value))}
          onScroll={(e) => back.current && (back.current.scrollTop = e.currentTarget.scrollTop)}
          spellCheck={false}
          aria-label={platformName(pf)}
          data-testid="pb-caption"
        />
      </div>
      <div className="pb-cfoot">
        {limit ? (
          <span className={`num ${over ? 'pb-amber' : 'muted'}`} data-testid="pb-counter">
            <b>{length}</b> / {limit}
          </span>
        ) : null}
        {over && <span className="muted small">{pf === 'x' ? t('pb.d.counterHintX', { max: limit ?? 0 }) : t('pb.d.counterHint', { pf: platformName(pf), max: limit ?? 0 })}</span>}
        <span className="sp" />
        {post.caption_custom && !over && (
          <button className="pb-link muted" onClick={() => (setText(''), (saved.current = ''), void actions.caption(post, null))}>
            {t('pb.d.reset')}
          </button>
        )}
        {over && (
          <button
            className="pb-link"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              const before = text;
              const r = await shorten(text, pf).finally(() => setBusy(false));
              if (!r) return;
              setText(r.text);
              saved.current = r.text;
              void actions.caption(post, r.text);
              ui.toast(t('pb.d.shortened', { provider: r.provider === 'rules' ? t('pb.d.rules') : r.provider }), {
                undo: () => {
                  setText(before);
                  saved.current = before;
                  void actions.caption(post, before);
                },
              });
            }}
            data-testid="pb-shorten"
          >
            <Sparkles className="ico" />
            {busy ? t('pb.d.shortening') : t('pb.d.shorten', { pf: platformName(pf) })}
          </button>
        )}
      </div>
      {post.warnings?.some((w) => w.kind === 'slot_clash') && (
        <p className="pb-hint pb-amber">
          <AlertTriangle className="ico" /> {t('pb.d.clash')}
        </p>
      )}
    </div>
  );
}
