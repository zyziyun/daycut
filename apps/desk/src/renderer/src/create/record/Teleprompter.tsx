// Teleprompter (MVP): fixed-speed scroll (words per minute), the current line large with its current word marked,
// the next line below; size A− / A+, mirror. "Follows your voice" is a later version (local streaming ASR).
import { t } from '../../i18n';

export const WPM = 140;

/** Seconds a line takes at ``wpm`` (CJK: ~4 characters per "word"). */
export function lineSeconds(text: string, wpm = WPM): number {
  const cjk = (text.match(/[\u3400-\u9fff]/g) ?? []).length;
  const words = text.replace(/[\u3400-\u9fff]/g, ' ').split(/\s+/).filter(Boolean).length + cjk / 4;
  return Math.max(1.2, (words / wpm) * 60);
}

export function Teleprompter({
  lines,
  cur,
  progress,
  size,
  mirror,
  paused,
  onSize,
  onMirror,
}: {
  lines: string[];
  cur: number;
  progress: number;
  size: number;
  mirror: boolean;
  paused: boolean;
  onSize: (n: number) => void;
  onMirror: () => void;
}) {
  const line = lines[cur] ?? '';
  const words = line.split(/(\s+)/);
  const nonSpace = words.filter((w) => w.trim()).length || 1;
  const at = Math.min(nonSpace - 1, Math.floor(progress * nonSpace));
  let k = -1;
  return (
    <div className={`cr-prompter ${mirror ? 'mirror' : ''}`} style={{ ['--pfs' as string]: `${size}px` }} data-testid="create-prompter">
      <div className="txt" data-testid="create-prompter-line">
        {words.map((w, i) => {
          if (!w.trim()) return <span key={i}>{w}</span>;
          k += 1;
          return k === at ? <mark key={i}>{w}</mark> : k > at ? <b key={i}>{w}</b> : <span key={i}>{w}</span>;
        })}
      </div>
      <div className="bar" />
      <div className="txt next">{lines[cur + 1] ?? ''}</div>
      <div className="meta">
        <span>{paused ? t('create.rec.paused') : t('create.rec.scroll', { wpm: WPM })}</span>
        <span>·</span>
        <span>{t('create.rec.lineOf', { n: Math.min(cur + 1, lines.length), total: lines.length })}</span>
        <span>·</span>
        <span>
          {t('create.rec.size')}
          <button onClick={() => onSize(Math.max(20, size - 4))} aria-label="A-">
            A−
          </button>
          <button onClick={() => onSize(Math.min(56, size + 4))} aria-label="A+" style={{ fontSize: 18 }}>
            A+
          </button>
        </span>
        <span>·</span>
        <button onClick={onMirror} aria-pressed={mirror}>
          {t('create.rec.mirror')}
        </button>
      </div>
    </div>
  );
}
