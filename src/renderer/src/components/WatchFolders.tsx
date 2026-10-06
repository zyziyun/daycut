// Settings: the watched folders (past work shows up from these without an import).
import { useState } from 'react';
import { t } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';

export function WatchFoldersField() {
  const { client } = useEngine();
  const { data, reload } = useHistory();
  const [text, setText] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const value = text ?? (data?.watch ?? []).join('\n');
  return (
    <div data-testid="watch-folders">
      <textarea className="input mono" rows={3} style={{ width: '100%' }} value={value} onChange={(e) => setText(e.target.value)} aria-label={t('history.watching')} />
      <div className="row" style={{ gap: 6, marginTop: 4 }}>
        <button
          className="btn sm"
          onClick={async () => {
            const dir = await window.desk.openFolder();
            if (dir) setText([...value.split('\n').filter((s) => s.trim()), dir].join('\n'));
          }}
        >
          {t('history.addWatch')}
        </button>
        <button
          className="btn sm primary"
          onClick={async () => {
            setMsg(null);
            try {
              await client!.setHistoryWatch(value.split('\n').map((s) => s.trim()).filter(Boolean));
              setText(null);
              reload();
              setMsg(t('settings.saved'));
            } catch (e) {
              setMsg((e as Error).message);
            }
          }}
        >
          {t('clients.save')}
        </button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
    </div>
  );
}
