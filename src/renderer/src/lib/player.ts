// Pure player math: frame stepping, shuttle speeds (J/K/L), selection loop, timecode, safe areas.

export function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

/** Snap a time to the frame grid (frame-accurate seeking: aim at the middle of the frame). */
export function frameTime(t: number, fps: number): number {
  const f = Math.round(t * fps);
  return (f + 0.5) / fps;
}

export function frameIndex(t: number, fps: number): number {
  return Math.floor(t * fps + 1e-6);
}

/** ←/→ = 1 frame, Shift = 1 second. */
export function step(t: number, dir: 1 | -1, fps: number, duration: number, big = false): number {
  if (big) return clamp(t + dir, 0, duration);
  const f = frameIndex(t, fps) + dir;
  return clamp((f + 0.5) / fps, 0, Math.max(0, duration - 0.5 / fps));
}

/** J/K/L shuttle: L speeds up forward (1, 2, 4), J backward (-1, -2, -4), K stops. */
export function shuttle(rate: number, key: 'j' | 'k' | 'l'): number {
  if (key === 'k') return 0;
  const dir = key === 'l' ? 1 : -1;
  if (rate === 0 || Math.sign(rate) !== dir) return dir;
  return clamp(rate * 2, -4, 4);
}

/** SMPTE-style HH:MM:SS:FF when fps is known (frame-accurate), m:ss.f otherwise. */
export function timecode(t: number, fps?: number): string {
  if (!Number.isFinite(t) || t < 0) t = 0;
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const p2 = (x: number) => String(x).padStart(2, '0');
  if (fps) {
    const f = Math.floor((t - Math.floor(t)) * fps + 1e-6);
    return `${p2(h)}:${p2(m)}:${p2(s)}:${p2(f)}`;
  }
  return `${h * 60 + m}:${(t % 60).toFixed(1).padStart(4, '0')}`;
}

/** Loop selection: when playing past the out point, jump back to in. */
export function loopTime(t: number, sel: { a: number; b: number } | null, loop: boolean): number | null {
  if (!loop || !sel || sel.b - sel.a < 0.05) return null;
  if (t >= sel.b || t < sel.a - 0.25) return sel.a;
  return null;
}

/** Platform UI-safe areas as fractions of the frame: keep text inside, captions inside the caption band. */
export function safeAreas(aspect: string, box?: number[] | null, capBox?: number[] | null, w?: number | null, h?: number | null) {
  if (box && capBox && w && h) {
    return {
      safe: { l: box[0] / w, t: box[1] / h, r: 1 - box[2] / w, b: 1 - box[3] / h },
      cap: { l: capBox[0] / w, t: capBox[1] / h, r: 1 - capBox[2] / w, b: 1 - capBox[3] / h },
    };
  }
  if (aspect === '9:16') return { safe: { l: 0.06, t: 0.1, r: 0.16, b: 0.22 }, cap: { l: 0.1, t: 0.62, r: 0.18, b: 0.24 } };
  if (aspect === '3:4') return { safe: { l: 0.045, t: 0.04, r: 0.045, b: 0.1 }, cap: { l: 0.11, t: 0.75, r: 0.11, b: 0.12 } };
  return null;
}
