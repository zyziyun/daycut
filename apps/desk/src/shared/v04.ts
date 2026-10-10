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
  /** ASR confidence 0..1 when the transcript has it (low ones get a dotted underline) */
  p?: number;
}

/** A filler / pause / low-confidence span of the transcript (the transcript's filter chips). */
export interface TextMark {
  kind: 'filler' | 'pause' | 'lowconf';
  i0: number;
  i1: number;
  text: string;
  save_s: number;
  group: string;
}

/** What one transcript Apply did to the rest of the clip (the applied cut card). */
export interface Retimed {
  captions?: { retimed?: number; shortened?: number; removed?: number };
  effects?: { trimmed?: { id: string; effect: string; label?: { en: string; zh: string }; from_s: number; to_s: number }[]; removed?: { id: string; effect: string; label?: { en: string; zh: string } }[] };
  sfx_removed?: number;
  targets?: string[];
}

/** Kept source ranges if pending cuts were applied (engine preview_edl: same snapping / segments as the render). */
export interface PreviewEdl {
  ok: boolean;
  keep: [number, number][];
  cuts: [number, number][];
  duration: number;
  source_duration?: number;
  dropped?: { index: number; error: EngineMsg }[];
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
  | { op: 'cut'; start: number; end: number; why?: string; words?: [number, number]; gap?: number; keep?: number; sig?: string }
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
  note?: string | null;
  describe: EngineMsg[];
  retimed?: Retimed | null;
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
  /** signature of `words` (a cut by word index is refused as stale-words when it changed) */
  words_sig?: string | null;
  marks?: TextMark[];
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

// ---------------------------------------------------------------- project-level 让 AI 改 (every clip of the page)
export type ProjectAskStage = 'read' | 'check' | 'ask' | 'plan';

export interface RerenderAction {
  kind: 'copy-prompt' | 'open-file' | 'regenerate' | 'reveal';
  label: EngineMsg;
  prompt?: string;
  file?: string;
  line?: number;
  items?: string[];
}

export interface RerenderPath {
  kind: 'rerender-scripts' | 'regenerate' | 're-export';
  message: EngineMsg;
  files?: { file: string; line: number; text: string }[];
  prompt?: string;
  items?: string[];
  actions: RerenderAction[];
}

/** The change cannot be made on these (flattened) clips: why, and the real way to get it. */
export interface NeedsRerender {
  clips: string[];
  titles: string[];
  code: string;
  reason: EngineMsg;
  targets: string[];
  /** true: the rule check answered (no model call) */
  rule?: boolean;
  paths: RerenderPath[];
}

export interface ProjectGroup {
  clip: string;
  title: string;
  mode?: string | null;
  proposals: Proposal[];
  dropped?: { op?: unknown; error?: EngineMsg | string }[];
  summary?: string | null;
  source?: string | null;
}

export interface ProjectAskResult {
  answer: 'changes' | 'needs_rerender' | 'mixed' | 'nothing';
  groups: ProjectGroup[];
  needs_rerender: NeedsRerender | null;
  summary?: string | null;
  warnings?: EngineMsg[];
  provider?: string | null;
  model?: string | null;
  routed?: string | null;
  fallback?: { from: string; to: string; code: string; error?: string } | null;
  /** the model call failed and no fallback answered: the rule answer is what is shown */
  failed?: { provider?: string | null; code?: string | null } | null;
  cost_usd?: number | null;
  seconds?: number | null;
  model_called?: boolean;
  engine?: string;
}

export interface ProjectAskJob {
  job: string;
  item: string;
  prompt: string;
  state: 'running' | 'done' | 'failed' | 'cancelled';
  stages: { stage: ProjectAskStage; at: number; n?: number | null; provider?: string | null }[];
  notices: { kind: 'fallback' | 'watchdog'; from?: string; to?: string; code?: string; at?: number; seconds?: number }[];
  clips: string[];
  timeout: number;
  elapsed: number;
  /** the rule answer (needs_rerender) sent before the model call */
  partial?: NeedsRerender | null;
  result: ProjectAskResult | null;
  error: EngineMsg | null;
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
  /** text in ``ui_lang``; with a code (references/MESSAGES.md) the UI words it itself */
  questions: { id: string; project?: string; text: string; code?: string; params?: EngineMsg['params']; options?: string[]; default?: string }[];
  risks: (string | EngineMsg)[];
  warnings: string[];
  estimate: { machine_min?: number; wall_min?: number; api_usd?: number };
  /** the plan's paragraph (despite the name: in ``summary_lang``) */
  summary_zh: string;
  /** the language summary_zh is written in (two-letter code; older plans: none) */
  summary_lang?: string;
  /** the language the planner wrote the questions, risks and reasons in (the UI's when the desk asked; older plans: none) */
  ui_lang?: 'en' | 'zh' | 'fr';
  revisions?: { prompt: string; at: string; changes?: string[] }[];
}

/** What a running plan / revision is doing now (the engine's ``vstudio.intake plan --json-events``, folded by the desk
 * engine): the current stage with its file / counters, and the stages seen so far. */
export type IntakeStage = 'scan' | 'probe' | 'listen' | 'faces' | 'transcribe' | 'model' | 'write';
export interface IntakeProgress {
  stage: IntakeStage;
  /** the file the stage works on (as named under the dropped folder) */
  file?: string;
  /** file i of n while reading the materials */
  i?: number;
  n?: number;
  kind?: string;
  /** transcription: seconds heard so far of total_s */
  done_s?: number;
  total_s?: number;
  /** probe: facts from the cache; transcribe: an earlier transcript was reused (shared | sidecar | audio | analysis) */
  cached?: boolean | string;
  /** the model the plan was asked of (stage model) */
  provider?: string;
  model?: string;
  /** files found under the inputs */
  files?: number;
  /** a transcript made earlier was used (kept after the transcribe stage) */
  reused?: boolean;
  seen?: IntakeStage[];
  at?: number;
}

export interface IntakeJob {
  id: string;
  state: 'running' | 'done' | 'error' | 'stopped';
  started?: number;
  step?: string;
  progress?: IntakeProgress | null;
  prompt?: string;
  inputs?: string[];
  /** the planner's language for this job (``--ui-lang``): en | zh | fr */
  lang?: string | null;
  plan: IntakePlan | null;
  error?: string | null;
  error_code?: import('./v02').FailureCode | null;
  error_provider?: string | null;
  applied?: { dir: string; name: string; recipe: string }[];
  /** how long the last plan / revision really took, reading the files and the AI call included (seconds) */
  seconds?: number | null;
  /** a request from Home: autopilot (applied and run at once) or ask (the plan waits for her Start) */
  mode?: 'autopilot' | 'ask' | null;
  name?: string | null;
}

/** GET /api/intake/open: requests from Home that are not projects yet (planning, a plan waiting for her, a failure). */
export interface OpenRequest {
  id: string;
  state: 'running' | 'done' | 'error';
  step?: string | null;
  mode: 'autopilot' | 'ask';
  prompt?: string | null;
  inputs: string[];
  started?: number | null;
  progress?: IntakeProgress | null;
  error_code?: import('./v02').FailureCode | null;
  error?: string | null;
  /** the plan's first project name once planned */
  name?: string | null;
  projects?: number | null;
  failed_apply?: boolean;
}

/** One decision the autopilot took (``vstudio.project decisions``), or one she took back (``asked``). */
export interface AutopilotDecision {
  checkpoint: string;
  item: string;
  kind?: string;
  labels?: { en?: string; zh?: string };
  value?: unknown;
  by?: 'ai' | 'rules';
  reason?: string | null;
  reason_code?: string | null;
  params?: Record<string, unknown>;
  provider?: string | null;
  at?: string | null;
  asked?: boolean;
  /** taste calls (filler-confirm, hook-pick): the options, each ``checked`` as the engine decided */
  options?: InboxOption[];
}

/** GET /api/autopilot/<item> */
export interface AutopilotDoc {
  item: string;
  supported: boolean;
  running: boolean;
  queued: number | null;
  autopilot: { on: boolean; spend_cap?: number; judge?: boolean; lang?: string; ask?: string[] } | null;
  decisions: AutopilotDecision[];
}

// ---------------------------------------------------------------- inbox
export type InboxGroup = 'failed' | 'choose' | 'review' | 'spend' | 'other';

/** One plain-language choice of an inbox item: what it is about (label / quote), what it saves, where to watch it. */
export interface InboxOption {
  id: string;
  clip?: string | null;
  /** the desk clip id (editor link + preview) and its title */
  clip_id?: string | null;
  clip_title?: string | null;
  /** the engine's own note (kept for search; never shown when a label exists) */
  text: string;
  checked?: boolean;
  kind?: string;
  label?: EngineMsg | null;
  detail?: EngineMsg | null;
  quote?: string | null;
  /** seconds this edit saves (negative) */
  secs?: number | null;
  approx?: boolean;
  /** seconds in the clip where the cut sits (the after preview plays ±3 s around it) */
  at?: number | null;
  /** the source recording around the cut (before preview), when it is in the folder */
  before?: { file: string; at: number } | null;
  file?: string | null;
  cover?: string | null;
  choices?: { id: string; label: EngineMsg; secs?: number | null; recommended?: boolean }[] | null;
  choice?: string | null;
  recommended?: boolean;
  /** an engine filler cut: the words around it (finds it in the clip's transcript) */
  ctx?: { before?: string | null; after?: string | null } | null;
}

export interface InboxItem {
  key: string;
  kind: string;
  group: InboxGroup;
  project: { id: string | null; name: string | null; kind?: string; thumb?: string | null; type?: string };
  code: string | null;
  params: Record<string, string | number>;
  text: string | null;
  label?: EngineMsg | null;
  options?: InboxOption[];
  reasons?: { code: string; n: number }[];
  jobs?: string[];
  minutes?: number;
  failure?: import('./v02').PilotFailure;
  source: 'picks' | 'batch' | 'live' | 'engine' | 'pilot' | 'create' | 'feedback';
  /** the item's project is archived: only that project's page lists it (not the Inbox, Home, badge, triage) */
  archived?: boolean;
  at?: number | null;
  /** Create items open their own screen (#/create/...) instead of being answered here */
  href?: string;
  /** the checkpoint's own label (author checkpoints: "Keep spans" / "保留片段") */
  labels?: { zh?: string; en?: string } | null;
  /** kind "author": she writes / approves a file; answered {done: true} */
  author?: InboxAuthor | null;
}

/** An author checkpoint's file (engine/desk_engine/inbox.py author_block). */
export interface InboxAuthor {
  labels?: { zh?: string; en?: string };
  help?: { zh?: string; en?: string };
  file: string | null;
  exists: boolean;
  is_dir?: boolean;
  template?: string | null;
  doc?: string | null;
  format?: string | null;
  /** the first lines of the file (or of the template while the file does not exist yet) */
  preview: string | null;
  more?: boolean;
  preview_of?: 'file' | 'template' | null;
}

export interface InboxDoc {
  items: InboxItem[];
  at: number;
  /** answered today (the "Done today" row) */
  done_today?: number;
}

// ---------------------------------------------------------------- calendar
/** One clip on one platform at one time (the board groups a clip's rows of one day into one card). */
export interface CalendarPost {
  id: string;
  item: string;
  clip: string;
  title: string;
  cover: string | null;
  platform: string;
  at: string;
  /** planned = draft; filled = the upload form is filled, waiting for her to press publish */
  state: 'planned' | 'ready' | 'filled' | 'posted';
  // decorated by the engine (older engines leave them out)
  status?: 'draft' | 'ready' | 'filled' | 'posted';
  enabled?: boolean;
  /** her text for this platform, else the clip's post copy */
  caption?: string;
  caption_custom?: boolean;
  /** caption length counted the platform's way (X: CJK = 2) and the platform's limit */
  length?: number;
  limit?: number | null;
  warnings?: PostWarning[];
  project?: string | null;
  duration?: number | null;
  stats?: { views?: number; likes?: number };
  /** the platform's title limit (null: the platform has no title) and this title's length, counted its way */
  title_limit?: number | null;
  title_length?: number;
  /** her own title for this platform (wins over the card's `title` there); title_custom = it is set */
  platform_title?: string;
  title_custom?: boolean;
  /** posted: the post's page when it was detected / typed, when, and how (her click in the built-in browser, an
   * official API, or marked by hand) */
  url?: string;
  posted_at?: string;
  via?: 'assisted' | 'api' | 'manual';
}

export interface PostWarning {
  kind: 'caption_too_long' | 'no_caption' | 'slot_clash' | 'title_too_long';
  platform: string;
  n?: number;
  max?: number;
  at?: string;
  other?: string;
}

export interface QueueClip {
  item: string;
  clip: string;
  title: string;
  project: string | null;
  cover: string | null;
  aspects: string[];
  duration?: number | null;
  has_post?: boolean;
}

export interface NewPost {
  item: string;
  clip: string;
  platform: string;
  at: string;
  caption?: string;
}

/** 「一句话排期」 preview (never written; Apply = scheduleMany(drafts)). */
export interface SchedulePlan {
  ok: boolean;
  reason: 'not_understood' | 'no_clips' | 'no_days' | null;
  text: string;
  start: string;
  drafts: (NewPost & { title?: string; cover?: string | null; project?: string | null })[];
  adjustments: { kind: 'moved'; platform: string; frm: string; to: string }[];
  platforms?: string[];
  time?: string | null;
  days?: number[];
  per_day?: number;
  clips?: number;
  from_selection?: boolean;
}

export interface CalendarDoc {
  posts: CalendarPost[];
  queue: QueueClip[];
  at: number;
}
