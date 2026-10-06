// One client workspace: client.yaml fields (style, platforms, tags, glossary / term fixes, filler rules, brand
// colours, cover style, cleanup profile), the manual funnel + 7-day post data, and the client's batches.
import { useEffect, useMemo, useState } from 'react';
import { CLEANUP_PROFILES, COVER_STYLES, FUNNEL, type ClientConfig, type GlossaryEntry } from '../../../shared/v02';
import { ErrorBox, Field } from '../components/ui';
import { t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { href } from '../lib/router';
import { PlatformPicker, StageBadge } from './Clients';

const list = (s: string) =>
  s
    .split(/[,，、\s]+/)
    .map((x) => x.trim().replace(/^#/, ''))
    .filter(Boolean);

export function ClientDetail({ slug }: { slug: string }) {
  const { client } = useEngine();
  const { data, error, reload, setData } = useLoad((c) => c.client(slug), [slug]);
  const batches = useLoad((c) => c.batches(), []);
  const [cfg, setCfg] = useState<ClientConfig | null>(null);
  const [tags, setTags] = useState('');
  const [extra, setExtra] = useState('');
  const [keep, setKeep] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const e = data.effective;
    setCfg(e);
    setTags((e.tags ?? []).join(', '));
    setExtra((e.fillers?.extra ?? []).join(', '));
    setKeep((e.fillers?.keep ?? []).join(', '));
  }, [data]);

  const dirty = useMemo(() => {
    if (!data || !cfg) return false;
    const now = { ...cfg, tags: list(tags), fillers: { extra: list(extra), keep: list(keep) } };
    return JSON.stringify(now) !== JSON.stringify(data.effective);
  }, [cfg, tags, extra, keep, data]);

  async function save() {
    if (!client || !cfg) return;
    setErr(null);
    try {
      const next = await client.updateClient(slug, {
        name: cfg.name,
        style: cfg.style,
        platforms: cfg.platforms,
        tags: list(tags),
        glossary: cfg.glossary.filter((g) => g.wrong.trim() && g.right.trim()),
        fillers: { extra: list(extra), keep: list(keep) },
        brand: cfg.brand,
        cover_style: cfg.cover_style,
        cleanup_profile: cfg.cleanup_profile,
        notes: cfg.notes,
      });
      setData(next);
      setMsg(t('clients.saved'));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  });

  if (!data || !cfg) {
    return (
      <>
        <div className="topbar">
          <h1>{slug}</h1>
        </div>
        <div className="page">
          <ErrorBox error={error} />
        </div>
      </>
    );
  }
  const set = <K extends keyof ClientConfig>(k: K, v: ClientConfig[K]) => setCfg({ ...cfg, [k]: v });
  const setG = (i: number, g: GlossaryEntry | null) =>
    set(
      'glossary',
      g === null ? cfg.glossary.filter((_, j) => j !== i) : cfg.glossary.map((x, j) => (j === i ? g : x)),
    );
  const mine = (batches.data ?? []).filter((b) => b.client === slug);

  return (
    <>
      <div className="topbar">
        <a className="btn ghost sm" href={href({ name: 'clients' })}>
          ← {t('nav.clients')}
        </a>
        <h1>{cfg.name || slug}</h1>
        <StageBadge stage={data.crm.stage} />
        <div className="sp" />
        <span className="muted small mono" title={data.dir}>
          client.yaml
        </span>
        <button className="btn primary" disabled={!dirty} onClick={save} data-testid="client-save">
          {t('clients.save')} <kbd>⌘S</kbd>
        </button>
      </div>
      <div className="page" style={{ display: 'grid', gridTemplateColumns: 'minmax(420px, 1fr) minmax(320px, 420px)', gap: 16, alignItems: 'start' }}>
        <div className="col" style={{ gap: 12 }}>
          {msg && <div className="notice accent">{msg}</div>}
          <ErrorBox error={err} />
          <div className="card col">
            <Field label={t('clients.name')}>
              <input className="input" value={cfg.name} maxLength={60} onChange={(e) => set('name', e.target.value)} />
            </Field>
            <Field label={t('clients.style')} hint={t('clients.styleHint')}>
              <textarea className="input" rows={3} maxLength={500} value={cfg.style} onChange={(e) => set('style', e.target.value)} />
            </Field>
            <Field label={t('clients.platforms')}>
              <PlatformPicker value={cfg.platforms} onChange={(v) => set('platforms', v)} />
            </Field>
            <Field label={t('clients.tags')} hint={t('clients.listHint')}>
              <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="RAG, 面试, AI" />
            </Field>
            <div className="row" style={{ gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
              <Field label={t('clients.cleanupProfile')}>
                <div className="tabs">
                  {CLEANUP_PROFILES.map((p) => (
                    <button key={p} className={`tab ${cfg.cleanup_profile === p ? 'on' : ''}`} onClick={() => set('cleanup_profile', p)}>
                      {t(`clients.profile.${p}`)}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label={t('clients.coverStyle')}>
                <div className="tabs">
                  {COVER_STYLES.map((p) => (
                    <button key={p} className={`tab ${cfg.cover_style === p ? 'on' : ''}`} onClick={() => set('cover_style', p)}>
                      {t(`clients.cover.${p}`)}
                    </button>
                  ))}
                </div>
              </Field>
            </div>
            <div className="row" style={{ gap: 16 }}>
              {(['accent', 'highlight'] as const).map((k) => (
                <Field key={k} label={t(`clients.brand.${k}`)}>
                  <div className="row">
                    <input type="color" aria-label={t(`clients.brand.${k}`)} value={cfg.brand?.[k] ?? '#000000'} onChange={(e) => set('brand', { ...cfg.brand, [k]: e.target.value.toUpperCase() })} />
                    <span className="mono small">{cfg.brand?.[k]}</span>
                  </div>
                </Field>
              ))}
            </div>
            <Field label={t('clients.fillersExtra')} hint={t('clients.fillersExtraHint')}>
              <input className="input" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="那么, 对吧" />
            </Field>
            <Field label={t('clients.fillersKeep')} hint={t('clients.fillersKeepHint')}>
              <input className="input" value={keep} onChange={(e) => setKeep(e.target.value)} placeholder="其实" />
            </Field>
            <Field label={t('clients.notes')}>
              <textarea className="input" rows={2} maxLength={2000} value={cfg.notes} onChange={(e) => set('notes', e.target.value)} />
            </Field>
          </div>
          <div className="card col">
            <div className="row">
              <b>{t('clients.glossary')}</b>
              <span className="muted small">{t('clients.glossaryHint')}</span>
              <div className="sp" style={{ flex: 1 }} />
              <button className="btn sm" onClick={() => set('glossary', [...cfg.glossary, { wrong: '', right: '' }])}>
                + {t('clients.glossaryAdd')}
              </button>
            </div>
            {cfg.glossary.length === 0 && <div className="muted small">{t('clients.glossaryEmpty')}</div>}
            <table className="t small">
              <tbody>
                {cfg.glossary.map((g, i) => (
                  <tr key={i}>
                    <td>
                      <input className="input" aria-label={t('clients.wrong')} value={g.wrong} maxLength={40} placeholder={t('clients.wrong')} onChange={(e) => setG(i, { ...g, wrong: e.target.value })} />
                    </td>
                    <td className="muted">→</td>
                    <td>
                      <input className="input" aria-label={t('clients.right')} value={g.right} maxLength={40} placeholder={t('clients.right')} onChange={(e) => setG(i, { ...g, right: e.target.value })} />
                    </td>
                    <td>{g.source === 'caption-fix' && <span className="badge accent" title={`${g.batch ?? ''} ${g.job ?? ''}`}>{t('clients.fromCaption')}</span>}</td>
                    <td>
                      <button className="btn ghost sm" aria-label={t('common.remove')} onClick={() => setG(i, null)}>
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="col" style={{ gap: 12 }}>
          <CrmCard slug={slug} crm={data.crm} onChange={reload} />
          <div className="card col">
            <div className="row">
              <b>{t('clients.batches')}</b>
              <div style={{ flex: 1 }} />
              <a className="btn sm" href={href({ name: 'new' })} onClick={() => sessionStorage.setItem('newClient', slug)}>
                + {t('batches.new')}
              </a>
            </div>
            {mine.length === 0 && <div className="muted small">{t('clients.noBatches')}</div>}
            {mine.map((b) => (
              <a key={b.id} className="item" href={href({ name: 'board', batch: b.id })}>
                <span>{b.name}</span>
                <span className="muted small">
                  {b.counts?.total ?? 0} · {b.delivered ? t('deliver.delivered') : b.state}
                </span>
              </a>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function CrmCard({ slug, crm, onChange }: { slug: string; crm: import('../../../shared/v02').Crm; onChange: () => void }) {
  const { client } = useEngine();
  const [amount, setAmount] = useState('');
  const [price, setPrice] = useState(crm.price_next != null ? String(crm.price_next) : '');
  const [post, setPost] = useState({ platform: 'xiaohongshu', plays: '', saves: '', likes: '', comments: '', followers: '', url: '' });
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const reached = new Set(crm.history.map((h) => h.stage));
  const num = (v: string) => (v.trim() === '' ? undefined : Math.max(0, Math.round(Number(v))));
  return (
    <div className="card col" data-testid="crm">
      <b>{t('crm.title')}</b>
      <div className="funnel">
        {FUNNEL.map((s) => (
          <button
            key={s}
            className={`step ${reached.has(s) ? 'on' : ''} ${crm.stage === s ? 'cur' : ''}`}
            title={crm.history.find((h) => h.stage === s)?.at ?? ''}
            onClick={() => run(() => client!.setCrm(slug, { stage: s }))}
          >
            {t(`funnel.${s}`)}
          </button>
        ))}
        <button className={`step lost ${crm.lost ? 'cur' : ''}`} onClick={() => run(() => client!.setCrm(slug, { stage: 'lost' }))}>
          {t('funnel.lost')}
        </button>
      </div>
      <div className="row">
        <input className="input" style={{ width: 120 }} inputMode="decimal" placeholder={t('crm.amount')} value={amount} onChange={(e) => setAmount(e.target.value)} />
        <button className="btn sm" disabled={!(Number(amount) > 0)} onClick={() => run(async () => (await client!.setCrm(slug, { revenue: Number(amount) }), setAmount('')))}>
          {t('crm.addRevenue')}
        </button>
        <span className="muted small">¥{crm.revenue.reduce((a, r) => a + r.amount, 0)}</span>
      </div>
      <div className="row">
        <input className="input" style={{ width: 120 }} inputMode="decimal" placeholder={t('crm.priceNext')} value={price} onChange={(e) => setPrice(e.target.value)} />
        <button className="btn sm" disabled={!(Number(price) >= 0) || price === ''} onClick={() => run(() => client!.setCrm(slug, { price_next: Number(price) }))}>
          {t('crm.savePrice')}
        </button>
        <span className="muted small">{t('crm.priceHint')}</span>
      </div>
      <b className="small">{t('crm.posts')}</b>
      <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
        <select className="input" value={post.platform} onChange={(e) => setPost({ ...post, platform: e.target.value })} aria-label={t('crm.platform')}>
          {['xiaohongshu', 'douyin', 'tiktok', 'youtube', 'bilibili'].map((p) => (
            <option key={p} value={p}>
              {t(`platform.${p === 'xiaohongshu' ? 'xiaohongshu-full' : p}`).replace(/ 9:16$/, '')}
            </option>
          ))}
        </select>
        {(['plays', 'saves', 'likes', 'comments', 'followers'] as const).map((k) => (
          <input key={k} className="input" style={{ width: 78 }} inputMode="numeric" placeholder={t(`crm.${k}`)} aria-label={t(`crm.${k}`)} value={post[k]} onChange={(e) => setPost({ ...post, [k]: e.target.value })} />
        ))}
        <input className="input" style={{ flex: 1, minWidth: 140 }} placeholder="https://…" value={post.url} onChange={(e) => setPost({ ...post, url: e.target.value })} />
        <button
          className="btn sm"
          disabled={!post.plays}
          onClick={() =>
            run(async () => {
              await client!.setCrm(slug, {
                post: { platform: post.platform, plays: num(post.plays), saves: num(post.saves), likes: num(post.likes), comments: num(post.comments), followers: num(post.followers), ...(post.url.startsWith('https://') ? { url: post.url } : {}) },
              });
              setPost({ ...post, plays: '', saves: '', likes: '', comments: '', followers: '', url: '' });
            })
          }
        >
          {t('crm.addPost')}
        </button>
      </div>
      {crm.posts.length > 0 && (
        <table className="t small">
          <thead>
            <tr>
              <th>{t('crm.date')}</th>
              <th>{t('crm.platform')}</th>
              <th>{t('crm.plays')}</th>
              <th>{t('crm.saves')}</th>
              <th>{t('crm.followers')}</th>
            </tr>
          </thead>
          <tbody>
            {crm.posts.map((p, i) => (
              <tr key={i}>
                <td>{p.at}</td>
                <td>{p.platform}</td>
                <td>{p.plays ?? '—'}</td>
                <td>{p.saves ?? '—'}</td>
                <td>{p.followers ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ErrorBox error={err} />
    </div>
  );
}
