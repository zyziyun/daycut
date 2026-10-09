// Data: how the posted ones did. Reelfold never reads her accounts, so views / likes are what she types in (one
// click on the number); the four tiles and the table only use those.
import { useState } from 'react';
import type { CalendarPost } from '../../../shared/v04';
import { fmtDate, fmtNumber, t } from '../i18n';
import { useAgencyMode } from '../lib/prefs';
import { go } from '../lib/router';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { ClipThumbLink, PostLink } from '../v4/kit';
import { clipHref } from '../lib/nav';
import { Pfs } from './Board';
import { base, groupPosts, iso, type PostGroup } from './model';
import type { usePublishData } from './usePublish';

type Actions = ReturnType<typeof usePublishData>['actions'];

function Num({ value, onSave, testId }: { value: number | null; onSave: (n: number) => void; testId: string }) {
  const [edit, setEdit] = useState<string | null>(null);
  if (edit !== null)
    return (
      <input
        className="input pb-numin num"
        autoFocus
        inputMode="numeric"
        value={edit}
        onChange={(e) => setEdit(e.target.value.replace(/[^\d]/g, ''))}
        onBlur={() => (edit !== '' && onSave(Number(edit)), setEdit(null))}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key === 'Escape') setEdit(null);
        }}
        data-testid={`${testId}-input`}
      />
    );
  return (
    <button className={`pb-numbtn num ${value == null ? 'empty' : ''}`} onClick={() => setEdit(value == null ? '' : String(value))} data-testid={testId}>
      {value == null ? t('pb.data.add') : fmtNumber(value)}
    </button>
  );
}

export function DataView({ posts, actions }: { posts: CalendarPost[]; actions: Actions }) {
  const agency = useAgencyMode();
  const [pf, setPf] = useState<string>('all');
  const now = new Date();
  const d30 = iso(new Date(now.getTime() - 30 * 86400000));
  const d60 = iso(new Date(now.getTime() - 60 * 86400000));
  const posted = posts.filter((p) => p.state === 'posted');
  const groups = groupPosts(posted).sort((a, b) => b.at.localeCompare(a.at));
  const last30 = groups.filter((g) => g.day >= d30);
  const prev30 = groups.filter((g) => g.day >= d60 && g.day < d30);
  const withViews = groups.filter((g) => g.views != null);
  const views = withViews.filter((g) => g.day >= d30).reduce((s, g) => s + (g.views ?? 0), 0);
  // best time: the weekday + hour with the most views per post
  const slots = new Map<string, { v: number; n: number; at: string }>();
  for (const g of withViews) {
    const k = `${new Date(`${g.day}T12:00`).getDay()} ${g.time}`;
    const s = slots.get(k) ?? { v: 0, n: 0, at: g.at };
    slots.set(k, { v: s.v + (g.views ?? 0), n: s.n + 1, at: s.at });
  }
  const best = [...slots.values()].sort((a, b) => b.v / b.n - a.v / a.n)[0];
  const byPf = new Map<string, number>();
  for (const p of posted) if (p.stats?.views) byPf.set(base(p.platform), (byPf.get(base(p.platform)) ?? 0) + p.stats.views);
  const totalPf = [...byPf.values()].reduce((a, b) => a + b, 0);
  const bestPf = [...byPf.entries()].sort((a, b) => b[1] - a[1])[0];
  const max = Math.max(1, ...withViews.map((g) => g.views ?? 0));
  const pfs = [...new Set(posted.map((p) => base(p.platform)))];
  const rows = pf === 'all' ? groups : groups.filter((g) => g.platforms.includes(pf));
  const diff = last30.length - prev30.length;
  const save = (g: PostGroup, k: 'views' | 'likes', n: number) => {
    // the number is for the card; it is kept on its first platform row (the others are cleared)
    const [first, ...rest] = g.on;
    void actions.stats(first, { [k]: n });
    for (const p of rest) if (p.stats?.[k]) void actions.stats(p, { [k]: 0 });
  };
  const likes = (g: PostGroup) => g.posts.reduce<number | null>((s, p) => (p.stats?.likes != null ? (s ?? 0) + p.stats.likes : s), null);
  return (
    <div className="pb-data" data-testid="pb-data">
      <div className="pb-tiles">
        <div className="pb-tile">
          <span className="muted">{t('pb.data.posted')}</span>
          <b className="num">{last30.length}</b>
          <span className={diff > 0 ? 'ok' : 'muted'}>{t('pb.data.vsPrev', { n: diff, d: `${diff > 0 ? '+' : ''}${diff}` })}</span>
        </div>
        <div className="pb-tile">
          <span className="muted">{t('pb.data.views')}</span>
          <b className="num">{withViews.length ? (views >= 10000 ? `${fmtNumber(Math.round(views / 100) / 10)}k` : fmtNumber(views)) : t('pb.data.none')}</b>
          <span className="muted">{t('pb.data.viewsHint', { n: withViews.length })}</span>
        </div>
        <div className="pb-tile">
          <span className="muted">{t('pb.data.bestTime')}</span>
          <b className="num">{best ? `${fmtDate(best.at, { weekday: 'short' })} ${best.at.slice(11, 16)}` : t('pb.data.none')}</b>
          <span className="muted">{t('pb.data.bestTimeHint')}</span>
        </div>
        <div className="pb-tile">
          <span className="muted">{t('pb.data.bestPlatform')}</span>
          <b className="row" style={{ gap: 8 }}>
            {bestPf ? (
              <>
                <PlatformIcon id={bestPf[0]} size={24} />
                {platformName(bestPf[0])}
              </>
            ) : (
              t('pb.data.none')
            )}
          </b>
          <span className="muted">{bestPf ? t('pb.data.share', { pct: Math.round((bestPf[1] / totalPf) * 100) }) : ''}</span>
        </div>
      </div>
      <div className="pb-table card">
        <div className="pb-thead">
          <h3>{t('pb.data.recent')}</h3>
          <span className="sp" />
          {agency && (
            <button className="pb-link" onClick={() => go({ name: 'metrics' })}>
              {t('pb.data.clientNumbers')}
            </button>
          )}
          <div className="pb-filter">
            <button className={pf === 'all' ? 'on' : ''} onClick={() => setPf('all')}>
              {t('pb.all')}
            </button>
            {pfs.map((p) => (
              <button key={p} className={pf === p ? 'on' : ''} onClick={() => setPf(p)}>
                <PlatformIcon id={p} size={16} />
                {platformName(p)}
              </button>
            ))}
          </div>
        </div>
        {!rows.length ? (
          <p className="pb-hint" style={{ padding: 24 }}>
            {t('pb.data.empty')}
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t('pb.data.col.post')}</th>
                <th>{t('pb.data.col.posted')}</th>
                <th>{t('pb.data.col.where')}</th>
                <th className="r">{t('pb.data.col.views')}</th>
                <th className="r">{t('pb.data.col.likes')}</th>
                <th>{t('pb.data.col.vsBest')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((g) => (
                <tr key={g.key} data-testid="pb-data-row">
                  <td>
                    <div className="row" style={{ gap: 14 }}>
                      <ClipThumbLink href={clipHref(g.item, g.clip)} src={g.cover} label={t('pub.openClip')} testId="pb-data-open-clip" />
                      <div className="col" style={{ gap: 2, minWidth: 0 }}>
                        <a className="clamp1 pb-cliplink" href={clipHref(g.item, g.clip)} lang="zh-CN" data-testid="pb-data-title">
                          <b>{g.title}</b>
                        </a>
                        <span className="muted">{g.project}</span>
                        <span className="row" style={{ gap: 4 }}>
                          {g.on
                            .filter((p) => p.url)
                            .slice(0, 3)
                            .map((p) => (
                              <PostLink key={p.id} url={p.url} />
                            ))}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="muted num">{fmtDate(g.at, { weekday: 'short', month: 'short', day: 'numeric' })} · {g.time}</td>
                  <td>
                    <Pfs ids={g.platforms} size={18} />
                  </td>
                  <td className="r">
                    <Num value={g.views} onSave={(n) => save(g, 'views', n)} testId="pb-views" />
                  </td>
                  <td className="r">
                    <Num value={likes(g)} onSave={(n) => save(g, 'likes', n)} testId="pb-likes" />
                  </td>
                  <td>
                    <span className="pb-bar">
                      <i style={{ width: `${((g.views ?? 0) / max) * 100}%` }} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
