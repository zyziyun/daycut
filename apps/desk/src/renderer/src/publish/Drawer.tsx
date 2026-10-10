// The second (and last) layer: a right drawer for one card. When (date / time, or typed "next Friday evening"),
// Where (one switch per connected platform with its account + own time + problem), Caption (a tab per platform with
// the counter, the overflow marked, "Shorten for X"), Back to queue (unschedule, undo; files never touched),
// Duplicate…, Done.
import { useEffect, useMemo, useState } from 'react';
import { CalendarDays, Clock, Copy, CornerUpLeft, ExternalLink, Plus, X } from 'lucide-react';
import type { CalendarPost } from '../../../shared/v04';
import { fmtClock, fmtDate, t } from '../i18n';
import { go } from '../lib/router';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { ClipThumbLink, PostLink } from '../v4/kit';
import { clipHref } from '../lib/nav';
import { useUi } from '../v4/ui';
import { StatusMark } from './Board';
import { addDays, base, dayOf, iso, parseWhen, sortIds, type PostGroup } from './model';
import type { Accounts } from './usePublish';
import { firstTab, PostCopy, TitleEdit, titleLimitsOf, type Actions, type Shorten } from './PostCopy';

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
  shorten: Shorten;
}) {
  const ui = useUi();
  const [typed, setTyped] = useState('');
  const [typedErr, setTypedErr] = useState(false);
  const rows = useMemo(() => {
    // her platforms + the ones already on this card, in the shared order (international first, then Chinese)
    const pfs = sortIds([...new Set([...accounts.connected, ...g.posts.map((p) => base(p.platform))])]);
    return pfs.map((pf) => ({ pf, post: g.posts.find((p) => base(p.platform) === pf) ?? null }));
  }, [accounts.connected, g.posts]);
  const onRows = rows.filter((r) => r.post && r.post.enabled !== false) as { pf: string; post: CalendarPost }[];
  const [tab, setTab] = useState<string>(() => firstTab(onRows));
  const fixes = new Set(g.warnings.filter((w) => w.kind !== 'slot_clash').map((w) => w.platform)).size;
  const titleLimits = titleLimitsOf(onRows, accounts);
  const addable = accounts.all.filter((pf) => !rows.some((r) => r.pf === pf));
  const addPlatform = (e: React.MouseEvent) =>
    ui.menu(
      e,
      addable.map((pf) => ({
        label: platformName(pf),
        icon: <PlatformIcon id={pf} size={14} />,
        testId: `pb-add-${pf}`,
        run: () => void actions.togglePlatform(g, pf, true, `${g.day}T${accounts.timeOf(pf)}`, platformName(pf)),
      })),
    );

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
          <ClipThumbLink href={clipHref(g.item, g.clip)} src={g.cover} label={t('pub.openClip')} testId="pb-drawer-open-clip" />
          <div className="col" style={{ gap: 6, minWidth: 0 }}>
            <TitleEdit g={g} actions={actions} limits={titleLimits} />
            <span className="muted num">{[g.project, g.duration ? fmtClock(g.duration) : null].filter(Boolean).join(' · ')}</span>
            <span className="row" style={{ gap: 6 }}>
              <StatusMark s={g.status} views={g.views} />
              {fixes > 0 && <span className="pb-amber">— {t('pb.d.fixes', { n: fixes })}</span>}
            </span>
            <span className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
              <a className="btn sm" href={clipHref(g.item, g.clip)} data-testid="pb-drawer-clip">
                {t('pub.openClip')}
              </a>
              {g.on
                .filter((p) => p.state === 'posted' && p.url)
                .map((p) => (
                  <span key={p.id} className="row" style={{ gap: 4 }}>
                    <PlatformIcon id={p.platform.split(':')[0]} size={14} />
                    <PostLink url={p.url} />
                  </span>
                ))}
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
                    {w.kind === 'caption_too_long' ? t('pb.d.tooLong') : w.kind === 'title_too_long' ? t('pl.d.titleTooLong') : t('pb.d.noCaption')}
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
          {addable.length > 0 && (
            <button className="pb-link pb-addpf" onClick={addPlatform} data-testid="pb-where-add">
              <Plus className="ico" />
              {t('pl.d.addPlatform')}
            </button>
          )}
        </div>

        {onRows.length > 0 && (
          <>
            <h4>{t('pb.d.caption')}</h4>
            <PostCopy rows={onRows} tab={tab} setTab={setTab} accounts={accounts} actions={actions} shorten={shorten} />
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

