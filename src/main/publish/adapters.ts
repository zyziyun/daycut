// Loads adapters/*.json (shipped) and <userData>/adapters/*.json (local overrides, same id wins) so selectors
// can be updated without a rebuild. Invalid files are reported, never half-used.
import fs from 'node:fs';
import path from 'node:path';
import { parseAdapter, type Adapter } from '../../shared/publish/adapterSchema';

export interface AdapterLoad {
  adapters: Adapter[];
  errors: { file: string; error: string }[];
}

export function loadAdapters(dirs: string[]): AdapterLoad {
  const byId = new Map<string, Adapter>();
  const errors: AdapterLoad['errors'] = [];
  for (const dir of dirs) {
    let files: string[];
    try {
      files = fs.readdirSync(dir).filter((f) => f.endsWith('.json') && !f.startsWith('_'));
    } catch {
      continue;
    }
    for (const f of files.sort()) {
      const file = path.join(dir, f);
      try {
        const r = parseAdapter(JSON.parse(fs.readFileSync(file, 'utf8')));
        if (r.ok) byId.set(r.adapter.id, r.adapter);
        else errors.push({ file, error: r.error });
      } catch (e) {
        errors.push({ file, error: (e as Error).message });
      }
    }
  }
  return { adapters: [...byId.values()], errors };
}
