// Import board (Create home + an episode's Storyboard): a HyperFrames project, a shot list (JSON / CSV / Markdown) or
// an editor timeline (EDL / OTIO / Premiere / Final Cut XML) -> shots. Pick a file or folder, or drop one. On home it
// becomes a new series + episode (opened on its storyboard); on a storyboard it replaces the shots (after asking).
import { useCallback, useState, type DragEvent, type ReactNode } from 'react';
import { Import } from 'lucide-react';
import type { CreateClient, ImportResult } from '../../../shared/create';
import { t } from '../i18n';
import { JobError, msgText, useCreate, errText, waitJob } from './api';
import { uiLang3 } from './bits';
import { goCreate } from './routes';

const IMPORT_WAIT_MS = 320_000;

export function useBoardImport(into?: { eid: string; shots: number; onDone: (r: ImportResult) => void }) {
  const c = useCreate();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const run = useCallback(
    async (path: string) => {
      if (!c || !path) return;
      if (into && into.shots > 0 && !window.confirm(t('create.import.replaceConfirm', { n: into.shots }))) return;
      setError(null);
      setDone(null);
      setBusy(path.split(/[\\/]/).filter(Boolean).pop() ?? path);
      try {
        const r = await importOnce(c, path, into?.eid);
        setDone(t('create.import.done', { n: r.n, importer: r.importer }));
        if (into) into.onDone(r);
        else goCreate({ screen: 'episode', eid: r.episode, tab: 'storyboard' });
      } catch (e) {
        setError(e instanceof JobError ? msgText(e.msg) : errText(e));
      } finally {
        setBusy(null);
      }
    },
    [c, into],
  );
  const pick = useCallback(async () => {
    const p = await window.desk.openFile('board');
    if (p) await run(p);
  }, [run]);
  return { busy, error, done, run, pick };
}

async function importOnce(c: CreateClient, path: string, eid?: string): Promise<ImportResult> {
  const { job } = eid ? await c.importBoardInto(eid, path) : await c.importBoard(path, { lang: uiLang3() });
  return waitJob<ImportResult>(c, job, undefined, 400, IMPORT_WAIT_MS);
}

/** Paths of the files / folders dropped on an element ('' entries removed). */
export function droppedPaths(e: DragEvent): string[] {
  return [...(e.dataTransfer?.files ?? [])].map((f) => window.desk.pathForFile?.(f) ?? '').filter(Boolean);
}

/** A drop target that imports the first dropped file / folder as a board. */
export function BoardDrop({ onPath, children, className }: { onPath: (p: string) => void; children: ReactNode; className?: string }) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`${className ?? ''} ${over ? 'cr-drop' : ''}`}
      onDragOver={(e) => {
        if (e.dataTransfer?.types?.includes('Files')) {
          e.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        const p = droppedPaths(e)[0];
        if (p) {
          e.preventDefault();
          e.stopPropagation();
          onPath(p);
        }
      }}
      data-testid="create-board-drop"
    >
      {children}
    </div>
  );
}

export function ImportBoardButton({ imp, testId, small }: { imp: ReturnType<typeof useBoardImport>; testId: string; small?: boolean }) {
  return (
    <button className={`btn ${small ? 'sm' : ''} cr-import`} disabled={!!imp.busy} onClick={() => void imp.pick()} title={t('create.import.hint')} data-testid={testId}>
      <Import className="ico" />
      {imp.busy ? t('create.import.working', { name: imp.busy }) : t('create.import.button')}
    </button>
  );
}

export function ImportNote({ imp, errorsOnly }: { imp: ReturnType<typeof useBoardImport>; errorsOnly?: boolean }) {
  if (imp.error)
    return (
      <div className="cr-err cr-import-note" role="alert" data-testid="create-import-error">
        {imp.error}
      </div>
    );
  if (imp.done && !errorsOnly)
    return (
      <div className="muted cr-import-note" data-testid="create-import-done">
        {imp.done}
      </div>
    );
  return null;
}
