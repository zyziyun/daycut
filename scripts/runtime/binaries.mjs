// Dependency closures of native binaries: Mach-O (@rpath, via otool) and PE (import + delay-import tables).
import fs from 'node:fs';
import path from 'node:path';
import { run } from './common.mjs';

/** @rpath/… closure of Mach-O files (paths relative to the conda prefix). */
export function machoClosure(prefix, roots) {
  const seen = new Set();
  const todo = [...roots];
  while (todo.length) {
    const rel = todo.pop();
    const out = run('otool', ['-L', path.join(prefix, rel)], { capture: true, quiet: true });
    for (const line of out.split('\n').slice(1)) {
      const dep = line.trim().split(' ')[0];
      if (!dep) continue;
      if (dep.startsWith('@rpath/')) {
        const r = `lib/${dep.slice(7)}`;
        if (!seen.has(r)) {
          if (!fs.existsSync(path.join(prefix, r))) throw new Error(`missing ${r} (needed by ${rel})`);
          seen.add(r);
          todo.push(r);
        }
      } else if (!dep.startsWith('/usr/lib/') && !dep.startsWith('/System/')) {
        throw new Error(`${rel} links a non-system absolute path: ${dep}`);
      }
    }
  }
  return [...seen].sort();
}

/** DLL closure of PE files inside one folder (imports not found there are assumed to be Windows system DLLs). */
export function peClosure(dir, roots) {
  const present = new Map(fs.readdirSync(dir).map((f) => [f.toLowerCase(), f]));
  const seen = new Set(roots);
  const todo = [...roots];
  while (todo.length) {
    const f = todo.pop();
    for (const imp of peImports(fs.readFileSync(path.join(dir, f)))) {
      const real = present.get(imp.toLowerCase());
      if (real && !seen.has(real)) {
        seen.add(real);
        todo.push(real);
      }
    }
  }
  return [...seen].sort();
}

/** Names from the import + delay-import tables of a PE32/PE32+ image. */
export function peImports(buf) {
  const pe = buf.readUInt32LE(0x3c);
  if (buf.toString('latin1', pe, pe + 4) !== 'PE\0\0') throw new Error('not a PE file');
  const nSections = buf.readUInt16LE(pe + 6);
  const optSize = buf.readUInt16LE(pe + 20);
  const opt = pe + 24;
  const plus = buf.readUInt16LE(opt) === 0x20b;
  const dirs = opt + (plus ? 112 : 96);
  const secs = [];
  for (let i = 0; i < nSections; i++) {
    const s = opt + optSize + i * 40;
    secs.push({ va: buf.readUInt32LE(s + 12), vsize: buf.readUInt32LE(s + 8), raw: buf.readUInt32LE(s + 20), rsize: buf.readUInt32LE(s + 16) });
  }
  const off = (rva) => {
    const s = secs.find((x) => rva >= x.va && rva < x.va + Math.max(x.vsize, x.rsize));
    return s ? rva - s.va + s.raw : -1;
  };
  const cstr = (o) => buf.toString('latin1', o, buf.indexOf(0, o));
  const names = [];
  const scan = (dirIndex, entrySize, nameField) => {
    const rva = buf.readUInt32LE(dirs + dirIndex * 8);
    if (!rva) return;
    for (let o = off(rva); o > 0; o += entrySize) {
      const nameRva = buf.readUInt32LE(o + nameField);
      if (!nameRva) break;
      const no = off(nameRva);
      if (no > 0) names.push(cstr(no));
    }
  };
  scan(1, 20, 12); // IMAGE_IMPORT_DESCRIPTOR.Name
  scan(13, 32, 4); // IMAGE_DELAYLOAD_DESCRIPTOR.DllNameRVA
  return names;
}

