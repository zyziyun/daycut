// The Create page module: one import site in App.tsx (nav item + screen) and one in Settings.tsx (Labs card).
// Everything else (routes, api, screens, copy, css) lives under create/.
import './create.css';
import { Pencil } from 'lucide-react';
import type { SettingsMsg } from '../../../shared/deskApi';
import { CreateHome } from './CreateHome';
import { EpisodeScreen } from './episode/EpisodeScreen';
import { RecordStudio } from './record/RecordStudio';
import { parseCreate } from './routes';
import { SeriesScreen } from './series/SeriesScreen';
import { VideoGenSection } from './settings/VideoGenSection';

export { setCreatePrefs, useCreateEnabled, createEnabled } from './flag';
export { CreateSettingsCard } from './settings/VideoGenSection';

export const CreateNavIcon = Pencil;

export function CreateScreen({ path, onSettings }: { path: string[]; onSettings?: (s: SettingsMsg) => void }) {
  const r = parseCreate(path);
  switch (r.screen) {
    case 'series':
      return (
        <div className="scroll">
          <SeriesScreen key={r.sid} sid={r.sid} tab={r.tab} />
        </div>
      );
    case 'episode':
      return (
        <div className="scroll">
          <EpisodeScreen key={r.eid} eid={r.eid} tab={r.tab} />
        </div>
      );
    case 'record':
      return <RecordStudio key={`${r.eid ?? ''}${r.shot ?? ''}${r.sid ?? ''}`} sid={r.sid} eid={r.eid} shot={r.shot} />;
    case 'settings':
      return (
        <div className="scroll">
          <VideoGenSection onSettings={onSettings} />
        </div>
      );
    default:
      return (
        <div className="scroll">
          <CreateHome />
        </div>
      );
  }
}
