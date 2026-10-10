// A recording's header in the clip editor (ux/record/pickups A1): Takes (the other takes of this Record visit, one
// click opens one; Record another take goes back to the recorder) and the one filled button, Finish — make my video:
// the clip as edited here (pickups and cuts in) is rendered once and handed to an autopilot request, like Finish in
// the recorder. Export stays next to it for a plain file.
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Clapperboard, Plus, Sparkles } from 'lucide-react';
import type { TakeInfo } from '../../../../shared/recIpc';
import type { OutputDoc } from '../../../../shared/v04';
import { fmtClock, getLang, t } from '../../i18n';
import { useEngine } from '../../lib/engine';
import { useHistory } from '../../lib/history';
import { href } from '../../lib/router';
import { waitJob } from '../../create/api';
import { errText } from '../msg';
import { useUi } from '../ui';

export function TakesMenu({ doc }: { doc: OutputDoc }) {
  const { client } = useEngine();
  const ui = useUi();
  const hist = useHistory();
  const [open, setOpen] = useState(false);
  const [takes, setTakes] = useState<TakeInfo[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);
  const r = doc.recording;
  const group = r?.group ?? null;
  useEffect(() => {
    if (!group) return;
    void window.desk.rec
      .list(group)
      .then(setTakes)
      .catch(() => setTakes([]));
  }, [open, group]);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    window.addEventListener('mousedown', down);
    return () => window.removeEventListener('mousedown', down);
  }, [open]);
  if (!r) return null;
  const list = takes ?? [];
  const n = list.length ? list.length - Math.max(0, list.findIndex((x) => x.id === r.session)) : 1;
  const go = async (tk: TakeInfo) => {
    if (!client) return;
    setBusy(tk.id);
    try {
      const { job } = await client.create.ingest(tk.dir, 'edit');
      const res = await waitJob<{ item?: string; clip?: string }>(client.create, job);
      if (!res.item || !res.clip) throw new Error(t('rec.editFailed'));
      hist.reload();
      setOpen(false);
      location.hash = href({ name: 'clip', id: res.item, clip: res.clip });
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="ce-takes" ref={ref}>
      <button className="btn ghost sm" onClick={() => setOpen(!open)} aria-expanded={open} data-testid="editor-takes">
        <Clapperboard className="ico" />
        {takes ? t('rec.take', { n }) : t('rec.takes')}
        <ChevronDown className="ico" />
      </button>
      {open && (
        <div className="menu" role="menu" data-testid="editor-takes-menu">
          {list.map((tk, i) => (
            <button key={tk.id} role="menuitem" className={tk.id === r.session ? 'on' : ''} disabled={!!busy || tk.id === r.session} onClick={() => void go(tk)} data-testid="editor-take">
              {busy === tk.id ? t('rec.preparing') : `${t('rec.take', { n: list.length - i })} · ${fmtClock(tk.secs)}`}
            </button>
          ))}
          {list.length > 0 && <span className="sep" />}
          <a role="menuitem" href={`#/create/record${group ? `?group=${group}` : ''}`} data-testid="editor-record-another">
            <Plus className="ico" />
            {t('pk.recordAnother')}
          </a>
        </div>
      )}
    </div>
  );
}

export function FinishButton({ item, clip, flush, primary }: { item: string; clip: string; flush: () => Promise<boolean>; primary: boolean }) {
  const { client } = useEngine();
  const ui = useUi();
  const hist = useHistory();
  const [busy, setBusy] = useState(false);
  const finish = async () => {
    if (!client || busy) return;
    setBusy(true);
    try {
      if (!(await flush())) return; // the transcript's cuts belong in it
      const r = await client.renderOutput(item, clip, { quality: 'final', targets: 'primary' });
      const file = r.targets[0]?.file;
      if (!file) throw new Error(t('pk.finishFailed'));
      const auto = (await window.desk.getSettings()).autopilot !== false;
      const req = await client.startIntake(t('rec.finishPrompt'), [file], undefined, getLang(), { mode: auto ? 'autopilot' : 'ask' });
      hist.reload();
      const to = `${href({ name: 'projects' })}?sel=${encodeURIComponent(req.id)}`;
      ui.toast(t(auto ? 'rec.sent' : 'rec.sentAsk'), { action: { label: t('rec.open'), href: to }, ms: 8000 });
      location.hash = to;
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className={`btn ${primary ? 'primary' : ''}`} disabled={busy} onClick={() => void finish()} data-testid="editor-finish">
      <Sparkles className="ico" />
      {busy ? t('pk.finishing') : t('rec.finish')}
    </button>
  );
}
