// The chat-first clip editor (ux/CHAT_EDIT.md, direction C): the clip's chat transcript as the engine / desk keep
// it with the clip's edit doc (`output chat`, show.chat), the context she points at, export jobs.
import type { EngineMsg, OutputDoc, Proposal, Step } from './v04';

/** What she points at: a timeline selection, caption cues, the open effect (engine `output ai --context`). */
export interface AskContext {
  range?: [number, number];
  cues?: string[];
  effect?: string;
}

export type TurnStatus = 'draft' | 'applied' | 'discarded' | 'reverted' | 'note';
export type CardKind = 'trim' | 'captions' | 'effect' | 'cover' | 'export';

/** One turn of the clip's conversation: her words + the AI's change set, or a card she opened herself. */
export interface ChatTurn {
  id: string;
  at?: string;
  role: 'user' | 'ai';
  text?: string | null;
  context?: AskContext | null;
  proposals: Proposal[];
  dropped?: { op?: unknown; error?: EngineMsg | string }[];
  warnings?: EngineMsg[];
  summary?: string | null;
  provider?: string | null;
  model?: string | null;
  cost_usd?: number | null;
  seconds?: number | null;
  status: TurnStatus;
  applied_step?: string | null;
  applied_ops?: number | null;
  reverted_by?: string | null;
  /** a card she opened without the model (/trim, /captions ...); 'transcript' = cuts she made in the transcript */
  card?: CardKind | 'transcript' | null;
  reply?: string | null;
}

export type HistStep = Step & { reverted?: boolean; revert_of?: string | null };
export type ChatDoc = Omit<OutputDoc, 'steps'> & { steps: HistStep[]; chat?: ChatTurn[] };

export interface ExportJob {
  ok: boolean;
  job: string;
  targets: string[];
}

/** The 8 platforms of the export card (engine target = platform:orientation), in the shared order: English / global
 * first, then Chinese. */
export const EXPORT_PLATFORMS = [
  { id: 'youtube', target: 'youtube:horizontal', aspect: '16:9' },
  { id: 'tiktok', target: 'tiktok:vertical', aspect: '9:16' },
  { id: 'instagram', target: 'instagram:vertical', aspect: '9:16' },
  { id: 'x', target: 'x:horizontal', aspect: '16:9' },
  { id: 'xiaohongshu', target: 'xiaohongshu:vertical', aspect: '3:4' },
  { id: 'douyin', target: 'douyin:vertical', aspect: '9:16' },
  { id: 'wechat-channels', target: 'wechat-channels:vertical', aspect: '9:16' },
  { id: 'bilibili', target: 'bilibili:horizontal', aspect: '16:9' },
] as const;
export type PlatformId = (typeof EXPORT_PLATFORMS)[number]['id'];
