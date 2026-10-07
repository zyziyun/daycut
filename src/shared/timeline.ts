// The clip editor's timeline media (engine desk_engine/timeline.py): a filmstrip sprite sheet + audio peaks per
// output file, and the state of 「听一遍这条片子」 (transcribing an output that has no transcript yet).

export interface StripInfo {
  /** absolute path of the sprite sheet (cols x rows tiles, row-major, tile i = the frame at i * interval) */
  sprite: string | null;
  tile: [number, number];
  cols: number;
  rows: number;
  n: number;
  interval: number;
  duration: number;
  /** peak per bucket, 0..1; peaks_rate buckets per second */
  peaks: number[];
  peaks_rate: number;
  has_audio: boolean;
  w?: number | null;
  h?: number | null;
}

export interface TranscribeState {
  state: 'idle' | 'running' | 'done' | 'failed';
  error?: string;
  words?: number;
}
