// Build-time check: has the macOS app been released? Decides SITE.downloadReady (config.ts), so the site's download
// buttons turn on by themselves once a release is published on GitHub (the deploy workflow also runs on
// `release: published`, which rebuilds the site right then).
//
//   1. SITE_DOWNLOAD_READY=1 / 0 in the environment forces the answer (local previews, emergencies).
//   2. GitHub API /releases/latest of the repo: ready when the latest PUBLISHED release (drafts and pre-releases are
//      never "latest") has a .dmg asset. 404 = nothing published yet = not ready. GITHUB_TOKEN / GH_TOKEN, when set
//      (CI), is sent to avoid the 60 requests/hour unauthenticated limit.
//   3. The API cannot be reached (offline, rate limit, outage): the fallback flag in config.ts.

type Cache = { reelfoldDownloadReady?: Promise<boolean> };

async function check(repo: string, fallback: boolean): Promise<boolean> {
  const forced = (process.env.SITE_DOWNLOAD_READY ?? '').trim().toLowerCase();
  if (['1', 'true', 'yes'].includes(forced)) return log(true, 'SITE_DOWNLOAD_READY');
  if (['0', 'false', 'no'].includes(forced)) return log(false, 'SITE_DOWNLOAD_READY');

  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  const url = `https://api.github.com/repos/${repo}/releases/latest`;
  try {
    const res = await fetch(url, {
      headers: {
        accept: 'application/vnd.github+json',
        'user-agent': 'reelfold-site-build',
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
      signal: AbortSignal.timeout(8000),
    });
    if (res.status === 404) return log(false, `no published release on ${repo}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rel = (await res.json()) as { tag_name?: string; assets?: { name: string }[] };
    const dmg = (rel.assets ?? []).some((a) => a.name.endsWith('.dmg'));
    return log(dmg, dmg ? `release ${rel.tag_name} has a DMG` : `release ${rel.tag_name} has no DMG yet`);
  } catch (e) {
    return log(fallback, `GitHub API unreachable (${(e as Error).message}); config fallback`);
  }
}

function log(ready: boolean, why: string): boolean {
  console.log(`[site] downloadReady=${ready} (${why})`);
  return ready;
}

/** Memoized per process: astro.config.mjs and the page build both import config.ts. */
export function resolveDownloadReady(githubUrl: string, fallback: boolean): Promise<boolean> {
  const g = globalThis as Cache;
  const repo = new URL(githubUrl).pathname.replace(/^\/|\/$/g, '');
  return (g.reelfoldDownloadReady ??= check(repo, fallback));
}
