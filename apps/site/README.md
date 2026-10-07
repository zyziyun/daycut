# Reelfold website (apps/site)

Lives in `apps/site/` of the [Reelfold](https://github.com/zyziyun/reelfold) monorepo; MIT like the rest of
the repo (see `LICENSE`). `npm install` works here or at the repo root (one npm workspace for all apps).

Product site for Reelfold (千剪), the free, open-source (MIT) batch video app for macOS. Design: direction F
("Paper", editorial calm) from the 2026-10 redesign (`site-redesign/` in the design repo: README, IMPLEMENTATION.md,
reference HTML and PNGs). Static Astro build served by a Cloudflare Worker on reelfold.com. No cookies, no analytics,
no third-party requests: fonts are self-hosted (SIL OFL, licences in `public/fonts/`). About 1 KB of inline JS
(scrolled-nav hairline, fade-in on scroll, language switch keeps `#section`); everything works without it.

## Pages (every page in 4 languages)

| Page | en | 中文 | Français | Español |
|---|---|---|---|---|
| Home | `/` | `/zh/` | `/fr/` | `/es/` |
| Use cases | `/podcast-clips/`, `/interview-clips/`, `/course-slicing/`, `/talking-head/`, `/studios/` | `/zh/…` | `/fr/…` | `/es/…` |
| Platform specs | `/platforms/` (anchor per platform, e.g. `/platforms/#xiaohongshu`) | `/zh/platforms/` | … | … |
| Comparisons | `/compare/opus-clip/`, `/compare/descript/`, `/compare/capcut/` | `/zh/compare/…` | … | … |
| Legal drafts (noindex) | `/privacy/`, `/terms/` | 中文 | English text + note | English text + note |

`/docs/` (nav + footer) is the separate Starlight docs site (`apps/docs`), copied into `dist/docs` at deploy time;
this site never builds anything under `/docs`. Old `/en/*` URLs are static redirect pages.

## Run

```bash
npm install
npm run dev          # http://localhost:4321
npm run build        # static site in dist/ (+ sitemap-index.xml)
npm run check        # copy rules + site checks on dist/ (below)
npm run preview      # serve dist/
npm run screenshots  # node scripts/screenshot.mjs <baseUrl> [name-regex]: full-page PNGs into screenshots/
npm run deploy       # manual build + wrangler deploy (normally CI does this on every push to main: docs/CI_CD.md)
```

Generators (outputs are committed, so `npm run build` needs only Node):

| Command | Writes | When |
|---|---|---|
| `npm run fonts:zh` | `public/fonts/noto-serif-sc-600-{core,extra}.woff2`, `src/styles/zh-font.css`, `src/data/zh-font.json` | after changing 中文 headings (build first). Needs `pip install fonttools brotli` |
| `npm run og` | `public/og/{en,zh,fr,es}.png` (1200×630) | after changing the hero copy. Needs Playwright + Chrome, ImageMagick |
| `npm run platforms` | `src/data/platforms.json` from `lib/vstudio/platform.py` | after the engine's platform profiles change |
| `python3 scripts/fr-typo.py` | narrow no-break spaces in French strings (before `: ; ? !` and inside `« »`) | after editing French copy |
| `node scripts/brand.mjs` | favicons, app icons, `site.webmanifest` | after a logo change |

## Structure

```
src/config.ts               URL, GitHub / download URLs, docs paths, skill command, and `downloadReady` (below)
src/i18n/{en,zh,fr,es}.ts   home + shared UI copy; zh/fr/es are typed against en (a missing key fails the build)
src/i18n/index.ts           LANGS, HTML_LANG, HREFLANG (en, zh-Hans, fr, es), prefix(), pathFor()
src/content/usecases.ts     the 5 use-case pages, written per language
src/content/compare.ts      the 3 comparison pages: values, notes, sources, CHECKED date
src/content/platforms.ts    /platforms/ copy; numbers come from src/data/platforms.json
src/data/batch.ts           the real batch on the home page (72-min lecture, 24 clips, timecodes, QC result)
src/layouts/Base.astro      <html lang>, head (Seo), fonts preload, nav, footer, the inline script
src/components/             Seo, SiteNav, SiteFooter, Ctas, Print, Img (AVIF+WebP <picture>), Faq, Crumbs, Related,
                            Icon, Logo, home/* (Hero, Steps, Audiences, Batch, Platforms, ThreeUp, CreateTeaser,
                            OpenSource, FinalCta), Privacy, Terms
src/views/                  page templates (HomePage, UseCasePage, ComparePage, PlatformsPage, LegalPage)
src/pages/                  thin route files: / , /[slug]/, /compare/[tool]/, /platforms/, … and the same under zh/ fr/ es/
src/lib/                    zhHeading (中文 clause-safe line breaks), images (screenshot registry), schema (JSON-LD),
                            releaseStatus (build-time downloadReady from the GitHub API)
src/assets/                 app screenshots (re-rendered with the Reelfold name), batch covers, demo sheets
src/styles/global.css       tokens + all component styles (ported from the F prototype)
scripts/                    check-copy, check-site, subset-zh-font.py, og, export-platforms.py, fr-typo.py, screenshot, brand
docs/SEO_SUBMIT.md          Google Search Console, Bing Webmaster, 百度站长 steps
```

## The "coming soon" switch

`SITE.downloadReady` in `src/config.ts`, decided at build time by `src/lib/releaseStatus.ts`: `true` when
`https://github.com/zyziyun/reelfold/releases/latest` is a published release with a `.dmg` (GitHub API; drafts never
count). While `false`, every CTA on every page and language is **Star on GitHub** + **Build from source**, the fine
print says the macOS app is coming soon, the header button is "Star", and the JSON-LD has no `downloadUrl`; once `true`
everything switches to **Download for macOS**. The deploy workflow (`.github/workflows/deploy-web.yml`) also runs on
`release: published`, so publishing a desk release turns the buttons on within minutes. `SITE_DOWNLOAD_READY=1` / `0`
forces it; `DOWNLOAD_READY_FALLBACK` in `config.ts` is used only when the API cannot be reached. The build logs
`[site] downloadReady=… (reason)`.

## SEO

- Per page and language: `<title>`, description, self canonical, hreflang `en` / `zh-Hans` / `fr` / `es` / `x-default`,
  `og:*` (locale + alternates, 1200×630 image per language), Twitter card.
- JSON-LD: home = SoftwareApplication (price 0, MIT, macOS) + Organization + FAQPage; use-case, compare and platform
  pages = BreadcrumbList + FAQPage. FAQ JSON-LD is built from the same arrays as the visible `<details>`.
- `sitemap-index.xml` (`@astrojs/sitemap`, all 40 indexable URLs with `xhtml:link` alternates); `robots.txt` points to it.
  Legal drafts are `noindex` and not in the sitemap.
- `npm run check` (scripts/check-site.mjs) fails on: not exactly one h1, skipped heading levels, missing
  title/description, non-absolute or wrong canonical, incomplete or non-reciprocal hreflang, JSON-LD that does not
  parse, missing OG image, `<img>` without alt/width/height, broken internal links or `#anchors`, third-party
  resources, and 中文 heading characters missing from the font subset.

## Copy rules

Enforced by `npm run check:copy` on the built HTML: no em-dashes; no hype words (最, 第一, 100%, 首个, 唯一, 顶级, 极致,
颠覆, 爆款, 保证; best, ultimate, guaranteed, 10x, seamless …). Honest claims only: the numbers are one real batch
(72-minute lecture → 24 clips × 4 formats = 96 files, $0.73 AI cost, 21/24 passed the automatic checks); the
comparison tables say "Not verified" where a primary source did not confirm a fact, and show the date they were checked.
Only the creator's own face appears in images.

## Lighthouse (2026-10-07, local build)

Mobile and desktop for `/`, `/zh/`, `/fr/`, `/es/`: Performance 98–100, Accessibility 100, Best Practices 100, SEO 100
(mobile LCP 2.2–2.3 s, CLS 0, TBT 0). `/podcast-clips/`, `/compare/descript/`, `/zh/platforms/` mobile: 99–100 / 100 / 100 / 100.

## Before publishing

1. `SITE.contactEmail` (legal pages) is a placeholder.
2. Legal review of `/privacy` and `/terms`, then remove the draft banners and `noindex`.
3. First macOS release: publish it on GitHub; the site redeploys and `downloadReady` turns on by itself.
4. Enable GitHub Discussions (linked from the open-source section and footer).
5. Re-check `src/content/compare.ts` before changing `CHECKED`; prices and features of other tools change.
6. Submit the site to search engines: `docs/SEO_SUBMIT.md`.
