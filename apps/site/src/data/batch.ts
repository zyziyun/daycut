// The real batch shown on the home page: ~/Desktop/video-studio-demos/batch-rag (72-min RAG lecture, 2026-10-06).
// 24 clips × 4 formats (Xiaohongshu 3:4, Xiaohongshu 9:16, Douyin, YouTube Shorts) = 96 files; $0.73 AI cost;
// automatic QC: 21 green, 3 red (ep09, ep19, ep21). `start` = where the clip starts in the lecture (segments.yaml).
// Covers: jobs/<id>/export/out/vertical/ep1/cover_3x4.png, resized into src/assets/clips/.
import type { Lang } from '../i18n';

export interface Clip { id: string; n: number; start: number; flagged: boolean; title: Record<Lang, string> }

export const CLIPS: Clip[] = [
  { id: 'ep02', n: 2, start: 313.52, flagged: false, title: { zh: 'RAG的上限，取决于数据质量', en: 'RAG is only as good as its data', fr: 'Un RAG ne vaut que ses données', es: 'Un RAG vale lo que valen sus datos' } },
  { id: 'ep04', n: 4, start: 439.0, flagged: false, title: { zh: '为什么没人只做语义检索', en: 'Why nobody uses semantic search alone', fr: 'Pourquoi personne ne s’en tient à la recherche sémantique', es: 'Por qué nadie usa solo búsqueda semántica' } },
  { id: 'ep08', n: 8, start: 1187.04, flagged: false, title: { zh: 'RAG怎么做到点哪句高亮哪句', en: 'How RAG highlights the exact source sentence', fr: 'Comment un RAG surligne la phrase source', es: 'Cómo un RAG resalta la frase de origen' } },
  { id: 'ep09', n: 9, start: 1557.02, flagged: true, title: { zh: '图片搜不到？caption要在入库时做', en: 'Images not found? Caption them at indexing time', fr: 'Images introuvables ? Légendez-les à l’indexation', es: '¿No encuentras imágenes? Descríbelas al indexar' } },
  { id: 'ep12', n: 12, start: 2186.02, flagged: false, title: { zh: '检索用小块，生成用大块', en: 'Small chunks to search, big chunks to answer', fr: 'Petits blocs pour chercher, grands blocs pour répondre', es: 'Bloques pequeños para buscar, grandes para responder' } },
  { id: 'ep14', n: 14, start: 2745.86, flagged: false, title: { zh: '混合检索：RRF只看排名不看分', en: 'Hybrid search: RRF uses rank, not score', fr: 'Recherche hybride : RRF regarde le rang, pas le score', es: 'Búsqueda híbrida: RRF mira el puesto, no la puntuación' } },
  { id: 'ep17', n: 17, start: 3279.2, flagged: false, title: { zh: '金融RAG：加过滤比换模型有用', en: 'Finance RAG: filters beat a bigger model', fr: 'RAG en finance : un filtre vaut mieux qu’un autre modèle', es: 'RAG financiero: un filtro rinde más que otro modelo' } },
  { id: 'ep22', n: 22, start: 3870.46, flagged: false, title: { zh: '查bug两周，最后只改了prompt', en: 'Two weeks of debugging, one prompt change', fr: 'Deux semaines de débogage, un seul prompt modifié', es: 'Dos semanas depurando, un solo cambio de prompt' } },
];

export const tc = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  const mm = String(m).padStart(2, '0'), ss = String(sec).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};
