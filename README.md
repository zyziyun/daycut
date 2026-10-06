# video-studio-site

Product website (官网) for the video-studio AI video studio: 中文 at `/`, English at `/en/`.
Static Astro build, zero JavaScript shipped, no cookies, no analytics, no third-party fonts (system font stack).

Not deployed. No GitHub repo created. Everything the creator must decide is listed at the bottom.

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
src/config.ts              ← the only place for URL, contact email, FORM_ENDPOINT, download URL, GitHub URL
src/i18n/zh.ts, en.ts      ← all copy (same shape; en.ts is type-checked against zh.ts)
src/components/Home.astro  ← all home sections: hero, how, proof, deliverables, partner + form, pricing,
                             desktop app, open source, FAQ, contact
src/components/Privacy.astro, Terms.astro   ← legal drafts (both languages), marked "draft, review before publishing"
src/layouts/Base.astro     ← header/footer, hreflang, OG tags
src/styles/global.css      ← Notebook Light theme (DESIGN.md §3 ②)
src/pages/{index,privacy,terms}.astro, src/pages/en/...
public/img/                ← optimised images (committed); sources in assets/demos/
scripts/                   ← optimize-images.sh, check-copy.mjs, screenshot.mjs
screenshots/               ← home desktop/mobile (zh + en) and privacy page
```

## Config (`src/config.ts`)

| Key | Default | Notes |
|---|---|---|
| `url` | `https://example.com` | Your domain; used for canonical, hreflang and OG tags. `astro.config.mjs` reads it. |
| `contactEmail` | `hello@example.com` | Placeholder. Used in the contact section, footer, legal pages and the mailto fallback. |
| `formEndpoint` | `''` | Empty = form is shown disabled with an "online form not open yet, email us" notice and a mailto button. Set a URL = the form POSTs there (standard `application/x-www-form-urlencoded`). |
| `downloadUrl` | `https://github.com/zyziyun/video-studio-desk-releases/releases/latest` | Both macOS and Windows buttons point here (a placeholder; the repo does not exist yet). |
| `githubUrl` | `https://github.com/zyziyun/video-studio` | Open-source section, contact, footer. |

## Form backend options (creator decides)

The form fields are: `name`, `contact`, `profile`, `content_type`, `hours`, `platforms` (multiple), `sample`, `notes`,
three consent checkboxes, a hidden `lang`, and a honeypot `_gotcha` (Formspree's name; other services ignore it or
you can rename it). It works as a plain HTML POST, so any of these can receive it:

| Option | How | Privacy notes | Fit |
|---|---|---|---|
| **Formspree** | Create a form, paste `https://formspree.io/f/<id>` into `formEndpoint`. | US company; submissions stored on their servers and emailed to you; free tier has limits. Mention them as processor in the privacy policy. Visitors in mainland China may find it slow or blocked. | Fastest for overseas visitors. |
| **Tally** | Build the form in Tally and link/embed it instead of this form (Tally does not take arbitrary POSTs). | EU-hosted (Belgium); GDPR-oriented. Embedding loads Tally's script, which breaks the "no third-party scripts" rule; linking out does not. | Good if you want Tally's dashboard; replace the form with a link. |
| **Cloudflare Workers + D1** | A ~40-line Worker that validates fields, checks the honeypot, inserts into a D1 table and emails you (e.g. via Cloudflare Email Routing / MailChannels). Put the Worker URL in `formEndpoint`. | You own the data; nothing leaves your Cloudflare account. You must handle deletion requests yourself (it's one SQL `DELETE`). | Best control; pairs naturally with Cloudflare Pages hosting. |
| **飞书问卷 / 腾讯问卷** | Create the questionnaire and replace the form with a link (or a QR code for 小红书 visitors). | Data stored in China by ByteDance / Tencent under their terms; good access from mainland China. Requires a 飞书/QQ account. | Most visitors come from 小红书 on phones in China: lowest friction there. |

Whichever you pick: update section 3 of the privacy policy ("where it is stored") in both languages.

## Deploy (not done; pick one)

`npm run build` produces a plain static folder `dist/`. Any static host works.

**Cloudflare Pages** (recommended: free, fast, can pair with Workers + D1 for the form)
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

The demo frames and contact sheets in `assets/demos/` come from `video-studio/docs/demos/` (approved by the
creator for public use). `scripts/optimize-images.sh` writes AVIF + WebP at 800/1600 px plus six single-frame
tiles and a 1200×630 `og.jpg`. Total image weight on the home page is roughly 100–300 KB (AVIF) depending on screen width; nothing above the fold is larger than 13 KB.

## What the creator must decide before publishing

1. **Domain** → `SITE.url`, then DNS per host above.
2. **Form backend** → `SITE.formEndpoint` (or swap the form for a Tally / 飞书 / 腾讯问卷 link), and update privacy §3.
3. **Contact email** → `SITE.contactEmail` (currently `hello@example.com`).
4. **Legal review** of `/privacy` and `/terms` (both languages): operating entity name, governing law, payment and
   refund terms, retention periods (30 days after delivery is a proposal), cross-border transfer consent wording
   (PIPL), and the AI-label rules per platform. Remove the draft banner only after review.
5. **Desktop downloads**: create the `video-studio-desk-releases` repo (or change `downloadUrl`), and confirm the
   note about MediaPipe usage statistics matches what the app actually shows.
6. **Promises on the page**: 72-hour delivery, "we reply to everyone", 7-day deletion turnaround, one free round of
   fixes (terms §5), early prices. Keep or edit; they are commitments once live.
7. **视频号**: the engine has no dedicated 视频号 platform profile yet; the site says it is delivered as 9:16.
