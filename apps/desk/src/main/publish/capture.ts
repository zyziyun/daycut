// "Capture this page" (developer aid for tuning adapter selectors): a redacted snapshot of the platform page that is
// open in the built-in browser, saved to <userData>/captures/<adapter>-<time>.html on this Mac only. It keeps the
// page's structure (tags, ids, classes, roles, aria-*, placeholders, input types, short UI labels) and drops what
// could be hers: no cookies or storage (never read), no input / textarea values, no editor contents, no images or
// media URLs, no link targets or query strings, no scripts; text inside anything that looks like a name, avatar,
// account, phone or e-mail is masked, long texts are cut and digit runs are masked. Open shadow roots are kept as
// <template shadowrootmode="open">; frames are listed by origin only.
import fs from 'node:fs';
import path from 'node:path';

export const CAPTURE_JS = `(() => {
  const KEEP = /^(id|class|role|type|name|placeholder|contenteditable|accept|maxlength|for|disabled|readonly|tabindex|data-placeholder|data-e2e|data-testid|aria-[a-z-]+)$/;
  const PERSONAL = /user|name|nick|avatar|account|profile|phone|mail|author|owner|fans|follower|creator-info|userinfo/i;
  const DROP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'LINK', 'META', 'BASE', 'TEMPLATE', 'OBJECT', 'EMBED']);
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const mask = (s) => s.replace(/[0-9]{4,}/g, (m) => '#'.repeat(m.length)).replace(/[\\w.+-]+@[\\w-]+\\.[\\w.]+/g, '[email]');
  let nodes = 0;
  const walk = (n, personal, depth) => {
    if (++nodes > 60000 || depth > 80) return '';
    if (n.nodeType === 3) {
      const t = n.nodeValue.replace(/\\s+/g, ' ');
      if (!t.trim()) return t ? ' ' : '';
      if (personal) return '▒';
      return esc(mask(t.length > 40 ? t.slice(0, 40) + '…' : t));
    }
    if (n.nodeType !== 1) return '';
    const el = n;
    const tag = el.tagName;
    if (DROP.has(tag)) return '';
    const lower = tag.toLowerCase();
    const sig = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '');
    const pers = personal || PERSONAL.test(sig);
    let attrs = '';
    for (const a of Array.from(el.attributes)) {
      if (!KEEP.test(a.name)) continue;
      let v = a.value;
      if (a.name === 'class' || a.name === 'id') v = v.slice(0, 200);
      else v = mask(v.slice(0, 80));
      attrs += ' ' + a.name + '="' + esc(v) + '"';
    }
    if (tag === 'A' && el.getAttribute('href')) {
      try { const u = new URL(el.href); attrs += ' data-capture-href="' + esc(u.origin + u.pathname.replace(/[0-9a-f]{12,}/gi, '{id}').replace(/[0-9]{5,}/g, '{n}')) + '"'; } catch (e) {}
    }
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      attrs += ' data-capture-visible="' + (el.getClientRects().length > 0) + '"';
      if (tag === 'TEXTAREA' || tag === 'SELECT') return '<' + lower + attrs + '></' + lower + '>';
      return '<' + lower + attrs + '>';
    }
    if (tag === 'IFRAME' || tag === 'FRAME') {
      let o = '';
      try { o = new URL(el.src).origin; } catch (e) {}
      return '<' + lower + attrs + ' data-capture-origin="' + esc(o) + '"></' + lower + '>';
    }
    if (tag === 'IMG' || tag === 'VIDEO' || tag === 'AUDIO' || tag === 'SOURCE' || tag === 'CANVAS' || tag === 'PICTURE') return '<' + lower + attrs + '></' + lower + '>';
    if (tag === 'svg' || tag === 'SVG') return '<svg' + attrs + '></svg>';
    if (el.isContentEditable && el.getAttribute('contenteditable') !== null) return '<' + lower + attrs + '>[editor contents removed]</' + lower + '>';
    let inner = '';
    if (el.shadowRoot) {
      let sh = '';
      for (const c of Array.from(el.shadowRoot.childNodes)) sh += walk(c, pers, depth + 1);
      inner += '<template shadowrootmode="open">' + sh + '</template>';
    }
    for (const c of Array.from(el.childNodes)) inner += walk(c, pers, depth + 1);
    if (/^(BR|HR|WBR)$/.test(tag)) return '<' + lower + attrs + '>';
    return '<' + lower + attrs + '>' + inner + '</' + lower + '>';
  };
  let where = '';
  try { const u = new URL(location.href); where = u.origin + u.pathname; } catch (e) {}
  return { url: where, title: mask(document.title.slice(0, 80)), html: walk(document.documentElement, false, 0), nodes };
})()`;

export interface CaptureResult {
  url: string;
  title: string;
  html: string;
  nodes: number;
}

export function saveCapture(dir: string, adapterId: string, c: CaptureResult, now = new Date()): string {
  fs.mkdirSync(dir, { recursive: true });
  const stamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const file = path.join(dir, `${adapterId}-${stamp}.html`);
  const head = `<!-- Reelfold page capture (redacted) · ${adapterId} · ${c.url} · ${now.toISOString()} · ${c.nodes} nodes\n     No cookies, storage, input values, editor contents, images or link targets. Selectors only. -->\n`;
  fs.writeFileSync(file, head + '<!doctype html>\n' + c.html + '\n');
  return file;
}
