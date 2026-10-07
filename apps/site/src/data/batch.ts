// The real batch shown on the 中文 home page (a 72-min RAG lecture, 2026-10-06; source media stays private).
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

// English pages (en / fr / es) show the English batch: a 124-min recorded backend class in English (2026-10-07;
// source media stays private). 9 clips x 3 formats (YouTube Shorts, TikTok, Instagram Reels) = 27 files; $0.29 AI API spend
// (gpt-4.1 caption glossary + proofreading; switched off for the final captions after it mis-fixed common
// English words, so the captions are local Whisper + a term list); 8 of 9 passed every check on their own, ep03 was flagged (dark first frame) and
// fixed with a longer chapter title. Covers: the batch's cover_3x4 per clip, resized into src/assets/clips/en-*.jpg.
// ep02 is left out of the sheet (its screen shows a test token payload).
export const CLIPS_EN: Clip[] = [
  { id: 'en-ep01', n: 1, start: 2559.67, flagged: false, title: { zh: '既然每次都查用户，为什么还用 JWT？', en: 'If you query the user anyway, why JWT?', fr: 'Si on relit l’utilisateur à chaque fois, pourquoi un JWT ?', es: 'Si igual consultas al usuario, ¿para qué JWT?' } },
  { id: 'en-ep03', n: 3, start: 2875.24, flagged: true, title: { zh: 'CORS 由浏览器执行，而不是服务器', en: 'CORS is enforced by the browser, not your server', fr: 'CORS est appliqué par le navigateur, pas par le serveur', es: 'CORS lo aplica el navegador, no tu servidor' } },
  { id: 'en-ep04', n: 4, start: 5505.53, flagged: false, title: { zh: '面试里的诚实回答：MySQL 8 有 JSON 列', en: 'The honest answer: MySQL 8 has a JSON column', fr: 'La réponse honnête : MySQL 8 a une colonne JSON', es: 'La respuesta honesta: MySQL 8 tiene columna JSON' } },
  { id: 'en-ep05', n: 5, start: 5123.71, flagged: false, title: { zh: '让 AI 优化慢查询，再用 EXPLAIN 验证', en: 'Ask AI to fix a slow query, then check EXPLAIN', fr: 'Demandez à l’IA, puis vérifiez avec EXPLAIN', es: 'Pide a la IA el índice y verifica con EXPLAIN' } },
  { id: 'en-ep06', n: 6, start: 5042.73, flagged: false, title: { zh: '每加一个索引，写入就更慢', en: 'Every index makes writes slower', fr: 'Chaque index ralentit les écritures', es: 'Cada índice hace más lentas las escrituras' } },
  { id: 'en-ep07', n: 7, start: 474.92, flagged: false, title: { zh: '存密码的两条规则', en: 'Two rules for storing passwords', fr: 'Deux règles pour stocker les mots de passe', es: 'Dos reglas para guardar contraseñas' } },
  { id: 'en-ep08', n: 8, start: 1773.96, flagged: false, title: { zh: 'JWT 被盗？短令牌加刷新令牌', en: 'Stolen JWT? Short access token + refresh token', fr: 'JWT volé ? Jeton court et jeton de rafraîchissement', es: '¿JWT robado? Token corto y token de refresco' } },
  { id: 'en-ep09', n: 9, start: 6285.51, flagged: false, title: { zh: 'CAP 定理：你从来不是“三选二”', en: 'CAP theorem: you never actually pick two', fr: 'Théorème CAP : on ne choisit jamais deux sur trois', es: 'Teorema CAP: nunca eliges dos de tres' } },
];

export const tc = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  const mm = String(m).padStart(2, '0'), ss = String(sec).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};
