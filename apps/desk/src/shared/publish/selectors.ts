// Adapter selectors: plain CSS, plus two text-based forms for pages whose class names are hashed (小红书, 抖音 build
// their class names per release, but the labels a creator reads stay put):
//   css:has-text(发布)          an element matching css whose own text contains 发布
//   css:has-text(/^\s*发布\s*$/) ... whose text matches the regular expression
//   css:near-text(标题)          an element matching css with 标题 in the text of one of its 4 nearest ancestors
// The lookup runs inside the platform page (isolated world) and also searches open shadow roots. Pure strings
// here so the same code runs over CDP (cdpFill) and in the page-signal / success checks.

const TEXT_SEL = /^(.*?):(has-text|near-text)\((.+)\)$/s;

export interface ParsedSelector {
  css: string;
  kind: 'css' | 'has-text' | 'near-text';
  text?: string;
  regex?: { source: string; flags: string };
}

export function parseSelector(sel: string): ParsedSelector {
  const m = TEXT_SEL.exec(sel.trim());
  if (!m) return { css: sel, kind: 'css' };
  const css = m[1].trim() || '*';
  const arg = m[3];
  const rx = /^\/(.*)\/([imsu]*)$/s.exec(arg);
  return { css, kind: m[2] as 'has-text' | 'near-text', ...(rx ? { regex: { source: rx[1], flags: rx[2] } } : { text: arg }) };
}

/** Why a selector is unusable (bad regex, empty css), or null. */
export function selectorError(sel: string): string | null {
  const p = parseSelector(sel);
  if (p.regex) {
    try {
      new RegExp(p.regex.source, p.regex.flags);
    } catch {
      return `bad regular expression in ${sel}`;
    }
  }
  if (p.kind !== 'css' && !p.text && !p.regex) return `empty text in ${sel}`;
  return null;
}

/** JS (an expression) that returns the first element matching any selector, or null. `visible`: only rendered
 * elements count (file inputs are hidden on purpose, so they are looked up without it). */
export function findJs(selectors: string[], visible: boolean): string {
  return `(() => {
  const SELS = ${JSON.stringify(selectors.map(parseSelector))};
  const roots = [document];
  for (let i = 0; i < roots.length && i < 400; i++) {
    for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
  }
  const vis = (el) => ${visible ? 'el.getClientRects().length > 0' : 'true'};
  const txt = (el) => ((el.innerText !== undefined ? el.innerText : el.textContent) || '').trim();
  const ok = (p, s) => (p.regex ? new RegExp(p.regex.source, p.regex.flags).test(s) : s.includes(p.text));
  const near = (p, el) => { let a = el.parentElement; for (let k = 0; a && k < 4; k++, a = a.parentElement) if (ok(p, txt(a))) return true; return false; };
  for (const p of SELS) {
    for (const r of roots) {
      let list;
      try { list = r.querySelectorAll(p.css); } catch (e) { continue; }
      for (const el of list) {
        if (!vis(el)) continue;
        if (p.kind === 'has-text' && !ok(p, txt(el))) continue;
        if (p.kind === 'near-text' && !near(p, el)) continue;
        return el;
      }
    }
  }
  return null; })()`;
}
