// JSON-LD builders (schema.org). Visible text and structured data come from the same arrays.
import { SITE, site } from '../config';
import { t, pathFor, HTML_LANG, type Lang } from '../i18n';

export const softwareApp = (lang: Lang) => ({
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: lang === 'zh' ? SITE.nameZh : SITE.name,
  alternateName: [SITE.name, SITE.nameZh],
  applicationCategory: 'MultimediaApplication',
  operatingSystem: 'macOS (Apple Silicon)',
  offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
  license: 'https://opensource.org/licenses/MIT',
  ...(SITE.downloadReady ? { downloadUrl: SITE.downloadUrl } : {}),
  url: `${site}${pathFor(lang)}`,
  codeRepository: SITE.githubUrl,
  isAccessibleForFree: true,
  description: t(lang).meta.description,
  inLanguage: HTML_LANG[lang],
});

export const organization = () => ({
  '@context': 'https://schema.org',
  '@type': 'Organization',
  name: SITE.name,
  alternateName: SITE.nameZh,
  url: `${site}/`,
  logo: `${site}/icon-512.png`,
  sameAs: [SITE.githubUrl],
});

export const faqPage = (items: { q: string; a: string }[]) => ({
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: items.map((x) => ({ '@type': 'Question', name: x.q, acceptedAnswer: { '@type': 'Answer', text: x.a } })),
});

/** Home → page. `trail` = [[name, page id or null]]; entries without a page (section labels with no index page
 * of their own, such as "Use cases") are left out, because Google needs a URL for every item. */
export const breadcrumbs = (lang: Lang, trail: [string, string | null][]) => ({
  '@context': 'https://schema.org',
  '@type': 'BreadcrumbList',
  itemListElement: [[t(lang).page.home, ''] as [string, string | null], ...trail].filter(([, page]) => page !== null).map(([name, page], i) => ({
    '@type': 'ListItem',
    position: i + 1,
    name,
    item: `${site}${pathFor(lang, page!)}`,
  })),
});
