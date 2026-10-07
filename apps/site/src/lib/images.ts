// Image registry: per-language app screenshots (zh has its own UI language; fr/es use the English app).
import type { ImageMetadata } from 'astro';
import homeEn from '../assets/app/home-en.png';
import homeZh from '../assets/app/home-zh.png';
import homeEnM from '../assets/app/home-en-m.webp';
import homeZhM from '../assets/app/home-zh-m.webp';
import review from '../assets/app/review.webp';
import publishEn from '../assets/app/publish-en.webp';
import publishZh from '../assets/app/publish-zh.webp';
import createEn from '../assets/app/create-en.png';
import createZh from '../assets/app/create-zh.png';
import texteditEn from '../assets/app/textedit-en.png';
import texteditZh from '../assets/app/textedit-zh.png';
import typing from '../assets/app/typing.png';
import longform from '../assets/demos/longform-slices.jpg';
import talkinghead from '../assets/demos/talkinghead.jpg';
import type { Lang } from '../i18n';

const SETS = {
  home: { en: homeEn, zh: homeZh },
  homeM: { en: homeEnM, zh: homeZhM },
  review: { en: review, zh: review },
  publish: { en: publishEn, zh: publishZh },
  create: { en: createEn, zh: createZh },
  textedit: { en: texteditEn, zh: texteditZh },
  typing: { en: typing, zh: typing },
  longform: { en: longform, zh: longform },
  talkinghead: { en: talkinghead, zh: talkinghead },
} satisfies Record<string, { en: ImageMetadata; zh: ImageMetadata }>;
export type ImgKey = keyof typeof SETS;
export const img = (key: ImgKey, lang: Lang): ImageMetadata => (lang === 'zh' ? SETS[key].zh : SETS[key].en);

const clips = import.meta.glob<{ default: ImageMetadata }>('../assets/clips/*.jpg', { eager: true });
export const clipImg = (id: string) => clips[`../assets/clips/${id}.jpg`].default;
