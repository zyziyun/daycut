// "2 posts are due": the scheduled posts whose time has come and that she still has to publish (also the ones that
// came due while Reelfold was closed). Shown at the top of Publish and Home; each row opens "Time to post".
import { useEffect, useState } from 'react';
import { BellRing, ChevronRight } from 'lucide-react';
import type { DueMsg } from '../../../shared/deskApi';
import type { CalendarPost } from '../../../shared/v04';
import { fmtAgo, t } from '../i18n';
import { useLoad } from '../lib/engine';
import { go } from '../lib/router';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { base, pfRank } from './model';

export function useDue(): DueMsg | null {
  const [due, setDue] = useState<DueMsg | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      void window.desk.publish
        .due()
        .then((d) => alive && setDue(d))
        .catch(() => undefined);
    load();
    const offs = [window.desk.on('publish:due', load), window.desk.on('publish:posted', load)];
    const tmr = setInterval(load, 60_000);
    return () => {
      alive = false;
      offs.forEach((f) => f());
      clearInterval(tmr);
    };
  }, []);
  return due;
}

/** Reads the calendar again whenever the due list changes (a post scheduled a moment ago, one posted). */
export function DueBanner() {
  const due = useDue();
  const key = due?.ids.join() ?? '';
  const cal = useLoad((c) => (key ? c.calendar() : Promise.resolve(null)), [key]);
  const posts = cal.data?.posts;
  if (!due || !posts) return null;
  const rows = due.ids
    .map((id) => posts.find((p) => p.id === id))
    .filter((p): p is CalendarPost => !!p && p.state !== 'posted')
    .sort((a, b) => a.at.localeCompare(b.at) || pfRank(a.platform) - pfRank(b.platform));
  if (!rows.length) return null;
  return (
    <div className="pl-due" role="status" data-testid="due-banner">
      <div className="pl-due-head">
        <BellRing className="ico" />
        <b>{t('pl.due.title', { n: rows.length })}</b>
        <span className="muted small">{t('pl.due.hint')}</span>
      </div>
      {rows.slice(0, 5).map((p, i) => {
        const api = due.api[p.id];
        return (
          <button key={p.id} className="pl-due-row" onClick={() => go({ name: 'postNow', id: p.id })} data-testid="due-row" data-post={p.id}>
            <PlatformIcon id={base(p.platform)} size={18} />
            <span className="clamp1" lang="zh-CN">
              {p.title}
            </span>
            <span className="muted small">→ {platformName(p.platform)}</span>
            <span className="sp" />
            {api?.status === 'failed' && <span className="pb-amber small">{t('pl.due.apiFailed')}</span>}
            <span className="muted small num">{t('pl.due.ago', { when: fmtAgo(new Date(`${p.at}:00`).getTime() / 1000) })}</span>
            <span className={`btn sm ${i === 0 ? 'primary' : ''}`}>
              {t('pl.due.post')}
              <ChevronRight className="ico" />
            </span>
          </button>
        );
      })}
    </div>
  );
}
