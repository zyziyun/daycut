// The taste calls the AI already made on a clip (ux/fewer-steps), pure + unit-tested: where an unsure filler word is in
// the clip's own transcript (to play it, or to skip it in the preview while she reviews), the answer that undoes /
// changes one option, and the decisions that belong to one clip.
import type { AutopilotDecision, InboxOption } from '../../../shared/v04';

const norm = (s: string) => s.normalize('NFKC').replace(/[\s\p{P}\p{S}]/gu, '').toLowerCase();

export interface Located {
  /** the word is in the clip: its first / last word index and seconds; else the place it was cut from */
  present: boolean;
  t: number;
  te: number;
  i0?: number;
  i1?: number;
}

/** Find a filler option in the clip's words: the word with the most context around it (`before` / `after`, the
 * engine's sentence around the cut); when the word is gone (it was cut), the joint of its context. null: not here. */
export function locateCut(words: { w: string; t: number; te: number }[], text: string, ctx?: { before?: string | null; after?: string | null } | null): Located | null {
  const T = norm(text);
  if (!T || !words.length) return null;
  const B = norm(ctx?.before ?? '').slice(-12);
  const A = norm(ctx?.after ?? '').slice(0, 12);
  let s = '';
  const owner: number[] = [];
  words.forEach((w, i) => {
    for (const ch of norm(w.w)) {
      s += ch;
      owner.push(i);
    }
  });
  const score = (k: number, len: number) => {
    let b = 0;
    while (b < B.length && k - 1 - b >= 0 && s[k - 1 - b] === B[B.length - 1 - b]) b++;
    let a = 0;
    while (a < A.length && k + len + a < s.length && s[k + len + a] === A[a]) a++;
    return a + b;
  };
  let best = -1;
  let at = -1;
  for (let k = s.indexOf(T); k >= 0; k = s.indexOf(T, k + 1)) {
    const sc = score(k, T.length);
    if (sc > best) [best, at] = [sc, k];
  }
  const ctxLen = Math.min(4, B.length + A.length);
  if (at >= 0 && (best >= ctxLen || !(B || A))) {
    const i0 = owner[at];
    const i1 = owner[at + T.length - 1];
    return { present: true, t: words[i0].t, te: words[i1].te, i0, i1 };
  }
  // gone: where the words before it meet the words after it
  if (B && A) {
    const tail = B.slice(-4);
    const head = A.slice(0, 4);
    const k = s.indexOf(tail + head);
    if (k >= 0) {
      const i = owner[k + tail.length];
      return { present: false, t: words[i].t, te: words[i].t };
    }
  }
  return null;
}

/** Her answer when she flips one option of a filler decision: a cut kept (Undo) or a kept word cut. */
export function flipAnswer(opts: InboxOption[], id: string): { approve: string[]; keep: string[] } {
  const cut = (o: InboxOption) => (o.id === id ? !o.checked : !!o.checked);
  return { approve: opts.filter(cut).map((o) => o.id), keep: opts.filter((o) => !cut(o)).map((o) => o.id) };
}

/** Her pick of an opening (-1 = no cold open), as the generic answer the desk sends. */
export function pickAnswer(opts: InboxOption[], id: string | null): { approve: string[]; keep: string[] } {
  return { approve: [id ?? '-1'], keep: opts.filter((o) => o.id !== id).map((o) => o.id) };
}

/** The decisions shown in this clip's editor: the taste calls about this clip that have options to show. */
export function clipDecisions(list: AutopilotDecision[], clip: string): AutopilotDecision[] {
  return list.filter((d) => !d.asked && (d.item === clip || clip.startsWith(`${d.item}/`)) && (d.options?.length ?? 0) > 0 && (d.kind === 'filler-confirm' || d.kind === 'hook-pick'));
}
