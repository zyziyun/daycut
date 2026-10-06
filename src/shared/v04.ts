// v0.4 engine documents: outputs (player + second-pass editor), intake (composer -> plan card), inbox, calendar.
// Mirrors engine/desk_engine/{outputs,intake,inbox,calendar}.py.

export type Aspect = '3:4' | '9:16' | '16:9' | string;

export interface ClipFile {
  path: string;
  aspect: Aspect;
  /** shown on the size chip instead of the aspect (e.g. "Edited" / "Original") */
  label?: string;
  w?: number | null;
  h?: number | null;
  fps?: number | null;
  duration?: number | null;
  platform?: string;
  safe_box?: number[] | null;
  caption_box?: number[] | null;
}

export interface PostCopy {
  title: string;
  body: string;
  tags: string[];
}

export interface Clip {
  id: string;
  title: string;
  /** done | running | queued | (batch job states) approved | packaged | failed ... */
  state: string;
  qc?: string | null;
  review?: string | null;
  files: ClipFile[];
  cover: string | null;
  post: PostCopy | null;
  duration: number | null;
  extra?: boolean;
  letter?: string | null;
}

export interface Confirmation {
  clip: string | null;
  text: string;
  source: string;
}

export interface ClipsDoc {
  item: string;
  kind: 'batch' | 'project' | 'work';
  clips: Clip[];
  confirm: Confirmation[];
}

export interface Word {
  w: string;
  t: number;
  te: number;
}

/** Every engine message: a code the desk localises + params, with the engine's own English / Chinese text. */
export interface EngineMsg {
  code: string;
  params?: Record<string, string | number | boolean | null>;
  message?: string;
  message_zh?: string;
}

export interface CaptionCue {
  id: string;
  start: number;
  end: number;
  text: string;
  added?: boolean;
  removed?: boolean;
}

export interface EffectInstance {
  id: string;
  effect: string;
  label?: { en: string; zh: string } | string;
  start: number;
  end: number;
  params: Record<string, unknown>;
}

/** The engine's op vocabulary (OUTPUT_EDIT.md section 3); one edit call = one undo step. */
export type EditOp =
  | { op: 'trim'; start?: number | null; end?: number | null }
  | { op: 'cut'; start: number; end: number; why?: string }
  | { op: 'cut_remove'; index: number }
  | { op: 'speed'; value: number }
  | { op: 'caption_text'; cue: string; text: string }
  | { op: 'caption_style'; style: { size?: number; color?: string; highlight?: string; keywords?: string[]; position?: 'bottom' | 'middle' | 'top' } }
  | { op: 'caption_add'; start: number; end: number; text: string }
  | { op: 'caption_remove'; cue: string }
  | { op: 'title'; text: string; sub?: string }
  | { op: 'effect_add'; effect: string; start: number; end?: number; params?: Record<string, unknown> }
  | { op: 'effect_update'; id: string; start?: number; end?: number; params?: Record<string, unknown> }
  | { op: 'effect_remove'; id: string }
  | { op: 'cover'; t?: number; text?: string; style?: 'card' | 'plain' | 'band'; clear?: boolean }
  | { op: 'export_add'; target: string; layout?: 'auto' | 'band' }
  | { op: 'export_remove'; target: string }
  | { op: 'reset' };

export interface Step {
  id: string;
  at?: string;
  by?: string;
  describe: EngineMsg[];
}

export interface OutputCaps {
  mode?: string;
  trim?: boolean;
  cut?: boolean;
  speed?: boolean;
  effects?: boolean;
  title_band?: boolean;
  cover?: boolean;
  export?: boolean;
  ai?: boolean;
  captions_ours?: boolean;
  caption_text?: boolean;
  caption_style?: boolean;
  caption_add?: boolean;
  caption_placements?: string[];
  relayout_layouts?: string[];
  [k: string]: unknown;
}

export interface OutputDoc {
  id: string;
  item: string;
  title: string;
  state: string;
  output_id: string | null;
  file: string | null;
  files: ClipFile[];
  cover: string | null;
  post: PostCopy | null;
  duration: number;
  fps: number;
  w?: number | null;
  h?: number | null;
  mode: 'pipeline' | 'flattened' | string;
  caps: OutputCaps;
  caps_notes: EngineMsg[];
  words: Word[];
  waveform: number[];
  captions: CaptionCue[];
  caption_style: { size?: number; color?: string; highlight?: string; keywords?: string[]; position?: string };
  effects: EffectInstance[];
  trim: { start: number; end: number } | null;
  cuts: { start: number; end: number; index: number }[];
  speed: number;
  title_band: { text: string; sub?: string } | null;
  cover_edit: { t?: number; text?: string; style?: string } | null;
  exports: { target: string; layout?: string }[];
  steps: Step[];
  undo: number;
  redo: number;
  renders: { target: string; quality?: string; file: string; fresh?: boolean; simulated?: boolean }[];
  warnings: EngineMsg[];
  safe_box?: number[] | null;
  caption_box?: number[] | null;
  engine: 'real' | 'desk';
}

export interface EffectDef {
  id: string;
  label: { en: string; zh: string };
  description?: { en: string; zh: string };
  category?: string;
  stage?: string;
  default_dur?: number;
  whole?: boolean;
  /** JSON-Schema subset: {type, default, minimum, maximum, enum, required, format, x-zh} */
  params: Record<string, { type?: string; default?: unknown; minimum?: number; maximum?: number; enum?: string[]; required?: boolean; format?: string; 'x-zh'?: string }>;
  thumbnail?: string | null;
}

export interface Proposal {
  id: string;
  op: EditOp;
  describe?: EngineMsg | null;
  why?: EngineMsg | string | null;
}

export interface AskResult {
  summary?: string | null;
  proposals: Proposal[];
  dropped?: { op?: unknown; error?: EngineMsg | string }[];
  warnings?: EngineMsg[];
  engine?: string;
  /** who answered ('rules': the desk's rule-based fallback), the provider the route chose, and the fallback record
   * when another provider answered instead (vstudio.llm complete -> output ai) */
  provider?: string | null;
  model?: string | null;
  routed?: string | null;
  fallback?: { from: string; to: string; code: string; error?: string } | null;
  /** the routed provider failed and no fallback answered: rules were used */
  failed?: { provider?: string | null; code?: string | null } | null;
}

// ---------------------------------------------------------------- intake
export interface IntakeMaterial {
  id: string;
  path: string;
  name: string;
  kind: string;
  role?: string;
  duration?: number;
}

export interface IntakeRow {
  id: string;
  params: { range?: [number, number]; title?: string };
  why?: string;
}

export interface IntakeProject {
  id: string;
  recipe: string;
  recipe_label?: string;
  type?: string;
  name: string;
  why?: string;
  items: { method: string; count: number; rows?: IntakeRow[]; focus?: string };
  params: Record<string, unknown> & { platforms?: string[]; aspects?: string[]; max_s?: number; min_s?: number };
  checkpoints: { id: string; kind: string; label: string; needs_you: boolean }[];
  estimate: { machine_min?: number; wall_min?: number; api_usd?: number; credits?: number | null };
  outputs?: { platforms?: string[]; videos?: number };
}

export interface IntakePlan {
  version: number;
  kind: 'vstudio.intake.plan';
  id: string;
  prompt: string;
  planner: {
    provider?: string;
    model?: string | null;
    /** true: the rule planner made this plan */
    fallback?: boolean;
    seconds?: number;
    routed?: string | null;
    /** another provider answered instead of the routed one */
    provider_fallback?: { from: string; to: string; code: string; error?: string } | null;
    failure?: string | null;
  };
  materials: IntakeMaterial[];
  projects: IntakeProject[];
  series: { id: string; name: string } | null;
  questions: { id: string; project?: string; text: string; options?: string[]; default?: string }[];
  risks: string[];
  warnings: string[];
  estimate: { machine_min?: number; wall_min?: number; api_usd?: number };
  summary_zh: string;
  revisions?: { prompt: string; at: string; changes?: string[] }[];
}

export interface IntakeJob {
  id: string;
  state: 'running' | 'done' | 'error';
  step?: string;
  prompt?: string;
  inputs?: string[];
  plan: IntakePlan | null;
  error?: string | null;
  applied?: { dir: string; name: string; recipe: string }[];
}

// ---------------------------------------------------------------- inbox
export type InboxGroup = 'choose' | 'review' | 'spend' | 'other';

export interface InboxItem {
  key: string;
  kind: string;
  group: InboxGroup;
  project: { id: string | null; name: string | null; kind?: string; thumb?: string | null; type?: string };
  code: string | null;
  params: Record<string, string | number>;
  text: string | null;
  options?: { id: string; clip?: string | null; text: string; checked?: boolean }[];
  reasons?: { code: string; n: number }[];
  jobs?: string[];
  minutes?: number;
  source: 'picks' | 'batch' | 'live' | 'engine';
  at?: number | null;
}

export interface InboxDoc {
  items: InboxItem[];
  at: number;
}

// ---------------------------------------------------------------- calendar
export interface CalendarPost {
  id: string;
  item: string;
  clip: string;
  title: string;
  cover: string | null;
  platform: string;
  at: string;
  state: 'planned' | 'ready' | 'posted';
}

export interface CalendarDoc {
  posts: CalendarPost[];
  queue: { item: string; clip: string; title: string; project: string | null; cover: string | null; aspects: string[] }[];
  at: number;
}
