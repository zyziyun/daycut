// API keys (Anthropic for claude segment planning, OpenAI when configured). Stored in the OS keychain through
// the main process; the UI only ever learns whether a key is set. Typing a key and saving replaces it.
import { useEffect, useState } from 'react';
import type { SecretName, SecretsStatusMsg } from '../../../shared/deskApi';
import { t } from '../i18n';
import { ErrorBox } from './ui';

const NAMES: SecretName[] = ['anthropic', 'openai'];

export function KeysCard({ onChange }: { onChange?: () => void }) {
  const [st, setSt] = useState<SecretsStatusMsg | null>(null);
  const [val, setVal] = useState<Record<SecretName, string>>({ anthropic: '', openai: '' });
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    void window.desk.secrets.status().then(setSt);
  }, []);
  const clean = (e: unknown) => (e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
  async function save(n: SecretName) {
    setErr(null);
    try {
      setSt(await window.desk.secrets.set(n, val[n].trim()));
      setVal((v) => ({ ...v, [n]: '' }));
      onChange?.();
    } catch (e) {
      setErr(clean(e));
    }
  }
  async function clear(n: SecretName) {
    setErr(null);
    try {
      setSt(await window.desk.secrets.clear(n));
      onChange?.();
    } catch (e) {
      setErr(clean(e));
    }
  }
  if (!st) return null;
  return (
    <div className="card col" data-testid="keys-card">
      <b>{t('keys.title')}</b>
      <span className="muted small">{st.backend === 'keychain' ? t('keys.keychain') : t('keys.noKeychain')}</span>
      {NAMES.map((n) => (
        <div key={n} className="col" style={{ gap: 4 }}>
          <div className="row">
            <span style={{ width: 110 }}>{t(`keys.${n}`)}</span>
            {st.keys[n] ? <span className="badge accent">{t('keys.saved')}</span> : <span className="badge">{t('keys.missing')}</span>}
            <span className="muted small">{t(`keys.${n}Use`)}</span>
          </div>
          <div className="row">
            <input
              className="input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              style={{ flex: 1 }}
              aria-label={t(`keys.${n}`)}
              placeholder={st.keys[n] ? t('keys.replace') : t('keys.paste')}
              value={val[n]}
              disabled={st.backend !== 'keychain'}
              onChange={(e) => setVal((v) => ({ ...v, [n]: e.target.value }))}
              onKeyDown={(e) => e.key === 'Enter' && val[n].trim() && void save(n)}
              data-testid={`key-${n}`}
            />
            <button className="btn sm" disabled={!val[n].trim() || st.backend !== 'keychain'} onClick={() => save(n)}>
              {t('keys.save')}
            </button>
            {st.keys[n] && (
              <button className="btn ghost sm" onClick={() => clear(n)}>
                {t('keys.remove')}
              </button>
            )}
          </div>
        </div>
      ))}
      <span className="muted small">{t('keys.restartHint')}</span>
      <ErrorBox error={err} />
    </div>
  );
}
