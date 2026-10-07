// Build-time check: has the macOS app been released (and does the release carry the Windows preview installer)? Decides SITE.downloadReady (config.ts), so the site's download
// buttons turn on by themselves once a release is published on GitHub (the deploy workflow also runs on
// `release: published`, which rebuilds the site right then).
//
//   1. SITE_DOWNLOAD_READY=1 / 0 in the environment forces the answer (local previews, emergencies).
//   2. GitHub API /releases/latest of the repo: ready when the latest PUBLISHED release (drafts and pre-releases are
//      never "latest") has a .dmg asset. 404 = nothing published yet = not ready. GITHUB_TOKEN / GH_TOKEN, when set
//      (CI), is sent to avoid the 60 requests/hour unauthenticated limit.
//   3. The API cannot be reached (offline, rate limit, outage): the fallback flag in config.ts.
//
// The same API answer also says whether that release carries the Windows installer (`*-win-x64-setup.exe`, unsigned
// preview): when it does, the site offers it as a secondary "Windows (preview)" link next to the macOS button.
// Forcing with SITE_DOWNLOAD_READY never invents a Windows link.

export type ReleaseStatus = {
  /** a published release with a .dmg exists: the macOS download buttons are on */
  ready: boolean;
  /** direct download URL of the Windows installer on that release, or null when it has none */
  windowsUrl: string | null;
};

type Asset = { name: string; browser_download_url?: string };
type Cache = { reelfoldReleaseStatus?: Promise<ReleaseStatus> };

const WIN_EXE = /-win-x64(-setup)?\.exe$/;

async function check(repo: string, fallback: boolean): Promise<ReleaseStatus> {
  const forced = (process.env.SITE_DOWNLOAD_READY ?? '').trim().toLowerCase();
  if (['1', 'true', 'yes'].includes(forced)) return log(true, null, 'SITE_DOWNLOAD_READY');
  if (['0', 'false', 'no'].includes(forced)) return log(false, null, 'SITE_DOWNLOAD_READY');

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
    if (res.status === 404) return log(false, null, `no published release on ${repo}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rel = (await res.json()) as { tag_name?: string; assets?: Asset[] };
    const assets = rel.assets ?? [];
    const dmg = assets.some((a) => a.name.endsWith('.dmg'));
    const win = dmg ? assets.find((a) => WIN_EXE.test(a.name))?.browser_download_url ?? null : null;
    return log(dmg, win, dmg ? `release ${rel.tag_name} has a DMG` : `release ${rel.tag_name} has no DMG yet`);
  } catch (e) {
    return log(fallback, null, `GitHub API unreachable (${(e as Error).message}); config fallback`);
  }
}

function log(ready: boolean, windowsUrl: string | null, why: string): ReleaseStatus {
  console.log(`[site] downloadReady=${ready} windows=${windowsUrl ? 'yes' : 'no'} (${why})`);
  return { ready, windowsUrl };
}

/** Memoized per process: astro.config.mjs and the page build both import config.ts. */
export function resolveReleaseStatus(githubUrl: string, fallback: boolean): Promise<ReleaseStatus> {
  const g = globalThis as Cache;
  const repo = new URL(githubUrl).pathname.replace(/^\/|\/$/g, '');
  return (g.reelfoldReleaseStatus ??= check(repo, fallback));
}
