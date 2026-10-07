# Reelfold website (apps/site)

Lives in `apps/site/` of the [Reelfold](https://github.com/zyziyun/reelfold) monorepo; MIT like the rest of
the repo (see `LICENSE`). `npm install` works here or at the repo root (one npm workspace for all apps).

Product website (官网) for Reelfold (千剪), the free, open-source (MIT) batch video app for macOS: English (default) at `/`,
`/privacy`, `/terms`; 中文 at `/zh/`, `/zh/privacy`, `/zh/terms`; Français at `/fr/`, `/fr/privacy`, `/fr/terms`
(the French legal pages show the English text with a note until a reviewed translation exists). The old `/en/*`
URLs are static redirect pages to the English equivalents (`redirects` in `astro.config.mjs`).
Static Astro build, no cookies, no analytics, no third-party fonts (system font stack). The only JavaScript is a
four-line inline script that keeps the current `#section` when you switch language; without it the switcher still
opens the same page in the other language.

SEO: every page has `<html lang>` (`en` / `zh-CN` / `fr`), a canonical URL, and hreflang alternates `en`, `zh-CN`,
`fr` and `x-default` (= English). There is no sitemap.

Not deployed. Everything the creator must decide is listed at the bottom.

## Run

```bash
npm install
npm run dev        # http://localhost:4321
npm run build      # static site in dist/
npm run preview    # serve dist/ locally
npm run check:copy # copy rules (see below) on the built HTML
npm run images     # re-generate WebP/AVIF from assets/demos (needs magick, cwebp, avifenc)
node scripts/screenshot.mjs   # full-page screenshots into screenshots/ (needs `npm run preview` running
                              # and Playwright; uses the installed Google Chrome, no browser download)
```

## Structure

```
src/config.ts              ← the only place for URL, contact email, GitHub URL, download URL and `downloadReady`
src/i18n/en.ts, zh.ts, fr.ts ← all copy (same shape; en.ts and fr.ts are type-checked against zh.ts)
src/i18n/index.ts          ← LANGS, prefix() / pathFor(): '' for English, '/zh' for 中文, '/fr' for Français
src/components/Home.astro  ← all home sections: hero, how, who it's for, Mac app, proof, deliverables,
                             local-first, Create (coming), open source (skill + build from source), FAQ
src/components/Cta.astro   ← download / Star on GitHub / Build from source buttons (follows `downloadReady`)
src/components/Privacy.astro, Terms.astro   ← legal drafts (both languages), marked "draft, review before publishing"
src/components/Logo.astro  ← Reelfold symbol + wordmark, inlined from assets/brand
src/layouts/Base.astro     ← header/footer, EN · 中文 · FR switcher, hreflang, OG tags
src/styles/global.css      ← Reelfold light theme: warm paper, ink, brand teal
src/pages/{index,privacy,terms}.astro (English), src/pages/zh/... (中文), src/pages/fr/... (Français)
assets/brand/              ← Reelfold symbol / wordmark / Windows icon SVGs and the 1280x640 social preview
                             (copies of the brand masters; `node scripts/brand.mjs` regenerates favicons + OG)
public/img/                ← optimised images (committed); sources in assets/demos/
scripts/                   ← brand.mjs, optimize-images.sh, check-copy.mjs, screenshot.mjs
screenshots/               ← home-en-*, home-zh-*, home-fr-* (desktop + mobile) and privacy-mobile
```

## Config (`src/config.ts`)

| Key | Default | Notes |
|---|---|---|
| `url` | `https://reelfold.com` | The domain; used for canonical, hreflang and OG tags. `astro.config.mjs` reads it. |
| `contactEmail` | `hello@example.com` | Placeholder. Used in the contact section, footer, legal pages and the mailto fallback. |
| `githubUrl` | `https://github.com/zyziyun/reelfold` | Star on GitHub, open-source section, footer (Discussions link = `githubUrl` + `/discussions`). |
| `downloadUrl` | `https://github.com/zyziyun/reelfold/releases/latest` | "Download for macOS" target (Windows is shown as "later"). |
| `downloadReady` | `false` | `false` until the first macOS release exists: no download link anywhere; the hero and Mac-app section show "Star on GitHub" + "Build from source" and a "coming soon" note, and the header button is "Star on GitHub". Set `true` to switch every one of them to "Download for macOS". |

## Deploy (not done; pick one)

`npm run build` produces a plain static folder `dist/`. Any static host works.

**Cloudflare Pages** (recommended: free and fast)
1. Push this repo to GitHub (or use `npx wrangler pages deploy dist` without Git).
2. Cloudflare dashboard → Workers & Pages → Create → Pages → connect the repo.
3. Build command `npm run build`, output directory `dist`, Node 20+.
4. Custom domain: Pages project → Custom domains → add `yourdomain.com`; if the domain's DNS is on Cloudflare
   the record is created for you, otherwise add the CNAME it shows (`<project>.pages.dev`).

**GitHub Pages**
1. Push to GitHub. Settings → Pages → Source: GitHub Actions; use the official Astro workflow
   (`withastro/action`).
2. If serving from `https://<user>.github.io/<repo>/` you must also set `base: '/<repo>'` in `astro.config.mjs`
   and the image paths need the base prefix; a custom domain avoids that.
3. Custom domain: Settings → Pages → Custom domain; at your DNS add a CNAME `www` → `<user>.github.io`,
   and for the apex domain A records `185.199.108.153`, `.109.153`, `.110.153`, `.111.153`. Tick "Enforce HTTPS".

**Vercel**
1. Import the repo; framework preset Astro is detected (build `npm run build`, output `dist`).
2. Custom domain: Project → Settings → Domains → add; set the A / CNAME records Vercel shows.

After choosing a domain, set `SITE.url` in `src/config.ts` and rebuild.

**Mainland China note:** sites hosted on a mainland server need ICP 备案. The hosts above serve from outside
the mainland (no 备案 needed) but speed from China varies; test from a phone on a Chinese network before sharing
links on 小红书.

## Copy rules

Enforced by `npm run check:copy` on the built HTML:
- No em-dashes.
- No hype words: 最, 第一, 100%, 首个, 唯一, 顶级, 极致, 颠覆, 爆款, 保证; best, ultimate, guaranteed, 10x, seamless, etc.
- Honest claims only. The proof numbers are from one internal batch on our own 72-minute lecture
  (24 clips × 4 platforms = 96 files, $0.73 API cost, 21/24 green on automatic QC) and are labelled as such,
  together with what is not good enough yet (caption accuracy, ~15 filler cuts per clip needing confirmation).

## Images

The demo frames and contact sheets in `assets/demos/` come from the repo's `docs/demos/` (approved by the
creator for public use). `scripts/optimize-images.sh` writes AVIF + WebP at 800/1600 px plus six single-frame
tiles. The Open Graph image `public/img/og.png` (1280×640) is the launch social preview, copied by `scripts/brand.mjs`. Total image weight on the home page is roughly 100–300 KB (AVIF) depending on screen width; nothing above the fold is larger than 13 KB.

## What the creator must decide before publishing

1. **Domain**: `reelfold.com` is set in `SITE.url`; point its DNS at the host (see Deploy above).
2. **Contact email** → `SITE.contactEmail` (currently `hello@example.com`).
3. **Legal review** of `/privacy` and `/terms` (zh and en; fr shows the English text): maintainer / entity name and
   the AI-label rules per platform. Remove the draft banner only after review.
4. **First macOS release**: publish it on `github.com/zyziyun/reelfold/releases`, then set `SITE.downloadReady = true`;
   confirm the note about MediaPipe usage statistics matches what the app actually shows.
5. **GitHub Discussions**: enable them on the repo (the footer links there).
6. **视频号**: the engine has no dedicated 视频号 platform profile yet; the site says it is delivered as 9:16.
