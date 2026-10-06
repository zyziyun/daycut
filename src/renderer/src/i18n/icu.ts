// A small ICU MessageFormat subset: {name}, {n, number}, {n, plural, =0 {..} one {# clip} other {# clips}},
// {kind, select, a {..} other {..}}. Nested messages and '#' inside plural branches are supported; anything the
// parser does not understand is returned as written (never throws in the UI).

export type Vars = Record<string, string | number | null | undefined>;

interface Ctx {
  locale: string;
  vars: Vars;
  pound?: number;
}

function findClose(s: string, from: number): number {
  let depth = 0;
  for (let i = from; i < s.length; i++) {
    const c = s[i];
    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

function parseBranches(s: string): Map<string, string> {
  const out = new Map<string, string>();
  let i = 0;
  while (i < s.length) {
    while (i < s.length && /\s/.test(s[i])) i++;
    let j = i;
    while (j < s.length && s[j] !== '{' && !/\s/.test(s[j])) j++;
    const key = s.slice(i, j);
    while (j < s.length && s[j] !== '{') j++;
    if (j >= s.length || !key) break;
    const end = findClose(s, j);
    if (end < 0) break;
    out.set(key, s.slice(j + 1, end));
    i = end + 1;
  }
  return out;
}

const pluralRules = new Map<string, Intl.PluralRules>();
function plural(locale: string, n: number): string {
  let r = pluralRules.get(locale);
  if (!r) {
    r = new Intl.PluralRules(locale);
    pluralRules.set(locale, r);
  }
  return r.select(n);
}

function num(locale: string, n: number): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(n);
}

function render(msg: string, ctx: Ctx): string {
  let out = '';
  let i = 0;
  while (i < msg.length) {
    const c = msg[i];
    if (c === '#' && ctx.pound !== undefined) {
      out += num(ctx.locale, ctx.pound);
      i++;
      continue;
    }
    if (c !== '{') {
      out += c;
      i++;
      continue;
    }
    const end = findClose(msg, i);
    if (end < 0) {
      out += msg.slice(i);
      break;
    }
    const body = msg.slice(i + 1, end);
    i = end + 1;
    const m = /^\s*(\w+)\s*(?:,\s*(\w+)\s*(?:,([\s\S]*))?)?$/.exec(body);
    if (!m) {
      out += `{${body}}`;
      continue;
    }
    const [, name, type, rest] = m;
    const v = ctx.vars[name];
    if (!type) {
      out += v === undefined || v === null ? '' : typeof v === 'number' ? num(ctx.locale, v) : String(v);
    } else if (type === 'number') {
      out += typeof v === 'number' ? num(ctx.locale, v) : String(v ?? '');
    } else if (type === 'plural' && rest !== undefined) {
      const n = typeof v === 'number' ? v : Number(v ?? 0);
      const br = parseBranches(rest);
      const pick = br.get(`=${n}`) ?? br.get(plural(ctx.locale, n)) ?? br.get('other') ?? '';
      out += render(pick, { ...ctx, pound: n });
    } else if (type === 'select' && rest !== undefined) {
      const br = parseBranches(rest);
      out += render(br.get(String(v)) ?? br.get('other') ?? '', ctx);
    } else {
      out += `{${body}}`;
    }
  }
  return out;
}

export function formatMessage(msg: string, locale: string, vars: Vars = {}): string {
  if (!msg.includes('{') && !msg.includes('#')) return msg;
  return render(msg, { locale, vars });
}

/** Placeholder names used by a message (for the en/zh parity test). */
export function placeholders(msg: string): string[] {
  const names = new Set<string>();
  const re = /\{\s*(\w+)\s*(?:,|\})/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(msg))) names.add(m[1]);
  return [...names].sort();
}
