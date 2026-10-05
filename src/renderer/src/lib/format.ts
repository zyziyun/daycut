export function hms(s: number | null | undefined): string {
  const n = Math.round(s ?? 0);
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const sec = n % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`;
}

export function bytes(n: number | null | undefined): string {
  let v = n ?? 0;
  for (const u of ['B', 'KB', 'MB', 'GB', 'TB']) {
    if (Math.abs(v) < 1024 || u === 'TB') return u === 'B' ? `${v.toFixed(0)} B` : `${v.toFixed(1)} ${u}`;
    v /= 1024;
  }
  return `${v}`;
}

export function usd(n: number | null | undefined): string {
  return `$${(n ?? 0).toFixed(2)}`;
}

export function secs(n: number | null | undefined): string {
  return n == null ? '-' : `${n.toFixed(1)}s`;
}
