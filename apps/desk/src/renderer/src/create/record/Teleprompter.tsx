// Teleprompter on the preview: the current line at the top of the camera frame, right under the lens (so the eyes
// stay near the camera), the word being said marked, the next line dimmed below. Fixed-speed scroll; "follows your
// voice" is a later version (local streaming ASR).
export function Teleprompter({ lines, cur, progress, size, mirror }: { lines: string[]; cur: number; progress: number; size: number; mirror: boolean }) {
  const line = lines[cur] ?? '';
  const words = line.split(/(\s+)/);
  const nonSpace = words.filter((w) => w.trim()).length || 1;
  const at = Math.min(nonSpace - 1, Math.floor(progress * nonSpace));
  let k = -1;
  return (
    <div className={`rs-prompter ${mirror ? 'mirror' : ''}`} style={{ ['--pfs' as string]: `${size}px` }} data-testid="create-prompter">
      <div className="txt" data-testid="create-prompter-line">
        {words.map((w, i) => {
          if (!w.trim()) return <span key={i}>{w}</span>;
          k += 1;
          return k === at ? <mark key={i}>{w}</mark> : k > at ? <b key={i}>{w}</b> : <span key={i}>{w}</span>;
        })}
      </div>
      {lines[cur + 1] && <div className="txt next">{lines[cur + 1]}</div>}
    </div>
  );
}
