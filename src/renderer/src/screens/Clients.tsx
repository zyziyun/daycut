// Clients (workspaces): one client.yaml per client overriding the global persona; batches belong to a client.
import { useEffect, useState } from 'react';
import { Empty, ErrorBox, Field, Modal } from '../components/ui';
import { t, tk } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { go, href } from '../lib/router';
import { PLATFORM_CHOICES } from './NewBatch';

export function StageBadge({ stage }: { stage: string | null }) {
  if (!stage) return <span className="muted small">—</span>;
  const tone = stage === 'paid' ? 'accent' : stage === 'lost' ? 'danger' : '';
  return <span className={`badge ${tone}`}>{tk(`funnel.${stage}`)}</span>;
}

export function PlatformPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="tabs" role="group">
      {PLATFORM_CHOICES.map((p) => (
        <button
          key={p.id}
          type="button"
          aria-pressed={value.includes(p.id)}
          className={`tab ${value.includes(p.id) ? 'on' : ''}`}
          onClick={() => onChange(value.includes(p.id) ? value.filter((y) => y !== p.id) : [...value, p.id])}
        >
          {tk(p.label)}
        </button>
      ))}
    </div>
  );
}

export function slugify(name: string): string {
  const s = name
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
  return s || `client-${Date.now().toString(36).slice(-5)}`;
}

function NewClient({ onClose }: { onClose: () => void }) {
  const { client } = useEngine();
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [platforms, setPlatforms] = useState<string[]>(['xiaohongshu:full']);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void window.desk.getSettings().then((s) => s.defaultPlatforms?.length && setPlatforms(s.defaultPlatforms));
  }, []);
  const valid = name.trim() && /^[a-z0-9][a-z0-9_-]{0,39}$/.test(slug);
  async function create() {
    if (!client || !valid) return;
    try {
      const c = await client.createClient({ slug, name: name.trim(), platforms });
      go({ name: 'client', slug: c.slug });
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <Modal title={t('clients.new')} onClose={onClose}>
      <Field label={t('clients.name')}>
        <input
          className="input"
          autoFocus
          value={name}
          maxLength={60}
          onChange={(e) => {
            setName(e.target.value);
            if (!slugEdited) setSlug(slugify(e.target.value));
          }}
          onKeyDown={(e) => e.key === 'Enter' && void create()}
        />
      </Field>
      <Field label={t('clients.slug')} hint={t('clients.slugHint')}>
        <input
          className="input mono"
          value={slug}
          maxLength={40}
          onChange={(e) => {
            setSlugEdited(true);
            setSlug(e.target.value);
          }}
        />
      </Field>
      <Field label={t('clients.platforms')}>
        <PlatformPicker value={platforms} onChange={setPlatforms} />
      </Field>
      <ErrorBox error={error} />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button className="btn primary" disabled={!valid} onClick={create}>
          {t('clients.create')}
        </button>
      </div>
    </Modal>
  );
}

export function Clients() {
  const { subscribe } = useEngine();
  const { data, error, reload } = useLoad((c) => c.clients(), []);
  const [creating, setCreating] = useState(false);
  useEffect(
    () =>
      subscribe((e) => {
        if (e.type === 'clients') reload();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe],
  );
  return (
    <>
      <div className="topbar">
        <h1>{t('nav.clients')}</h1>
        <div className="sp" />
        <button className="btn primary" onClick={() => setCreating(true)} data-testid="new-client">
          {t('clients.new')}
        </button>
      </div>
      <div className="page">
        <ErrorBox error={error} />
        {data && data.length === 0 && <Empty>{t('clients.empty')}</Empty>}
        {data && data.length > 0 && (
          <table className="t">
            <thead>
              <tr>
                <th>{t('clients.name')}</th>
                <th>{t('clients.stage')}</th>
                <th>{t('clients.platforms')}</th>
                <th>{t('clients.batches')}</th>
                <th>{t('clients.glossary')}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.slug} className="click" tabIndex={0} onClick={() => go({ name: 'client', slug: c.slug })} onKeyDown={(e) => e.key === 'Enter' && go({ name: 'client', slug: c.slug })}>
                  <td>
                    <a href={href({ name: 'client', slug: c.slug })} onClick={(e) => e.stopPropagation()}>
                      {c.name}
                    </a>
                    <div className="muted small mono">{c.slug}</div>
                  </td>
                  <td>
                    <StageBadge stage={c.stage} />
                  </td>
                  <td className="small">{c.platforms.join(', ') || '—'}</td>
                  <td>{c.batches}</td>
                  <td>{c.glossary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {creating && <NewClient onClose={() => setCreating(false)} />}
    </>
  );
}
