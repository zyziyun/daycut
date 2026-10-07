// Active human review time (PRODUCT_V02.md P0-3/P0-5: 人审秒数). Time only counts while the window is visible
// AND focused AND the reviewer did something (key, pointer, scroll, video playing) within the idle cutoff.
// After the cutoff the clock stops at lastActivity + cutoff, so walking away never inflates the number.
// Pure (clock injected) so it is unit-tested; the renderer hook feeds it DOM events.

export interface TimerOptions {
  /** seconds without input after which time stops counting */
  idleCutoffS?: number;
}

export class ReviewTimer {
  private activeMs = 0;
  private lastTick: number;
  private lastActivity: number;
  private visible = true;
  private focused = true;
  /** a playing video counts as activity (reviewers watch without touching anything) */
  private playing = false;
  readonly idleMs: number;

  constructor(now: number, opts: TimerOptions = {}) {
    this.idleMs = (opts.idleCutoffS ?? 60) * 1000;
    this.lastTick = now;
    this.lastActivity = now;
  }

  private engaged(): boolean {
    return this.visible && this.focused;
  }

  /** Credit time since the last tick, up to the idle cutoff. Call before every state change. */
  tick(now: number): void {
    if (now <= this.lastTick) return;
    if (this.engaged()) {
      const limit = this.playing ? now : Math.min(now, this.lastActivity + this.idleMs);
      if (limit > this.lastTick) this.activeMs += limit - this.lastTick;
    }
    this.lastTick = now;
  }

  activity(now: number): void {
    this.tick(now);
    this.lastActivity = now;
  }

  setVisible(v: boolean, now: number): void {
    this.tick(now);
    this.visible = v;
    if (v) this.lastActivity = now;
  }

  setFocused(f: boolean, now: number): void {
    this.tick(now);
    this.focused = f;
    if (f) this.lastActivity = now;
  }

  setPlaying(p: boolean, now: number): void {
    this.tick(now);
    this.playing = p;
    this.lastActivity = now;
  }

  /** Active seconds so far (ticks first). */
  seconds(now: number): number {
    this.tick(now);
    return Math.round(this.activeMs / 100) / 10;
  }

  /** Seconds accrued since the last take() - what a `timing stop` event reports. */
  private taken = 0;
  take(now: number): number {
    const s = this.seconds(now);
    const d = Math.round((s - this.taken) * 10) / 10;
    this.taken = s;
    return Math.max(0, d);
  }

  isIdle(now: number): boolean {
    return !this.engaged() || (!this.playing && now - this.lastActivity > this.idleMs);
  }
}
