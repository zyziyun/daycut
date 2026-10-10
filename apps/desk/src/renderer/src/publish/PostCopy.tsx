// A post's copy, one tab per switched-on platform: the platform's own title (with its counter) and the caption (the
// counter, the overflow marked, "Shorten for X"). One component for the publish drawer and the clip's own page, on
// the same calendar rows (a platform's copy = its row's caption; empty = the clip's post copy).
import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Sparkles } from 'lucide-react';
import type { CalendarPost } from '../../../shared/v04';
import { xWeightedLength } from '../../../shared/publish/postCopy';
import { titleLength } from '../../../shared/publish/postNow';
import { t } from '../i18n';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { useUi } from '../v4/ui';
import { base, overflowAt, type PostGroup } from './model';
import type { Accounts, usePublishData } from './usePublish';

export type Actions = ReturnType<typeof usePublishData>['actions'];
export type Shorten = (text: string, platform: string) => Promise<{ text: string; provider: string } | undefined>;
export type Row = { pf: string; post: CalendarPost };

/** The tab to open first: a platform whose caption is too long, else the first one. */
export function firstTab(rows: Row[]): string {
  return rows.find((r) => r.post.warnings?.some((w) => w.kind === 'caption_too_long'))?.pf ?? rows[0]?.pf ?? '';
}

/** the platforms of a card that have a title field, with their limit (the adapter's, else the engine's) */
export function titleLimitsOf(rows: Row[], accounts: Accounts): { pf: string; post: CalendarPost; limit: number }[] {
  return rows
    .map(({ pf, post }) => ({ pf, post, limit: titleLimitOf(pf, post, accounts) }))
    .filter((x): x is { pf: string; post: CalendarPost; limit: number } => x.limit !== null);
}

export function PostCopy({ rows, tab, setTab, accounts, actions, shorten }: { rows: Row[]; tab: string; setTab: (pf: string) => void; accounts: Accounts; actions: Actions; shorten: Shorten }) {
  const cur = rows.find((r) => r.pf === tab) ?? rows[0];
  if (!cur) return null;
  const tl = titleLimitsOf(rows, accounts).find((x) => x.pf === cur.pf);
  return (
    <>
      <div className="pb-ctabs" role="tablist">
        {rows.map(({ pf, post }) => (
          <button key={pf} role="tab" aria-selected={pf === cur.pf} className={pf === cur.pf ? 'on' : ''} onClick={() => setTab(pf)} data-testid="pb-ctab" data-pf={pf}>
            <PlatformIcon id={pf} size={16} />
            {platformName(pf)}
            {post.warnings?.some((w) => w.kind !== 'slot_clash') && <i className="wdot" />}
          </button>
        ))}
      </div>
      {tl ? <PostTitleEdit key={`t:${cur.post.id}:${cur.post.platform_title ?? cur.post.title}`} post={cur.post} limit={tl.limit} actions={actions} /> : null}
      <CaptionEditor key={cur.post.id} post={cur.post} actions={actions} shorten={shorten} />
    </>
  );
}

export function CaptionEditor({ post, actions, shorten }: { post: CalendarPost; actions: Actions; shorten: Shorten }) {
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

/** A platform's title limit for this post: the adapter's title field (none = the platform has no title), else the
 * engine's platform rule. */
export function titleLimitOf(pf: string, post: CalendarPost, accounts: Accounts): number | null {
  const a = accounts.adapterOf(pf);
  if (a) return a.fields.title ? a.fields.title.maxLength ?? post.title_limit ?? null : null;
  return post.title_limit ?? null;
}

/** The card's title, edited in place: Enter / leaving the field saves it on every platform of the card (a
 * platform's own title still wins there); Escape puts it back. Counters for the platforms that limit titles (小红书 20, …). */
export function TitleEdit({ g, actions, limits }: { g: PostGroup; actions: Actions; limits: { pf: string; post: CalendarPost; limit: number }[] }) {
  const [v, setV] = useState(g.title);
  const saved = useRef(g.title);
  useEffect(() => {
    setV(g.title);
    saved.current = g.title;
  }, [g.title]);
  const commit = () => {
    const x = v.replace(/\s*\n\s*/g, ' ').trim();
    if (!x) return setV(saved.current);
    if (x !== saved.current) {
      saved.current = x;
      void actions.retitle(g, x);
    }
  };
  const shared = limits.filter((l) => !l.post.title_custom);
  return (
    <div className="col" style={{ gap: 4, minWidth: 0 }}>
      <input
        className="pb-title-input"
        lang="zh-CN"
        value={v}
        maxLength={300}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
          if (e.key === 'Escape') {
            e.stopPropagation();
            setV(saved.current);
          }
        }}
        aria-label={t('pl.d.title')}
        data-testid="pb-title"
      />
      {shared.length > 0 && (
        <span className="pb-tcount" data-testid="pb-title-counts">
          {shared.map((l) => {
            const n = titleLength(l.pf, v.trim());
            return (
              <span key={l.pf} className={`num ${n > l.limit ? 'pb-amber' : 'muted'}`} data-pf={l.pf} data-over={n > l.limit}>
                <PlatformIcon id={l.pf} size={12} /> {fmtNum(n)}/{l.limit}
              </span>
            );
          })}
        </span>
      )}
    </div>
  );
}

const fmtNum = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

/** One platform's own title (in its caption tab): typing gives it its own title; "Use the card's title" resets. */
export function PostTitleEdit({ post, limit, actions }: { post: CalendarPost; limit: number; actions: Actions }) {
  const pf = base(post.platform);
  const own = post.platform_title ?? post.title;
  const [v, setV] = useState(own);
  const saved = useRef(own);
  const n = titleLength(pf, v.trim());
  const commit = () => {
    const x = v.replace(/\s*\n\s*/g, ' ').trim();
    if (!x) return setV(saved.current);
    if (x !== saved.current) {
      saved.current = x;
      void actions.postTitle(post, x === post.title ? null : x);
    }
  };
  return (
    <div className="pb-ptitle">
      <label className="pb-ptitle-l">
        <span className="muted small">{t('pl.d.titleFor', { pf: platformName(pf) })}</span>
        <input
          className={`input ${n > limit ? 'bad' : ''}`}
          value={v}
          onChange={(e) => setV(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
          data-testid="pb-post-title"
          data-pf={pf}
        />
      </label>
      <div className="pb-cfoot">
        <span className={`num ${n > limit ? 'pb-amber' : 'muted'}`} data-testid="pb-title-counter">
          <b>{fmtNum(n)}</b> / {limit}
        </span>
        {pf === 'xiaohongshu' && <span className="muted small">{t('pl.d.xhsCount')}</span>}
        <span className="sp" />
        {post.title_custom && (
          <button className="pb-link muted" onClick={() => void actions.postTitle(post, null)} data-testid="pb-title-reset">
            {t('pl.d.titleReset')}
          </button>
        )}
      </div>
    </div>
  );
}
