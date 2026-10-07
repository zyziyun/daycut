// Small Create building blocks: format art (synthetic, no faces), source chips, cast avatars, header, tabs, ask bar.
import { useState, type ReactNode } from 'react';
import { Camera, ChevronRight, Clapperboard, Megaphone, MessagesSquare, ShoppingBag, Smile, Sparkles } from 'lucide-react';
import type { FormatId, L10n, Route, SourceOption } from '../../../shared/create';
import { swatch, yuan } from '../../../shared/create';
import { getLang, t, tk, type MessageKey } from '../i18n';
import { media } from '../v4/kit';
import { createHref, type CreateRoute } from './routes';

/** {en, zh, fr} -> the UI language (zh-CN -> zh), English fallback. */
export function l10n(d: L10n | string | undefined | null): string {
  if (!d) return '';
  if (typeof d === 'string') return d;
  const l = getLang() === 'zh-CN' ? 'zh' : getLang() === 'fr' ? 'fr' : 'en';
  return d[l] ?? d.en;
}

export function uiLang3(): 'en' | 'zh' | 'fr' {
  return getLang() === 'zh-CN' ? 'zh' : getLang() === 'fr' ? 'fr' : 'en';
}

const ART: Record<FormatId, { a: string; b: string; c: string; icon: ReactNode }> = {
  'series-ad': { a: '#2f5d62', b: '#5e8c88', c: '#d9c9a8', icon: <Megaphone className="ico" /> },
  'product-spot': { a: '#e9e2d6', b: '#c9b79c', c: '#8a6e4b', icon: <ShoppingBag className="ico" /> },
  interview: { a: '#6d7a83', b: '#a5afb5', c: '#e6d8c3', icon: <MessagesSquare className="ico" /> },
  'talk-show': { a: '#b9a487', b: '#e7dccb', c: '#6b5a44', icon: <Smile className="ico" /> },
  sketch: { a: '#24465a', b: '#4f7d94', c: '#e8eef0', icon: <Clapperboard className="ico" /> },
  record: { a: '#5b6168', b: '#9aa1a6', c: '#d8cfc2', icon: <Camera className="ico" /> },
};

/** A calm abstract illustration per format (shapes only; never a person or anyone's photo). */
export function FormatArt({ id, badge = true }: { id: FormatId; badge?: boolean }) {
  const a = ART[id] ?? ART['series-ad'];
  const g = `g-${id}`;
  return (
    <div className="cr-art" aria-hidden="true">
      <svg viewBox="0 0 200 160" preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id={g} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={a.a} />
            <stop offset="1" stopColor={a.b} />
          </linearGradient>
        </defs>
        <rect width="200" height="160" fill={`url(#${g})`} />
        {id === 'series-ad' && (
          <>
            <path d="M0 120 C40 100 70 130 110 112 S170 96 200 110 L200 160 L0 160Z" fill={a.c} opacity="0.35" />
            <rect x="120" y="26" width="34" height="60" rx="6" fill="#fff" opacity="0.85" />
            <rect x="126" y="34" width="22" height="34" rx="2" fill={a.a} opacity="0.5" />
          </>
        )}
        {id === 'product-spot' && (
          <>
            <circle cx="140" cy="60" r="34" fill="#fff" opacity="0.55" />
            <rect x="122" y="56" width="36" height="52" rx="10" fill={a.c} />
            <rect x="128" y="48" width="24" height="10" rx="3" fill={a.c} opacity="0.7" />
          </>
        )}
        {id === 'interview' && (
          <>
            <rect x="96" y="30" width="70" height="40" rx="12" fill="#fff" opacity="0.8" />
            <rect x="60" y="78" width="70" height="36" rx="12" fill={a.c} opacity="0.9" />
            <rect x="152" y="96" width="6" height="40" rx="3" fill="#2a2622" opacity="0.7" />
            <circle cx="155" cy="92" r="9" fill="#2a2622" opacity="0.8" />
          </>
        )}
        {id === 'talk-show' && (
          <>
            <circle cx="140" cy="44" r="40" fill="#fff" opacity="0.5" />
            <rect x="134" y="70" width="12" height="70" rx="6" fill={a.c} />
            <rect x="126" y="56" width="28" height="22" rx="11" fill={a.c} />
          </>
        )}
        {id === 'sketch' && (
          <>
            <path d="M0 110 L200 80 L200 160 L0 160Z" fill={a.c} opacity="0.25" />
            <rect x="110" y="30" width="60" height="44" rx="4" fill="#fff" opacity="0.85" />
            <path d="M110 30 L170 30 L162 20 L118 20Z" fill="#fff" opacity="0.6" />
            <circle cx="126" cy="96" r="6" fill="#fff" opacity="0.8" />
            <circle cx="146" cy="104" r="6" fill="#fff" opacity="0.8" />
            <circle cx="166" cy="96" r="6" fill="#fff" opacity="0.8" />
          </>
        )}
        {id === 'record' && (
          <>
            <rect x="104" y="28" width="62" height="96" rx="10" fill="#1f1d1a" opacity="0.85" />
            <circle cx="135" cy="68" r="14" fill={a.c} opacity="0.9" />
            <rect x="118" y="88" width="34" height="26" rx="13" fill={a.c} opacity="0.9" />
            <circle cx="155" cy="38" r="4" fill="#e5484d" />
          </>
        )}
      </svg>
      {badge && <span className="badge">{a.icon}</span>}
    </div>
  );
}

const CAST_COLORS = ['#0f7a6c', '#c2603a', '#2f6aa6', '#7c6bb0', '#b08a2e', '#8c8379'];

export function CastAvatar({ id, i }: { id: string; i: number }) {
  return (
    <div className="cr-avatar" style={{ background: CAST_COLORS[i % CAST_COLORS.length] }} aria-hidden="true">
      {id.slice(0, 2)}
    </div>
  );
}

/** "Kling 3.0", "Hailuo 02", "Text card", "Record"… for a route / option. */
export function sourceLabel(r: Pick<Route, 'kind' | 'label' | 'provider' | 'model'> | Pick<SourceOption, 'kind' | 'label' | 'provider' | 'model'>): string {
  if (r.kind === 'card') return tk('create.route.card');
  if (r.kind === 'record') return tk('create.route.record');
  if (r.kind === 'reuse') return tk('create.route.reuse');
  if (r.kind === 'local') return `${t('create.board.thisMac')} · LTX-2`;
  if (r.kind === 'placeholder') return tk('create.kind.placeholder');
  if (r.provider === 'jimeng') return `${tk('create.svc.jimeng')} Seedance`;
  if (r.kind === 'agent') return t('create.src.agent', { name: r.label ?? r.provider ?? '' });
  if (r.kind === 'plugin') return t('create.src.plugin', { name: r.label ?? r.provider ?? '' });
  return r.label ?? r.model ?? r.provider ?? '';
}

export function SrcChip({ r, onClick, testId }: { r: Route; onClick?: () => void; testId?: string }) {
  return (
    <button className="cr-src" onClick={onClick} data-testid={testId} title={sourceLabel(r)}>
      <i className={`cr-sw sw-${swatch(r.kind, r.provider)}`} />
      {sourceLabel(r)}
    </button>
  );
}

export function priceText(cny: number | null | undefined, kind: string): string {
  if (kind === 'manual') return t('create.option.credits');
  if (cny === null || cny === undefined || cny === 0) return t('create.plan.free');
  return yuan(cny);
}

export function Crumbs({ items }: { items: { label: string; to?: CreateRoute | string }[] }) {
  return (
    <div className="cr-crumb">
      {items.map((it, i) => (
        <span key={i} className="row" style={{ gap: 8 }}>
          {i > 0 && <ChevronRight className="ico" />}
          {it.to ? <a href={typeof it.to === 'string' ? it.to : createHref(it.to)}>{it.label}</a> : <span>{it.label}</span>}
        </span>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, on, href, testId }: { tabs: { id: T; key: MessageKey; n?: number | null }[]; on: T; href: (id: T) => string; testId: string }) {
  return (
    <nav className="cr-tabs" data-testid={testId}>
      {tabs.map((x) => (
        <a key={x.id} href={href(x.id)} className={x.id === on ? 'on' : ''} data-testid={`${testId}-${x.id}`}>
          {t(x.key)}
          {x.n ? <span className="n">{x.n}</span> : null}
        </a>
      ))}
    </nav>
  );
}

/** The natural-language bar at the bottom of the bible and the storyboard. */
export function AskBar({ placeholder, onAsk, busy, testId }: { placeholder: string; onAsk: (text: string) => void | Promise<void>; busy?: boolean; testId: string }) {
  const [v, setV] = useState('');
  return (
    <form
      className="cr-ask"
      onSubmit={(e) => {
        e.preventDefault();
        if (!v.trim() || busy) return;
        void onAsk(v.trim());
        setV('');
      }}
    >
      <Sparkles className="ico" />
      <input value={v} onChange={(e) => setV(e.target.value)} placeholder={placeholder} aria-label={placeholder} data-testid={testId} disabled={busy} />
      <span className="cr-hint">⌘K</span>
    </form>
  );
}

export function Still({ src, alt = '' }: { src?: string | null; alt?: string }) {
  return src ? <img src={media(src)} alt={alt} loading="lazy" /> : null;
}
