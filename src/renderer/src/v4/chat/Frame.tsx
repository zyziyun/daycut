// One frame of the clip drawn into a canvas (effect / cover previews). A hidden video seeks to each time once.
import { useEffect, useRef } from 'react';
import { media } from '../kit';

export function FrameAt({ file, t, w = 96, h = 128 }: { file: string | null; t: number; w?: number; h?: number }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (!file) return;
    let alive = true;
    const v = document.createElement('video');
    v.muted = true;
    v.preload = 'auto';
    v.src = media(file);
    const draw = () => {
      const c = ref.current;
      if (!alive || !c || !v.videoWidth) return;
      c.width = w * 2;
      c.height = h * 2;
      const ctx = c.getContext('2d');
      const r = Math.max(c.width / v.videoWidth, c.height / v.videoHeight);
      ctx?.drawImage(v, (c.width - v.videoWidth * r) / 2, (c.height - v.videoHeight * r) / 2, v.videoWidth * r, v.videoHeight * r);
    };
    v.addEventListener('loadeddata', () => (v.currentTime = Math.max(0, Math.min((v.duration || t) - 0.05, t))), { once: true });
    v.addEventListener('seeked', draw, { once: true });
    return () => {
      alive = false;
      v.removeAttribute('src');
      v.load();
    };
  }, [file, t, w, h]);
  return <canvas ref={ref} width={w} height={h} />;
}
